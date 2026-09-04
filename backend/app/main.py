"""PaiSense API entry point.

Run from the backend/ folder:
    .venv\\Scripts\\uvicorn.exe app.main:app --reload

Interactive docs once it's up: http://127.0.0.1:8000/docs
"""

from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Response
from psycopg.errors import ForeignKeyViolation

from .auth import require_api_key
from .db import get_conn
from .serialize import out
from .accounts import (
    add_account_number,
    relink_unlinked,
    create_account,
    get_account,
    list_accounts,
    set_number_active,
    update_account,
)
from .importer import run as run_import, status as import_status, store_batch
from .ingest import ingest, list_ignored, list_unparsed, reprocess_failed
from .patterns import generate as generate_pattern, stats as pattern_stats
from .models import AccountIn, AccountNumberIn, AccountPatch, SmsIn, TransactionIn, TransactionPatch
from .transactions import (
    create_transaction,
    delete_transaction,
    get_transaction,
    list_for_review,
    list_transactions,
    reconcile_account,
    set_review,
    summary as txn_summary,
    update_transaction,
)

app = FastAPI(title="PaiSense API")

# Every route except /health and the docs needs X-API-Key. Registered as
# middleware rather than per-route so a new endpoint is protected by
# default - forgetting to add a dependency is how endpoints leak.
app.middleware("http")(require_api_key)


@app.get("/health")
def health():
    """Proves two things at once: the server is up, and the database answers.

    Worth having before any real route — when a transactions endpoint breaks
    later, this tells you instantly whether it's your SQL or the connection.
    """
    with get_conn() as conn:
        row = conn.execute("select 1 as ok").fetchone()
    return {"status": "ok", "db_connected": row["ok"] == 1}


@app.post("/transactions")
def post_transaction(txn: TransactionIn, response: Response):
    """Create a transaction. Idempotent on upi_ref.

    201 if a new row was written, 200 if this upi_ref already existed and the
    stored row is being returned unchanged. See ADR 012 for why re-sending the
    same SMS is a success rather than an error.
    """
    try:
        with get_conn() as conn:
            row, created = create_transaction(conn, txn)
    except ForeignKeyViolation:
        # account_id pointed at a card that doesn't exist. That's the caller's
        # mistake, so 400 — not a 500, which would imply the server broke.
        raise HTTPException(
            status_code=400,
            detail=f"account_id {txn.account_id} does not exist",
        )

    response.status_code = 201 if created else 200
    return out(row)


@app.post("/sms")
def post_sms(sms: SmsIn):
    """Take one bank SMS, store it, and extract a transaction from it.

    Always 200, even when the message can't be understood. An unparseable
    SMS is a recorded outcome, not a failed request — the phone did its job
    by forwarding it, and the message is stored either way. The response
    says what happened via raw_sms.parse_status:

      parsed  - a transaction was created or matched; transaction_id is set
      ignored - an OTP or marketing message, correctly skipped
      failed  - should have parsed and didn't; parse_error says why
    """
    return out(ingest(sms))


@app.post("/sms/batch")
def post_sms_batch(messages: list[SmsIn]):
    """Store many messages at once WITHOUT extracting them.

    The first-install path: the phone reads months of inbox and sends it in
    batches. Storing is free and instant; extraction happens afterwards via
    /sms/import/run, mostly without the model at all.

    Re-running the same import is harmless - duplicates are absorbed by the
    unique constraint, which matters because someone unsure whether it worked
    will press the button again.
    """
    return out(store_batch(messages))


@app.get("/sms/import/status")
def get_import_status():
    """How much is imported and how much is still waiting, per sender.

    Drives the app's progress line: "312 of 412 processed".
    """
    return out(import_status())


@app.post("/sms/import/run")
def post_import_run(
    budget: int = Query(default=30, ge=1, le=200, description="Max model calls to spend"),
    seed_per_round: int = Query(default=4, ge=1, le=20),
):
    """Work through the pending queue, spending at most `budget` model calls.

    Alternates learning and sweeping: a few messages through the model,
    regenerate patterns from what came back, then clear everything those
    patterns can now handle for free. Each model call buys a pattern worth
    dozens of messages.

    Safe to call repeatedly - whatever is left stays pending and is picked up
    next time, which is how an import survives running out of quota.
    """
    return out(run_import(budget=budget, seed_per_round=seed_per_round))


@app.get("/sms/unparsed")
def get_unparsed_sms(limit: int = Query(default=50, ge=1, le=200)):
    """Messages needing attention — never attempted, or attempted and failed.

    This is the alarm for a bank changing its message format. Correctly
    ignored OTPs are excluded; including them would bury the signal.
    """
    return out(list_unparsed(limit))


