"""LLM-generated regex patterns: the model as compiler, not runtime.

The expensive part of reading an SMS is asking a model to understand it. But
a bank sends the same shape of message every time, so that understanding only
has to happen once. The model reads a few stored messages, writes a regex that
parses that shape, and from then on the regex does the work — free, instant,
deterministic, and offline.

The model remains the fallback for anything no pattern matches, and the author
of the next pattern when a bank rewrites its wording.

The dangerous failure is NOT "the pattern doesn't match" — that falls through
to the model and costs one API call. It's "the pattern matches and captures
the wrong field", which would silently produce wrong numbers forever with
nothing to notice it. Hence validate_pattern(): a generated pattern must
reproduce the model's own answer on every sample before it is trusted.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from psycopg import Connection

from .llm import LLMError, LLMProvider, default_provider

# India has no daylight saving, so a fixed offset is exact. Duplicated from
# sms.py rather than imported to keep this module free of that dependency —
# patterns are the cheap path and shouldn't drag the LLM path in with them.
IST = timezone(timedelta(hours=5, minutes=30))

# Group names the runtime knows how to use. Anything else the model invents is
# ignored rather than silently mis-assigned.
KNOWN_GROUPS = {
    "amount",
    "merchant",
    "counterparty",
    "account_last4",
    "reference",
    "occurred",
    "balance",
}

# A list, not a single pattern. One sender routinely sends several formats —
# RBL debits and credits differ in wording, date format AND reference label,
# and IDFC sends card purchases alongside standing-instruction charges.
# Asking for one pattern per sender either fails or, worse, produces something
# that spans two shapes and captures the wrong field from one of them.
GENERATION_SCHEMA = {
    "type": "object",
    "properties": {
        "patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short label, e.g. 'RBL UPI debit'."},
                    "pattern": {
                        "type": "string",
                        "description": "Python regex with named groups, matching only its own samples.",
                    },
                    "date_format": {
                        "type": "string",
                        "description": "strptime format for the 'occurred' group. Null if no date.",
                        "nullable": True,
                    },
                    "txn_type": {"type": "string", "enum": ["expense", "income", "card_payment"]},
                    "sample_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "0-based indices of the samples this pattern covers.",
                    },
                },
                "required": ["name", "pattern", "date_format", "txn_type", "sample_indices"],
            },
        }
    },
    "required": ["patterns"],
}

INSTRUCTIONS = """\
You write Python regular expressions that extract fields from Indian bank SMS.

You are given messages from ONE bank, numbered from 0, plus the values already \
extracted from each. The bank sends several different message formats. \
GROUP them by format and write one regex per group.

Use named groups. Only these names are understood:
  amount          the transaction amount, digits only, commas allowed
  merchant        a business name, when the message contains one
  counterparty    a UPI VPA or the other party's masked account digits
  account_last4   the trailing digits of the OWNER's account or card
  reference       the transaction reference / UPI Ref / RRN
  occurred        the date and time exactly as printed, as one substring
  balance         the available limit or balance stated afterwards

Rules:
- Each regex must match every sample listed in its own sample_indices, and \
should NOT match samples belonging to a different group.
- Use re.search semantics, not fullmatch.
- Capture only what varies. Anchor on the fixed wording around it.
- Prefer explicit character classes over .* - a greedy wildcard will swallow \
neighbouring fields and capture the wrong value.
- Omit a group entirely if that field is absent from the format.
- date_format must parse the 'occurred' group with datetime.strptime. If a \
format carries no date, omit the occurred group and set date_format null.
- txn_type describes what that message FORMAT always means, not one instance.
- Every sample index must appear in exactly one group.
"""


@dataclass
class PatternResult:
    """One pattern's attempt at a message."""

    fields: dict
    pattern_id: int


def _rows(conn: Connection, sender_code: str) -> list[dict]:
    return conn.execute(
        """
        select * from sms_patterns
        where status = 'active' and upper(%s) like '%%' || upper(sender_code) || '%%'
        order by hits desc, id
        """,
        (sender_code,),
    ).fetchall()


