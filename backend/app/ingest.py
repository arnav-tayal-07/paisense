"""Ingesting an SMS: store it, read it, record what happened.

The ordering here is the whole point of ADR 018. The message is stored and
COMMITTED before extraction is attempted, in its own database connection.
If the LLM call times out, the quota runs out, or the process dies mid-request,
the message is already durably on disk and can be replayed. Doing both in one
transaction would roll the message away along with the failure — which is
exactly the data loss the table exists to prevent.
"""

from datetime import datetime, timezone

from .cards import resolve_card_id
from .db import get_conn
from .models import SmsIn
from .sms import extract
from .transactions import create_transaction

# ON CONFLICT DO NOTHING against (sender, body, sms_sent_at): the phone
# re-uploads its inbox on every open, so the same message arrives repeatedly.
_INSERT_RAW = """
insert into raw_sms (sender, body, sms_sent_at)
values (%s, %s, %s)
on conflict (sender, body, sms_sent_at) do nothing
returning *
"""

_SELECT_RAW = """
select * from raw_sms
where sender = %s and body = %s and sms_sent_at = %s
"""

_UPDATE_RAW = """
update raw_sms
set parse_status = %s, parse_error = %s, transaction_id = %s, parsed_at = now()
where id = %s
returning *
"""

_SELECT_UNPARSED = """
select * from raw_sms
where parse_status in ('pending', 'failed')
order by received_at desc
limit %s
"""


def store_raw(sms: SmsIn) -> tuple[dict, bool]:
    """Persist the message. Returns (row, is_new).

    is_new=False means this exact message was already stored — the re-scan
    case. The caller skips re-extraction, which saves an LLM call on every
    message in the inbox every time the app opens.
    """
    with get_conn() as conn:
        row = conn.execute(_INSERT_RAW, (sms.sender, sms.message, sms.sms_sent_at)).fetchone()
        if row is not None:
            return row, True
        existing = conn.execute(
            _SELECT_RAW, (sms.sender, sms.message, sms.sms_sent_at)
        ).fetchone()
        return existing, False


def process_raw(raw: dict) -> dict:
    """Extract a stored message and record the outcome. Returns the updated row.

    Runs the LLM call OUTSIDE any open database connection, so a slow or
    hanging provider doesn't hold a connection from the pool.
    """
    result = extract(raw["sender"], raw["body"])

    if result.status != "parsed":
        # 'ignored' (an OTP) and 'failed' (should have worked) both land here,
        # kept distinct so a genuine failure isn't buried among OTPs.
        with get_conn() as conn:
            return conn.execute(
                _UPDATE_RAW, (result.status, result.error, None, raw["id"])
            ).fetchone()

    with get_conn() as conn:
        txn = result.txn
        # Digits -> account. Returns None when unknown or ambiguous, and the
        # transaction is stored unlinked rather than mis-linked. Replaying
        # this message after adding the card fixes it.
        txn.card_id = resolve_card_id(conn, raw["sender"], result.card_last4)

        # created=False means dedupe_key already existed — a message that
        # produced this transaction before. Still link the raw row to it, so
        # every copy of the message points at the transaction it describes.
        row, _created = create_transaction(conn, txn)

        return conn.execute(
            _UPDATE_RAW, ("parsed", None, row["id"], raw["id"])
        ).fetchone()


def ingest(sms: SmsIn) -> dict:
    """Full path for one incoming message.

    Never raises on a message it can't understand — an unparseable SMS is a
    recorded outcome, not a failed request. The phone did its job by sending
    it, and the message is safely stored either way.
    """
    raw, is_new = store_raw(sms)

    if not is_new:
        # Already seen. Re-parse only if the last attempt failed — a retry
        # after fixing a prompt or a card is useful, re-running a successful
        # parse is a wasted LLM call.
        if raw["parse_status"] == "failed":
            raw = process_raw(raw)
        return {"raw_sms": raw, "duplicate": True}

    return {"raw_sms": process_raw(raw), "duplicate": False}


def list_unparsed(limit: int = 50) -> list[dict]:
    """Messages that need attention: never attempted, or attempted and failed.

    This is the early warning that a bank changed its format. 'ignored' rows
    are deliberately excluded — an OTP that was correctly skipped is not a
    problem, and including them would bury the real signal.
    """
    with get_conn() as conn:
        return conn.execute(_SELECT_UNPARSED, (limit,)).fetchall()


def reprocess_failed(limit: int = 50) -> dict:
    """Replay everything that failed. Safe to run any time.

    Replay is only safe because dedupe_key (ADR 017) makes re-inserting a
    transaction a no-op. Without it this would duplicate every row it touched.
    """
    rows = list_unparsed(limit)
    outcomes = {"parsed": 0, "ignored": 0, "failed": 0, "pending": 0}
    for raw in rows:
        updated = process_raw(raw)
        outcomes[updated["parse_status"]] += 1
    return {"attempted": len(rows), **outcomes}
