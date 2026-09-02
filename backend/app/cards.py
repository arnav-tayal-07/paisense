"""Card account lookup.

An SMS gives you four or five digits. The transactions table wants a card_id
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
from card_numbers n
join cards c on c.id = n.card_id
where n.last4 = %s
  and c.issuer_code is not null
  and upper(%s) like '%%' || upper(c.issuer_code) || '%%'
"""

_BY_LAST4 = """
select distinct c.id
from card_numbers n
join cards c on c.id = n.card_id
where n.last4 = %s
"""


def resolve_card_id(conn: Connection, sender: str, last4: str | None) -> int | None:
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


_INSERT_CARD = """
insert into cards (name, issuer_code, statement_day, due_days_after, credit_limit)
values (%s, %s, %s, %s, %s)
returning *
"""

_INSERT_NUMBER = """
insert into card_numbers (card_id, last4, network)
values (%s, %s, %s)
on conflict (card_id, last4) do nothing
returning *
"""

_LIST_CARDS = """
select c.*,
       coalesce(
         json_agg(
           json_build_object('last4', n.last4, 'network', n.network,
                             'is_active', n.is_active)
           order by n.id
         ) filter (where n.id is not null),
         '[]'
       ) as numbers
from cards c
left join card_numbers n on n.card_id = c.id
group by c.id
order by c.id
"""


def create_card(
    conn: Connection,
    name: str,
    statement_day: int,
    issuer_code: str | None = None,
    due_days_after: int = 20,
    credit_limit=None,
) -> dict:
    """Create a card account. Numbers are added separately."""
    return conn.execute(
        _INSERT_CARD,
        (name, issuer_code, statement_day, due_days_after, credit_limit),
    ).fetchone()


def add_card_number(
    conn: Connection, card_id: int, last4: str, network: str | None = None
) -> dict | None:
    """Attach a physical card to an account.

    Returns None if that number is already on this account — re-adding is a
    no-op rather than an error, so setup can safely be re-run.
    """
    return conn.execute(_INSERT_NUMBER, (card_id, last4, network)).fetchone()


def list_cards(conn: Connection) -> list[dict]:
    """All accounts, each with its card numbers nested."""
    return conn.execute(_LIST_CARDS).fetchall()
