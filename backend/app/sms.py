"""Turn a bank SMS into a transaction, using an LLM (ADR 019).

No regexes. A regex encodes one bank's format and breaks the day that bank
changes it; the model reads the message the way a person would, so a new bank
or a reworded template needs no code change.

The model's job is narrow on purpose: read the message, return structured
fields, or say it isn't a transaction. It never decides what goes in the
database — that's Python's job below, including a guardrail that rejects
amounts the model may have invented.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

import re

from .llm import LLMError, LLMProvider, default_provider
from .models import TransactionIn

# India has no daylight saving, so a fixed offset is exactly right and avoids
# depending on the tzdata package that zoneinfo needs on Windows.
IST = timezone(timedelta(hours=5, minutes=30))


# --------------------------------------------------------------------------
# What we ask the model for
# --------------------------------------------------------------------------

# Every field is a string, even the numbers. Letting the model emit JSON
# numbers would hand it the float problem we spent ADR 011 avoiding —
# 3230.00 could come back as 3230.0 or 3.23e3. Strings arrive exactly as
# written, and Python converts them to Decimal.
# Every key is REQUIRED and nullable. That combination is deliberate: with
# only is_transaction required, the model was free to return a minimal answer
# and did exactly that on noisier messages — {"is_transaction": true,
# "type": "expense"} and nothing else. Requiring every key removes the
# latitude; nullable gives it somewhere honest to put "this message has no
# merchant" instead of inventing one.
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "is_transaction": {
            "type": "boolean",
            "description": "False for OTPs, marketing, balance alerts, delivery updates.",
        },
        "type": {
            "type": "string",
            "enum": ["expense", "income", "card_payment"],
            "nullable": True,
        },
        "amount": {
            "type": "string",
            "description": "Digits exactly as they appear, e.g. '845' or '3,230.00'. Never null for a transaction.",
            "nullable": True,
        },
        "merchant": {
            "type": "string",
            "description": "Who was paid. Null if the message names nobody.",
            "nullable": True,
        },
        "card_last4": {
            "type": "string",
            "description": "The masked digits only, 4 or 5 of them. Amex shows 5. Null if absent.",
            "nullable": True,
        },
        "occurred_at": {
            "type": "string",
            "description": "ISO 8601 in IST, e.g. 2026-08-27T17:31:03+05:30. Midnight if no time given.",
            "nullable": True,
        },
        "avl_limit": {
            "type": "string",
            "description": "Available/remaining limit if stated. Null otherwise.",
            "nullable": True,
        },
        "reason": {
            "type": "string",
            "description": "If is_transaction is false, one short phrase saying what it is.",
            "nullable": True,
        },
    },
    "required": [
        "is_transaction",
        "type",
        "amount",
        "merchant",
        "card_last4",
        "occurred_at",
        "avl_limit",
        "reason",
    ],
}

INSTRUCTIONS = """\
You extract transaction details from Indian bank SMS messages.

Set is_transaction false for anything that is not money moving: OTPs, \
promotional messages, balance enquiries, statement reminders, delivery \
notifications, failed or declined transaction alerts.

When it IS a transaction, classify it:
- expense: money left the account or was spent on a card
- income: money arrived (salary, refund, transfer received)
- card_payment: a payment made TOWARDS a credit card bill. This is neither \
spending nor income - it settles purchases already recorded as expenses.

