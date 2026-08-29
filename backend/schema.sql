-- PaiSense schema — the source of truth.
-- Supabase's SQL editor is where these get RUN, but this file is what they ARE.
-- Rule: nothing exists in the database that isn't written down here.
-- Order matters: a table must be created before anything that references it.

-- Credit cards. Referenced by transactions.card_id, so it goes first.
create table cards (
  id             bigint generated always as identity primary key,
  name           text not null,
  last4          char(4),
  statement_day  int not null check (statement_day between 1 and 31),
  due_days_after int not null default 20,
  credit_limit   numeric(12, 2),
  created_at     timestamptz not null default now()
);

-- Every expense and income row. References cards, so it comes after it.
create table transactions (
  id              bigint generated always as identity primary key,

  -- Direction of the money. text + check, not a native enum: adding a third
  -- value later is one line here, vs. an ALTER TYPE migration with an enum.
  -- No default — a row that can't say which way the money went isn't a transaction.
  type            text not null check (type in ('expense', 'income')),

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

  -- The dedupe key. Nullable because cash and manual entries have no UPI ref.
  -- unique + nullable is the trick: Postgres treats NULLs as distinct, so any
  -- number of cash rows coexist, while a re-scanned SMS collides on its ref
  -- and gets dropped by ON CONFLICT (upi_ref) DO NOTHING.
  upi_ref         text unique,

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

