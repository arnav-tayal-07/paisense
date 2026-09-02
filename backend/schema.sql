-- PaiSense schema — the source of truth.
-- Supabase's SQL editor is where these get RUN, but this file is what they ARE.
-- Rule: nothing exists in the database that isn't written down here.
-- Order matters: a table must be created before anything that references it.

-- A credit ACCOUNT: one credit limit, one statement date, one due date.
-- Not one piece of plastic — see card_numbers below. Referenced by
-- transactions.card_id, so it goes first.
create table cards (
  id             bigint generated always as identity primary key,
  name           text not null,

  -- DLT sender segment for the issuer: AXISBK, IDFCFB, AMEXIN, HDFCBK...
  -- Disambiguates lookups. Two banks can legitimately issue cards ending in
  -- the same four digits, and the sender header is the only part of an SMS
  -- that reliably identifies the bank — Amex never names itself in the body.
  issuer_code    text,

  -- Day the bill is generated. Values 29-31 must be clamped to the last day
  -- of shorter months when computing dates. February exists.
  statement_day  int not null check (statement_day between 1 and 31),

  -- Two ways a card can express its due date, and real cards use both:
  --   due_day        - fixed day of the following month ("due on the 8th")
  --   due_days_after - fixed offset from the statement ("due 20 days later")
  -- A card with statement on the 24th and payment due on the 8th is 15 days
  -- in January and 12 in February, so an offset would drift by three days
  -- and in February would put the reminder AFTER the due date.
  due_day        int check (due_day between 1 and 31),
  due_days_after int,

  credit_limit   numeric(12, 2),

  -- A closed account keeps its history but drops out of due-date reminders
  -- and "which cards do I have" lists.
  is_active      boolean not null default true,

  created_at     timestamptz not null default now(),

  -- Exactly one due rule. Neither set means no due date can be computed and
  -- reminders silently never fire; both set means two answers that will
  -- eventually disagree.
  constraint cards_due_rule_check
    check ((due_day is null) <> (due_days_after is null))
);

-- The physical cards on an account. One IDFC account can carry a Visa and a
-- RuPay with different last4 digits sharing a single limit — standard in
-- India, because RuPay is what links to UPI. Two rows in `cards` would store
-- that one limit twice and duplicate the statement and due dates.
create table card_numbers (
  id          bigint generated always as identity primary key,

  -- Deleting an account removes its cards; a number is meaningless without
  -- the account. Transactions are unaffected — they reference cards(id), and
  -- that FK still blocks deleting an account that has spending history.
  card_id     bigint not null references cards(id) on delete cascade,

  -- 4 digits normally, 5 for Amex.
  last4       text not null check (last4 ~ '^[0-9]{4,6}$'),

  network     text check (network in ('visa', 'rupay', 'mastercard', 'amex', 'diners', 'other')),

  -- Reissued cards keep their row so historical SMS still resolve, but stop
  -- being offered as current.
  is_active   boolean not null default true,

  created_at  timestamptz not null default now(),

  -- Not globally unique on last4: two banks issuing cards ending 3577 is
  -- legitimate. The resolver disambiguates by issuer_code instead.
  constraint card_numbers_unique_per_card unique (card_id, last4)
);

-- Every SMS triggers a lookup by last4. Hot path.
create index card_numbers_last4_idx on card_numbers (last4);

alter table card_numbers enable row level security;

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

  -- The ACCOUNT this belongs to. Nullable: only card spends point at one.
  -- No ON DELETE clause, so the default blocks deleting an account that
  -- still has history — spending records shouldn't vanish with the card.
  card_id         bigint references cards(id),

  -- WHICH physical card, as the message reported it. Text rather than a
  -- foreign key on purpose: a snapshot of what the SMS actually said, in
  -- the same spirit as raw_sms. Survives a card_numbers row being edited or
  -- deleted, needs no join, and can't drift from the evidence. Lets you
  -- separate RuPay (UPI) spending from Visa (swipe) on one account.
  card_last4      text,

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

  -- Whether a human still needs to look at this. The extraction guardrail
  -- catches an invented amount but not the model picking the wrong REAL
  -- number, and not a spend it wrongly called "not a transaction".
  --   auto      - confident, counts immediately
  --   pending   - flagged, excluded from totals until ticked
  --   confirmed - user ticked it
  --   rejected  - user crossed it. Kept, not deleted: the audit trail matters
  --               and a deleted row would return on the next inbox re-scan.
  review_status   text not null default 'auto'
                    check (review_status in ('auto', 'pending', 'confirmed', 'rejected')),

  -- Why it was flagged. Shown on the review card so the user knows what to
  -- check instead of guessing.
  review_reason   text,

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

-- The review queue is a small slice of a large table.
create index transactions_review_idx on transactions (txn_time desc)
  where review_status = 'pending';

-- Every listing and total reads this.
create index transactions_countable_idx on transactions (txn_time desc)
  where review_status in ('auto', 'confirmed');

-- Matches cards. Data API is disabled, but RLS on by default is the right posture.
alter table transactions enable row level security;


-- Every SMS the phone forwards, stored before any parsing is attempted.
-- References transactions, so it comes last. See ADR 018.
--
-- Without this table a bank changing its message format loses those
-- transactions permanently — the phone's inbox is the only copy and the
-- failure is silent. With it, a format change becomes a backlog: fix the
-- parser, replay the stored messages, and dedupe_key stops anything already
-- inserted from doubling up.
create table raw_sms (
  id              bigint generated always as identity primary key,

  -- DLT header, e.g. AX-AXISBK-S. What routing keys off.
  sender          text not null,

  -- The message exactly as received. Never normalised — this is the evidence,
  -- and a "helpful" cleanup here would be invisible when a parse goes wrong.
  body            text not null,

  -- When the PHONE says it arrived, vs when the backend heard about it.
  -- The two differ by however long the app was closed.
  sms_sent_at     timestamptz not null,
  received_at     timestamptz not null default now(),

  -- pending      -> not yet attempted
  -- parsed       -> produced a transaction
  -- ignored      -> two models agreed it isn't a transaction (OTP, marketing)
  -- needs_review -> contains an amount but nothing could be read from it
  -- failed       -> the provider broke; retryable
  parse_status    text not null default 'pending'
                    check (parse_status in ('pending', 'parsed', 'ignored',
                                            'needs_review', 'failed')),
  parse_error     text,
  parsed_at       timestamptz,

  -- Which model produced the last extraction. A retry deliberately avoids
  -- it: temperature 0 means the same model returns the same answer, so
  -- re-running it would only ever confirm its own mistake.
  model           text,

  -- ON DELETE SET NULL: deleting a transaction must not delete the evidence
  -- it was derived from.
  transaction_id  bigint references transactions(id) on delete set null,

  created_at      timestamptz not null default now(),

  -- The phone re-uploads its inbox on every open. Same sender + same text +
  -- same send time is the same message. Without this, raw_sms grows forever.
  constraint raw_sms_unique_message unique (sender, body, sms_sent_at)
);

-- Drives GET /sms/unparsed — the "a bank changed something" alarm. Partial,
-- because parsed and ignored rows are the overwhelming majority.
create index raw_sms_needs_attention_idx on raw_sms (received_at desc)
  where parse_status in ('pending', 'failed');

alter table raw_sms enable row level security;

