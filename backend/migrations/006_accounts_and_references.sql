-- 006 — bank accounts are not credit cards
--
-- Run once. schema.sql updated to match. See ADR 026.
--
-- Real UPI messages from RBL and Bank of Baroda arrived and nothing in the
-- schema fitted them:
--
--   "Your a/c XX7489 is debited for Rs.658.36 on 02-09-26 and credited to
--    a/c XX7575 (UPI Ref 661188335104)"
--   "Rs.340.00 Dr. from A/C XXXXXX1614 and Cr. to paytmqr6s4v8c@ptys.
--    Ref:623928991037. AvlBal:Rs7180.70"
--
-- Four problems:
--   1. XX7489 is a savings account. The schema only knew about credit cards,
--      so nothing linked and every UPI transaction was orphaned.
--   2. AvlBal is money you HAVE; avl_limit meant credit REMAINING. Same
--      arithmetic, opposite meaning, misleading name.
--   3. The UPI reference was never captured, and it is the only thing making
--      each transaction unique - see the dedupe bug below.
--   4. RBL names no merchant at all, only a destination account. BOB gives a
--      VPA. Neither fits "merchant".
--
-- THE BUG THIS FIXES: RBL's debit format carries a date but no time, so
-- txn_time defaulted to midnight. Two UPI payments of the same amount on the
-- same day produced an identical dedupe_key, and the second was silently
-- discarded by ON CONFLICT DO NOTHING. No error, no review card, nothing in
-- /sms/unparsed. For UPI that is a normal Tuesday, not an edge case.

begin;

-- --------------------------------------------------------------------
-- 1. cards -> accounts. It was already the account rather than the
--    plastic (ADR 020); now it covers bank accounts too.
-- --------------------------------------------------------------------

alter table cards rename to accounts;
alter table card_numbers rename to account_numbers;

alter table accounts add column kind text not null default 'credit_card'
  check (kind in ('credit_card', 'bank_account'));

-- Statement days, due dates and credit limits are credit-card concepts. A
-- savings account has none of them, so they must be null there - otherwise
-- the due-date logic would invent a bill that doesn't exist.
alter table accounts alter column statement_day drop not null;
alter table accounts drop constraint cards_due_rule_check;

alter table accounts add constraint accounts_kind_fields check (
  (kind = 'credit_card'
     and statement_day is not null
     and ((due_day is null) <> (due_days_after is null)))
  or
  (kind = 'bank_account'
     and statement_day is null and due_day is null
     and due_days_after is null and credit_limit is null)
);

-- --------------------------------------------------------------------
-- 2. transactions: honest column names
-- --------------------------------------------------------------------

alter table transactions rename column card_id to account_id;
alter table transactions rename column card_last4 to account_last4;

-- Was avl_limit. For a card this is credit remaining; for a bank account it
-- is money remaining. One name for "what the bank said was left afterwards",
-- because the reconciliation arithmetic is identical either way.
alter table transactions rename column avl_limit to reported_balance;

-- Who the money went to or came from. UPI gives a VPA
-- (paytmqr6s4v8c@ptys) or just a destination account (XX7575) - neither is
-- a merchant name, and forcing them into `merchant` would mean a spending
-- report full of raw account numbers.
alter table transactions add column counterparty text;

-- --------------------------------------------------------------------
-- 3. Index names follow the tables they belong to
-- --------------------------------------------------------------------

alter index transactions_card_id_idx rename to transactions_account_id_idx;
alter index card_numbers_last4_idx rename to account_numbers_last4_idx;

commit;
