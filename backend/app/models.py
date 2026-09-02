"""Request/response shapes. Pydantic validates incoming JSON before it reaches SQL.

Rule of thumb for this file: the optionality here must mirror the nullability in
schema.sql exactly. If they drift, you get either a 500 from Postgres rejecting a
null, or a row you didn't mean to allow. See ADR 011 for why each column is what
it is.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SmsIn(BaseModel):
    """One bank SMS, forwarded by the phone exactly as received."""

    # DLT header, e.g. AX-AXISBK-S. Routing and card disambiguation both key
    # off this, and it's the only part of a message that reliably names the
    # bank — Amex never names itself in the body.
    sender: str

    # The message verbatim. Not cleaned, trimmed or normalised by the phone:
    # this is evidence, and a well-meaning transformation on the client would
    # be invisible here when a parse goes wrong.
    message: str

    # When the PHONE received it, which is not when the backend hears about
    # it — the app may have been closed for days. Part of the uniqueness key,
    # so it must come from the SMS itself, not from the upload time.
    sms_sent_at: datetime


class TransactionIn(BaseModel):
    """What a client must send to create a transaction."""

    # Literal mirrors the `check (type in (...))` constraint. Rejecting a bad
    # value here gives a clear 422 listing the allowed options, instead of
    # letting Postgres raise a constraint violation that surfaces as a 500.
    # card_payment = settling a credit card bill: neither spending nor
    # earnings, and excluded from both totals. See ADR 016.
    type: Literal["expense", "income", "card_payment"]

    # Decimal, not float — the same reason the column is numeric(12,2).
    # gt=0 mirrors `check (amount > 0)`; direction lives in `type`.
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)

    # All nullable in the schema, so all optional here.
    merchant: Optional[str] = None
    category: Optional[str] = None
    payment_method: Optional[str] = None
    note: Optional[str] = None

    # The account. Resolved from card_last4 by app.cards.resolve_card_id —
    # callers usually supply card_last4 and let the lookup fill this in.
    card_id: Optional[int] = None

    # Which physical card, as the message reported it. One account can carry
    # a Visa and a RuPay with different digits sharing a limit, so this is
    # how RuPay (UPI) spend is told apart from Visa (swipe).
    card_last4: Optional[str] = None

    # A real bank reference when the message carries one. Data only — it no
    # longer drives dedupe, and is no longer unique. See ADR 017.
    upi_ref: Optional[str] = None

    # What dedupe actually runs on, derived by the parser rather than read
    # from the message. Null for manual entry, which is why two identical
    # hand-typed rows are allowed: that repetition is usually deliberate.
    dedupe_key: Optional[str] = None

    # The card's available limit as reported by a card SMS, snapshotted at
    # this transaction. Null for everything else.
    avl_limit: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)

    # Optional on the way in: if the caller doesn't say when the money moved,
    # the database fills in now(). The SMS parser will pass the real time.
    txn_time: Optional[datetime] = None

    # Not null in the schema, but it has a default, so the caller can omit it.
    source: Literal["manual", "sms", "agent"] = "manual"
