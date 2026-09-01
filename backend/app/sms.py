"""Bank SMS parsing.

⚠️ SCAFFOLDING ONLY — the approach is UNDER REVIEW. See "Open decisions" in
docs/HANDOFF.md before writing anything here. Per-bank regex may be replaced
by, or paired with, LLM extraction, because a regex breaks whenever a bank
changes its format. Do not just fill in the TODO patterns without resolving
that first.

Routed on the DLT sender header, never on the message body. The header is
registered and stable; the body is not, and Amex's message never names the
bank at all. See ADR 001 for why parsing happens server-side.

Each bank gets its own handler. Adding a bank = one regex + one function +
one entry in HANDLERS. Nothing else in the codebase changes.
"""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .models import TransactionIn

# India has no daylight saving, so a fixed offset is exactly right and avoids
# depending on the tzdata package (which zoneinfo needs on Windows).
IST = timezone(timedelta(hours=5, minutes=30))


# --------------------------------------------------------------------------
# Helpers — utility, not parsing. Use these; you don't need to write them.
# --------------------------------------------------------------------------


def to_amount(raw: str) -> Decimal:
    """'3,230.00' -> Decimal('3230.00'). Handles '845' too."""
    return Decimal(raw.replace(",", "").strip())


def dedupe_key(bank: str, last4: str, when: datetime, amount: Decimal) -> str:
    """Build the derived dedupe key (ADR 017).

    Card SMS carry no reference number, so the key is constructed from the
    fields that together identify the transaction. Same inputs must always
    produce the same string, or re-scans will duplicate.
    """
    return f"{bank}:{last4}:{when.isoformat()}:{amount}"


# --------------------------------------------------------------------------
# YOUR PART STARTS HERE
#
# Two patterns, two handlers. Run `python check_sms.py` from backend/ to see
# exactly which fields you're getting right — it prints expected vs actual
# per field, so a wrong capture group shows up immediately.
# --------------------------------------------------------------------------


# Axis spend, sender AX-AXISBK-S. The five fields live on separate lines,
# so re.MULTILINE lets you anchor on ^ instead of guessing at separators.
#
#   Spent INR 845
#   Axis Bank Card no. XX7851
#   27-08-26 17:31:03 IST
#   PVR LIMITED
#   Avl Limit: INR 1356517.12
#
# Capture: amount, last4, date, time, merchant, avl_limit
AXIS_SPEND = re.compile(
    r"""
    TODO_WRITE_THE_AXIS_PATTERN
    """,
    re.VERBOSE | re.MULTILINE,
)


def parse_axis(message: str) -> TransactionIn | None:
    """Parse an Axis card spend. Return None if the message doesn't match.

    Returning None matters: Axis sends OTPs, balance alerts and marketing on
    the same sender. Anything that isn't a spend must fall through, not crash.
    """
    raise NotImplementedError("your turn")


# Amex bill payment, sender TX-AMEXIN-S. One line, not five:
#
#   Dear Customer, a payment of INR 3,230.00 was received on your Amex Card
#   ***71003 29/08/2026. It may take 24-48 hours for your payment to be
#   credited. Thank you.
#
# Note: FIVE digits after ***, comma in the amount, DD/MM/YYYY, no time,
# no merchant. type is 'card_payment', not 'expense' (ADR 016).
AMEX_PAYMENT = re.compile(
    r"""
    TODO_WRITE_THE_AMEX_PATTERN
    """,
    re.VERBOSE,
)


def parse_amex(message: str) -> TransactionIn | None:
    """Parse an Amex bill payment. Return None if the message doesn't match."""
    raise NotImplementedError("your turn")


# --------------------------------------------------------------------------
# Routing — done.
# --------------------------------------------------------------------------

# Sender headers vary by operator prefix (AX-, VM-, TX-, JD-...) but the
# middle segment identifies the bank, so match on that rather than the whole
# string: AX-AXISBK-S and VM-AXISBK-S are both Axis.
HANDLERS = {
    "AXISBK": parse_axis,
    "AMEXIN": parse_amex,
}


def parse_sms(sender: str, message: str) -> TransactionIn | None:
    """Dispatch to the right bank handler. None if unknown or unparseable."""
    for bank_code, handler in HANDLERS.items():
        if bank_code in sender.upper():
            return handler(message)
    return None
