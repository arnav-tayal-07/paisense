# Session handoff — continue here

> **For any AI assistant picking this project up: read this file, then [decisions.md](decisions.md), before doing anything.**
> Last updated: 2026-09-04. **Backend deployed, Android app built and running on real data.** 149 transactions imported from Arnav's actual bank SMS.

## The one rule that overrides everything

**Arnav is learning. Do NOT write core logic for him.** Work in pair mode:
- He writes: routes, SQL, regexes, agent logic — with guidance and PR-style review.
- Assistant writes: boilerplate, config, deploy files — always explained.
- Explain concepts before code. Small phases, each ending in something runnable.
- He learns well from review feedback (see the cards-table review in the chat archive).

## Project state

| Item | Status |
|---|---|
| Decisions | OK [decisions.md](decisions.md), ADR 001-031. Sessions since are recorded in the git log |
| Repo | OK https://github.com/arnav-tayal-07/paisense (**public**) |
| **Live API** | OK **https://paisense.onrender.com** - auto-deploys on push to `main` |
| **API key** | OK every route except `/health` and `/docs` needs `X-API-Key` |
| Supabase | OK Mumbai, 5 tables, 11 migrations, RLS on everything |
| Keepalive | OK GitHub Action pings `/health` daily; secret set, run verified green |
| Transactions API | OK full CRUD + filtering + review queue + reconciliation |
| Accounts API | OK credit cards and bank accounts, several numbers per account |
| SMS ingestion | OK LLM extraction, self-written regex patterns, replay on failure |
| Bulk import | OK store-many plus a budgeted queue worker |
| Android app | OK **built and installed** - 5 tabs, SMS import, review, editing |
| Agent | TODO deferred until after the app |
| Automated tests | TODO none. Has now bitten us EIGHT times |

**Local dev:** `cd backend` then `.\.venv\Scripts\uvicorn.exe app.main:app --reload`.
Requests need the key: header `X-API-Key`, value from `backend\.env`.

## The Android app (native Kotlin + Compose)

Lives in `android/`, package `com.paisense.app`, min SDK 26. Build and install:

```
cd android
./gradlew.bat installDebug          # needs USB debugging on
```

Gradle needs Android Studio's bundled JDK, not the system one:
`JAVA_HOME="/c/Program Files/Android/Android Studio/jbr"`.

**Five tabs**: Summary, Expenses, Income, Card, Review.

| File | Holds |
|---|---|
| `MainActivity.kt` | tab scaffold, onboarding gate |
| `ui/OnboardingScreen.kt` + `OnboardingViewModel.kt` | permission, 1/2/3-month import |
| `ui/HomeViewModel.kt` | all six fetches, each independently caught |
| `ui/MoneyScreens.kt` | Summary panel, Card section, ledger lists |
| `ui/IncomeScreen.kt` | manual income entry only |
| `ui/EditDialog.kt` | rename any transaction |
| `ui/ReviewScreen.kt` | tick / cross queue |
| `work/ImportWorker.kt` | the import, in WorkManager with a notification |
| `data/` | Api, SmsReader, models |

**Things that are the way they are for a reason:**

- **Money is a String all the way through.** JSON has no decimal type; parsing to Double reintroduces exactly what `numeric(12,2)` avoids. An empty bucket defaulting to int `0` instead of `"0"` crashed the app — same boundary, third time.
- **Every fetch fails independently.** One bad endpoint used to blank the whole app.
- **`SmsReader` filters on device**: DLT-shaped sender AND the body must mention money. On a real inbox that was 293 messages → 184, and 95 senders → 33. Senders matter more: one with a single message can never yield a pattern.
- **A verb filter was tried and reverted** — it dropped real transactions phrased "Dr. from A/C" and "Thank you for payment of INR". The phone only skips what obviously isn't a transaction; deciding what one IS belongs to the model.
- **Import runs in WorkManager**, not a ViewModel. It was in `viewModelScope` first, so leaving the screen silently killed it while the button said "continue in background".

## Real data currently in the database

149 transactions, 184 raw messages, from Arnav's actual banks (RBL 7489, BOB 1614, IDFC card 7714 + 3577). One month imported.

```
Account spending (UPI)  ~104   Card spending  6   Card bills  3
Income (manual)            0   Wallets/other  11
```

## Where the code lives (backend)


| File | Holds |
|---|---|
| [main.py](../backend/app/main.py) | every route. HTTP only — status codes, query params |
| [db.py](../backend/app/db.py) | `get_conn()`, one connection per use, `.env` by absolute path |
| [models.py](../backend/app/models.py) | Pydantic shapes: `SmsIn`, `TransactionIn` |
| [transactions.py](../backend/app/transactions.py) | all transaction SQL, incl. the `ON CONFLICT` dedupe |
| [accounts.py](../backend/app/accounts.py) | account SQL + `resolve_account_id` (last4 -> account, kind-aware) |
| [sms.py](../backend/app/sms.py) | prompt, JSON schema, guardrails. **No database** |
| [llm.py](../backend/app/llm.py) | provider interface, Gemini REST, model fallback chain |
| [ingest.py](../backend/app/ingest.py) | orchestration: store -> pattern or model -> link -> record |
| [patterns.py](../backend/app/patterns.py) | generates, validates and runs the model-written regexes |
| [importer.py](../backend/app/importer.py) | bulk import: store many, extract on a budget |
| [auth.py](../backend/app/auth.py) | the shared API key, as middleware so new routes are covered |
| [check_sms.py](../backend/check_sms.py) | manual extraction test. Costs quota to run |

