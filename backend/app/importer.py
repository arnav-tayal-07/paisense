"""Bulk import: months of SMS history without months of API quota.

Storing is separated from extracting. A few hundred messages land in raw_sms
instantly and for free; extraction then happens gradually, and mostly without
the model at all.

The trick is that extraction TEACHES. A handful of messages go through the LLM,
those become the ground truth for generating a regex, and the regex then clears
every other message in that format for nothing. Each model call buys a pattern
worth dozens of messages, so 400 messages cost tens of calls rather than 400.

There is a bootstrap problem in that: pattern generation validates against
transactions the model already parsed, and on a fresh import none exist. So the
run alternates — seed a little, learn, sweep for free, repeat.
"""

from collections import defaultdict

from .db import get_conn
from .ingest import _record_pattern_hit, process_raw
from .models import SmsIn
from .patterns import generate, match_message

_INSERT_RAW = """
insert into raw_sms (sender, body, sms_sent_at)
values (%s, %s, %s)
on conflict (sender, body, sms_sent_at) do nothing
returning id
"""

_PENDING = """
select * from raw_sms
where parse_status = 'pending'
order by sms_sent_at desc
limit %s
"""

_STATUS = """
select sender, parse_status, count(*) as n
from raw_sms group by sender, parse_status order by sender, parse_status
"""


def store_batch(messages: list[SmsIn]) -> dict:
    """Store many messages at once. No extraction, so this is fast and free.

    Returns how many were new. Re-running the same import is harmless — the
    unique constraint on (sender, body, sms_sent_at) absorbs repeats, which
    matters because a user who isn't sure whether it worked will press the
    button again.
    """
    stored = 0
    with get_conn() as conn:
        for m in messages:
            row = conn.execute(_INSERT_RAW, (m.sender, m.message, m.sms_sent_at)).fetchone()
            if row is not None:
                stored += 1

    return {"received": len(messages), "stored": stored, "already_had": len(messages) - stored}


def status() -> dict:
    """What's imported, what's waiting, broken down by sender.

    Drives the progress line in the app: "312 of 412 processed".
    """
    with get_conn() as conn:
        rows = conn.execute(_STATUS).fetchall()

    by_sender = defaultdict(dict)
    totals = defaultdict(int)
    for r in rows:
        by_sender[r["sender"]][r["parse_status"]] = r["n"]
        totals[r["parse_status"]] += r["n"]

    done = sum(v for k, v in totals.items() if k != "pending")
    return {
        "pending": totals.get("pending", 0),
        "processed": done,
        "total": done + totals.get("pending", 0),
        "by_status": dict(totals),
        "by_sender": {k: dict(v) for k, v in by_sender.items()},
    }


def _sweep_patterns(limit: int = 500) -> int:
    """Clear every pending message an existing pattern can handle. Free.

    Deliberately does not fall back to the model — anything a pattern misses
    stays pending for the seeding step to decide about.
    """
    cleared = 0
    with get_conn() as conn:
        pending = conn.execute(_PENDING, (limit,)).fetchall()

    for raw in pending:
        with get_conn() as conn:
            hit = match_message(conn, raw["sender"], raw["body"])
        if hit is not None:
            _record_pattern_hit(raw, hit)
            cleared += 1

    return cleared


def _spread_across_senders(rows: list[dict], n: int) -> list[dict]:
    """Pick n messages, round-robin by sender.

    Taking the first n would spend the whole budget on whichever bank texts
    most, and learn nothing about the others. Round-robin means every bank
    gets a pattern before any bank gets a second one.
    """
    buckets = defaultdict(list)
    for r in rows:
        buckets[r["sender"]].append(r)

    picked, i = [], 0
    while len(picked) < n and any(buckets.values()):
        for sender in list(buckets):
            if not buckets[sender]:
                continue
            if i < len(buckets[sender]):
                picked.append(buckets[sender][i])
                if len(picked) >= n:
                    break
        i += 1
        if i > 50:
            break
    return picked


def run(budget: int = 30, seed_per_round: int = 4, sweep_limit: int = 500) -> dict:
    """Work through the pending queue, spending at most `budget` model calls.

    Alternates between learning and sweeping: a few messages through the model,
    regenerate patterns for the senders they came from, then clear everything
    those patterns can now handle for free. Repeat until the queue is empty or
    the budget is gone.

    Safe to call repeatedly. Anything left pending is simply picked up next
    time, which is how an import survives a quota limit — it resumes tomorrow
    rather than failing.
    """
    result = {
        "by_pattern": _sweep_patterns(sweep_limit),
        "by_model": 0,
        "model_calls": 0,
        "patterns_generated": 0,
        "rounds": 0,
    }

    # How many verified samples a sender had the last time we generated for it.
    #
    # "Once per sender per run" was the obvious rule and it was wrong: the one
    # attempt happened early, when a bank had a single sample, and nothing had
    # enough evidence to activate. Regenerating every round is the opposite
    # mistake — generation costs a model call and rewrites the same patterns.
    #
    # The rule that works: regenerate only when meaningfully NEW evidence has
    # arrived, because a format needs two samples before it can be trusted.
    generated_at: dict[str, int] = {}
    seen: dict[str, int] = defaultdict(int)

    while result["model_calls"] < budget:
        with get_conn() as conn:
            pending = conn.execute(_PENDING, (sweep_limit,)).fetchall()

        if not pending:
            break

        seeds = _spread_across_senders(
            pending, min(seed_per_round, budget - result["model_calls"])
        )
        if not seeds:
            break

        touched = set()
        for raw in seeds:
            updated = process_raw(raw)
            result["model_calls"] += 1
            if updated["parse_status"] == "parsed":
                result["by_model"] += 1
                touched.add(raw["sender"])
                seen[_sender_code(raw["sender"])] += 1

        # Learn from what just came back, then let the new patterns pay for
        # themselves on the rest of the queue.
        for sender in touched:
            code = _sender_code(sender)

            # Two new samples since last time. Below that there isn't enough
            # for a second example of any format, so generation would just
            # produce candidates and burn a call doing it.
            if seen[code] - generated_at.get(code, 0) < 2:
                continue

            generated_at[code] = seen[code]
            with get_conn() as conn:
                out = generate(conn, code)
            # Generation is a model call too - counting only extractions
            # under-reported the real cost of an import.
            result["model_calls"] += 1
            result["patterns_generated"] += out.get("active", 0)

        result["by_pattern"] += _sweep_patterns(sweep_limit)
        result["rounds"] += 1

        # A round that learned nothing and cleared nothing will not do better
        # on the next pass — stop rather than burning the whole budget.
        if not touched:
            break

    result["remaining"] = status()["pending"]
    return result


def _sender_code(sender: str) -> str:
    """AX-AXISBK-S -> AXISBK. The middle segment identifies the bank.

    Falls back to the whole header for anything not in DLT shape.
    """
    parts = sender.split("-")
    return parts[1] if len(parts) >= 3 else sender