def match_message(conn: Connection, sender: str, body: str) -> PatternResult | None:
    """Try every active pattern for this sender. None if none match.

    Ordered by hit count, so the format you actually receive most often is
    tried first — for a bank sending five kinds of message, that's usually
    one comparison instead of five.
    """
    for row in _rows(conn, sender):
        try:
            m = re.search(row["pattern"], body, re.IGNORECASE | re.DOTALL)
        except re.error:
            # A pattern that no longer compiles is worse than no pattern.
            conn.execute(
                "update sms_patterns set status='retired', note=%s where id=%s",
                ("failed to compile at runtime", row["id"]),
            )
            continue

        if not m:
            continue

        fields = _decode(m, row)
        if fields is None:
            # Matched but produced nothing usable — count it as a miss so the
            # miss rate reflects reality rather than looking healthy.
            conn.execute("update sms_patterns set misses = misses + 1 where id=%s", (row["id"],))
            continue

        conn.execute(
            "update sms_patterns set hits = hits + 1, last_used_at = now() where id=%s",
            (row["id"],),
        )
        return PatternResult(fields=fields, pattern_id=row["id"])

    return None


def _decode(m: re.Match, row: dict) -> dict | None:
    """Turn regex groups into typed values. None if the essentials are missing."""
    groups = {k: v for k, v in m.groupdict().items() if k in KNOWN_GROUPS and v}

    raw_amount = groups.get("amount")
    if not raw_amount:
        return None

    try:
        amount = Decimal(raw_amount.replace(",", "").strip())
    except InvalidOperation:
        return None
    if amount <= 0:
        return None

    occurred = None
    if groups.get("occurred") and row["date_format"]:
        try:
            occurred = datetime.strptime(groups["occurred"].strip(), row["date_format"])
        except ValueError:
            # The field moved or the format changed. Fall through to the model
            # rather than storing a wrong date.
            return None

    balance = None
    if groups.get("balance"):
        try:
            balance = Decimal(groups["balance"].replace(",", "").strip())
        except InvalidOperation:
            balance = None

    return {
        "type": row["txn_type"],
        "amount": amount,
        "merchant": groups.get("merchant"),
        "counterparty": groups.get("counterparty"),
        "account_last4": groups.get("account_last4"),
        "reference": groups.get("reference"),
        "occurred_at": occurred,
        "reported_balance": balance,
    }


_SAMPLES = """
select r.body, t.amount, t.merchant, t.counterparty, t.account_last4,
       t.upi_ref, t.txn_time, t.reported_balance, t.type
from raw_sms r
join transactions t on t.id = r.transaction_id
where r.parse_status = 'parsed'
  and upper(r.sender) like '%%' || upper(%s) || '%%'
  and t.review_status in ('auto', 'confirmed')
order by r.received_at desc
limit %s
"""