**Layering rule that's worth keeping:** routes do HTTP, `*.py` data modules do SQL, `sms.py` does parsing and touches no database, `ingest.py` is the only thing that coordinates across them. That's why the extractor could be tested against six messages without a database, and why swapping Gemini out means editing one file.

## The API as it stands

Every route below needs `X-API-Key`. Only `/health` and `/docs` are open.

| Route | Behaviour |
|---|---|
| `GET /health` | server + DB. Open, so the keepalive can reach it |
| `POST` `GET` `PATCH` `DELETE /transactions` | full CRUD; PATCH is partial (`exclude_unset`) |
| `GET /transactions` filters | type, category, merchant, account_id, start, end, limit, include_unreviewed |
| `GET /transactions/review` | the tick/cross queue, each row with its source SMS |
| `POST /transactions/{id}/confirm` and `/reject` | green tick / red cross |
| `POST` `GET` `PATCH /accounts` | credit card and bank accounts |
| `POST /accounts/{id}/numbers` | attach a card; PATCH .../numbers/{last4} retires a reissued one |
| `GET /accounts/{id}/reconcile` | recorded spend vs the bank's own balance figures |
| `POST /sms` | one message: store, extract, link, record. **Always 200** |
| `POST /sms/batch` | many messages, stored pending, no extraction. Instant and free |
| `POST /sms/import/run?budget=N` | work the queue, spending at most N model calls |
| `GET /sms/import/status` | progress, broken down by sender |
| `GET /sms/unparsed` | the alarm list |
| `GET /sms/ignored` | where a wrongly-dropped spend would hide |
| `POST /sms/reprocess` | replay failures |
| `POST /sms/patterns/{sender_code}` | have the model write regexes for a bank |
| `GET /sms/patterns` | patterns with hit/miss counts |

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

## Extraction: two layers (ADRs 019, 022, 023, 026, 029, 030, 031)

**Layer 1 - patterns.** Regexes the model wrote itself, stored in `sms_patterns`. Free, about a second, deterministic. Tried first.

**Layer 2 - the model.** Gemini with a constrained JSON schema at temperature 0. Handles anything no pattern matches, and writes the next pattern.

**One field is always regex, never the model:** `upi_ref`. A reference is a meaningless identifier *and* the dedupe key, so a transposed digit looks perfectly valid and silently breaks dedupe. The model is asked too, purely so a disagreement can be flagged.

**Guardrails - do not remove:**
- Every schema field is **required AND nullable**. With only `is_transaction` required, the model returned two fields and nothing else on noisy messages.
- The amount must **literally appear** in the message text. An invented number is the one silent failure.
- A pattern goes active only if it reproduces the model's own answer on **2+** samples AND fails to match other formats from the same bank.

**Handles with no bank-specific code:** four date formats including `(2026:08:27 08:01:42)`, 12-hour time, Amex's five digits, a payee named mid-sentence, UPI VPAs; OTPs and marketing rejected.

**Model choice is a quota decision.** `gemini-3.6-flash` allows 20 calls/day on free tier. `llm.py` walks a chain of five and falls through on 429/404/503/timeout, remembering what worked.

## Import economics (measured)

| | messages | model calls |
|---|---|---|
| first import, learning 4 formats | 64 | 32 |
| second import, patterns already exist | 56 | **0** |

The learning cost is paid once per format.

## The exact next step

**Counterparty labels.** 107 of 139 transactions show a masked account number
instead of a name, because RBL's UPI format never states a payee. Renaming
works today but applies to ONE row; naming  should name every
transaction with those digits, past and future. Small table, lookup at read
time, and it is the single biggest readability win left.

Then, in rough order:

- **Automated tests.** Eight incidents now, several of which a five-line test
  would have caught. This is the largest piece of debt in the project.
- **Import more history.** Only one month is loaded; the app supports 1/2/3.
- **Notifications for card due dates** (7/3/1 days) - the reminder feature from
  ADR 005, still unbuilt.  already supplies the dates.
- **Biometric gate** (ADR 007).
- **Phase 4, the agent** - deliberately deferred until the app is solid.

## Deploy notes

Render reads settings from its dashboard, **not** from `render.yaml` — that file only applies to their Blueprint flow, and creating a Web Service manually ignores it. The settings that matter, entered by hand:

- Root Directory `backend`, Region Singapore, Free instance
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (`$PORT` must stay a variable; Render assigns it)
- `DATABASE_URL` and `GEMINI_API_KEY` set in Render's Environment tab, never committed