@app.post("/sms/reprocess")
def post_reprocess_sms(limit: int = Query(default=50, ge=1, le=200)):
    """Retry every failed message. Safe to run any time.

    Use after fixing a prompt or adding a card that transactions couldn't be
    linked to. Replay is only safe because dedupe_key makes re-inserting an
    existing transaction a no-op.
    """
    return out(reprocess_failed(limit))


@app.get("/sms/ignored")
def get_ignored_sms(limit: int = Query(default=50, ge=1, le=200)):
    """Messages judged not to be transactions.

    Kept out of /sms/unparsed so OTPs don't bury real failures — but exposed
    here because this is the one place a wrongly-dropped spend could hide.
    An ignored row is in no other list and is never retried.
    """
    return out(list_ignored(limit))


@app.post("/sms/patterns/{sender_code}")
def post_generate_pattern(sender_code: str, samples: int = Query(default=8, ge=2, le=20)):
    """Have the model write a regex for one bank's message format.

    Learns from messages it already parsed correctly, so the right answers
    are ground truth already in the database - validation costs no extra API
    calls. A pattern only becomes active if it reproduces the model's own
    answer on EVERY sample.

    After this, messages in that format cost nothing to parse.
    """
    with get_conn() as conn:
        return out(generate_pattern(conn, sender_code, limit=samples))


@app.get("/sms/patterns")
def get_patterns():
    """Every pattern with its hit and miss counts.

    A rising miss rate is how a bank announces it changed its wording -
    which is the trigger to regenerate, rather than doing it on a calendar.
    """
    with get_conn() as conn:
        return out(pattern_stats(conn))


@app.get("/summary")
def get_summary(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
):
    """Money grouped the way it needs to be read.

    Credit card spending is money owed but not yet paid; account spending is
    money already gone; a card bill payment is neither, because the purchases
    it settles were counted when they happened (ADR 016). Keeping them apart
    is the difference between a total you can act on and one you can't.
    """
    with get_conn() as conn:
        return out(txn_summary(conn, start, end))


@app.post("/accounts/relink")
def post_relink():
    """Attach transactions that couldn't find an account when they arrived.

    Registering an account does nothing retroactively on its own, so anything
    that failed to resolve stays unlinked and invisible to per-account totals.
    Run this after adding an account.
    """
    with get_conn() as conn:
        return out(relink_unlinked(conn))


@app.get("/transactions/review")
def get_review_queue(limit: int = Query(default=50, ge=1, le=200)):
    """Transactions awaiting a tick, each with the SMS it came from.

    Flagged when the extraction was suspicious: two models disagreed, the
    amount equals the available limit exactly, or the card isn't registered.
    Everything else lands as 'auto' and never appears here — a queue you
    scroll past without reading is worse than no queue.
    """
    with get_conn() as conn:
        return out(list_for_review(conn, limit))


@app.post("/transactions/{txn_id}/confirm")
def post_confirm_transaction(txn_id: int):
    """Green tick. The transaction starts counting toward totals."""
    with get_conn() as conn:
        row = set_review(conn, txn_id, "confirmed")
    if row is None:
        raise HTTPException(status_code=404, detail=f"No transaction {txn_id} awaiting review")
    return out(row)


@app.post("/transactions/{txn_id}/reject")
def post_reject_transaction(txn_id: int):
    """Red cross: the extraction was wrong. Excluded from every total.

    Marked, not deleted — the audit trail matters, and a deleted row would
    simply be recreated by the next inbox re-scan.

    This means "the parser got it wrong", NOT "I didn't make this purchase".
    A charge you don't recognise is a bank dispute, not a database edit; the
    dispute number is in the stored message.
    """
    with get_conn() as conn:
        row = set_review(conn, txn_id, "rejected")
    if row is None:
        raise HTTPException(status_code=404, detail=f"No transaction {txn_id} awaiting review")
    return out(row)


@app.patch("/transactions/{txn_id}")
def patch_transaction(txn_id: int, changes: TransactionPatch):
    """Correct a transaction. Only the fields you send are touched.

    The main use is the review card: often the honest answer isn't tick or
    cross but "yes I bought that, it was ₹2,000 not ₹10,170". Without this
    you'd have to reject a real transaction and lose it.

    Does NOT change review_status — confirm is a separate, deliberate act.
    Editing a value and accepting it are different decisions, and collapsing
    them would mean a stray edit silently marks something reviewed.
    """
    try:
        with get_conn() as conn:
            row = update_transaction(conn, txn_id, changes.model_dump(exclude_unset=True))
    except ForeignKeyViolation:
        raise HTTPException(status_code=400, detail=f"account_id {changes.account_id} does not exist")

    if row is None:
        raise HTTPException(status_code=404, detail=f"No transaction with id {txn_id}")
    return out(row)


