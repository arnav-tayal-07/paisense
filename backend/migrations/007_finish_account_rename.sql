-- 007 — finish what 006 started
--
-- Migration 006 renamed card_numbers to account_numbers but left its column
-- and constraints with the old names. schema.sql described the intended
-- state, the database had the old one, and every query against
-- account_numbers.account_id failed with "column does not exist".
--
-- Caught by deploying: GET /accounts returned 500 in production while every
-- local test passed, because the extraction tests never touch the database
-- and the account tests were written before the rename. A reminder that
-- "the code imports" is not the same as "the code runs".

begin;

alter table account_numbers rename column card_id to account_id;

-- Constraint names are cosmetic to Postgres but not to a human reading an
-- error message. "card_numbers_unique_per_card" on a table called
-- account_numbers is exactly the kind of stale name that wastes ten minutes
-- during a real incident.
alter table account_numbers rename constraint card_numbers_card_id_fkey
  to account_numbers_account_id_fkey;
alter table account_numbers rename constraint card_numbers_unique_per_card
  to account_numbers_unique_per_account;
alter table account_numbers rename constraint card_numbers_last4_check
  to account_numbers_last4_check;
alter table account_numbers rename constraint card_numbers_network_check
  to account_numbers_network_check;
alter table account_numbers rename constraint card_numbers_pkey
  to account_numbers_pkey;

commit;
