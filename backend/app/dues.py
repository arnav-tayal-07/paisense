"""When the next credit card bill is due, and how much is on it.

The account stores a RULE (statement day, plus either a fixed due day or an
offset) rather than dates, so any cycle can be computed on demand and nothing
needs generating in advance — see ADR 021.

Two things this has to get right, and both are the kind of bug that only shows
up in February:

- **Clamping.** A statement day of 31 has to become 28 or 29 in February, and
  30 in April. Naively constructing date(2026, 2, 31) raises.
- **Which cycle you are in.** On the 20th with a statement on the 24th, the
  current bill is still open and its due date is next month. On the 25th the
  statement has already generated, so the following cycle is the one to show.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from psycopg import Connection

IST = timezone(timedelta(hours=5, minutes=30))


def _clamp(year: int, month: int, day: int) -> date:
    """The given day of that month, or its last day if the month is shorter."""
    return date(year, month, min(day, monthrange(year, month)[1]))


def _add_month(d: date) -> tuple[int, int]:
    return (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)


def cycle_for(account: dict, today: date | None = None) -> dict | None:
    """The billing cycle currently accumulating, and when it must be paid.

    Returns None for a bank account, which has no statement or due date.
    """
    if account.get("kind") != "credit_card" or not account.get("statement_day"):
        return None

    today = today or datetime.now(IST).date()
    statement_day = account["statement_day"]

    def due_for(stmt: date) -> date:
        if account.get("due_day"):
            # Fixed day of the month AFTER the statement.
            y, m = _add_month(stmt)
            return _clamp(y, m, account["due_day"])
        return stmt + timedelta(days=account.get("due_days_after") or 20)

    # The statement that closes the cycle currently accumulating. If this
    # month's statement has already generated, the open cycle closes next month.
    next_stmt = _clamp(today.year, today.month, statement_day)
    if today > next_stmt:
        y, m = _add_month(next_stmt)
        next_stmt = _clamp(y, m, statement_day)

    cycle_start = _prev_statement(next_stmt, statement_day) + timedelta(days=1)

    # THE BILL YOU ACTUALLY OWE NEXT.
    #
    # Reporting only the accumulating cycle was wrong and dangerously so: with
    # a statement on the 24th, on 4 September the open cycle closes 24
    # September and is due 8 October — but the statement generated on 24 August
    # is due on 8 SEPTEMBER, four days away. Showing October would have let a
    # bill go unpaid while the app said there was a month to spare.
    last_stmt = _prev_statement(next_stmt, statement_day)
    last_due = due_for(last_stmt)

    # Once that bill's due date has passed, the next one owed is the upcoming
    # statement's.
    if last_due < today:
        last_stmt, last_due = next_stmt, due_for(next_stmt)

    return {
        # The payment to make next, and what it covers.
        "due_date": last_due.isoformat(),
        "days_until_due": (last_due - today).days,
        "billed_statement_date": last_stmt.isoformat(),
        # The cycle still accumulating — spending here lands on a LATER bill.
        "cycle_start": cycle_start.isoformat(),
        "statement_date": next_stmt.isoformat(),
        "cycle_due_date": due_for(next_stmt).isoformat(),
    }


def _prev_statement(stmt: date, statement_day: int) -> date:
    y, m = (stmt.year - 1, 12) if stmt.month == 1 else (stmt.year, stmt.month - 1)
    return _clamp(y, m, statement_day)


_CYCLE_SPEND = """
select coalesce(sum(amount), 0) as total, count(*) as count
from transactions
where account_id = %s and type = 'expense'
  and review_status in ('auto', 'confirmed')
  and txn_time >= %s and txn_time < %s
"""

_OUTSTANDING = """
select
  coalesce(sum(case when type = 'expense'      then amount else 0 end), 0)
- coalesce(sum(case when type = 'card_payment' then amount else 0 end), 0) as owed
from transactions
where account_id = %s and review_status in ('auto', 'confirmed')
"""


def dues(conn: Connection) -> list[dict]:
    """Every credit card account with its next payment date and what's on it.

    `outstanding` is every purchase ever made on the card minus every bill
    payment — what you owe right now. `cycle_spend` is only what has landed
    since the last statement, which is what the NEXT bill will ask for. They
    are different numbers and confusing them is how people underpay.
    """
    accounts = conn.execute(
        "select * from accounts where kind = 'credit_card' and is_active order by id"
    ).fetchall()

    out = []
    for account in accounts:
        cycle = cycle_for(account)
        if cycle is None:
            continue

        spend = conn.execute(
            _CYCLE_SPEND, (account["id"], cycle["cycle_start"], cycle["statement_date"])
        ).fetchone()
        owed = conn.execute(_OUTSTANDING, (account["id"],)).fetchone()

        # The bank's own figure, if a recent card SMS carried one.
        reported = conn.execute(
            """select reported_balance from transactions
               where account_id = %s and reported_balance is not null
               order by txn_time desc limit 1""",
            (account["id"],),
        ).fetchone()
        available = reported["reported_balance"] if reported else None

        # Prefer the bank's arithmetic: limit minus what's still available IS
        # what you owe, and it needs no history at all. Deriving it from our
        # own rows requires every purchase since the account opened, which we
        # don't have — that produced a NEGATIVE outstanding, because the bill
        # payments we recorded settled purchases from before the import window.
        if account.get("credit_limit") is not None and available is not None:
            outstanding = account["credit_limit"] - available
            reason = None
        elif owed["owed"] >= 0:
            outstanding = owed["owed"]
            reason = None
        else:
            outstanding = None
            reason = (
                "set the card's credit limit to compute this — our own history "
                "starts mid-cycle, so bill payments exceed recorded purchases"
            )

        out.append(
            {
                "account_id": account["id"],
                "name": account["name"],
                "credit_limit": account["credit_limit"],
                **cycle,
                "cycle_spend": spend["total"],
                "cycle_count": spend["count"],
                "outstanding": outstanding,
                "outstanding_unknown_reason": reason,
                # What the bank last said was left to spend.
                "available_limit": available,
            }
        )

    return out
