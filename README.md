# Iran War Monitor AI Agentic Analyst

This repository is now a minimal app with two tabs only:

- `CURRENT PICTURE`
- `ABOUT`

`CURRENT PICTURE` is generated from IranMonitor prompt export data and refreshed on a schedule.

## Runtime Scope

Only the components required for current-picture generation are run in production:

- `researcher` (for scheduled generation)
- `api` (for serving endpoints + frontend)

The startup script no longer launches monitor/orchestrator/source-monitor processes.

## How Current Picture Works

1. Fetch source payload from `https://www.iranmonitor.org/api/export-prompt`
2. Append style instruction from `UI_CURRENT_PICTURE_STYLE_PROMPT`
3. Generate output with Groq
4. Persist snapshot in SQLite (`/memory/posts.db`, `context_snapshots` as `ui_current_picture`)
5. Frontend polls `GET /current-picture/latest`

## Endpoints Used by UI

- `GET /current-picture/latest`
- `GET /health`

Deprecated for this UI flow:

- `GET /context/current-picture` returns `410`

## Local Run

### Prereqs

- Python 3.11+
- Node 20+
- Redis

### Install

```bash
pip install -r requirements.txt
cd frontend && npm ci
```

### Configure

Copy `.env.example` to `.env` and set:

- `GROQ_API_KEY` or `GROQ_API_KEYS`
- `REDIS_URL`

### Start

```bash
./start_all.sh
```

App/API default: `http://localhost:8000`

## Deployment

Railway deployment doc: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

Important secret for CI deploys:

- `RAILWAY_API_TOKEN` (not `RAILWAY_TOKEN`)

## Secrets and Public Repo Safety

This repo is safe to keep public **only if** secrets stay out of git:

- `.env` is ignored
- `/memory` is ignored
- API keys should live in Railway/GitHub secrets, not tracked files

Run a quick scan before pushing if needed:

```bash
rg -n "gsk_|tvly-|RAILWAY_API_TOKEN|TELEGRAM_API_HASH|TELEGRAM_SESSION_STRING" .
```
