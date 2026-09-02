-- 004 — a due date can be a fixed DAY, not just an offset
--
-- Run once in the Supabase SQL editor. schema.sql is updated to match.
-- See ADR 021.
--
-- due_days_after assumed every card says "payment due N days after the
-- statement". Real card: statement on the 24th, payment due on the 8th of
-- the following month. That is 15 days in January, 12 in February, 14 in
-- April. Storing a single offset would drift by up to three days and, in
-- February, would place the reminder AFTER the payment was due.
--
-- Both styles exist on real cards, so support either and require exactly one.

begin;

alter table cards alter column due_days_after drop not null;
alter table cards alter column due_days_after drop default;

-- Fixed day of the month the payment is due, in the month AFTER the
-- statement. 29-31 must be clamped to the last day of shorter months when
-- computing an actual date.
alter table cards add column due_day int check (due_day between 1 and 31);

-- Exactly one of the two must be set. Neither means no due date can be
-- computed and reminders would silently never fire; both means two answers
-- that will eventually disagree.
alter table cards add constraint cards_due_rule_check
  check ((due_day is null) <> (due_days_after is null));

comment on column cards.due_day is
  'Day of the month payment is due, in the month after the statement. '
  'Mutually exclusive with due_days_after. Clamp 29-31 to month end.';

commit;
