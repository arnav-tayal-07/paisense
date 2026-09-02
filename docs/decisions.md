# Decision log

Short records of every significant choice and the reasoning. Newest at the bottom.
Format: context → decision → why → what we gave up.

## 001 — SMS parsing instead of payment-app APIs

**Context:** Wanted automatic UPI capture from Google Pay / PhonePe / Paytm.
**Decision:** Read bank debit SMS on-device and parse them in the backend.
**Why:** The payment apps expose no public transaction APIs. Every UPI debit triggers a bank SMS regardless of which app made the payment, so SMS covers all of them at once. Alternatives considered: Gmail alert parsing (needs Google OAuth, slower), Account Aggregator APIs (needs registered entity for production), manual CSV upload (not automatic).
**Trade-off:** Android-only; needs SMS permission; regexes must be maintained per bank format.

## 002 — React Native + Expo over Flutter

**Decision:** App in React Native + Expo (TypeScript).
**Why:** Already know JavaScript (one new language = zero, vs. Dart = one). React skills transfer to web frontend work. EAS builds APKs in the cloud for free — no local Android SDK. SMS/notification/calendar libraries exist for both frameworks, so no capability difference for this app.
**Trade-off:** Flutter has slightly more consistent UI rendering — irrelevant for a lists-and-forms app.

## 003 — Cloud backend (Render) + managed Postgres, not laptop hosting

**Decision:** FastAPI on Render free tier; Postgres on Supabase/Neon free tier.
**Why:** Laptop hosting means the app dies when the laptop sleeps. Render free tier is enough for personal use. SQLite was rejected because Render's free disk is wiped on every deploy — data must live in a managed database that survives.
**Trade-off:** Free tier sleeps after ~15 min idle (~40s cold start). Acceptable because reminders don't depend on the server (see 005).

## 004 — Agent = Claude with tools, not literal RAG

**Decision:** The "tally keeper" is a Claude tool-use agent (add_expense, delete_expense, search, monthly_total, card tools, income tools) — not a RAG pipeline.
**Why:** Data is structured rows, not documents. Tool calls execute real SQL — exact answers, real writes. RAG (embeddings + vector search) is for unstructured text and can't reliably do "delete that Zomato expense" or exact monthly totals.
**Trade-off:** Needs an Anthropic API key and per-use cost (small at personal volume).

## 005 — Reminders on the phone, not the server

**Decision:** Card due-date reminders = local notifications (7/3/1 days before) + writing events to the device calendar via expo-calendar.
**Why:** Works offline and while the free-tier server sleeps. Device calendar auto-syncs to Google Calendar because the phone is signed into Google — zero OAuth code.
**Trade-off:** Reminders only update when the app opens and re-syncs schedules.

## 006 — Voice on-device, brain in backend

**Context:** Wanted a voice-only agent, ideally not "just an API call".
**Decision:** Speech-to-text and text-to-speech run on-device (expo-speech-recognition, expo-speech). The agent loop stays in the backend.
**Why:** On-device STT/TTS is free, fast, private. The LLM can't ship in the APK: the API key would be extractable by anyone, and small on-device models are unreliable at tool calling. The backend agent is not a thin wrapper — it's a multi-step loop where Claude chains tool calls.
**Trade-off:** Voice needs internet for the agent step (data is in cloud Postgres anyway).

## 007 — Fingerprint gate instead of voice identification

**Context:** Wanted "proper voice identification" so only the owner can command the app.
**Decision:** Gate the agent behind device biometrics (expo-local-authentication). No speaker verification.
**Why:** Voice ID is weak security (defeated by recordings, similar voices; banks are rolling it back) and research-grade to implement. Fingerprint/face unlock is stronger, uses existing hardware, ~20 lines of code.
**Trade-off:** None meaningful. Voice ID stays on the wishlist as an ML learning experiment only.

## 008 — Text chat built before voice

**Decision:** Phase 4 builds the agent with a text interface; voice is layered on in Phase 6.
**Why:** The agent is modality-agnostic — it receives text either way. Debugging the agent, tools, and voice simultaneously multiplies pain. Text box stays as fallback even in the final app (STT will mangle merchant names sometimes).

## 009 — Gemini free tier for the agent during development

