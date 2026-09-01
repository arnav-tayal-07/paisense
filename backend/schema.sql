-- PaiSense schema — the source of truth.
-- Supabase's SQL editor is where these get RUN, but this file is what they ARE.
-- Rule: nothing exists in the database that isn't written down here.
-- Order matters: a table must be created before anything that references it.

-- Credit cards. Referenced by transactions.card_id, so it goes first.
create table cards (
  id             bigint generated always as identity primary key,
  name           text not null,
  -- 4-6 digits, not char(4): Amex shows five (***71003). text rather than
  -- char also avoids blank-padding surprises in comparisons.
  last4          text check (last4 ~ '^[0-9]{4,6}$'),
  statement_day  int not null check (statement_day between 1 and 31),
  due_days_after int not null default 20,
  credit_limit   numeric(12, 2),
  created_at     timestamptz not null default now()
);

-- RLS on, no policies. Deny-all for the anon/authenticated roles; the backend
-- connects as the table owner via the session pooler, and owners bypass RLS.
-- If the Data API is ever re-enabled, this table reads as EMPTY until policies
-- exist — it fails silent, not loud. Verified enabled in Supabase 2026-08-29.
alter table cards enable row level security;

-- Every expense and income row. References cards, so it comes after it.
create table transactions (
  id              bigint generated always as identity primary key,

  -- Direction of the money. text + check, not a native enum: adding a third
  -- value later is one line here, vs. an ALTER TYPE migration with an enum.
  -- (Which promptly happened — card_payment was added in migration 001.)
  -- card_payment = paying off a credit card bill. Neither spending nor
  -- earnings: the purchases it settles were already logged as expenses.
  -- Excluded from both totals; stored because due-date reminders need it.
  -- No default — a row that can't say which way the money went isn't a transaction.
  type            text not null check (type in ('expense', 'income', 'card_payment')),

  -- numeric, never float: 0.1 + 0.2 must equal 0.3 when it's someone's money.
  -- 12 digits, 2 decimal = up to 9,999,999,999.99. Always positive; `type`
  -- carries the sign, so a negative amount here would double-count direction.
  amount          numeric(12, 2) not null check (amount > 0),

  -- Nullable: an SMS often parses an amount but no clean merchant name,
  -- and you'd rather store the transaction than reject it.
  merchant        text,

  -- Nullable: uncategorised is a legitimate state. Categorising happens later,
  -- by hand or by the agent. Forcing it at insert time means guessing.
  category        text,

  -- When the money actually moved — not when you recorded it.
  -- timestamptz, so it's an unambiguous instant rather than a wall-clock guess.
  -- Defaults to now() for manual entry; the SMS parser passes the real time.
  txn_time        timestamptz not null default now(),

  -- Real bank reference when the message carries one. NOT unique any more:
  -- dedupe is dedupe_key's job alone, and a second unique constraint would
  -- raise instead of being swallowed by ON CONFLICT (dedupe_key).
  upi_ref         text,

  -- What dedupe actually runs on. DERIVED by the parser, not read from the
  -- message — credit card SMS carry no reference at all, so the key is built
  -- from bank + card + timestamp + amount. Nullable: manual entries have no
  -- natural key, and Postgres treats NULLs as distinct, so any number of
  -- them coexist while a re-scanned SMS collides and is dropped by
  -- ON CONFLICT (dedupe_key) DO NOTHING.
  dedupe_key      text unique,

  -- 'upi' | 'card' | 'cash' | 'netbanking' etc. Left unconstrained for now:
  -- you don't yet know the full set your SMS formats will produce.
  -- Tighten to a check once the parser has seen real messages.
  payment_method  text,

  -- Nullable: only card spends point at a card. No ON DELETE clause, so the
  -- default (no action) blocks deleting a card that still has history —
  -- which is what you want; spending records shouldn't vanish with the card.
  card_id         bigint references cards(id),

  -- How the row got here. Not null with a default because every row has a
  -- provenance, and 'manual' is the honest answer when nothing says otherwise.
  -- Useful later for "trust SMS rows, re-check agent rows".
  source          text not null default 'manual'
                    check (source in ('manual', 'sms', 'agent')),

  -- Free text, always optional.
  note            text,

  -- The card's available limit as reported by the SMS at that moment. On
  -- transactions rather than cards: a column on cards would be one stale
  -- number, whereas the newest row per card gives the current figure and
  -- keeps the history. Null for anything that isn't a card SMS.
  avl_limit       numeric(12, 2),

  -- When the ROW appeared, not when the money moved. Separate from txn_time:
  -- scanning Friday's SMS on Sunday gives txn_time = Friday, created_at = Sunday.
  -- Never set by application code — the database owns this one.
  created_at      timestamptz not null default now()
);

-- Phase 2 will query "this month's spend" constantly; that's a range scan on
-- txn_time. desc because every screen shows newest first.
create index transactions_txn_time_idx on transactions (txn_time desc);

-- For per-card totals and due-date screens. Partial: most rows have no card,
-- and there's no reason to index the NULLs.
create index transactions_card_id_idx on transactions (card_id)
  where card_id is not null;

-- Matches cards. Data API is disabled, but RLS on by default is the right posture.
alter table transactions enable row level security;

