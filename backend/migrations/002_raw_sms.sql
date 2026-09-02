-- 002 — store every incoming SMS, parsed or not
--
-- Run once in the Supabase SQL editor. schema.sql is updated to match.
-- See ADR 018.
--
-- The point: without this, a bank changing its message format means those
-- transactions are gone for good. The phone's inbox is the only copy, and
-- you won't notice for weeks. With it, a format change is a backlog you
-- replay later instead of data you lost.

begin;

create table raw_sms (
  id              bigint generated always as identity primary key,

  -- DLT header, e.g. AX-AXISBK-S. What routing keys off.
  sender          text not null,

  -- The message, exactly as received. Never cleaned up or normalised —
  -- this is the evidence, and a "helpful" transformation here would be
  -- invisible later when a parse goes wrong.
  body            text not null,

  -- When the PHONE says the message arrived, not when the server heard
  -- about it. The two differ by however long the app was closed.
  sms_sent_at     timestamptz not null,

  -- When this row reached the backend.
  received_at     timestamptz not null default now(),

  -- pending -> not yet attempted
  -- parsed  -> produced a transaction
  -- ignored -> recognised as a non-transaction (OTP, marketing, balance alert)
  -- failed  -> should have parsed and didn't; THIS is the early-warning list
  parse_status    text not null default 'pending'
                    check (parse_status in ('pending', 'parsed', 'ignored', 'failed')),

  -- Why it failed, when it did. Free text, for debugging a format change.
  parse_error     text,

  parsed_at       timestamptz,

  -- The row this message produced, if any. ON DELETE SET NULL: deleting a
  -- transaction must not delete the evidence it came from.
  transaction_id  bigint references transactions(id) on delete set null,

  created_at      timestamptz not null default now()
);

-- The phone re-uploads its inbox on every open, so the same message arrives
-- repeatedly. Same sender + same text + same send time IS the same message.
-- Without this, raw_sms grows without bound.
alter table raw_sms add constraint raw_sms_unique_message
  unique (sender, body, sms_sent_at);

-- Drives GET /sms/unparsed — the "a bank changed something" alarm.
-- Partial: 'parsed' and 'ignored' rows are the overwhelming majority and
-- there's no reason to index them.
create index raw_sms_needs_attention_idx on raw_sms (received_at desc)
  where parse_status in ('pending', 'failed');

alter table raw_sms enable row level security;

commit;
