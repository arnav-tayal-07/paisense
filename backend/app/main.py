"""PaiSense API entry point.

Run from the backend/ folder:
    .venv\\Scripts\\uvicorn.exe app.main:app --reload

Interactive docs once it's up: http://127.0.0.1:8000/docs
"""

from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Response
from psycopg.errors import ForeignKeyViolation

from .db import get_conn
from .ingest import ingest, list_unparsed, reprocess_failed
from .models import SmsIn, TransactionIn
from .transactions import (
    create_transaction,
    delete_transaction,
    get_transaction,
    list_transactions,
)

app = FastAPI(title="PaiSense API")


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
        # card_id pointed at a card that doesn't exist. That's the caller's
        # mistake, so 400 — not a 500, which would imply the server broke.
        raise HTTPException(
            status_code=400,
            detail=f"card_id {txn.card_id} does not exist",
        )

    response.status_code = 201 if created else 200
    return row


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
    return ingest(sms)


@app.get("/sms/unparsed")
def get_unparsed_sms(limit: int = Query(default=50, ge=1, le=200)):
    """Messages needing attention — never attempted, or attempted and failed.

    This is the alarm for a bank changing its message format. Correctly
    ignored OTPs are excluded; including them would bury the signal.
    """
    return list_unparsed(limit)


@app.post("/sms/reprocess")
def post_reprocess_sms(limit: int = Query(default=50, ge=1, le=200)):
    """Retry every failed message. Safe to run any time.

    Use after fixing a prompt or adding a card that transactions couldn't be
    linked to. Replay is only safe because dedupe_key makes re-inserting an
    existing transaction a no-op.
    """
    return reprocess_failed(limit)


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
    card_id: int | None = Query(default=None, description="Spend on one card"),
    start: datetime | None = Query(default=None, description="Inclusive lower bound on txn_time"),
    end: datetime | None = Query(default=None, description="Exclusive upper bound on txn_time"),
):
    """Transactions matching the filters, newest first by txn_time.

    All filters optional and combinable:
      ?type=expense&start=2026-08-01&end=2026-09-01  -> August expenses
      ?merchant=zom                                  -> anything Zomato-ish
    """
    with get_conn() as conn:
        return list_transactions(
            conn,
            limit,
            txn_type=txn_type,
            category=category,
            merchant=merchant,
            card_id=card_id,
            start=start,
            end=end,
        )


@app.get("/transactions/{txn_id}")
def get_transaction_by_id(txn_id: int):
    """One transaction by id."""
    with get_conn() as conn:
        row = get_transaction(conn, txn_id)

    if row is None:
        raise HTTPException(status_code=404, detail=f"No transaction with id {txn_id}")
    return row


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
