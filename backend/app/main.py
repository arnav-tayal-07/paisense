"""PaiSense API entry point.

Run from the backend/ folder:
    .venv\\Scripts\\uvicorn.exe app.main:app --reload

Interactive docs once it's up: http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI, HTTPException, Response
from psycopg.errors import ForeignKeyViolation

from .db import get_conn
from .models import TransactionIn
from .transactions import create_transaction

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


# --- Yours to write: GET /transactions ---
#
# List recent transactions, newest first. Notes in the chat.