**Context:** Anthropic has no free tier; wanted a ₹0 way to build and test the agent.
**Decision:** Develop the agent on Google Gemini Flash (free tier, supports function calling). Keep the provider behind one small interface so switching (e.g., to Claude for tool-use quality + no-training-on-data policy) is a one-file change.
**Why:** Free tier covers hundreds of requests/day — plenty for development. Test data is fake, so the free tier's "may use prompts for product improvement" clause doesn't matter yet.
**Trade-off:** Revisit before real financial data flows daily: either paid tier or Claude, for privacy and better multi-step tool chaining.

## 010 — Name: PaiSense

**Decision:** The app is called PaiSense (working name was Kharcha).
**Why:** Double meaning — "pai" (the old smallest rupee unit, as in *pai-pai ka hisaab*, accounting for every last penny) + "sense" (making sense of your money). Checked Play Store / web presence: no existing app uses it. First choice "Munshi" was already taken twice on the Play Store; "TallyBaba" risks the Tally Solutions trademark; plain kharcha/paisa names are crowded.

## 011 — transactions table: permissive nullability, strict on the core four

**Context:** Designing `CREATE TABLE transactions`. The open question was which columns get `not null`.
**Decision:** Only `type`, `amount`, `txn_time`, `created_at` (plus `id`, `source`, which defaults) are `not null`. `merchant`, `category`, `upi_ref`, `payment_method`, `card_id`, `note` are nullable.
**Why:** The test applied per column was "can a real transaction exist without this?", not "should this be filled in?". A half-parsed bank SMS with an amount but no clean merchant name is still a transaction worth storing — a `not null` on `merchant` would make the Phase 3 parser reject real spending. Direction, amount, and time are the irreducible core: without them there is no row worth keeping.
**Trade-off:** More null-handling in Phase 2 query code and in the app's display layer. Accepted: rejecting real data is worse than handling nulls.

Supporting choices in the same table:

- `amount numeric(12,2) check (amount > 0)` — `type` carries the direction, so a negative amount would double-encode sign and could silently cancel out real spend in monthly totals.
- `type text check (...)` rather than a native Postgres enum — adding a third value later is one line instead of an `ALTER TYPE` migration.
- `upi_ref text unique` and nullable — Postgres treats NULLs as distinct, so unlimited cash rows coexist while a re-scanned SMS collides on its ref and is dropped by `ON CONFLICT (upi_ref) DO NOTHING`. This one column is the entire dedupe strategy.
- `source` (`manual`/`sms`/`agent`), not null with a default — every row has a provenance; lets later code trust SMS rows and re-check agent-written ones.
- `txn_time` and `created_at` kept separate — when the money moved vs. when the row appeared. Scanning Friday's SMS on Sunday must not report Sunday's spending.
- `card_id` with no `ON DELETE` clause — the default blocks deleting a card that still has history, so spending records can't vanish with the card.
- `payment_method` deliberately left unconstrained until Phase 3 reveals the real value set from live SMS formats.

## 012 — Duplicate upi_ref is a success (200), not a conflict (409)

**Context:** `on conflict (upi_ref) do nothing` returns no row when it collides. `POST /transactions` had to decide what that means to the caller.
**Decision:** Fetch and return the existing row. 201 when a row was created, 200 when it already existed. Never an error.
**Why:** The Phase 3 SMS parser re-scans the inbox on every app open, so re-sending an already-stored transaction is the *normal* path, not a failure. A 409 would force the client to treat an error status as success — which means the day a real error appears, it gets swallowed by the same branch. Making the endpoint idempotent keeps "did this fail?" answerable.
**Trade-off:** A conflict costs a second query (the insert returns nothing, then a select by `upi_ref` fetches the row). Only on the conflict path, and only one indexed lookup. The alternative — `do update set upi_ref = excluded.upi_ref` to force `returning` to yield a row — avoids the round trip but writes a dead tuple and takes a row lock on every duplicate, which is worse at re-scan volume.
**Note:** Rows with a NULL `upi_ref` (cash, manual entry) never conflict — Postgres treats NULLs as distinct — so this path only ever triggers for real UPI references.

## 013 — Filtering built as composed SQL fragments, not a query builder

**Context:** `GET /transactions` needed optional filters (type, category, merchant, date range) that combine freely. Phase 4's agent tools map onto exactly these.
**Decision:** Build the `where` clause by joining hard-coded SQL fragments whose values are still passed as `%s` parameters. No ORM, no query-builder library.
**Why:** The rule "never f-string SQL" is really "never interpolate *values*". Fragments like `"type = %s"` are literals written in the source; the user's value never touches the string and travels separately to psycopg. That keeps injection impossible while allowing the clause to vary. An ORM would solve this too, but adds a dependency and an abstraction layer for one query on a two-table schema.
**Trade-off:** Adding a filter means editing a list in `list_transactions` rather than getting it for free. Fine at this size; revisit if the filter set grows past a handful.

