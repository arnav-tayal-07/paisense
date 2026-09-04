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
        "account_last4": {
            "type": "string",
            "description": (
                "Trailing digits of the sender's OWN card or account, no X or * characters. "
                "4 to 6 of them. NOT the destination account."
            ),
            "nullable": True,
        },
        "counterparty": {
            "type": "string",
            "description": (
                "Who the money went to or came from: a UPI VPA like name@bank, or the "
                "other account's masked digits. Null if the message names neither."
            ),
            "nullable": True,
        },
        "reference": {
            "type": "string",
            "description": "Transaction reference exactly as printed - UPI Ref, Ref, RRN.",
            "nullable": True,
        },
        "occurred_at": {
            "type": "string",
            "description": "ISO 8601 in IST, e.g. 2026-08-27T17:31:03+05:30. Midnight if no time given.",
            "nullable": True,
        },
        "reported_balance": {
            "type": "string",
            "description": (
                "What the bank said was left afterwards - 'Avl Limit' on a card, "
                "'AvlBal' on a bank account. Null if not stated."
            ),
            "nullable": True,
        },
        "reason": {
            "type": "string",
            "description": "If is_transaction is false, one short phrase saying what it is.",
            "nullable": True,
        },
        "new_credit_limit": {
            "type": "string",
            "description": (
                "If the message announces a NEW credit limit, the new total limit "
                "as digits. From 'revised to INR 36300.00' this is 36300.00. Null "
                "otherwise. An INCREASE BY amount is not the new limit - only give "
                "a figure when the message states the resulting total."
            ),
            "nullable": True,
        },
        "credit_limit_effective": {
            "type": "string",
            "description": (
                "Date the new limit takes effect, ISO 8601 (2026-08-30). Null if "
                "not stated or if there is no limit change."
            ),
            "nullable": True,
        },
    },
    "required": [
        "is_transaction",
        "type",
        "amount",
        "merchant",
        "account_last4",
        "counterparty",
        "reference",
        "occurred_at",
        "reported_balance",
        "reason",
        "new_credit_limit",
        "credit_limit_effective",
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
- merchant: a recognisable business NAME only, e.g. PVR LIMITED, Anthropic. \
Null if the message names no business. Never put an account number here.
- counterparty: where the money went or came from when it isn't a business \
name - a UPI VPA like paytmqr6s4v8c@ptys, or the other party's masked \
account digits. A message can have a counterparty and no merchant.
- account_last4: the trailing digits of the sender's OWN card or account, \
never the destination. 4 to 6 digits, no X or * characters.
- reference: the transaction reference exactly as printed, after labels like \
"UPI Ref", "UPI Ref no", "Ref:" or "RRN". Copy it character for character.
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

    # A credit-limit announcement is not a transaction, but it IS the only
    # place the bank tells us the limit — and `outstanding` is computed from
    # it. Carried out separately so the caller can update the account.
    new_credit_limit: str | None = None
    credit_limit_effective: str | None = None

    # Returned alongside the transaction as well as on it: turning digits into
    # an account_id needs a database lookup, which has no place in a parser.
    account_last4: str | None = None

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


# The one field extracted by regex rather than by the model, and the reason is
# exactness (ADR 026). A reference is a meaningless identifier - there is no
# context to reason from, so a model transposing one digit produces a string
# that looks perfectly valid. And this string IS the dedupe key: one wrong
# character means the same transaction inserts twice on the next re-scan,
# silently. A regex is exact or it fails; there is no "nearly right".
#
# Label forms seen in real messages:
#   RBL debit   "(UPI Ref 661188335104)"
#   RBL credit  "(UPI Ref no 105143193111)"
#   BOB         "Ref:623928991037."
_REFERENCE = re.compile(
    r"\b(?:UPI\s*Ref(?:erence)?(?:\s*no\.?)?|Ref(?:erence)?(?:\s*no\.?)?|RRN)\s*[:.\-]?\s*([A-Za-z0-9]{6,})",
    re.IGNORECASE,
)


def find_reference(message: str) -> str | None:
    """Pull the transaction reference out verbatim. None if there isn't one."""
    m = _REFERENCE.search(message)
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# Conversion helpers — the model returns strings, Python decides what's valid
# --------------------------------------------------------------------------


def to_amount(raw: str) -> Decimal:
    """'3,230.00' -> Decimal('3230.00'). Handles '845' too."""
    return Decimal(raw.replace(",", "").replace("INR", "").strip())


def build_dedupe_key(
    sender: str,
    last4: str | None,
    when: datetime,
    amount: Decimal,
    reference: str | None = None,
) -> str:
    """The dedupe key. A real reference beats a derived one.

    A transaction reference is unique by definition, so when the message
    carries one it IS the key and nothing else is needed.

    The derived fallback (ADR 017) exists for card messages, which carry no
    reference — and it is genuinely weaker. RBL's debit format has a date but
    no time, so txn_time falls back to midnight; two UPI payments of the same
    amount on the same day would produce identical keys and the second would
    be silently discarded. That is precisely why the reference is pulled out
    by regex rather than trusted to a model.
    """
    # A reference stands alone, with NO bank prefix. UPI references are issued
    # centrally and are globally unique, so the same payment produces the same
    # reference in every message about it. Prefixing with the sender defeated
    # that entirely: one transfer texted about by BOB, RBL and SBI became three
    # transactions, because all three keys differed.
    if reference:
        return f"ref:{reference}"

    # No reference, so fall back to the derived key — but keyed on the ISSUER,
    # not the full sender header. Banks send the same alert from several
    # headers: IDFC used both CP-IDFCFB-S and JM-IDFCFB-S for one identical
    # message, which produced two rows for one purchase. The issuer segment is
    # the same across those, while still keeping different banks apart.
    return f"{issuer_code(sender)}|{last4 or '-'}|{when.isoformat()}|{amount}"


def issuer_code(sender: str) -> str:
    """AX-AXISBK-S -> AXISBK. The middle segment identifies the bank.

    Falls back to the whole header for anything not in DLT shape.
    """
    parts = (sender or "").upper().strip().split("-")
    return parts[1] if len(parts) >= 3 else (sender or "").upper().strip()


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
        limit_amount = data.get("new_credit_limit")
        limit_from = data.get("credit_limit_effective")

        if looks_like_money(body) and avoid_model is None and not limit_amount:
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

        return Extraction(
            status="ignored",
            error=reason,
            model=used,
            # Carried even though this isn't a transaction: a credit-limit
            # notice names the card it applies to, and without those digits
            # there is no way to know which account to update.
            account_last4=data.get("account_last4") or None,
            new_credit_limit=limit_amount,
            credit_limit_effective=limit_from,
        )

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

    last4 = data.get("account_last4") or None

    reported_balance = None
    if data.get("reported_balance"):
        try:
            reported_balance = to_amount(data["reported_balance"])
        except InvalidOperation:
            # Not worth failing the whole transaction over — the amount and
            # payee are the point, the balance is a nice-to-have.
            reported_balance = None

    # Regex first, model second. The regex is authoritative because it copies
    # characters; the model is asked as well purely so a disagreement can be
    # surfaced rather than assumed away.
    reference = find_reference(body)
    model_reference = data.get("reference") or None

    review_reason = None

    if reference and model_reference and reference != model_reference:
        review_reason = (
            f"reference disagreement: regex read {reference!r}, model read {model_reference!r}"
        )
    elif not reference and model_reference:
        # The regex didn't recognise the label. Use the model's value so the
        # transaction still gets a real key, but flag it — an unrecognised
        # label means a format the pattern should learn.
        reference = model_reference
        review_reason = f"reference {model_reference!r} found by model only, label not recognised"

    txn = TransactionIn(
        type=data.get("type", "expense"),
        amount=amount,
        merchant=data.get("merchant") or None,
        counterparty=data.get("counterparty") or None,
        txn_time=occurred_at,
        reported_balance=reported_balance,
        account_last4=last4,
        upi_ref=reference,
        source="sms",
        dedupe_key=(
            build_dedupe_key(sender, last4, occurred_at, amount, reference)
            if (reference or occurred_at)
            else None
        ),
    )

    # The amount guardrail only catches an INVENTED number. It cannot catch the
    # model picking the wrong REAL one, and most messages carry two candidates —
    # the amount and the balance. If those come back equal, the wrong one was
    # chosen: a payment for exactly your remaining balance, to the paisa,
    # does not happen.
    if review_reason is None and reported_balance is not None and amount == reported_balance:
        review_reason = "amount matches the reported balance exactly - likely the wrong number"

    # last4 is on the transaction and returned separately: resolving it to an
    # account_id needs a database lookup that has no business in a parser.
    return Extraction(
        status="parsed", txn=txn, account_last4=last4, model=used, review_reason=review_reason
    )
