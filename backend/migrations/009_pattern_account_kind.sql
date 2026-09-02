-- 009 — patterns know which kind of account they describe
--
-- Run once. schema.sql updated to match. See ADR 030.
--
-- One bank sends BOTH credit card messages and bank account UPI messages,
-- sometimes from the same DLT header. Multiple patterns per sender already
-- handled that, but two things were still missing:
--
--   1. Nothing stopped a card pattern from also matching a UPI message from
--      the same bank. Each pattern was only ever checked against its own
--      samples, so a loose regex could swallow the other format and file the
--      transaction against the wrong account.
--   2. When resolving last4 to an account, nothing constrained the search by
--      kind. A card ending 3577 and a savings account ending 3577 at the same
--      bank would be indistinguishable.

begin;

-- Which kind of account this format's messages are about. Null when the
-- format doesn't say - resolution then falls back to searching both.
alter table sms_patterns add column account_kind text
  check (account_kind in ('credit_card', 'bank_account'));

commit;
