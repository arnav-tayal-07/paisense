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
