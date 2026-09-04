-- 010 — money blocked is not money spent
--
-- An IPO application blocks funds in the account: the bank says
-- "Rs.14938.00 is blocked in your A/C", and later either debits it (allotted)
-- or releases it (not allotted). Counting a block as an expense inflated
-- spending by ~28,700 on one month of real data, for money that was never
-- actually spent.
--
-- Also covers UPI mandates and pre-authorisations, which behave the same way.

begin;

alter table transactions drop constraint transactions_type_check;
alter table transactions add constraint transactions_type_check
  check (type in ('expense', 'income', 'card_payment', 'blocked'));

commit;
