-- 001 — make the schema able to hold credit-card SMS
--
-- Run this once in the Supabase SQL editor. schema.sql has been updated to
-- match, so a fresh database built from schema.sql needs none of this.
--
-- Driven by two real messages (Axis AX-AXISBK-S, Amex TX-AMEXIN-S).
-- See ADR 015, 016, 017.

begin;

-- 1. Amex shows FIVE digits (***71003), not four. char(4) physically cannot
--    hold it. char() also blank-pads, which makes equality comparisons
--    surprising later. text plus a digit-shape check.
alter table cards alter column last4 type text using trim(both from last4);

alter table cards add constraint cards_last4_digits
  check (last4 ~ '^[0-9]{4,6}$');

-- 2. A credit-card bill payment is neither spending nor earnings — the
--    purchases it settles were already recorded as expenses when they
--    happened. Counting it either way corrupts the totals. It's still worth
--    storing: Phase 6's due-date reminders need to know a bill was paid.
alter table transactions drop constraint transactions_type_check;

alter table transactions add constraint transactions_type_check
  check (type in ('expense', 'income', 'card_payment'));

-- 3. Card SMS carry no transaction reference at all, so dedupe can no longer
--    hang off upi_ref. dedupe_key is DERIVED by the parser (bank + card +
--    timestamp + amount) rather than read from the message, and is what
--    ON CONFLICT targets from now on. Nullable: manual entries have no
--    natural key, and NULLs never collide, which is the behaviour we want.
alter table transactions add column dedupe_key text;

alter table transactions add constraint transactions_dedupe_key_key
  unique (dedupe_key);

-- 4. upi_ref keeps its data but LOSES its unique constraint. Two unique
--    constraints would be a trap: `on conflict (dedupe_key) do nothing`
--    only swallows dedupe_key collisions, so a upi_ref collision would raise
--    a 500 instead of being quietly ignored. Dedupe is one column's job.
alter table transactions drop constraint transactions_upi_ref_key;

-- 5. Snapshot of the card's available limit at the moment of the transaction.
--    Lives on transactions, not cards: a column on cards would be one stale
--    number, whereas the newest row per card gives the current figure AND
--    keeps the history.
alter table transactions add column avl_limit numeric(12, 2);

commit;
