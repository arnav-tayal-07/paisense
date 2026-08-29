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
