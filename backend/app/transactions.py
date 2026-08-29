"""Transaction data access.

The SQL lives here, not in the routes. Phase 3's POST /sms will parse a bank
message into a TransactionIn and call create_transaction() — the same function
this phase's route calls. One insert path, two entry points, no duplicated
ON CONFLICT handling.
"""

from datetime import datetime

from psycopg import Connection

from .models import TransactionIn

# %s placeholders, never f-strings or .format(). psycopg sends the values
# separately from the statement, so a merchant literally named
# "'; drop table transactions; --" is stored as text, not executed.
_INSERT = """
insert into transactions
  (type, amount, merchant, category, txn_time,
   upi_ref, payment_method, card_id, source, note)
values
  (%s, %s, %s, %s, coalesce(%s, now()),
   %s, %s, %s, %s, %s)
on conflict (upi_ref) do nothing
returning *
"""

_SELECT_BY_REF = "select * from transactions where upi_ref = %s"


def create_transaction(conn: Connection, txn: TransactionIn) -> tuple[dict, bool]:
    """Insert a transaction. Returns (row, created).

    created=False means this upi_ref was already in the table and the existing
    row is being returned untouched — the SMS re-scan case.
    """
    params = (
        txn.type,
        txn.amount,
        txn.merchant,
        txn.category,
        # coalesce(%s, now()) in the SQL: pass None and the database supplies
        # the time. Keeps "what time is it" the database's job, not Python's,
        # so a laptop with a wrong clock can't write a wrong txn_time.
        txn.txn_time,
        txn.upi_ref,
        txn.payment_method,
        txn.card_id,
        txn.source,
        txn.note,
    )

    row = conn.execute(_INSERT, params).fetchone()

    # THE TRAP: `on conflict do nothing` combined with `returning *` returns
    # NO ROW when it conflicts. fetchone() gives None — not the existing row.
    # So a conflict needs a second query to go get it.
    if row is not None:
        return row, True

    existing = conn.execute(_SELECT_BY_REF, (txn.upi_ref,)).fetchone()
    return existing, False


def list_transactions(
    conn: Connection,
    limit: int,
    *,
    txn_type: str | None = None,
    category: str | None = None,
    merchant: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict]:
    """Transactions matching the given filters, newest first.

    Every filter is optional; passing none of them returns the most recent
    `limit` rows. Phase 4's agent tools map onto this directly — monthly_total
    is start/end, search is merchant.
    """
    # Each entry pairs a SQL fragment with its value. The fragments are
    # hard-coded strings written here; only the values are user input, and
    # those still travel as %s parameters. That distinction is what keeps the
    # f-string below safe — see ADR 013.
    filters = [
        ("type = %s", txn_type),
        ("category = %s", category),
        # ilike = case-insensitive LIKE. Wrapping in % makes it a contains
        # match, so "zom" finds "Zomato".
        ("merchant ilike %s", f"%{merchant}%" if merchant else None),
        # Half-open interval: start <= txn_time < end. Using <= on both ends
        # would double-count a transaction landing exactly at midnight on the
        # boundary when the agent asks for two consecutive months.
        ("txn_time >= %s", start),
        ("txn_time < %s", end),
    ]

    conditions = [sql for sql, value in filters if value is not None]
    params = [value for _, value in filters if value is not None]

    where = f"where {' and '.join(conditions)}" if conditions else ""

    # txn_time desc, not id — id is insertion order, so an SMS scanned on
    # Sunday for a Friday purchase would surface as if it had just happened.
    query = f"""
        select * from transactions
        {where}
        order by txn_time desc
        limit %s
    """
    params.append(limit)

    return conn.execute(query, params).fetchall()


_SELECT_BY_ID = "select * from transactions where id = %s"


def get_transaction(conn: Connection, txn_id: int) -> dict | None:
    """One transaction by id, or None if there's no such row."""
    return conn.execute(_SELECT_BY_ID, (txn_id,)).fetchone()


# `returning id` is what makes this tell the difference between "deleted one
# row" and "there was nothing to delete". A bare DELETE succeeds either way.
_DELETE_BY_ID = "delete from transactions where id = %s returning id"


def delete_transaction(conn: Connection, txn_id: int) -> bool:
    """Delete one transaction. Returns True if a row was actually removed."""
    return conn.execute(_DELETE_BY_ID, (txn_id,)).fetchone() is not None