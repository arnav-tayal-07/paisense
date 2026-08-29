# Session handoff — continue here

> **For any AI assistant picking this project up: read this file, then [decisions.md](decisions.md), before doing anything.**
> Last updated: 2026-08-29 (end of the initial planning + Phase 1 session).

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
| FastAPI app code | ❌ not started (backend/app/ is empty) |

## The exact next step

Phase 2: the expense/income API. **Arnav writes the routes and the SQL** — he knows FastAPI and raw SQL basics. Assistant writes app wiring/config only.

Schema state is fully settled as of 2026-08-29: both tables exist in Supabase, `schema.sql` mirrors them exactly (verified column-by-column and via `pg_class`), both have RLS enabled with **zero policies**.

RLS gotcha to remember: policy-less RLS is deny-all, but the backend connects as the table owner through the session pooler and owners bypass RLS — so it works today. If the Data API is ever re-enabled or a non-owner role is used, both tables read as empty rather than erroring. Fails silent, not loud.

## Session note (2026-08-29, second session)

The transactions table was handed over as finished code rather than written by Arnav. He was walked through `id` (got it right unaided), then stalled on `type`/`amount`, was offered three ways forward, and chose "just give me the code" after one push-back. That was his call and the right thing to respect — but it means **the nullability reasoning in ADR 011 is not yet his**. Worth re-testing in Phase 2: ask him to justify a `not null` choice on a new column before accepting it. Hold the pair-mode line on routes and regexes.

## Phase plan (currently mid-Phase 1/2)

1. ✅→ Backend skeleton + DB connection (done except schema completion)
2. Expense/income API — Arnav writes routes + SQL (he knows FastAPI + raw SQL basics from a practice project)
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
