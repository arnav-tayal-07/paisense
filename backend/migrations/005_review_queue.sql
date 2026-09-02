-- 005 — human review for uncertain extractions
--
-- Run once in the Supabase SQL editor. schema.sql updated to match.
-- See ADR 024.
--
-- The guardrail in sms.py catches an INVENTED amount. It cannot catch three
-- other failures:
--   1. the model calls a real spend "not a transaction"  -> silently dropped
--   2. the model picks the wrong real number from the message (every IDFC
--      message contains both a spend amount and an available limit)
--   3. a transaction whose card can't be resolved is stored unlinked
--
-- None of those announce themselves. This adds a queue the user can tick or
-- cross, plus the provenance needed to retry on a DIFFERENT model — retrying
-- on the same one at temperature 0 reproduces the same mistake exactly.

begin;

-- auto      -> extracted confidently, counts immediately
-- pending   -> needs a human tick, excluded from totals until then
-- confirmed -> user ticked it
-- rejected  -> user crossed it. Kept, not deleted: the audit trail matters,
--              and a deleted row would be re-created by the next re-scan.
alter table transactions add column review_status text not null default 'auto'
  check (review_status in ('auto', 'pending', 'confirmed', 'rejected'));

-- Why it was flagged, shown on the review card so the user knows what to
-- check rather than guessing.
alter table transactions add column review_reason text;

-- The review queue is a small slice of a large table.
create index transactions_review_idx on transactions (txn_time desc)
  where review_status = 'pending';

-- Totals and listings read this constantly.
create index transactions_countable_idx on transactions (txn_time desc)
  where review_status in ('auto', 'confirmed');

-- needs_review: the message looks like it contains money but no transaction
-- could be extracted from it. Distinct from 'ignored' (confidently not a
-- transaction) and 'failed' (the provider broke).
alter table raw_sms drop constraint raw_sms_parse_status_check;
alter table raw_sms add constraint raw_sms_parse_status_check
  check (parse_status in ('pending', 'parsed', 'ignored', 'failed', 'needs_review'));

-- Which model produced the last extraction, so a retry can deliberately pick
-- a different one. Same model at temperature 0 gives the same answer, so a
-- blind retry of a hallucination reproduces it.
alter table raw_sms add column model text;

commit;
