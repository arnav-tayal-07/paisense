-- 011 — when the credit limit took effect
--
-- Outstanding is computed as (credit limit - available balance), which is the
-- bank's own arithmetic and needs no history. But it is only valid if BOTH
-- figures describe the same moment.
--
-- Arnav's limit went from 20,000 to 36,300 effective 30 August, while the most
-- recent balance we had was from 27 August. Subtracting an old balance from a
-- new limit overstated the debt by 16,300 - it reported 20,209 when the real
-- figure was about 3,900.
--
-- Recording when the limit took effect lets the calculation refuse to run
-- rather than produce a confident wrong answer.

begin;

alter table accounts add column credit_limit_from date;

comment on column accounts.credit_limit_from is
  'When credit_limit took effect. Outstanding cannot be derived from a balance '
  'reported before this date, because the two figures describe different limits.';

commit;
