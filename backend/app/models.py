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


class TransactionIn(BaseModel):
    """What a client must send to create a transaction."""

    # Literal mirrors the `check (type in (...))` constraint. Rejecting a bad
    # value here gives a clear 422 listing the allowed options, instead of
    # letting Postgres raise a constraint violation that surfaces as a 500.
    type: Literal["expense", "income"]

    # Decimal, not float — the same reason the column is numeric(12,2).
    # gt=0 mirrors `check (amount > 0)`; direction lives in `type`.
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)

    # All nullable in the schema, so all optional here.
    merchant: Optional[str] = None
    category: Optional[str] = None
    upi_ref: Optional[str] = None
    payment_method: Optional[str] = None
    card_id: Optional[int] = None
    note: Optional[str] = None

    # Optional on the way in: if the caller doesn't say when the money moved,
    # the database fills in now(). The SMS parser will pass the real time.
    txn_time: Optional[datetime] = None

    # Not null in the schema, but it has a default, so the caller can omit it.
    source: Literal["manual", "sms", "agent"] = "manual"
