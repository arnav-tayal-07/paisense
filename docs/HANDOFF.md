# Session handoff — continue here

> **For any AI assistant picking this project up: read this file, then [decisions.md](decisions.md), before doing anything.**
> Last updated: 2026-08-30 (**Phases 1–3 complete** — SMS ingestion verified end to end on real messages).

## The one rule that overrides everything

**Arnav is learning. Do NOT write core logic for him.** Work in pair mode:
- He writes: routes, SQL, regexes, agent logic — with guidance and PR-style review.
- Assistant writes: boilerplate, config, deploy files — always explained.
- Explain concepts before code. Small phases, each ending in something runnable.
- He learns well from review feedback (see the cards-table review in the chat archive).

## Project state

| Item | Status |
|---|---|
| Architecture + all decisions | ✅ [decisions.md](decisions.md), ADR 001–025 |
| GitHub repo | ✅ https://github.com/arnav-tayal-07/paisense |
| **Live API** | ✅ **https://paisense.onrender.com** — Render free tier, Singapore. Auto-deploys on push to `main` |
| Supabase project | ✅ `paisense`, Mumbai, Data API disabled, RLS on every table |
| `backend/.env` | ✅ `DATABASE_URL` + `GEMINI_API_KEY`, git-ignored |
| Python venv | ✅ `backend/.venv` — fastapi, uvicorn, psycopg[binary], python-dotenv, httpx |
| Schema | ✅ 4 tables + 4 migrations, live DB verified against [schema.sql](../backend/schema.sql) |
| Transactions API | ✅ full CRUD with filtering |
| SMS ingestion | ✅ LLM extraction, raw audit trail, replay on failure |
| Real data in DB | ✅ 1 card account (IDFC, 2 numbers), 4 transactions, 3 raw_sms |
| Card + review routes | ✅ full CRUD, review queue, reconciliation (ADR 024-025) |
| Keepalive workflow | ⚠️ committed, needs `PAISENSE_API_URL` secret set in GitHub |
| UPI messages | ⚠️ **untested, and `upi_ref` is never extracted** — see below |
| Expo app (Phase 6) | ❌ not started — decided to build BEFORE the agent |
| Agent (Phase 4) | ❌ deferred until after the app |
| Automated tests | ❌ none — carried debt |

