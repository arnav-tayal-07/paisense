"""Transaction data access.

The SQL lives here, not in the routes. Phase 3's POST /sms will parse a bank
message into a TransactionIn and call create_transaction() — the same function
this phase's route calls. One insert path, two entry points, no duplicated
ON CONFLICT handling.
"""

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
