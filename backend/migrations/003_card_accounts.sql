-- 003 — separate the credit account from the physical cards on it
--
-- Run once in the Supabase SQL editor. schema.sql is updated to match.
-- See ADR 020.
--
-- Driving case: one IDFC FIRST account, one credit limit, one statement and
-- one due date — but two physical cards (Visa and RuPay) with different last4
-- digits. RuPay-plus-Visa on a single account is standard in India now,
-- because RuPay is what links to UPI, so this is not an edge case.
--
-- Modelling them as two rows in `cards` would store one credit limit twice,
-- duplicate the statement and due dates, and make "spend on my IDFC card"
-- a sum across rows that something will eventually forget to do.
--
-- `cards` is empty, so nothing needs migrating — this is a restructure.

begin;

-- ---------------------------------------------------------------------
-- 1. cards becomes the ACCOUNT: one limit, one statement, one due date
-- ---------------------------------------------------------------------

-- last4 belongs to a piece of plastic, not to an account.
alter table cards drop constraint if exists cards_last4_digits;
alter table cards drop column if exists last4;

-- The DLT sender segment for this issuer: AXISBK, IDFCFB, AMEXIN, HDFCBK...
-- Used to disambiguate lookups — two banks can legitimately issue cards
-- ending in the same four digits, and the sender header is the only thing
-- in an SMS that reliably says which bank sent it.
alter table cards add column issuer_code text;

-- A closed card must keep its history but stop appearing in due-date
-- reminders and "which cards do I have" lists.
alter table cards add column is_active boolean not null default true;

comment on column cards.statement_day is
  'Day of month the statement generates. Values 29-31 must be clamped to the '
  'last day of shorter months when computing due dates.';

-- ---------------------------------------------------------------------
-- 2. card_numbers: the physical cards on an account
-- ---------------------------------------------------------------------

create table card_numbers (
  id          bigint generated always as identity primary key,

  -- Deleting an account removes its cards: a card number is meaningless
  -- without the account it belongs to. Transactions are NOT affected —
  -- they point at cards(id) and that FK still blocks deleting an account
  -- with spending history.
  card_id     bigint not null references cards(id) on delete cascade,

  -- 4 digits normally, 5 for Amex. Same rule the old cards.last4 had.
  last4       text not null check (last4 ~ '^[0-9]{4,6}$'),

  network     text check (network in ('visa', 'rupay', 'mastercard', 'amex', 'diners', 'other')),

  -- Reissued or expired cards keep their row so historical SMS still
  -- resolve, but stop being offered as the current card.
  is_active   boolean not null default true,

  created_at  timestamptz not null default now(),

  -- The same number can't be registered twice on one account. Deliberately
  -- NOT globally unique: two different banks issuing cards ending 3577 is
  -- legitimate, and the resolver disambiguates by issuer instead.
  constraint card_numbers_unique_per_card unique (card_id, last4)
);

-- Every SMS triggers a lookup by last4, so this is the hot path.
create index card_numbers_last4_idx on card_numbers (last4);

alter table card_numbers enable row level security;

-- ---------------------------------------------------------------------
-- 3. transactions: record WHICH physical card, not just which account
-- ---------------------------------------------------------------------

-- Stored as text rather than a foreign key to card_numbers, on purpose:
-- this is a snapshot of what the message actually said, in the same spirit
-- as raw_sms. It survives a card row being edited or deleted, needs no
-- join to read, and can't drift from the evidence. card_id still carries
-- the real relationship for aggregation.
--
-- Lets you split RuPay (UPI) spending from Visa (swipe) on one account.
alter table transactions add column card_last4 text;

commit;