Run it from `backend\`: `.\.venv\Scripts\uvicorn.exe app.main:app --reload`, then http://127.0.0.1:8000/docs
(PowerShell needs the leading `.\` and you must be in `backend\`, not the repo root.)

## Where the code lives

| File | Holds |
|---|---|
| [main.py](../backend/app/main.py) | every route. HTTP only — status codes, query params |
| [db.py](../backend/app/db.py) | `get_conn()`, one connection per use, `.env` by absolute path |
| [models.py](../backend/app/models.py) | Pydantic shapes: `SmsIn`, `TransactionIn` |
| [transactions.py](../backend/app/transactions.py) | all transaction SQL, incl. the `ON CONFLICT` dedupe |
| [cards.py](../backend/app/cards.py) | card SQL + `resolve_card_id` (last4 → account) |
| [sms.py](../backend/app/sms.py) | prompt, JSON schema, guardrails. **No database** |
| [llm.py](../backend/app/llm.py) | provider interface, Gemini REST, model fallback chain |
| [ingest.py](../backend/app/ingest.py) | orchestration: store → extract → link → record |
| [check_sms.py](../backend/check_sms.py) | manual extraction test. Costs quota to run |

**Layering rule that's worth keeping:** routes do HTTP, `*.py` data modules do SQL, `sms.py` does parsing and touches no database, `ingest.py` is the only thing that coordinates across them. That's why the extractor could be tested against six messages without a database, and why swapping Gemini out means editing one file.

## The API as it stands

| Route | Behaviour |
|---|---|
| `GET /health` | server + DB reachability |
| `POST /transactions` | 201 created, 200 + existing row on duplicate `dedupe_key` (ADR 012), 400 bad card, 422 validation |
| `GET /transactions` | newest first by `txn_time`; filters `type`, `category`, `merchant` (partial, case-insensitive), `card_id`, `start`, `end`; `limit` 1-200 default 50 |
| `GET /transactions/{id}` | one row, 404 if absent |
| `DELETE /transactions/{id}` | 204, 404 if absent (ADR 014) |
| `POST /sms` | store raw, extract, link card, insert. **Always 200** - an unparseable SMS is a recorded outcome, not a failed request |
| `GET /sms/unparsed` | `pending` + `failed` messages. The format-change alarm |
| `POST /sms/reprocess` | replay failures. Safe because `dedupe_key` makes re-insert a no-op |
| `GET /sms/ignored` | messages judged not to be transactions — where a wrongly-dropped spend would hide |
| `PATCH /transactions/{id}` | partial edit. Does NOT change review_status |
| `GET /transactions/review` | the tick/cross queue, each row with its source SMS |
| `POST /transactions/{id}/confirm` \| `/reject` | green tick / red cross |
| `POST` `GET` `PATCH /cards` | account CRUD — the app's edit button |
| `POST /cards/{id}/numbers` | attach a physical card (Visa + RuPay on one account) |
| `PATCH /cards/{id}/numbers/{last4}` | retire a reissued card without losing history |
| `GET /cards/{id}/reconcile` | check spending against the bank's own limit figures |

Phase 4's agent tools map straight onto the GET filters: `monthly_total` is `start`/`end`, `search` is `merchant`.

## How a request flows

```
POST /sms  {sender, message, sms_sent_at}
   |
   main.py            route, validates against SmsIn
   |
   ingest.py  store_raw()      -> INSERT raw_sms, COMMIT, connection closed
   |                              (before extraction, on purpose - ADR 018)
   |
   ingest.py  process_raw()
   |    |
   |    sms.py    extract()    -> builds prompt + JSON schema
   |    |    llm.py            -> Gemini REST, walks the model chain on 429
   |    |    sms.py            -> guardrails: amount must appear in the text
   |    |                         strings -> Decimal, ISO -> datetime
   |    |                      -> Extraction(parsed | ignored | failed)
   |    |
   |    cards.py   resolve_card_id()   last4 -> account, or None if ambiguous
   |    transactions.py create_transaction()  ON CONFLICT (dedupe_key)
   |    |
   |    UPDATE raw_sms SET parse_status, transaction_id
   |
   200 {raw_sms: {...}, duplicate: false}