**Date ranges are half-open** — `start <= txn_time < end`, not `<=` on both ends. Asking for August then September with inclusive bounds double-counts anything landing exactly on the boundary instant. The agent will generate these ranges programmatically for `monthly_total`, so the off-by-one would be systematic rather than rare.

## 014 — Missing row is a 404, even though a duplicate is a 200

**Context:** `DELETE /transactions/{id}` and `GET /transactions/{id}` had to decide what "not found" means. ADR 012 had just established that a *duplicate* is a success.
**Decision:** 404 when the id doesn't exist. 204 No Content on a successful delete.
**Why:** These look contradictory but aren't. A duplicate `upi_ref` is the expected steady state of a re-scanning parser — it means "already handled", which is success. A missing id means the caller referred to something that isn't there, which is a real mistake worth surfacing. The agent's `delete_expense` tool needs to distinguish "removed it" from "there was nothing to remove" so it can say so rather than claim a deletion that never happened.
**Implementation note:** `delete ... returning id` is what makes this possible — a bare `DELETE` reports success whether or not it matched anything.

---

*ADRs 015–017 all come from reading two real SMS (Axis `AX-AXISBK-S`, Amex `TX-AMEXIN-S`) before writing any regex. Each one invalidated an assumption baked into the schema on day one. Applied together as migration [001](../backend/migrations/001_credit_card_sms.sql).*

## 015 — `last4` is text with a 4–6 digit check, not `char(4)`

**Context:** The `cards` table assumed every card shows four trailing digits.
**Decision:** `last4 text check (last4 ~ '^[0-9]{4,6}$')`.
**Why:** Amex is a 15-digit card and its SMS shows **five** — `***71003`. `char(4)` physically cannot store that, so an Amex card could never be added. `char` also blank-pads to a fixed width, which makes later equality comparisons quietly surprising. `text` plus a shape check keeps the validation without the width.
**Trade-off:** The check no longer pins an exact length, so a typo of five digits on a Visa passes. Acceptable — the alternative excludes a card you actually own.

## 016 — Credit card bill payments are a third type, not income

**Context:** The Amex message is *"a payment of INR 3,230.00 was received on your Amex Card"* — paying off the card, not spending or earning.
**Decision:** Add `card_payment` to the `type` check. Excluded from both spend and income totals.
**Why:** Recording it as income inflates earnings by an amount that was never earned. Recording it as an expense double-counts, because every purchase it settles was already logged as an expense when the card was swiped. It is a transfer between two accounts the user owns. Dropping the message entirely was the other option, rejected because Phase 6's due-date reminders need to know a bill was actually paid.
**Trade-off:** Every future total, filter, and agent tool must remember to exclude `card_payment`. That's a standing footgun — the mitigation is that it's recorded here and the type name says what it is.
**Note:** ADR 011 justified `text` + `check` over a native enum on the grounds that a third value would one day be one line rather than a migration. That happened within two days.

## 017 — Dedupe moves from `upi_ref` to a derived `dedupe_key`

**Context:** ADR 011 made `upi_ref` the entire dedupe strategy. Neither real credit card SMS contains a transaction reference of any kind.
**Decision:** Add `dedupe_key text unique`, derived by the parser from bank + card + timestamp + amount. `upi_ref` keeps its data but **loses its unique constraint**.
**Why:** With no reference in the message, `upi_ref` is null, and Postgres treats every null as distinct — so re-scanning the inbox would insert the same card transaction again on every app open. A derived key restores the property ADR 012 depends on. Deriving rather than reading is the key move: the parser can always construct one, whatever the bank sends.
**Why `upi_ref` loses unique:** two unique constraints would be a trap. `on conflict (dedupe_key) do nothing` only swallows collisions on the column it names — a `upi_ref` collision would raise and surface as a 500 rather than being ignored. Dedupe must be exactly one column's job.
**Trade-off:** A derived key is only as good as its inputs. Two identical amounts on the same card in the same second would collapse into one row. Judged impossible in practice; if a bank ever sends a reference, prefer it over the derived key.

## 018 — Store every raw SMS before parsing it