Rules:
- Return EVERY field. Use null for anything the message does not contain. \
Never omit a key.
- When is_transaction is true, amount and occurred_at must NOT be null - \
every transaction message states an amount and a date somewhere.
- amount: copy the digits exactly as written, keeping commas and decimals.
- merchant: who was paid. Null if the message names nobody. For a recurring \
standing instruction, the merchant is whoever is being paid.
- card_last4: the masked digits only, no X or * characters. May be 4 or 5.
- occurred_at: the time in the MESSAGE, not the time you are reading it. \
Indian dates are day-first: 27-08-26 and 27 AUG 2026 are both 27 August \
2026; 29/08/2026 is 29 August 2026. Times may be 12-hour with AM/PM - \
08:38 PM is 20:38. Use +05:30. If only a date is given, use 00:00:00.
- Ignore phone numbers, reference IDs, URLs and card-blocking instructions. \
They are noise, never the amount or the merchant.
- Never guess a merchant, an amount, or a date. Null is always better than \
a plausible invention.
"""


@dataclass
class Extraction:
    """Result of looking at one message.

    Four outcomes, matching raw_sms.parse_status:
      parsed       - a transaction, ready to insert
      ignored      - definitely not a transaction (an OTP); nothing wrong
      needs_review - the message contains money but nothing could be read
                     from it. Two models declined; a human should look
      failed       - the provider broke; retryable
    """

    status: Literal["parsed", "ignored", "needs_review", "failed"]
    txn: TransactionIn | None = None
    error: str | None = None
    card_last4: str | None = None

    # Which model answered, so a retry can deliberately pick a different one.
    model: str | None = None

    # Set when the extraction is suspicious enough to want a human tick.
    # None means confident.
    review_reason: str | None = None


# Every Indian bank SMS writes money as INR or Rs. followed by digits. This is
# NOT a parser — it answers one question: could this message plausibly contain
# a transaction? Used only to decide whether to trust a "no" from the model.
_LOOKS_LIKE_MONEY = re.compile(r"(?:INR|RS\.?)\s*[\d,]+(?:\.\d{1,2})?", re.IGNORECASE)


def looks_like_money(message: str) -> bool:
    return bool(_LOOKS_LIKE_MONEY.search(message))


# --------------------------------------------------------------------------
# Conversion helpers — the model returns strings, Python decides what's valid
# --------------------------------------------------------------------------


def to_amount(raw: str) -> Decimal:
    """'3,230.00' -> Decimal('3230.00'). Handles '845' too."""
    return Decimal(raw.replace(",", "").replace("INR", "").strip())


def build_dedupe_key(sender: str, last4: str | None, when: datetime, amount: Decimal) -> str:
    """The derived dedupe key (ADR 017).

    Card SMS carry no reference number, so the key is built from the fields
    that together identify the transaction. Same inputs must always produce
    the same string, or a re-scan inserts a duplicate. That's why the bank
    comes from the sender header rather than the message body — the body
    wording could change, the DLT header won't.
    """
    bank = sender.upper().strip()
    return f"{bank}|{last4 or '-'}|{when.isoformat()}|{amount}"


def amount_appears_in(amount_raw: str, message: str) -> bool:
    """Guardrail: the amount must literally occur in the source text.

    An LLM can invent a number. This is the cheapest possible check that it
    didn't - if '845' isn't in the message, we are not writing 845 to the
    database. Compares with separators stripped so '3,230.00' matches
    '3230.00' and vice versa.
    """
    needle = amount_raw.replace(",", "").replace(" ", "")
    haystack = message.replace(",", "").replace(" ", "")
    return needle in haystack


# --------------------------------------------------------------------------
# The one function the rest of the app calls
# --------------------------------------------------------------------------


def extract(
    sender: str,
    body: str,
    provider: LLMProvider | None = None,
    avoid_model: str | None = None,
) -> Extraction:
    """Read one SMS and return what it is.

    Never raises. A failure is a returned status, because the caller has
    already stored the raw message and needs to record why it couldn't be
    parsed rather than lose the whole request.

    avoid_model excludes a model that already answered — retrying the same
    one at temperature 0 reproduces its answer exactly, so a retry only means
    anything if something changed.
    """
    provider = provider or default_provider(exclude=avoid_model)

    try:
        data = provider.extract_json(INSTRUCTIONS, f"From: {sender}\n\n{body}", EXTRACTION_SCHEMA)
    except LLMError as e:
        # Provider problem, not a message problem. Worth retrying later,
        # which is exactly what raw_sms exists to allow.
        return Extraction(status="failed", error=str(e))

    used = getattr(provider, "last_model", None)

    if not data.get("is_transaction"):
        reason = data.get("reason", "not a transaction")

        # A "no" is only trusted when the message contains no money. If it
        # does, get a second opinion from a different model before dropping
        # a possible transaction on the floor — this is the silent failure
        # that would otherwise never surface, because 'ignored' rows are
        # excluded from the alarm list on purpose.
        if looks_like_money(body) and avoid_model is None:
            second = extract(sender, body, avoid_model=used)

            if second.status == "parsed":
                # Models disagree. Take the transaction, but flag it — one of
                # the two is wrong and only a human knows which.
                second.review_reason = (
                    f"models disagreed: {used} said '{reason}', "
                    f"{second.model} read a transaction"
                )
                return second

            if second.status == "ignored":
                # Both declined. Trust it, but record that money was present
                # and it was double-checked.
                return Extraction(status="ignored", error=f"{reason} (confirmed by 2 models)", model=used)

            # Second attempt broke rather than answered. The message contains
            # money and nothing could read it — a human should look.
            return Extraction(
                status="needs_review",
                error=f"contains an amount but no transaction could be read ({reason})",
                model=used,
            )

        return Extraction(status="ignored", error=reason, model=used)

    amount_raw = data.get("amount")
    if not amount_raw:
        return Extraction(
            status="failed", error="model returned a transaction with no amount", model=used
        )

    # The guardrail. Cheap, and it catches the failure mode that would
    # otherwise be silent: a plausible-looking invented number.
    if not amount_appears_in(amount_raw, body):
        return Extraction(
            status="failed",
            error=f"amount {amount_raw!r} does not appear in the message",
            model=used,
        )

    try:
        amount = to_amount(amount_raw)
    except InvalidOperation:
        return Extraction(status="failed", error=f"could not read amount {amount_raw!r}", model=used)

    occurred_raw = data.get("occurred_at")
    try:
        occurred_at = datetime.fromisoformat(occurred_raw) if occurred_raw else None
    except ValueError:
        return Extraction(status="failed", error=f"could not read date {occurred_raw!r}")

    # No timezone in what came back means IST — that's where the banks are.
    if occurred_at and occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=IST)

    last4 = data.get("card_last4") or None

    avl_limit = None
    if data.get("avl_limit"):
        try:
            avl_limit = to_amount(data["avl_limit"])
        except InvalidOperation:
            # Not worth failing the whole transaction over — the amount and
            # merchant are the point, the limit is a nice-to-have.
            avl_limit = None

    txn = TransactionIn(
        type=data.get("type", "expense"),
        amount=amount,
        merchant=data.get("merchant") or None,
        txn_time=occurred_at,
        avl_limit=avl_limit,
        card_last4=last4,
        source="sms",
        dedupe_key=build_dedupe_key(sender, last4, occurred_at, amount) if occurred_at else None,
    )

    # The guardrail above only catches an INVENTED amount. It cannot catch the
    # model picking the wrong REAL number, and every IDFC message contains two
    # candidates — the spend and the available limit. If those come back equal,
    # the wrong one was chosen: a purchase for exactly your remaining limit,
    # to the paisa, does not happen.
    review_reason = None
    if avl_limit is not None and amount == avl_limit:
        review_reason = "amount matches the available limit exactly - likely the wrong number"

    # card_last4 is set on the transaction above, and returned separately as
    # well: card_id needs a database lookup (app.cards.resolve_card_id) that
    # has no business inside a parsing function.
    return Extraction(
        status="parsed", txn=txn, card_last4=last4, model=used, review_reason=review_reason
    )
