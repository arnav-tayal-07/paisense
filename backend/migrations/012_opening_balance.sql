-- 012 - a starting point for card balances (SUPERSEDED, still applied)
--
-- Written for an all-time-outstanding model that no longer exists. Cards are
-- now measured from the current cycle only, with everything before it assumed
-- settled, so there is no balance to carry and nothing to seed.
--
-- The columns are applied and empty. No code reads or writes them. Kept
-- rather than dropped because a destructive migration to remove two unused
-- nullable columns buys nothing, and this file has to stay for anyone
-- rebuilding the database from scratch.
--
-- Original reasoning below.
--
-- Outstanding is now computed from our own rows: purchases minus bill
-- payments. That is exact IF we have every transaction since the account
-- opened, and we don't - history starts one month ago. The payments we have
-- settled purchases from before that window, so the arithmetic goes negative.
--
-- opening_balance is what was owed on opening_balance_at. Everything after it
-- is added or subtracted from our rows. Enter it once from a statement and
-- the figure is correct from then on; leave it null and the number is
-- reported as approximate rather than wrong.

begin;

alter table accounts add column opening_balance numeric(12, 2);
alter table accounts add column opening_balance_at date;

comment on column accounts.opening_balance is
  'Amount owed on opening_balance_at. Transactions after that date are applied '
  'to it. Null means outstanding is derived from partial history and is only '
  'a lower bound.';

commit;
