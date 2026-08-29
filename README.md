# Kharcha — automatic UPI expense manager

A personal expense manager that logs UPI spends **automatically** (no manual entry), tracks income and credit cards, computes card due dates with reminders, and is controlled by a **voice agent** that acts as a proper tally keeper.

> Built as a learning project — every phase is documented in [docs/](docs/), including the *why* behind each decision, not just the code.

## How it works

Google Pay / PhonePe / Paytm have no public transaction APIs. But every UPI debit fires a **bank SMS**. So:

```
Bank SMS ──> Android app reads it ──> FastAPI backend parses it (regex + dedupe) ──> Postgres
                                            │
Voice command ──> on-device speech-to-text ─┤──> Claude agent calls tools (SQL) ──> spoken reply
```

- **Reminders live on the phone** (local notifications + device calendar → syncs to Google Calendar), so they work even when the free-tier server is asleep.
- **The agent brain lives in the backend** — the Anthropic API key can never ship inside an APK, and the tools need database access.
- **Voice is an input method, not the agent itself** — on-device STT/TTS wrap the same agent the text chat uses.

## Stack

| Layer | Tech | Hosting |
|---|---|---|
| Android app | React Native + Expo (TypeScript) | APK via EAS cloud build |
| Backend | FastAPI (Python) | Render (free tier) |
| Database | Postgres | Supabase / Neon (free tier) |
| Agent | Claude API (tool use) | Called from backend |
| Voice | expo-speech-recognition + expo-speech | On-device, free |
| Security | Fingerprint gate (expo-local-authentication) | On-device |

## Project status

- [x] Phase 0 — architecture & decisions ([docs/decisions.md](docs/decisions.md))
- [ ] Phase 1 — backend skeleton + database connection
- [ ] Phase 2 — expense & income API
- [ ] Phase 3 — SMS parser (bank regex + dedupe)
- [ ] Phase 4 — Claude tool-use agent
- [ ] Phase 5 — deploy (Render + managed Postgres)
- [ ] Phase 6 — Expo app: screens, voice, fingerprint, notifications, calendar
- [ ] Phase 7 — EAS APK build + real-world test

## Repo layout

```
backend/   FastAPI app (Python)
app/       Expo React Native app (added in Phase 6)
docs/      Architecture notes + decision log
```

## Running the backend locally

```
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# create backend/.env with DATABASE_URL=postgresql://...
uvicorn app.main:app --reload
```