**Context:** Arnav asked why the parser can't be universal — work regardless of bank, format or future changes. It can't: any extraction method, regex or LLM, can fail on input it wasn't built for.
**Decision:** A `raw_sms` table holding sender, body, send time and a parse status, written **before** extraction is attempted. Parsing updates the row rather than being a precondition for storing it.
**Why:** This turns the unanswerable question ("how do we never fail?") into a survivable one ("what happens when we do?"). Without it, a bank reformatting means those transactions are lost permanently — the phone's inbox is the only copy, the failure is silent, and it goes unnoticed for weeks. With it, the messages are all on disk: fix the parser, replay them, and `dedupe_key` (ADR 017) stops anything already inserted from doubling up. Replay being safe is what makes the whole thing work, and that property already exists and is tested.
**Consequence:** It also decouples the parser decision from everything else. Regex, LLM or hybrid can be swapped later and re-run over stored history, so the approach question stops being irreversible.
**Trade-off:** Every message is stored twice — once raw, once parsed. At a handful of SMS a day that's negligible, and the raw copy is the audit trail for any transaction whose origin is ever in doubt.

**Four states, not two.** `ignored` (an OTP, correctly skipped) is deliberately distinct from `failed` (a spend the parser should have understood). Collapsing them would bury the alarm: `GET /sms/unparsed` lists only `failed` and `pending`, which is the signal that a bank changed something.

## 019 — LLM extraction on Gemini free tier, including real SMS (amends 009)

