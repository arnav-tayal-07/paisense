-- 013 - wallets are not bank accounts
--
-- Amazon Pay balance and Swiggy Money were being counted as spending. They
-- are not, and counting them charges the same rupees twice: money left the
-- bank when the wallet was topped up, and that debit was already recorded.
-- Spending it afterwards moves nothing out of any account.
--
-- Modelling a wallet as its own account kind, rather than filtering the
-- senders out, keeps the transactions visible and lets them bucket
-- themselves. The alternative - a hardcoded list of merchant headers - is
-- the per-bank-rules design this project deliberately abandoned, and it
-- would go stale the first time a new wallet appeared.
--
-- A wallet has no statement day, no due date and no credit limit, the same
-- as a bank account.

begin;

alter table accounts drop constraint accounts_kind_check;
alter table accounts add constraint accounts_kind_check
  check (kind in ('credit_card', 'bank_account', 'wallet'));

alter table accounts drop constraint accounts_kind_fields;
alter table accounts add constraint accounts_kind_fields check (
  (kind = 'credit_card'
     and statement_day is not null
     and ((due_day is null) <> (due_days_after is null)))
  or
  (kind in ('bank_account', 'wallet')
     and statement_day is null and due_day is null
     and due_days_after is null and credit_limit is null)
);

-- Patterns record which kind of account a format belongs to, so a regex
-- written for a wallet message can say so.
alter table sms_patterns drop constraint sms_patterns_account_kind_check;
alter table sms_patterns add constraint sms_patterns_account_kind_check
  check (account_kind in ('credit_card', 'bank_account', 'wallet'));

comment on column accounts.kind is
  'credit_card | bank_account | wallet. Wallet spending is excluded from '
  'totals: the money already left a bank account when the wallet was '
  'topped up, so counting it again double-counts it.';

commit;
