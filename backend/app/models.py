"""Request/response shapes. Pydantic validates incoming JSON before it reaches SQL.

Rule of thumb for this file: the optionality here must mirror the nullability in
schema.sql exactly. If they drift, you get either a 500 from Postgres rejecting a
null, or a row you didn't mean to allow. See ADR 011 for why each column is what
it is.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class TransactionPatch(BaseModel):
    """Fields a user may correct on an existing transaction.

    Every field optional: a PATCH sends only what changed. Anything omitted
    is left alone, which is what distinguishes PATCH from PUT — sending
    `{"amount": "2000"}` must not blank out the merchant.

    Deliberately NOT editable: `dedupe_key` (changing it would let the same
    SMS insert a second row on the next re-scan), `source`, and `created_at`.
    """

    type: Optional[Literal["expense", "income", "card_payment", "blocked"]] = None
    amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    merchant: Optional[str] = None
    category: Optional[str] = None
    txn_time: Optional[datetime] = None
    payment_method: Optional[str] = None
    account_id: Optional[int] = None
    counterparty: Optional[str] = None
    note: Optional[str] = None


class AccountIn(BaseModel):
    """A credit card account or a bank account.

    Statement days, due dates and credit limits are credit-card concepts —
    a savings account has none of them. The validator enforces that, so a
    bank account can't quietly acquire a due date the app would then remind
    you about.
    """

    name: str
    kind: Literal["credit_card", "bank_account"] = "credit_card"

    # DLT sender segment: IDFCFB, AXISBK, RBLBNK, BOBSMS. Disambiguates when
    # two banks issue accounts ending in the same digits.
    issuer_code: Optional[str] = None

    # Credit-card only, all four.
    statement_day: Optional[int] = Field(default=None, ge=1, le=31)
    due_day: Optional[int] = Field(default=None, ge=1, le=31)
    due_days_after: Optional[int] = Field(default=None, ge=1, le=60)
    credit_limit: Optional[Decimal] = Field(default=None, ge=0, max_digits=12, decimal_places=2)

    @model_validator(mode="after")
    def fields_match_kind(self):
        # Caught here as a clear 422 rather than as a constraint violation
        # surfacing from Postgres as an unreadable 500.
        if self.kind == "credit_card":
            if self.statement_day is None:
                raise ValueError("statement_day is required for a credit_card")
            if (self.due_day is None) == (self.due_days_after is None):
                raise ValueError("set exactly one of due_day or due_days_after")
        else:
            extras = [
                f
                for f in ("statement_day", "due_day", "due_days_after", "credit_limit")
                if getattr(self, f) is not None
            ]
            if extras:
                raise ValueError(f"a bank_account cannot have {', '.join(extras)}")
        return self


class AccountPatch(BaseModel):
    """Partial update to an account — the app's edit button.

    No cross-field validator here: a PATCH may legitimately send only
    `due_day`, and the database check constraint is the backstop. The route
    clears the other due field when one is set, so both can never be
    populated at once.
    """

    name: Optional[str] = None
    issuer_code: Optional[str] = None
    statement_day: Optional[int] = Field(default=None, ge=1, le=31)
    due_day: Optional[int] = Field(default=None, ge=1, le=31)
    due_days_after: Optional[int] = Field(default=None, ge=1, le=60)
    credit_limit: Optional[Decimal] = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    is_active: Optional[bool] = None


class AccountNumberIn(BaseModel):
    """One card or account number belonging to an account.

    A credit account can carry several (Visa + RuPay sharing one limit); a
    bank account usually has one.
    """

    last4: str = Field(pattern=r"^[0-9]{4,6}$")
    network: Optional[Literal["visa", "rupay", "mastercard", "amex", "diners", "other"]] = None


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
    type: Literal["expense", "income", "card_payment", "blocked"]

    # Decimal, not float — the same reason the column is numeric(12,2).
    # gt=0 mirrors `check (amount > 0)`; direction lives in `type`.
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)

    # All nullable in the schema, so all optional here.
    merchant: Optional[str] = None
    category: Optional[str] = None
    payment_method: Optional[str] = None
    note: Optional[str] = None

    # The account this belongs to. Resolved from account_last4 by
    # app.accounts.resolve_account_id — callers supply the digits and let the
    # lookup fill this in.
    account_id: Optional[int] = None

    # The card or account the message named, as it reported it. One credit
    # account can carry a Visa and a RuPay with different digits, so this is
    # how RuPay (UPI) spend is told apart from Visa (swipe).
    account_last4: Optional[str] = None

    # A real bank reference when the message carries one. Data only — it no
    # longer drives dedupe, and is no longer unique. See ADR 017.
    upi_ref: Optional[str] = None

    # What dedupe actually runs on, derived by the parser rather than read
    # from the message. Null for manual entry, which is why two identical
    # hand-typed rows are allowed: that repetition is usually deliberate.
    dedupe_key: Optional[str] = None

    # What the bank said was left afterwards: "Avl Limit" on a card,
    # "AvlBal" on a bank account. One name, because the reconciliation
    # arithmetic is identical either way.
    reported_balance: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)

    # Who the money went to or came from when there's no business name: a UPI
    # VPA like paytmqr6s4v8c@ptys, or the other party's masked digits.
    counterparty: Optional[str] = None

    # Optional on the way in: if the caller doesn't say when the money moved,
    # the database fills in now(). The SMS parser will pass the real time.
    txn_time: Optional[datetime] = None

    # Not null in the schema, but it has a default, so the caller can omit it.
    source: Literal["manual", "sms", "agent"] = "manual"
