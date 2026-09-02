-- 008 — patterns the LLM writes for itself
--
-- Run once. schema.sql updated to match. See ADR 029.
--
-- The LLM becomes a COMPILER rather than a runtime: it reads a handful of
-- messages from one bank, writes a regex that parses that format, and from
-- then on the regex does the work. Free, instant, deterministic, offline.
-- The model stays as the fallback for anything the pattern misses, and as
-- the author of the next pattern when a bank changes its wording.
--
-- This is what makes importing months of history practical. Several hundred
-- messages through the LLM would exhaust free-tier quota for days; the same
-- messages through a regex take milliseconds.

begin;

create table sms_patterns (
  id            bigint generated always as identity primary key,

  -- The DLT sender segment, e.g. RBLBNK, IDFCFB, BOBSMS. Matched as a
  -- substring of the full header, so VA-RBLBNK-S and VM-RBLBNK-T both hit.
  sender_code   text not null,

  -- Human label, e.g. "RBL UPI debit". One BANK can need several patterns:
  -- RBL sends debits and credits from the same header with different
  -- wording, date formats and reference labels.
  name          text not null,

  -- Regex with NAMED groups. The names ARE the field mapping, so there's no
  -- separate lookup table to drift out of sync with the pattern.
  -- Recognised: amount, merchant, counterparty, account_last4, reference,
  --             occurred, balance
  pattern       text not null,

  -- strptime format for whatever `occurred` captured. Null when the format
  -- has no date at all.
  date_format   text,

  -- Fixed for the format. A pattern matches one shape of message, and that
  -- shape always means the same direction - RBL's "is debited for" is always
  -- an expense, "is credited for" always income.
  txn_type      text not null check (txn_type in ('expense', 'income', 'card_payment')),

  -- candidate -> generated but failed validation, or not yet validated. NOT used.
  -- active    -> reproduced the LLM's own answer on every sample. Trusted.
  -- retired   -> superseded, or started missing too often.
  status        text not null default 'candidate'
                  check (status in ('candidate', 'active', 'retired')),

  -- How many stored messages it was validated against. One sample is not
  -- evidence: RBL's debit format alone would look like the whole story.
  sample_count  int not null default 0,

  -- Runtime counters. A rising miss rate is how a bank announces that it
  -- changed its format, so regeneration triggers on evidence rather than on
  -- a calendar - re-generating a working pattern monthly risks replacing it
  -- with a worse one and never noticing.
  hits          bigint not null default 0,
  misses        bigint not null default 0,

  -- Why it failed validation, when it did. Kept for debugging a bad pattern.
  note          text,

  created_at    timestamptz not null default now(),
  last_used_at  timestamptz
);

-- Every incoming message looks up patterns by sender. Hot path.
create index sms_patterns_lookup_idx on sms_patterns (sender_code)
  where status = 'active';

alter table sms_patterns enable row level security;

-- Deliberately NO owner column. An SMS format belongs to a bank, not to a
-- customer: RBL's message shape is identical for every RBL customer. When
-- PaiSense becomes multi-user, transactions are per-user and patterns stay
-- shared, so one user hitting a new format teaches it for everybody.

commit;
