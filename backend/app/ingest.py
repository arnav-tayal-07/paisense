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
set parse_status = %s, parse_error = %s, transaction_id = %s,
    model = %s, parsed_at = now()
where id = %s
returning *
"""

# needs_review is included: a message containing money that nothing could read
# is exactly as much of an alarm as an outright failure.
_SELECT_UNPARSED = """
select * from raw_sms
where parse_status in ('pending', 'failed', 'needs_review')
order by received_at desc
limit %s
"""

# Deliberately separate from the alarm list. These are messages two models
# agreed were not transactions — almost always right, but the only place a
# wrongly-dropped spend could be hiding, so it has to be inspectable.
_SELECT_IGNORED = """
select * from raw_sms
where parse_status = 'ignored'
order by received_at desc
limit %s
"""

_MARK_REVIEW = """
update transactions set review_status = 'pending', review_reason = %s
where id = %s and review_status = 'auto'
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
    # Avoid the model that answered last time. A retry on the same model at
    # temperature 0 returns the same answer, so it would only ever confirm
    # its own mistake.
    result = extract(raw["sender"], raw["body"], avoid_model=raw.get("model"))

    if result.status != "parsed":
        # ignored / needs_review / failed all land here, kept distinct so a
        # genuine miss isn't buried among correctly-skipped OTPs.
        with get_conn() as conn:
            return conn.execute(
                _UPDATE_RAW, (result.status, result.error, None, result.model, raw["id"])
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

        # Money that belongs to a card we can't identify won't appear in any
        # per-card total, and nothing else would ever mention it.
        reason = result.review_reason
        if reason is None and result.card_last4 and txn.card_id is None:
            reason = f"card ending {result.card_last4} is not registered"

        if reason:
            conn.execute(_MARK_REVIEW, (reason, row["id"]))

        return conn.execute(
            _UPDATE_RAW, ("parsed", None, row["id"], result.model, raw["id"])
        ).fetchone()


def ingest(sms: SmsIn) -> dict:
    """Full path for one incoming message.

    Never raises on a message it can't understand — an unparseable SMS is a
    recorded outcome, not a failed request. The phone did its job by sending
    it, and the message is safely stored either way.
    """
    raw, is_new = store_raw(sms)

    if not is_new:
        # Already seen. Re-parse only if the last attempt didn't produce a
        # usable result — re-running a successful parse is a wasted LLM call,
        # and re-running a confident 'ignored' just burns quota on OTPs.
        if raw["parse_status"] in ("failed", "needs_review", "pending"):
            raw = process_raw(raw)
        return {"raw_sms": raw, "duplicate": True}

    return {"raw_sms": process_raw(raw), "duplicate": False}


def list_unparsed(limit: int = 50) -> list[dict]:
    """Messages needing attention: never attempted, failed, or unreadable.

    The early warning that a bank changed its format. Confidently-ignored
    rows are excluded — including OTPs would bury the real signal.
    """
    with get_conn() as conn:
        return conn.execute(_SELECT_UNPARSED, (limit,)).fetchall()


def list_ignored(limit: int = 50) -> list[dict]:
    """Messages judged not to be transactions.

    Almost all of these are correct. It exists because it's the one place a
    wrongly-dropped spend could hide: an 'ignored' row is in no other list,
    is never retried, and would otherwise be invisible forever.
    """
    with get_conn() as conn:
        return conn.execute(_SELECT_IGNORED, (limit,)).fetchall()


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
