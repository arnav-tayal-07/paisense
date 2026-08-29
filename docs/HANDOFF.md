# Session handoff — continue here

> **For any AI assistant picking this project up: read this file, then [decisions.md](decisions.md), before doing anything.**
> Last updated: 2026-08-30 (end of the Phase 2 session — schema done, POST + GET working).

## The one rule that overrides everything

**Arnav is learning. Do NOT write core logic for him.** Work in pair mode:
- He writes: routes, SQL, regexes, agent logic — with guidance and PR-style review.
- Assistant writes: boilerplate, config, deploy files — always explained.
- Explain concepts before code. Small phases, each ending in something runnable.
- He learns well from review feedback (see the cards-table review in the chat archive).

## Project state

| Item | Status |
|---|---|
| Architecture + all decisions | ✅ documented in [decisions.md](decisions.md) (ADR 001–010) |
| GitHub repo | ✅ https://github.com/arnav-tayal-07/paisense |
| Supabase project | ✅ `paisense`, region Mumbai, Data API disabled, RLS on |
| `backend/.env` with DATABASE_URL | ✅ exists locally (session pooler string), connection tested OK, git-ignored |
| Python venv | ✅ `backend/.venv` — fastapi, uvicorn, psycopg[binary], python-dotenv |
| `cards` table | ✅ created in Supabase (via SQL editor, RLS enabled) |
| `transactions` table | ✅ created in Supabase, verified — see [schema.sql](../backend/schema.sql) and ADR 011 |
| `backend/schema.sql` | ✅ complete and verified against the live DB — both tables, indexes, RLS |
| FastAPI app code | ✅ Phase 2 complete — `/health` + full transactions CRUD, all verified against the live DB |

Run it from `backend\`: `.\.venv\Scripts\uvicorn.exe app.main:app --reload`, then http://127.0.0.1:8000/docs
(PowerShell needs the leading `.\` and you must be in `backend\`, not the repo root.)

Files: [db.py](../backend/app/db.py) connection, [models.py](../backend/app/models.py) Pydantic, [transactions.py](../backend/app/transactions.py) SQL, [main.py](../backend/app/main.py) routes.

## The API as it stands

| Route | Behaviour |
|---|---|
| `GET /health` | server + DB reachability |
| `POST /transactions` | 201 created, 200 + existing row on duplicate `upi_ref` (ADR 012), 400 on bad `card_id`, 422 on bad type/amount |
| `GET /transactions` | newest first by `txn_time`; optional `type`, `category`, `merchant` (partial, case-insensitive), `start`, `end`; `limit` 1–200 default 50 |
| `GET /transactions/{id}` | one row, 404 if absent |
| `DELETE /transactions/{id}` | 204 on success, 404 if absent (ADR 014) |

Phase 4's agent tools map straight onto the GET filters: `monthly_total` is `start`/`end`, `search` is `merchant`.

## The exact next step

**Phase 3 — the SMS parser.** Arnav supplies real anonymized bank SMS; he writes the regexes. New endpoint `POST /sms` takes raw message text, parses it into a `TransactionIn`, and calls the existing `create_transaction()` — the dedupe is already built and tested, so re-scanning the inbox is safe from day one. Regexes live server-side (ADR 001) so a bank changing its format doesn't need a new APK.

**Carried debt, deal with it before Phase 5 deploy:**

- **No tests.** Everything to date was verified by hand or by throwaway scripts. There is no regression net, and Phase 3 will be editing these exact routes.
- `POST` shows "Undocumented" beside its 201 because the status is set dynamically rather than declared — cosmetic, fix with `responses={...}`.
- No `PATCH` — a transaction can be created and deleted but not corrected.

## Schema state — settled, don't revisit

Both tables exist in Supabase, `schema.sql` mirrors them exactly (verified column-by-column and via `pg_class`), both have RLS enabled with **zero policies**.

RLS gotcha: policy-less RLS is deny-all, but the backend connects as the table owner through the session pooler and owners bypass RLS — so it works today. If the Data API is ever re-enabled or a non-owner role is used, both tables read as empty rather than erroring. Fails silent, not loud.

Test data currently in `transactions`: 2 rows (ids 1 and 2, Zomato and Auto). Delete them before real data goes in.

## Known gotcha for Phase 6

`amount` is `numeric(12,2)` in Postgres and `Decimal` in Python, but JSON has no decimal type — `120.50` serialises to `120.5` and the Expo app will parse it as a JavaScript float. Serialise money as a string at the API boundary before the app is built.

## Session notes — how the pair-mode rule actually played out

**2026-08-29 (schema session).** The transactions table was handed over as finished code rather than written by Arnav. He was walked through `id` (got it right unaided), stalled on `type`/`amount`, was offered three ways forward, and chose "just give me the code" after one push-back. **The nullability reasoning in ADR 011 is therefore not yet his.**

**2026-08-30 (Phase 2 session).** Same pattern, with a real win at the end. `POST /transactions`, the Pydantic models and the insert were written by the assistant as an annotated worked example at his request. He then wrote `list_transactions` himself — including choosing `txn_time desc` over `id` and getting the `(limit,)` tuple and `.fetchall()` right. The `GET` route wrapper was assistant-written.

**How to run the rule (updated):** "never hand over finished code" is the default, not an absolute. Push back **once**, briefly, with a concrete alternative — then do what he picks without arguing again. Repeated refusal is friction, not teaching. He does engage when the target is small and unambiguous (three named blanks worked; a blank page did not). Prefer worked-example-then-parallel-task over blank-page assignments. Avoid `...` and `???` as blanks — he pasted them literally as code, reasonably.

## Phase plan (Phase 3 next)

1. ✅ Backend skeleton + DB connection + schema — done and verified
2. ✅ Expense/income API — full CRUD with filtering, verified against the live DB
3. SMS parser — he supplies real anonymized bank SMS; he writes regexes; dedupe by upi_ref
4. Agent — **Gemini Flash free tier** (ADR 009), function calling, tools: add/delete/search expenses, monthly totals, income, card spends, dues. Provider behind a swappable interface. Text chat first.
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
