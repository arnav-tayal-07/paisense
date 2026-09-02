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

**This also settles hybrid vs LLM-only: LLM-only.** The strongest argument for the hybrid was privacy — regexes would keep known banks local so only unknown formats left the server. With free tier accepted, that argument is gone, leaving only latency and cost, and neither matters at a handful of messages a day. Regexes can be added later purely as an optimisation for a high-volume bank. Nothing needs them now, and skipping them is what Arnav wanted from the start.