@app.post("/accounts", status_code=201)
def post_account(account: AccountIn):
    """Create a credit card account or a bank account.

    An account is the thing money belongs to; the card or account NUMBERS on
    it are a separate table, because one credit account can carry a Visa and
    a RuPay sharing a single limit (ADR 020, 026).
    """
    with get_conn() as conn:
        return out(create_account(
            conn,
            name=account.name,
            kind=account.kind,
            statement_day=account.statement_day,
            issuer_code=account.issuer_code,
            due_days_after=account.due_days_after,
            credit_limit=account.credit_limit,
            due_day=account.due_day,
        ))


@app.get("/accounts")
def get_accounts():
    """All accounts, each with its physical cards nested."""
    with get_conn() as conn:
        return out(list_accounts(conn))


@app.patch("/accounts/{account_id}")
def patch_account(account_id: int, changes: AccountPatch):
    """Edit an account — the app's edit button.

    Setting one due rule clears the other, so switching from "due 20 days
    after" to "due on the 8th" is a single field, not two.
    """
    with get_conn() as conn:
        row = update_account(conn, account_id, changes.model_dump(exclude_unset=True))
    if row is None:
        raise HTTPException(status_code=404, detail=f"No account with id {account_id}")
    return out(row)


@app.post("/accounts/{account_id}/numbers", status_code=201)
def post_account_number(account_id: int, number: AccountNumberIn):
    """Attach a physical card. Re-adding an existing one is a no-op."""
    with get_conn() as conn:
        if get_account(conn, account_id) is None:
            raise HTTPException(status_code=404, detail=f"No card with id {account_id}")
        row = add_account_number(conn, account_id, number.last4, number.network)
        if row is None:
            raise HTTPException(
                status_code=409,
                detail=f"{number.last4} is already on card {account_id}",
            )
        return out(row)


@app.patch("/accounts/{account_id}/numbers/{last4}")
def patch_account_number(account_id: int, last4: str, is_active: bool):
    """Retire or restore a physical card after reissue.

    Never deletes: an old SMS from the replaced card must still resolve to
    this account, so history survives a reissue.
    """
    with get_conn() as conn:
        row = set_number_active(conn, account_id, last4, is_active)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{last4} is not on card {account_id}")
    return out(row)


@app.get("/accounts/{account_id}/reconcile")
def get_account_reconciliation(account_id: int):
    """Check recorded spending against the bank's own available-limit figures.

    Between two consecutive card SMS the limit should move by exactly the
    later transaction's amount. If it moved further, a transaction happened
    that was never recorded. This is the only check that can detect a
    MISSING message — everything else can only inspect ones that arrived.
    """
    with get_conn() as conn:
        return out(reconcile_account(conn, account_id))


@app.get("/transactions")
def get_transactions(
    # A plain argument with a default becomes a query parameter: ?limit=20.
    # le=200 caps it, so ?limit=999999 is rejected with a 422 rather than
    # dragging the whole table across the wire once this is real data.
    limit: int = Query(default=50, ge=1, le=200),
    # alias="type" keeps the query parameter named ?type= while the Python
    # argument avoids shadowing the built-in `type`.
    txn_type: Literal["expense", "income", "card_payment"] | None = Query(
        default=None, alias="type"
    ),
    category: str | None = None,
    merchant: str | None = Query(default=None, description="Case-insensitive partial match"),
    account_id: int | None = Query(default=None, description="Spend on one card"),
    start: datetime | None = Query(default=None, description="Inclusive lower bound on txn_time"),
    end: datetime | None = Query(default=None, description="Exclusive upper bound on txn_time"),
    include_unreviewed: bool = Query(
        default=False,
        description="Include rows awaiting review or rejected. Off by default so totals stay honest.",
    ),
):
    """Transactions matching the filters, newest first by txn_time.

    All filters optional and combinable:
      ?type=expense&start=2026-08-01&end=2026-09-01  -> August expenses
      ?merchant=zom                                  -> anything Zomato-ish
    """
    with get_conn() as conn:
        return out(list_transactions(
            conn,
            limit,
            txn_type=txn_type,
            category=category,
            merchant=merchant,
            account_id=account_id,
            start=start,
            end=end,
            countable_only=not include_unreviewed,
        ))


@app.get("/transactions/{txn_id}")
def get_transaction_by_id(txn_id: int):
    """One transaction by id."""
    with get_conn() as conn:
        row = get_transaction(conn, txn_id)

    if row is None:
        raise HTTPException(status_code=404, detail=f"No transaction with id {txn_id}")
    return out(row)


@app.delete("/transactions/{txn_id}", status_code=204)
def delete_transaction_by_id(txn_id: int):
    """Delete one transaction.

    204 No Content on success — there's nothing meaningful to return, and the
    row is gone. 404 if it never existed, so the agent's delete_expense tool
    can tell "removed it" from "there was nothing to remove" and say so.
    """
    with get_conn() as conn:
        deleted = delete_transaction(conn, txn_id)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"No transaction with id {txn_id}")
