"""Transaction data access.

The SQL lives here, not in the routes. Phase 3's POST /sms will parse a bank
message into a TransactionIn and call create_transaction() — the same function
this phase's route calls. One insert path, two entry points, no duplicated
ON CONFLICT handling.
"""

from datetime import datetime
from decimal import Decimal

from psycopg import Connection

from .models import TransactionIn

# %s placeholders, never f-strings or .format(). psycopg sends the values
# separately from the statement, so a merchant literally named
# "'; drop table transactions; --" is stored as text, not executed.
_INSERT = """
insert into transactions
  (type, amount, merchant, category, txn_time,
   upi_ref, dedupe_key, payment_method, account_id, account_last4,
   source, note, reported_balance, counterparty)
values
  (%s, %s, %s, %s, coalesce(%s, now()),
   %s, %s, %s, %s, %s,
   %s, %s, %s, %s)
on conflict (dedupe_key) do nothing
returning *
"""

_SELECT_BY_DEDUPE_KEY = "select * from transactions where dedupe_key = %s"


def create_transaction(conn: Connection, txn: TransactionIn) -> tuple[dict, bool]:
    """Insert a transaction. Returns (row, created).

    created=False means this dedupe_key was already in the table and the
    existing row is being returned untouched — the SMS re-scan case.
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
        txn.dedupe_key,
        txn.payment_method,
        txn.account_id,
        txn.account_last4,
        txn.source,
        txn.note,
        txn.reported_balance,
        txn.counterparty,
    )

    row = conn.execute(_INSERT, params).fetchone()

    # THE TRAP: `on conflict do nothing` combined with `returning *` returns
    # NO ROW when it conflicts. fetchone() gives None — not the existing row.
    # So a conflict needs a second query to go get it.
    if row is not None:
        return row, True

    # Only reachable when dedupe_key collided — a NULL key can't conflict,
    # because Postgres treats every NULL as distinct.
    existing = conn.execute(_SELECT_BY_DEDUPE_KEY, (txn.dedupe_key,)).fetchone()
    return existing, False


def list_transactions(
    conn: Connection,
    limit: int,
    *,
    txn_type: str | None = None,
    category: str | None = None,
    merchant: str | None = None,
    source: str | None = None,
    account_id: int | None = None,
    account_kind: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    countable_only: bool = True,
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
        ("source = %s", source),
        # Spend per card. The SMS gives a last4 string; the parser resolves
        # that to a account_id, so filtering happens on the foreign key.
        ("account_id = %s", account_id),
        # Card spending vs account spending, decided server-side. The app used
        # to pull every expense and filter locally, which needed a limit above
        # the 200 cap and returned 422.
        ("account_id in (select id from accounts where kind = %s)", account_kind),
        # Half-open interval: start <= txn_time < end. Using <= on both ends
        # would double-count a transaction landing exactly at midnight on the
        # boundary when the agent asks for two consecutive months.
        ("txn_time >= %s", start),
        ("txn_time < %s", end),
    ]

    conditions = [sql for sql, value in filters if value is not None]
    params = [value for _, value in filters if value is not None]

    # Default excludes anything awaiting a tick or already crossed out. If
    # unreviewed rows counted toward totals, flagging them would achieve
    # nothing — the wrong number would still be in your monthly spend.
    if countable_only:
        conditions.append("review_status in ('auto', 'confirmed')")

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


_SELECT_REVIEW = """
select t.*, r.body as source_message, r.sender as source_sender
from transactions t
left join raw_sms r on r.transaction_id = t.id
where t.review_status = 'pending'
order by t.txn_time desc
limit %s
"""

# `and review_status = 'pending'` makes this idempotent: ticking twice is a
# no-op rather than resurrecting something already rejected.
_SET_REVIEW = """
update transactions set review_status = %s
where id = %s and review_status = 'pending'
returning *
"""


def list_for_review(conn: Connection, limit: int = 50) -> list[dict]:
    """Transactions awaiting a human tick, with the message they came from.

    The original SMS travels with the row on purpose — the whole point of the
    card is comparing what was extracted against what the bank actually said.
    """
    return conn.execute(_SELECT_REVIEW, (limit,)).fetchall()


def set_review(conn: Connection, txn_id: int, status: str) -> dict | None:
    """Confirm or reject. None if the row isn't pending review."""
    return conn.execute(_SET_REVIEW, (status, txn_id)).fetchone()


_RECONCILE = """
select id, txn_time, type, amount, reported_balance, merchant, account_last4
from transactions
where account_id = %s and reported_balance is not null
  and review_status in ('auto', 'confirmed')
order by txn_time
"""


def reconcile_account(conn: Connection, account_id: int) -> dict:
    """Check recorded spending against the bank's own available-limit figures.

    Every card SMS reports the limit remaining afterwards. Between two
    consecutive messages the limit should move by exactly the amount of the
    later transaction — down for a spend, up for a bill payment. If it moved
    further than that, a transaction happened that was never recorded, and
    the arithmetic says so without needing to read any message.

    This is the only check that can catch a MISSING transaction. Everything
    else can only inspect messages that did arrive.
    """
    rows = conn.execute(_RECONCILE, (account_id,)).fetchall()
    gaps = []

    for prev, curr in zip(rows, rows[1:]):
        observed = prev["reported_balance"] - curr["reported_balance"]
        # A spend reduces the available limit; paying the bill restores it.
        expected = curr["amount"] if curr["type"] != "card_payment" else -curr["amount"]
        unexplained = observed - expected

        if unexplained != 0:
            gaps.append(
                {
                    "between": [prev["id"], curr["id"]],
                    "from": prev["txn_time"].isoformat(),
                    "to": curr["txn_time"].isoformat(),
                    "unexplained_amount": str(unexplained),
                    "note": (
                        "limit fell further than recorded spending - a transaction is missing"
                        if unexplained > 0
                        else "limit fell less than recorded spending - an amount may be wrong"
                    ),
                }
            )

    return {
        "account_id": account_id,
        "checked": len(rows),
        "gaps": gaps,
        # Fewer than two datapoints means nothing can be compared yet.
        "conclusive": len(rows) >= 2,
    }