Free tier sleeps after 15 min idle, ~50s to wake. Supabase separately **pauses a free project after 7 days idle** and needs a manual click to restore — that is the failure worth preventing, and what the daily keepalive is for.

## Bugs found by using it on real data — read before changing these

Every one came from Arnav using the app, and none would have surfaced from testing.

1. **Card bills counted twice.** A payment produces two messages: the bank says money left, the card says money arrived. `card_payment_mirror` marks the card side; only the bank side counts.
2. **IPO blocks counted as spending.** "Rs.14938 is blocked in your A/C" is money held, not spent. The extractor now refuses blocked-funds messages entirely — if allotted, the bank sends its own debit.
3. **The due date showed the wrong bill.** It reported the cycle still accumulating (8 Oct) while the bill actually owed was 8 Sept, four days away. `cycle_for` now returns both, and `due_date` is the one owed.
4. **Outstanding was a stale snapshot.** `limit - available` is only true at the instant the bank sent it; transactions since must be re-applied.
5. **Outstanding compared different limits.** His limit went 20,000 → 36,300 on 30 Aug while the newest balance was from the 27th, overstating debt by 16,300. `accounts.credit_limit_from` makes the calculation REFUSE rather than answer wrongly.
6. **Duplicates from multiple DLT headers.** Banks send the same alert from several senders. A reference now keys alone (`ref:...`); the derived key uses the issuer segment, not the full header.
7. **Orphans from a key-format change.** Re-parsing created a new row and repointed the message, leaving the old one behind as a phantom. `_drop_orphan` cleans up.
8. **HTTP 422** — the app pulled every expense with `limit=500` to filter locally, over the 200 cap. Filtering moved to the server: `?account_kind=credit_card`.
9. **Bank credits are not income.** Refunds, split settlements, his own transfers. Income is manual-entry only now; the "received" section was removed from the UI entirely at his request.

## Known limitations, not bugs

- **107 of 139 transactions have no payee name** because RBL's UPI format says "credited to a/c XX0233" and stops. No prompt can extract what isn't there. Tapping a row renames it; a per-counterparty label that applies to all matching rows is the proper fix and is NOT built.
- **Only one month is imported.** Older spending isn't in the database. Re-run import from onboarding for 2 or 3 months.
- **`outstanding` currently refuses to compute** for the IDFC card, correctly — the newest balance predates the limit change. It resolves itself as soon as a new card message arrives, now that limit notices are read automatically.

## Carried debt

- **Still no automated tests.** Now eight separate incidents.
- Counterparty labels not built.
- The agent (Phase 4) is still deferred.

## Schema state - settled, don't revisit

Five tables, nine migrations, all applied and verified against [schema.sql](../backend/schema.sql):

- `accounts` - credit card OR bank account; card-only fields constrained by `kind`
- `account_numbers` - the card/account numbers on it (Visa + RuPay share one account)
- `transactions` - the money
- `raw_sms` - every message, stored before parsing
- `sms_patterns` - regexes the model wrote for itself. Deliberately has NO owner
  column: an SMS format belongs to a bank, not a customer, so in a multi-user
  PaiSense transactions are per-user and patterns stay shared

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

**2026-09-02 (backend completion).** All code assistant-written at his direction. Four of his interventions changed the architecture, and every one was right: *"why not a universal method that needs no updating"* killed regex-only parsing (ADR 019); *"switch models automatically when quota runs out"* produced the fallback chain (ADR 023); *"generate a regex from one SMS and reuse it"* became the whole pattern system, which is the single best idea in the project (ADR 029); and *"the same bank has card and account formats, keep them separate"* found a real gap in pattern isolation (ADR 030). He also chose native Android over React Native after being given the trade-off (ADR 027), and decided single-user-for-now with multi-user later (ADR 028).

**Pattern that holds:** he is strongest on architecture and requirements, and reliably questions the approach before accepting a task. Lead with the *why* and the trade-off; he engages and often improves it. Leading with code loses him. He also asks for a plain summary when overwhelmed - give a short one, not a longer one.

## Phase plan (the app is next)

1. ✅ Backend skeleton + DB connection + schema — done and verified
2. ✅ Expense/income API — full CRUD with filtering, verified against the live DB
3. ✅ SMS ingestion — LLM extraction (no regexes, ADR 019), `raw_sms` audit trail, replay on failure. Verified on real Axis/Amex/IDFC messages
4. Agent — Gemini via the existing `llm.py` interface, function calling, tools: add/delete/search expenses, monthly totals, income, card spends, dues. Text chat first.
5. Deploy — Render free tier (backend) + this Supabase DB
6. **NEXT: native Android app (Kotlin + Compose, ADR 027 - not Expo)** — screens, then on-device voice (expo-speech-recognition + expo-speech), fingerprint gate (expo-local-authentication), local notifications 7/3/1 days before card due dates, expo-calendar for due-date events
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
