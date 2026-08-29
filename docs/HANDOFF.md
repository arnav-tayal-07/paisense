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
| `cards` table | ✅ created in Supabase (via SQL editor, RLS enabled) — see below |
| `transactions` table | ❌ **NEXT STEP — Arnav owes a draft** (see below) |
| `backend/schema.sql` | ❌ must be created to mirror what runs in Supabase (repo = source of truth) |
| FastAPI app code | ❌ not started (backend/app/ is empty) |

## The exact next step

Arnav was asked to draft `CREATE TABLE transactions` himself and paste it for review BEFORE running it. Do not write it for him. The agreed design:

- Columns: `id, type, amount, merchant, category, txn_time, upi_ref, payment_method, card_id, source, note, created_at`
- Already taught: identity PK, `numeric(12,2)` for money (never float), `timestamptz` for txn_time, `unique` nullable `upi_ref` (dedupe for SMS re-scans via ON CONFLICT DO NOTHING), `check (type in ('expense','income'))`, `card_id references cards(id)`, cards-before-transactions ordering.
- Review hardest: his `not null` choices (amount/type/txn_time must be not null; merchant/category/upi_ref/card_id/note nullable).

The `cards` table already in Supabase (mirror into schema.sql):

```sql
create table cards (
  id             bigint generated always as identity primary key,
  name           text not null,
  last4          char(4),
  statement_day  int not null check (statement_day between 1 and 31),
  due_days_after int not null default 20,
  credit_limit   numeric(12, 2),
  created_at     timestamptz not null default now()
);
```

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
