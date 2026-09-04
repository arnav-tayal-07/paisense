"""Credit card bills, counted from the current cycle only.

**The deliberate simplification.** Everything before the current billing cycle
is assumed settled: no carried-forward balance, no interest, no minimum-due
tracking. Arnav asked for this explicitly, and it is the right call — those
figures cannot be derived from one month of imported SMS, and a guess at them
would be worse than not showing them.

What that buys: every number here is computable from transactions inside one
bounded window, so it is exact rather than approximate.

What it costs: if a previous bill genuinely went unpaid, this understates what
is owed. Revisit only if that starts happening.

The cycle rule lives on the account (statement day, plus either a fixed due day
or an offset — ADR 021), so any cycle is computed on demand. Two things the
date maths must get right, and both only break in February:

- **Clamping.** Statement day 31 becomes 28 or 29 in February, 30 in April.
  Constructing date(2026, 2, 31) raises.
- **Rolling over.** Once this month's statement has generated, the open cycle
  is the next one.

Nothing is read from the balance figures banks put in messages: those are
snapshots, stale the moment anything else happens, and meaningless against a
credit limit that has since changed.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from psycopg import Connection

IST = timezone(timedelta(hours=5, minutes=30))


def _clamp(year: int, month: int, day: int) -> date:
    """That day of the month, or the last day if the month is shorter."""
    return date(year, month, min(day, monthrange(year, month)[1]))


def _add_month(d: date) -> tuple[int, int]:
    return (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)


def _prev_statement(stmt: date, statement_day: int) -> date:
    y, m = (stmt.year - 1, 12) if stmt.month == 1 else (stmt.year, stmt.month - 1)
    return _clamp(y, m, statement_day)


def cycle_for(account: dict, today: date | None = None) -> dict | None:
    """The cycle running right now, and when its bill falls due.

    None for a bank account, which has no statement or due date.
    """
    if account.get("kind") != "credit_card" or not account.get("statement_day"):
        return None

    today = today or datetime.now(IST).date()
    statement_day = account["statement_day"]

    # The statement that will close the cycle we are in. If this month's has
    # already generated, the open cycle closes next month.
    statement = _clamp(today.year, today.month, statement_day)
    if today > statement:
        y, m = _add_month(statement)
        statement = _clamp(y, m, statement_day)

    # The cycle began the day after the previous statement.
    cycle_start = _prev_statement(statement, statement_day) + timedelta(days=1)

    if account.get("due_day"):
        # A fixed day of the month AFTER the statement.
        y, m = _add_month(statement)
        due = _clamp(y, m, account["due_day"])
    else:
        due = statement + timedelta(days=account.get("due_days_after") or 20)

    return {
        "cycle_start": cycle_start.isoformat(),
        "statement_date": statement.isoformat(),
        "due_date": due.isoformat(),
        "days_until_due": (due - today).days,
        "days_until_statement": (statement - today).days,
    }


_CYCLE_TOTALS = """
select
  coalesce(sum(case when type = 'expense'      then amount else 0 end), 0) as spent,
  count(*) filter (where type = 'expense')                                 as spend_count,
  coalesce(sum(case when type = 'card_payment' then amount else 0 end), 0) as paid
from transactions
where account_id = %s
  and review_status in ('auto', 'confirmed')
  and txn_time >= %s::date
"""


def dues(conn: Connection) -> list[dict]:
    """Every credit card: this cycle's spending, and what's left to spend.

    - `cycle_spend`   charged since the cycle began
    - `paid`          paid during this cycle (clearing the previous bill)
    - `available`     credit limit minus this cycle's spending
    - `due_date`      when this cycle's bill must be paid

    Everything before the cycle start is assumed settled, so these are exact
    for the window they cover rather than approximations of an all-time
    balance we have no way to compute.
    """
    accounts = conn.execute(
        "select * from accounts where kind = 'credit_card' and is_active order by id"
    ).fetchall()

    out = []
    for account in accounts:
        cycle = cycle_for(account)
        if cycle is None:
            continue

        totals = conn.execute(
            _CYCLE_TOTALS, (account["id"], cycle["cycle_start"])
        ).fetchone()

        limit = account.get("credit_limit")
        # Available is the limit minus what has been charged this cycle.
        # Payments are NOT added back: they cleared the previous bill, which
        # this model already assumes settled — counting them again would
        # inflate the headroom.
        available = (limit - totals["spent"]) if limit is not None else None

        out.append(
            {
                "account_id": account["id"],
                "name": account["name"],
                "credit_limit": limit,
                **cycle,
                "cycle_spend": totals["spent"],
                "cycle_count": totals["spend_count"],
                "paid": totals["paid"],
                "available": available,
                # The one input only the user can supply.
                "needs_limit": limit is None,
            }
        )

    return out