_SUMMARY = """
select
  case
    -- Income you TYPED IN. A bank credit is not income: it might be a
    -- refund, a friend settling a split, a cheque, or you moving your own
    -- money between accounts. One of Arnav's credits is literally himself.
    -- Counting those as earnings makes the figure meaningless, so only a
    -- manual entry counts and SMS credits are reported separately.
    when t.type = 'income' and t.source = 'manual' then 'income'
    when t.type = 'income'       then 'received'

    -- 'blocked' is a legal type but nothing produces it any more: the
    -- extractor now refuses IPO and mandate blocks outright as not being
    -- transactions at all. Kept in the CASE so an old row can't silently
    -- fall through into a spending bucket.
    when t.type = 'blocked'      then 'blocked'

    -- A card bill payment generates TWO messages: the bank says money left
    -- the account, the card says money arrived. One event, two notifications,
    -- and counting both doubled the total. Only the bank side is a real
    -- outflow; the card side is its mirror, kept for computing what the card
    -- still owes but never added to any total.
    when t.type = 'card_payment' and a.kind = 'credit_card' then 'card_payment_mirror'
    when t.type = 'card_payment' then 'card_payment'
    when a.kind = 'credit_card'  then 'card_spend'
    when a.kind = 'bank_account' then 'account_spend'
    else 'unlinked'
  end as bucket,
  count(*) as count,
  sum(t.amount) as total
from transactions t
left join accounts a on a.id = t.account_id
where t.review_status in ('auto', 'confirmed')
  and (%s::timestamptz is null or t.txn_time >= %s)
  and (%s::timestamptz is null or t.txn_time <  %s)
group by 1
"""


def summary(conn: Connection, start=None, end=None) -> dict:
    """Money grouped the way it actually needs to be read.

    Five buckets, and the distinctions are real rather than cosmetic:

    - `income` is money in.
    - `card_spend` is credit card purchases — money you owe but haven't paid.
    - `account_spend` is UPI and bank debits — money already gone.
    - `card_payment` is settling a card bill. Counting it as spending would
      double-count every purchase it settles (ADR 016), so it stands alone.
    - `unlinked` is spending whose account couldn't be identified. Shown
      rather than hidden: silently dropping it would make the totals wrong
      in a way nothing announces.
    """
    rows = conn.execute(_SUMMARY, (start, start, end, end)).fetchall()
    buckets = {r["bucket"]: {"count": r["count"], "total": r["total"]} for r in rows}

    # Decimal("0"), not 0. An int here serialises as a JSON number while every
    # populated bucket serialises as a string, and a client that expects one
    # type gets the other the moment a bucket happens to be empty. That is
    # exactly what broke the app the first day someone had no manual income.
    for key in ("income", "received", "card_spend", "account_spend",
                "card_payment", "card_payment_mirror", "blocked", "unlinked"):
        buckets.setdefault(key, {"count": 0, "total": Decimal("0")})

    spent = buckets["card_spend"]["total"] + buckets["account_spend"]["total"]
    income = buckets["income"]["total"]
    return {
        "buckets": buckets,
        # Deliberately excludes card_payment: a bill payment is not new
        # spending, it settles purchases already counted.
        "total_spent": spent,
        # Only entries the user typed. Bank credits are in "received" and
        # stay out of this figure - see the bucket comment above.
        "total_income": income,
        "net": income - spent,
    }


_SELECT_BY_ID = "select * from transactions where id = %s"


def get_transaction(conn: Connection, txn_id: int) -> dict | None:
    """One transaction by id, or None if there's no such row."""
    return conn.execute(_SELECT_BY_ID, (txn_id,)).fetchone()


# `returning id` is what makes this tell the difference between "deleted one
# row" and "there was nothing to delete". A bare DELETE succeeds either way.
def update_transaction(conn: Connection, txn_id: int, changes: dict) -> dict | None:
    """Apply a partial update. None if there's no such row.

    Column names come from a fixed allow-list, never from the request — the
    caller passes a Pydantic model's `exclude_unset` dump, so only fields the
    client actually sent are present, and only known columns are accepted.
    Values still travel as %s parameters (ADR 013).
    """
    allowed = {
        "type",
        "amount",
        "merchant",
        "category",
        "txn_time",
        "payment_method",
        "account_id",
        "counterparty",
        "note",
    }
    fields = {k: v for k, v in changes.items() if k in allowed}
    if not fields:
        return conn.execute(_SELECT_BY_ID, (txn_id,)).fetchone()

    assignments = ", ".join(f"{col} = %s" for col in fields)
    params = list(fields.values()) + [txn_id]
    return conn.execute(
        f"update transactions set {assignments} where id = %s returning *", params
    ).fetchone()


_DELETE_BY_ID = "delete from transactions where id = %s returning id"


def delete_transaction(conn: Connection, txn_id: int) -> bool:
    """Delete one transaction. Returns True if a row was actually removed."""
    return conn.execute(_DELETE_BY_ID, (txn_id,)).fetchone() is not None