```

Nothing below `main.py` knows about HTTP; `sms.py` never touches the database; `ingest.py` is the only module that coordinates across layers.

## Extraction: LLM, no regexes (ADRs 019, 022, 023)

Message goes to Gemini with a constrained JSON schema at temperature 0. No per-bank patterns exist and none are wanted - a regex encodes a format and breaks when a bank changes it.

Handles with no bank-specific code: `27-08-26`, `29/08/2026` and `07 AUG 2026`; 12-hour time (`08:38 PM` -> `20:38`); Amex's five-digit suffix; a payee named mid-sentence with no keyword; OTPs and marketing rejected.

**Two guardrails - do not remove:**
- Every schema field is **required AND nullable**. With only `is_transaction` required, the model returned `{is_transaction, type}` and nothing else on noisy messages.
- The extracted amount must **literally appear** in the message. An invented number is the one failure mode that would otherwise be silent.

**Model choice is a quota decision, not a quality one.** `gemini-3.6-flash` allows 20 requests **per day** on free tier. Quota is per-model, so `llm.py` walks a chain of five and falls through on 429/404/503/timeout, remembering what worked. `GEMINI_MODEL` pins one; `GEMINI_MODELS` overrides the chain.

## The exact next step

**The Expo app.** Decided deliberately to build this BEFORE the agent — the agent is purely additive and nothing depends on it, whereas the SMS pipeline has only ever been tested by pasting messages by hand.

Sequence agreed:
1. Screens against the live API — transaction list, cards, the review card with tick/cross
2. SMS reading, which needs native modules and a development build
3. (Deploy already done)

**Skip Expo Go — go straight to a development build.** `expo-sms` cannot read messages; reading needs `react-native-get-sms-android` (stored inbox, what the re-scan design needs) or `@maniac-tech/react-native-expo-read-sms` (incoming only). Neither is in Expo Go, so a dev build via EAS is required anyway. Arnav asked to skip Expo Go entirely, which is the right call.

**Two constraints, both real:**
- **Never publishable on the Play Store.** Google restricts `READ_SMS` to apps whose core function is SMS handling. Sideloaded APKs are unaffected, so nothing is blocked — but this sharpens ADR 001's "needs SMS permission" into "and therefore never on Play".
- The Expo read-SMS library documents testing only to SDK 50 and has open 2026 bug reports. Lightly maintained, and it's on the core capture path.

**The app needs its own outbox.** `raw_sms` guarantees nothing is lost *once the server has it*. Between phone and server there is no such guarantee, and Render's free tier sleeps — so a forwarded message can hit a cold start and time out. The app must hold each message locally and only mark it sent on acknowledgement. Same reasoning as ADR 018, one layer up.

## Deploy notes

Render reads settings from its dashboard, **not** from `render.yaml` — that file only applies to their Blueprint flow, and creating a Web Service manually ignores it. The settings that matter, entered by hand:

- Root Directory `backend`, Region Singapore, Free instance
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (`$PORT` must stay a variable; Render assigns it)
- `DATABASE_URL` and `GEMINI_API_KEY` set in Render's Environment tab, never committed

Free tier sleeps after 15 min idle, ~50s to wake. Supabase separately **pauses a free project after 7 days idle** and needs a manual click to restore — that is the failure worth preventing, and what the daily keepalive is for.

## UPI gap — known, not yet fixed

`upi_ref` and `payment_method` appear **nowhere** in `app/sms.py`. The extraction schema asks for eight fields and neither is among them, so a UPI message loses its reference number silently. No UPI message has ever been tested — all six cases are credit card messages.

Planned fix, and the reasoning matters: extract `upi_ref` with a **regex**, not the LLM. A UPI reference is an exact identifier and it *is* the dedupe key — an LLM transposing one digit produces a plausible-looking string that silently breaks dedupe on the next re-scan. Regex is exact or it fails. The LLM keeps the fields that need judgement (amount, merchant, date, type). Ask the model for the reference too and flag disagreement for review.

Blocked on Arnav supplying a real UPI debit SMS.

## Carried debt

- **No automated tests.** `check_sms.py` is a manual script and costs API quota to run. There is no regression net.
- No `PATCH /transactions` - a transaction can be created and deleted but not corrected.
- `POST /transactions` shows "Undocumented" beside its 201; fix with `responses={...}`.
- Two leftover manual test rows in `transactions` (ids 1, 2 - Zomato and Auto). Delete when convenient.

## Schema state - settled, don't revisit

Four tables, four migrations, all applied and verified against [schema.sql](../backend/schema.sql):

- `cards` - the ACCOUNT: one limit, one statement day, one due rule
- `card_numbers` - the physical cards on it (Visa + RuPay share one account)
- `transactions` - the money
- `raw_sms` - every message, stored before parsing

RLS gotcha: policy-less RLS is deny-all, but the backend connects as the table owner through the session pooler and owners bypass RLS - so it works today. If the Data API is ever re-enabled or a non-owner role used, tables read as EMPTY rather than erroring. Fails silent, not loud.

Real data currently in the DB: card account 3 (IDFC FIRST, statement 24, due day 8, numbers 7714 Visa + 3577 RuPay), 4 transactions, 3 raw_sms.

## Known gotcha for Phase 6

`amount` is `numeric(12,2)` in Postgres and `Decimal` in Python, but JSON has no decimal type — `120.50` serialises to `120.5` and the Expo app will parse it as a JavaScript float. Serialise money as a string at the API boundary before the app is built.

## Session notes — how the pair-mode rule actually played out

**2026-08-29 (schema session).** The transactions table was handed over as finished code rather than written by Arnav. He was walked through `id` (got it right unaided), stalled on `type`/`amount`, was offered three ways forward, and chose "just give me the code" after one push-back. **The nullability reasoning in ADR 011 is therefore not yet his.**

**2026-08-30 (Phase 2 session).** Same pattern, with a real win at the end. `POST /transactions`, the Pydantic models and the insert were written by the assistant as an annotated worked example at his request. He then wrote `list_transactions` himself — including choosing `txn_time desc` over `id` and getting the `(limit,)` tuple and `.fetchall()` right. The `GET` route wrapper was assistant-written.

**2026-08-30 (later, Phase 3 start).** He asked directly whether it's bad to understand concepts but not be able to write the code, and then whether he could just have code written and focus on understanding it. Answered honestly: recognition isn't recall, and regexes are the worst file to not own because he alone maintains them when a bank reformats. He then chose to write both parsers himself — **unprompted, and the strongest choice he's made**. Before starting he pushed back on the whole approach ("why not a universal method"), which was a better question than the task he'd been given and changed the plan. Two things follow: he engages far more with architecture than with syntax, and leading with the *why* gets more out of him than leading with the code. Diagnosis that seems to hold: concepts are ahead of syntax, and he stalls on blank pages, not on hard ideas.

**2026-08-30 (Phase 3 build).** All code assistant-written at his direction, and he steered rather than typed — which on this phase was the higher-value contribution. Three of his interventions changed the architecture: *"why not a universal method that needs no updating"* killed regexes in favour of LLM extraction (ADR 019); *"can we switch models automatically when quota runs out"* produced the fallback chain (ADR 023); and *"ask once for statement and due date, with an edit button"* confirmed storing the rule rather than dates. He also supplied the real SMS that broke four schema assumptions.

**How to run the rule (updated):** "never hand over finished code" is the default, not an absolute. Push back **once**, briefly, with a concrete alternative — then do what he picks without arguing again. Repeated refusal is friction, not teaching. He does engage when the target is small and unambiguous (three named blanks worked; a blank page did not). Prefer worked-example-then-parallel-task over blank-page assignments. Avoid `...` and `???` as blanks — he pasted them literally as code, reasonably.

**Where he's strongest:** architecture and requirements. He questions the approach before accepting a task, and has been right every time. Lead with the *why* and the design trade-off; he'll engage and often improve it. Leading with code loses him.

## Phase plan (Phase 4 next)

1. ✅ Backend skeleton + DB connection + schema — done and verified
2. ✅ Expense/income API — full CRUD with filtering, verified against the live DB
3. ✅ SMS ingestion — LLM extraction (no regexes, ADR 019), `raw_sms` audit trail, replay on failure. Verified on real Axis/Amex/IDFC messages
4. Agent — Gemini via the existing `llm.py` interface, function calling, tools: add/delete/search expenses, monthly totals, income, card spends, dues. Text chat first.
5. Deploy — Render free tier (backend) + this Supabase DB
6. Expo React Native app (TypeScript) — screens, then on-device voice (expo-speech-recognition + expo-speech), fingerprint gate (expo-local-authentication), local notifications 7/3/1 days before card due dates, expo-calendar for due-date events
7. APK via EAS cloud build

## Conventions

- Every decision gets an ADR entry in [decisions.md](decisions.md); commit + push after each work chunk
- Commits end with: `Co-Authored-By: Claude <noreply@anthropic.com>` (model name as appropriate)
- Secrets only in `backend/.env` (git-ignored); `.env.example` documents the shape; never print/paste secrets in chat
- `chat-archive/` holds raw session transcripts — local only, git-ignored, never push

## Gotchas already learned (don't re-teach unless asked)

- Placeholders (`YOUR-USERNAME`, `[YOUR-PASSWORD]`) — he's been bitten 3×, now knows
- PowerShell vs Git Bash path syntax; venvs break when moved (recreate instead)
- Old `C:\projects\kharcha` empty locked folder may still exist — ignore/delete it
- User's shell is PowerShell; give Windows paths in commands