def generate(
    conn: Connection,
    sender_code: str,
    limit: int = 8,
    provider: LLMProvider | None = None,
) -> dict:
    """Write and validate a pattern for one sender from stored messages.

    Uses transactions the model has ALREADY extracted as ground truth, so
    validation costs no extra API calls — the right answers are in the
    database, put there by the model itself.
    """
    samples = conn.execute(_SAMPLES, (sender_code, limit)).fetchall()

    if len(samples) < 2:
        # One sample is not evidence. RBL's debit format alone would look
        # like the whole story and silently drop every credit.
        return {
            "sender_code": sender_code,
            "generated": False,
            "reason": f"need at least 2 parsed messages, have {len(samples)}",
        }

    provider = provider or default_provider()

    payload = json.dumps(
        [
            {
                "message": s["body"],
                "extracted": {
                    "amount": str(s["amount"]),
                    "merchant": s["merchant"],
                    "counterparty": s["counterparty"],
                    "account_last4": s["account_last4"],
                    "reference": s["upi_ref"],
                    "balance": str(s["reported_balance"]) if s["reported_balance"] else None,
                    "type": s["type"],
                },
            }
            for s in samples
        ],
        indent=2,
    )

    try:
        spec = provider.extract_json(INSTRUCTIONS, payload, GENERATION_SCHEMA)
    except LLMError as e:
        return {"sender_code": sender_code, "generated": False, "reason": str(e)}

    results = []

    for group in spec.get("patterns", []):
        indices = [i for i in group.get("sample_indices", []) if 0 <= i < len(samples)]
        mine = [samples[i] for i in indices]

        if not mine:
            continue

        ok, note = validate(group, mine)

        # One sample can be reproduced by a pattern that simply hard-codes it.
        # Passing on a single example is not evidence, so it stays a candidate
        # until a second message of that format arrives.
        status = "active" if (ok and len(mine) >= 2) else "candidate"
        if ok and len(mine) < 2:
            note = f"{note} - needs a second sample before it can be trusted"

        row = conn.execute(
            """
            insert into sms_patterns
              (sender_code, name, pattern, date_format, txn_type, status, sample_count, note)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            returning *
            """,
            (
                sender_code.upper(),
                group["name"],
                group["pattern"],
                group.get("date_format"),
                group["txn_type"],
                status,
                len(mine),
                note,
            ),
        ).fetchone()

        results.append(
            {
                "pattern_id": row["id"],
                "name": row["name"],
                "status": row["status"],
                "samples": len(mine),
                "note": note,
            }
        )

    return {
        "sender_code": sender_code,
        "generated": bool(results),
        "formats_found": len(results),
        "active": sum(1 for r in results if r["status"] == "active"),
        "patterns": results,
    }


def validate(spec: dict, samples: list[dict]) -> tuple[bool, str]:
    """Does this pattern reproduce the model's own answers on every sample?

    This is the whole safety mechanism. A pattern that fails to match is
    harmless — it falls back to the model. A pattern that matches and captures
    the WRONG field would produce wrong numbers forever with nothing to notice,
    so nothing becomes active without agreeing on every single sample.
    """
    try:
        rx = re.compile(spec["pattern"], re.IGNORECASE | re.DOTALL)
    except re.error as e:
        return False, f"pattern does not compile: {e}"

    unknown = set(rx.groupindex) - KNOWN_GROUPS
    if unknown:
        return False, f"unknown group names: {sorted(unknown)}"

    fake_row = {"txn_type": spec["txn_type"], "date_format": spec.get("date_format")}

    for i, s in enumerate(samples):
        m = rx.search(s["body"])
        if not m:
            return False, f"sample {i} did not match"

        got = _decode(m, fake_row)
        if got is None:
            return False, f"sample {i} matched but produced no usable amount"

        if got["amount"] != s["amount"]:
            return False, f"sample {i}: amount {got['amount']} != {s['amount']}"

        if got["type"] != s["type"]:
            return False, f"sample {i}: type {got['type']} != {s['type']}"

        # A reference is the dedupe key, so a near-miss here is worse than
        # not capturing it at all.
        if s["upi_ref"] and got["reference"] and got["reference"] != s["upi_ref"]:
            return False, f"sample {i}: reference {got['reference']!r} != {s['upi_ref']!r}"

        if s["txn_time"] and got["occurred_at"]:
            # A pattern produces a naive datetime in local (IST) terms, because
            # that's how the message is written. The stored value is an aware
            # timestamptz, which psycopg hands back in UTC. Stripping tzinfo
            # without converting first compares 10:05 IST against 04:35 UTC —
            # the same instant, five and a half hours apart on paper.
            want = s["txn_time"].astimezone(IST).replace(tzinfo=None)
            if got["occurred_at"].replace(tzinfo=None) != want:
                return False, f"sample {i}: date {got['occurred_at']} != {want} (IST)"

    return True, f"validated against {len(samples)} samples"


def stats(conn: Connection) -> list[dict]:
    """Every pattern with its hit and miss counts.

    A rising miss rate is how a bank tells you it changed its wording.
    """
    return conn.execute(
        """
        select id, sender_code, name, status, sample_count, hits, misses,
               case when hits + misses = 0 then null
                    else round(misses::numeric / (hits + misses), 3)
               end as miss_rate,
               note, created_at, last_used_at
        from sms_patterns
        order by sender_code, status, id
        """
    ).fetchall()