**Context:** ADR 009 accepted the free tier's "prompts may be used for product improvement" clause on the explicit basis that test data was fake, and flagged a revisit before real financial data flowed. This is that revisit.
**Decision:** Extract transactions from SMS with an LLM on the Gemini free tier, using real messages. No regexes for now.
**Why:** Arnav's requirement was a parser that works across banks and formats without needing updates — a regex encodes a format and breaks when it changes, so it cannot meet that bar. An LLM can. The assistant raised the privacy trade-off twice: free-tier prompts may be sampled for human review and used as training signal, and the exposure is an identity-linked record of personal spending. Arnav weighed it and accepted: the data is his own, a bank SMS contains no full card number or credentials, and free tier means unmetered iteration during development.
**What we gave up:** The messages cannot be un-sent, and training influence is irreversible. Revisit if the app is ever used by anyone else, where the data would no longer be his to trade away.
**Reversibility:** Keep the provider behind one interface (ADR 009's original point) so switching to a no-training tier is a one-file change. `raw_sms` (ADR 018) stores every message, so re-extracting under a different provider later is a replay, not a re-collection.

**Correction (same day):** this ADR originally justified the trade-off as "the data is his own." The first two sample messages were in fact borrowed from someone else as format references, and were committed and sent to Gemini only with altered digits and limits. From the IDFC messages onward the data is genuinely his, so the reasoning holds going forward.

**This also settles hybrid vs LLM-only: LLM-only.** The strongest argument for the hybrid was privacy — regexes would keep known banks local so only unknown formats left the server. With free tier accepted, that argument is gone, leaving only latency and cost, and neither matters at a handful of messages a day. Regexes can be added later purely as an optimisation for a high-volume bank. Nothing needs them now, and skipping them is what Arnav wanted from the start.

## 020 — A credit account and a piece of plastic are different things

**Context:** One IDFC FIRST account turned out to carry two physical cards — a Visa and a RuPay, different last4 digits, one shared credit limit, one statement, one due date. `cards` assumed one row = one card = one limit.
**Decision:** `cards` becomes the account. A new `card_numbers` table holds the physical cards (`card_id`, `last4`, `network`, `is_active`). `last4` is removed from `cards` entirely.
**Why:** Two rows in `cards` would store one credit limit twice, duplicate the statement and due dates, and turn "spend on my IDFC card" into a sum across rows that something will eventually forget to do. The `avl_limit` from an SMS would also look like it belonged to one card when it is in fact the shared figure. RuPay-plus-Visa on one account is standard in India — RuPay is what links to UPI — so this is the normal case, not an edge case.
**Trade-off:** A join to resolve a card, and two inserts to register one card. Both trivial at this size.

**Edge cases this now handles:**

- *Card reissued after expiry* — add a row, mark the old one inactive. History survives because transactions reference the account, not the number.
- *Account closed* — `cards.is_active = false` drops it from reminders and pickers while keeping every transaction.
- *Two banks issuing cards ending in the same digits* — `last4` is deliberately **not** globally unique. `cards.issuer_code` holds the DLT sender segment (`IDFCFB`, `AXISBK`) and the resolver matches on issuer first.
- *Ambiguity* — if `last4` matches several accounts and the issuer can't separate them, `resolve_card_id` returns `None` rather than guessing. A wrong link silently corrupts a card's totals; an unlinked transaction is visible and fixable by replaying from `raw_sms`.
- *Statement day 29–31* — recorded as a column comment: due-date computation must clamp to the last day of shorter months. February exists.
- *Re-running setup* — `add_card_number` uses `ON CONFLICT DO NOTHING`, so adding the same number twice is a no-op rather than an error.

**Also added: `transactions.card_last4`.** Text, not a foreign key — a snapshot of what the message actually said, in the same spirit as `raw_sms`. It survives a `card_numbers` row being edited or deleted, needs no join to read, and can't drift from the evidence. `card_id` still carries the real relationship for aggregation. Together they let you split RuPay (UPI) spend from Visa (swipe) on a single account.

## 021 — A due date can be a fixed day, not only an offset

**Context:** `cards.due_days_after` assumed every card says "payment due N days after the statement." Arnav's IDFC card generates its statement on the 24th and takes payment on the **8th of the following month**.
**Decision:** Add `due_day` (fixed day of the following month). Keep `due_days_after` (fixed offset). Exactly one must be set, enforced by `check ((due_day is null) <> (due_days_after is null))`.
**Why:** 24th → 8th is 15 days in January, 12 in February, 14 in April. Storing a single offset would drift by up to three days, and in February would schedule the reminder *after* the payment was due — the failure mode the reminders exist to prevent. Both styles are common on real cards, so the schema has to express either.
**Why not just store an explicit due date per statement:** that requires a row per billing cycle and something to generate it. A rule plus `statement_day` computes any cycle's dates on demand, and cards change their rule roughly never.
**Trade-off:** Date computation must now branch on which field is set, and clamp `due_day` 29–31 to the last day of shorter months.

**Pattern worth noting:** this is the fourth schema assumption broken by looking at real data rather than imagining it — after `char(4)` vs Amex's five digits (015), bill payments having no valid `type` (016), card SMS carrying no reference (017), and one account carrying two physical cards (020). Every one was cheap to fix while the tables were empty and would have been expensive with a year of rows in them.

## 022 — Model choice is driven by free-tier quota, not quality

**Context:** Extraction was built on `gemini-3.6-flash`. Mid-testing every call started timing out, then returned 429: `GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 20`. Twenty requests **per day**.
**Decision:** Default to `gemini-3.1-flash-lite`, overridable with `GEMINI_MODEL` in `.env`.
**Why:** Twenty a day is unusable — a single busy day of spending produces that many SMS before any retries or testing. The lite model draws on a separate, far larger free pool and passed all six extraction cases identically, including the two hardest: 12-hour time (`08:38 PM` → `20:38`) and three different day-first date formats. There was no quality reason to prefer the larger model for this task; extraction is constrained, schema-bound, and short.
**Trade-off:** A lite model may handle a genuinely unusual message worse. `raw_sms` makes that recoverable — switch `GEMINI_MODEL`, run `POST /sms/reprocess`, and the stored messages are re-extracted.

**A 429 now raises `QuotaExceeded`, not a generic error**, and the message includes which quota and the retry delay. "429" alone is useless: a per-minute limit clears in seconds, a per-day limit does not, and the response is different in each case.

**What this incident proved about the design.** All three messages arriving during the outage were stored, marked `failed` with the reason, and appeared in `GET /sms/unparsed`. Nothing was lost. Once quota returned, `POST /sms/reprocess` replayed them: 2 parsed, 1 correctly ignored, 0 failed. That is precisely the scenario ADR 018 was written for, and it happened by accident on the first real run — a provider outage is not hypothetical, and without `raw_sms` those three transactions would have been gone permanently and silently.

## 023 — Automatic fallback down a chain of models

**Context:** ADR 022 switched models to dodge a 20/day limit, but that only moves the wall. The 429 names the quota `GenerateRequestsPerDayPerProjectPerModel` — **per model** — so each model has an independent daily allowance.
**Decision:** `GeminiProvider` takes an ordered chain and tries each in turn. Exhausting one falls through to the next; the effective daily budget is the sum of the chain rather than the first entry.
**Why:** Free-tier limits are the binding constraint on this project, not cost or quality. Five models with separate pools is several times the headroom for no money and about thirty lines of code.

**What falls through and what doesn't.** `QuotaExceeded` (429) and `ModelUnavailable` (404, 503, timeout) advance to the next model. Anything else — a malformed request, a bad schema — fails immediately, because it would fail identically on every model and retrying would burn four more quotas to learn the same thing.

**Timeouts count as unavailable.** Observed for real: an exhausted model stalled for a full 30 seconds before it began returning clean 429s. A model that hangs is no more useful than one that's out of quota.

**It remembers what worked.** The last successful model is tried first next time, so a healthy fallback isn't re-tested against an exhausted primary on every message. The chain wraps around rather than truncating, so once daily quotas reset it drifts back to the preferred model on its own.

**Configuration:** `GEMINI_MODEL` pins one model (for testing a specific one); `GEMINI_MODELS` overrides the whole chain as a comma-separated list. The default chain was verified against the live API — 2.5-series models return 404 on this key and are excluded.

## 024 — Human review for what the guardrails can't catch

**Context:** Arnav asked what happens if the model hallucinates an amount or misses a transaction entirely. Auditing the answer honestly turned up three failures the existing guardrail does not cover, on top of the one it does.

| Failure | Before | Now |
|---|---|---|
| Provider down / out of quota | ✅ `failed`, replayed | unchanged |
| Invented amount not in the message | ✅ rejected | unchanged |
| Model calls a real spend "not a transaction" | ❌ **silently dropped** | second opinion, then `needs_review` |
| Model picks the wrong *real* number | ❌ **passes the guardrail** | flagged when it equals `avl_limit` |
| Transaction whose card can't be resolved | ❌ stored unlinked, invisible | flagged for review |
| Transaction that never generated an SMS | ❌ undetectable | caught by reconciliation |

**Decision:** Add `transactions.review_status` (`auto` / `pending` / `confirmed` / `rejected`) with a queue the user ticks or crosses, plus a reconciliation check against the bank's own available-limit figures.

**Why the amount guardrail was never enough.** It verifies the amount *appears* in the message. Every IDFC message contains two candidate numbers — the spend and `Avbl Limit` — so picking the wrong one passes the check. A ₹10,170 coffee would have sailed through. The narrow fix: if the extracted amount exactly equals the extracted available limit, the wrong number was chosen. A purchase for precisely your remaining limit, to the paisa, does not happen.

**Why a "no" from the model is no longer trusted on its own.** `ignored` rows are excluded from the alarm list so OTPs don't bury real failures — which also made a wrongly-ignored spend invisible forever. Now, if the message contains a currency amount and the model says it isn't a transaction, a **different** model is asked. Agreement is trusted; disagreement produces a transaction flagged for review. This is the only mechanism that can rescue the silent case.

**Why retries use a different model.** Temperature 0 means the same model returns the same answer, so replaying a hallucination reproduces it exactly. `raw_sms.model` records who answered; retries exclude it. Different model, different mistake — or agreement, which is itself evidence.

**Why reconciliation matters most.** Every other check inspects messages that arrived. Only this one detects a message that *never did*: between two consecutive card SMS the available limit must move by exactly the later transaction's amount — down for a spend, up for a bill payment. Anything else means spending happened that was never recorded, proved by arithmetic against the bank's own numbers rather than by trusting the extractor. Verified in testing: a deliberately removed ₹2,000 transaction was detected purely from the limit figures.

**Rejection is marked, not deleted.** The audit trail matters, and a deleted row would simply be recreated by the next inbox re-scan.

**Red cross means "the parser got it wrong", not "I didn't make this purchase."** Those need opposite responses — one is a database edit, the other is a bank dispute. Conflating them would turn a possible fraudulent charge into a quietly deleted row. The dispute number is in the stored message.

**The real design risk is review fatigue.** A queue that flags everything gets tapped through without reading, which produces *false* confidence — worse than no review. So the triggers are deliberately narrow: models disagreed, amount equals the available limit, or the card isn't registered. Everything else is `auto` and never surfaces. If the queue turns out too noisy or too quiet, the thresholds move; the mechanism doesn't.

**Unreviewed rows do not count.** `list_transactions` defaults to `auto` + `confirmed` only. If flagged rows still counted toward totals, flagging them would achieve nothing.

## 025 — PATCH semantics: send only what changed

**Context:** The review card needs a third option. Tick and cross don't cover the common case — "yes I bought that, but it was ₹2,000 not ₹10,170" — and without an edit, correcting a wrong amount meant rejecting a real transaction and losing it.
**Decision:** `PATCH /transactions/{id}` and `PATCH /cards/{id}`, both partial: only fields present in the request body are written, using Pydantic's `exclude_unset`.
**Why partial and not PUT:** sending `{"amount": "2000"}` must not blank the merchant. A PUT would require the client to echo back every field it isn't changing, which turns every edit into a read-modify-write and makes concurrent edits destructive.
**Column names come from a fixed allow-list**, never from the request body — the update statement is assembled from known column names with values still passed as `%s` (ADR 013). A request key that isn't in the list is ignored rather than interpolated.

**Not editable on a transaction:** `dedupe_key` (changing it would let the same SMS insert a second row on the next re-scan), `source`, and `created_at`. Those describe how the row came to exist, not what it says.

**PATCH does not change `review_status`.** Editing a value and accepting it are separate decisions; collapsing them would mean a stray edit silently marks something reviewed. The app calls PATCH then confirm — two calls, unambiguous semantics.

**Setting one due rule clears the other** (ADR 021 requires exactly one). Switching a card from "due 20 days after" to "due on the 8th" is one field in the request, not two. Without this the database check constraint would reject the obvious request and surface as a 500.

**Validation sits in front of SQL, not behind it.** `CardIn` rejects both-or-neither due rules as a 422 naming the problem, rather than letting Postgres raise a constraint violation the user can't interpret. The constraint remains as the backstop that can't be bypassed.

## 026 — Bank accounts, and a regex for the one field that must be exact

**Context:** Real UPI messages arrived from RBL and Bank of Baroda. Every previous message had been a credit card message, and nothing in the schema fitted these.

**The bug they exposed, which was live:** RBL's debit format carries a date and **no time**, so `txn_time` fell back to midnight. The derived dedupe key (ADR 017) is bank + card + timestamp + amount — so two UPI payments of the same amount on the same day produced an *identical* key and the second was silently discarded by `ON CONFLICT DO NOTHING`. No error, no review card, nothing in `/sms/unparsed`. For UPI, two small payments in a day is a normal Tuesday, not an edge case.

**Decision, in four parts:**

**1. `cards` becomes `accounts`, with a `kind`.** `XX7489` is a savings account, not a card. ADR 020 had already made this table the account rather than the plastic; this extends it to bank accounts. Statement days, due dates and credit limits are credit-card concepts, enforced by a conditional check so a bank account cannot acquire a due date the app would then remind you about.

**2. `avl_limit` becomes `reported_balance`.** For a card, "available" is credit remaining. For a bank account it's money you have. Opposite meanings, identical arithmetic — both fall on a debit — so one column, named for what it actually is: what the bank said was left afterwards.

**3. `upi_ref` is extracted by REGEX, not by the model.** This is the one place regex beats an LLM and the reason is exactness. A reference is a meaningless identifier — there is no context to reason from, so a model transposing one digit produces a string that looks entirely valid. And that string *is* the dedupe key: one wrong character means the same transaction inserts twice on the next re-scan, silently. A regex is exact or it fails; there is no "nearly right". Labels seen in real messages: `UPI Ref`, `UPI Ref no`, `Ref:`.

The model is *also* asked for the reference — not to use, but so a disagreement can be surfaced. Regex wins; a mismatch flags for review. If the regex finds nothing and the model does, the model's value is used and flagged, because an unrecognised label is a format the pattern should learn.

**4. `counterparty` is a new column.** RBL names no business at all, only a destination account (`XX7575`). BOB gives a UPI VPA (`paytmqr6s4v8c@ptys`). Neither is a merchant, and forcing them into `merchant` would produce a spending report full of raw account numbers.

**The general principle, worth keeping:** use a model where meaning must be inferred, and a regex where characters must be copied. ADR 019 rejected regexes for *parsing* and that still holds — a pattern that encodes a message format breaks when the bank rewrites it. A pattern that copies an identifier after a label does not have that fragility, and gets the one guarantee an LLM cannot give.

**Trade-off:** more columns, and the `accounts` rename touched every module. Cheap now with four transactions in the table; expensive after a year of data.

**Verified across four banks and ten cases:** Axis, Amex, IDFC (purchase + standing instruction), RBL (debit with no time, credit with a different date format and label on the same sender), BOB (VPA payee, `AvlBal`, and a `(2026:08:27 08:01:42)` colon date format seen nowhere else) — plus an OTP, a marketing message and an account-linking notice, all correctly ignored.

## 027 — Native Android in Kotlin, superseding ADR 002

**Context:** ADR 002 chose React Native + Expo. Building the app forced a closer look, and the reasoning no longer holds for this app specifically.

**Decision:** Native Android, Kotlin + Jetpack Compose, built locally in Android Studio over USB. No React Native, no Expo, no EAS.

**Why the original reasoning expired:** ADR 002's case for React Native was code sharing across iOS and Android, plus "one new language = zero" since JavaScript was already known. But **iOS cannot read SMS at all** — Apple has never exposed the inbox to third-party apps. PaiSense can therefore only ever be an Android app, so React Native's abstraction was being paid for a cross-platform benefit that could never be collected.

**Three reliability arguments, in order of weight:**

1. **`BroadcastReceiver` fires when the app is closed.** Android wakes a native receiver the instant an SMS arrives, even if the app hasn't been opened in a week. React Native's JS thread isn't running then, and background delivery is exactly where the community bridge modules are weakest.
2. **No bridge on the critical path.** Kotlin calls the SMS APIs directly. The RN route depends on `@maniac-tech/react-native-expo-read-sms` or `react-native-get-sms-android` — community modules documenting support only to Expo SDK 50, with open 2026 bug reports, sitting between the app and its core data source.
3. **`WorkManager` for the outbox.** Messages must survive Render's cold start, so the phone needs its own retry queue. Android provides one that survives reboots and handles backoff; in React Native it would be hand-rolled.

**What we gave up:** Kotlin and Jetpack Compose are both new to Arnav, where JavaScript was not — the honest cost, and it shifts the pair-mode balance toward the assistant writing more than it would in JS. Also a ~10GB Android Studio install, and no web version to share as a URL. Cross-platform support is *not* in this list, because it was never achievable.

**What we gained beyond reliability:** USB debugging is a faster loop than EAS cloud builds — install to the phone in seconds, with no queue and no free-tier build limits.

**Rejected alternative worth recording:** a tiny native SMS forwarder plus a web UI on Vercel. It would have put most of the work in JavaScript and produced a shareable URL, but due-date reminders (ADR 005) and the biometric gate (ADR 007) both need a real app, so the native app was needed regardless — and building two things is worse than building one.

**Not affected:** ADR 001 (parsing stays server-side), 005 (reminders on-device), 006 (voice on-device), 007 (fingerprint gate). Those decisions were about *where* logic runs, not which framework runs it.

## 028 — Single user now, multi-user later; a shared API key in the meantime

**Context:** Arnav wants PaiSense multi-user eventually, but personal and simple while he's learning. Meanwhile the deployed API had no authentication at all, and its URL was committed to a **public** repository.

**Decision:** Stay single-user. Add one shared secret (`X-API-Key`) as middleware over every route except `/health` and the docs. Real per-user authentication waits until multi-user is actually wanted.

**Why not build multi-user now:** the schema half is cheap to defer — adding `user_id` to four tables is an `ALTER TABLE`, a backfill of `1`, and a `NOT NULL`. The expensive half is authentication, and that costs the same whenever it's built. Nothing is saved by doing it early, and it would slow down every feature in between.

**Why the key could not wait:** the API was open to anyone who read the repo. `GET /transactions` exposed every row, `POST /sms` burned Gemini quota, and `DELETE /transactions/{id}` destroyed data. Four test rows made it low-stakes on the day; real spending would not have.

**Three implementation details that matter:**

- **Middleware, not a per-route dependency.** A new endpoint is protected by default. Remembering to add a decorator is exactly how endpoints leak.
- **Fail closed.** An unset `PAISENSE_API_KEY` returns 503, never "allow everyone". A missing environment variable must not silently reopen the database.
- **`hmac.compare_digest`, not `==`.** A plain string comparison returns as soon as characters differ, so its timing leaks how much of the key was correct. Overkill at this scale; costs one import.

**`/health` stays open** — the keepalive workflow pings it and it reveals nothing beyond "the server is up". `/docs` stays open too: it describes the shape of the API, not the data.

**Note on patterns and ownership:** when the LLM-generated regex patterns (ADR 029) arrive, they are the one thing that should *not* become per-user. An SMS format belongs to a bank, not to a customer — RBL's message shape is identical for everyone. In a multi-user world, transactions are per-user and patterns are shared, so one user hitting a new bank format teaches it for everybody.
