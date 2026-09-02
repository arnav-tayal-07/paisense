"""Card account lookup.

An SMS gives you four or five digits. The transactions table wants a account_id
pointing at an account. This is the bit in between, and it is deliberately
cautious: a wrong link is worse than no link, because a transaction attributed
to the wrong card quietly corrupts that card's totals, while an unlinked one
is visible and fixable (re-run it after adding the card — raw_sms keeps every
message and dedupe_key makes the replay safe).
"""

from psycopg import Connection

# Matching on issuer first. Two banks can legitimately issue cards ending in
# the same four digits, and the DLT sender header is the only part of an SMS
# that reliably identifies the bank — Amex never names itself in the body.
#
# Inactive numbers are included on purpose: an old SMS from a card that has
# since been reissued should still resolve to the right account. is_active
# governs what's offered as current, not what history links to.
_BY_ISSUER_AND_LAST4 = """
select c.id
from account_numbers n
join accounts c on c.id = n.account_id
where n.last4 = %s
  and c.issuer_code is not null
  and upper(%s) like '%%' || upper(c.issuer_code) || '%%'
"""

_BY_LAST4 = """
select distinct c.id
from account_numbers n
join accounts c on c.id = n.account_id
where n.last4 = %s
"""


def resolve_account_id(conn: Connection, sender: str, last4: str | None) -> int | None:
    """Find the account a card number belongs to. None if unsure.

    Three outcomes, and the third is the one that matters:
      - issuer + last4 match exactly one account -> that account
      - no issuer match, but last4 matches exactly one account -> that account
      - last4 matches several accounts and the issuer can't separate them
        -> None, because guessing would silently corrupt a card's totals
    """
    if not last4:
        return None

    rows = conn.execute(_BY_ISSUER_AND_LAST4, (last4, sender or "")).fetchall()
    if len(rows) == 1:
        return rows[0]["id"]

    # Either no card has an issuer_code set yet, or the sender didn't match
    # one. Fall back to the digits alone — but only if they're unambiguous.
    rows = conn.execute(_BY_LAST4, (last4,)).fetchall()
    if len(rows) == 1:
        return rows[0]["id"]

    return None


_INSERT_ACCOUNT = """
insert into accounts (name, kind, issuer_code, statement_day, due_days_after, due_day, credit_limit)
values (%s, %s, %s, %s, %s, %s, %s)
returning *
"""

_INSERT_NUMBER = """
insert into account_numbers (account_id, last4, network)
values (%s, %s, %s)
on conflict (account_id, last4) do nothing
returning *
"""

_LIST_ACCOUNTS = """
select c.*,
       coalesce(
         json_agg(
           json_build_object('last4', n.last4, 'network', n.network,
                             'is_active', n.is_active)
           order by n.id
         ) filter (where n.id is not null),
         '[]'
       ) as numbers
from accounts c
left join account_numbers n on n.account_id = c.id
group by c.id
order by c.id
"""


def create_account(
    conn: Connection,
    name: str,
    kind: str = "credit_card",
    statement_day: int | None = None,
    issuer_code: str | None = None,
    due_days_after: int | None = None,
    credit_limit=None,
    due_day: int | None = None,
) -> dict:
    """Create a card account. Numbers are added separately.

    Exactly one of due_day / due_days_after must be set — the database
    enforces it (ADR 021). Both default to None so neither is set by
    accident; the caller has to say which rule this card uses.
    """
    return conn.execute(
        _INSERT_ACCOUNT,
        (name, kind, issuer_code, statement_day, due_days_after, due_day, credit_limit),
    ).fetchone()


def add_account_number(
    conn: Connection, account_id: int, last4: str, network: str | None = None
) -> dict | None:
    """Attach a physical card to an account.

    Returns None if that number is already on this account — re-adding is a
    no-op rather than an error, so setup can safely be re-run.
    """
    return conn.execute(_INSERT_NUMBER, (account_id, last4, network)).fetchone()


def list_accounts(conn: Connection) -> list[dict]:
    """All accounts, each with its card numbers nested."""
    return conn.execute(_LIST_ACCOUNTS).fetchall()


def get_account(conn: Connection, account_id: int) -> dict | None:
    return conn.execute("select * from accounts where id = %s", (account_id,)).fetchone()


def update_account(conn: Connection, account_id: int, changes: dict) -> dict | None:
    """Partial update to an account. None if there's no such card.

    Setting one due rule clears the other. The database enforces that exactly
    one is set, so sending `due_day` on a card that currently uses
    `due_days_after` would otherwise violate the constraint and surface as a
    500 — when what the user meant was obviously "switch to a fixed day".
    """
    allowed = {
        "name",
        "kind",
        "issuer_code",
        "statement_day",
        "due_day",
        "due_days_after",
        "credit_limit",
        "is_active",
    }
    fields = {k: v for k, v in changes.items() if k in allowed}

    if "due_day" in fields and "due_days_after" not in fields:
        fields["due_days_after"] = None
    elif "due_days_after" in fields and "due_day" not in fields:
        fields["due_day"] = None

    if not fields:
        return get_account(conn, account_id)

    assignments = ", ".join(f"{col} = %s" for col in fields)
    params = list(fields.values()) + [account_id]
    return conn.execute(
        f"update accounts set {assignments} where id = %s returning *", params
    ).fetchone()


def set_number_active(conn: Connection, account_id: int, last4: str, is_active: bool) -> dict | None:
    """Retire or restore a physical card.

    Retiring does not delete: historical SMS from a reissued card must still
    resolve to the right account. is_active governs what's offered as current,
    not what history links to.
    """
    return conn.execute(
        "update account_numbers set is_active = %s where account_id = %s and last4 = %s returning *",
        (is_active, account_id, last4),
    ).fetchone()
