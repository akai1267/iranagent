# Iran War Monitor AI Agentic Analyst

Multi-agent Iran conflict intelligence system with persistent context memory, observatory tracing, and quota-aware LLM orchestration.

## What this is

This project runs a coordinated backend of four agents plus one API service:

- `monitor`: ingests RSS, X (via Nitter RSS), and Telegram sources into a scored stream
- `orchestrator`: triages signal priority and routes tasks/interrupts
- `researcher`: builds layered context, updates theories, writes posts, answers queries
- `source_monitor`: evaluates source quality and proposes source list improvements
- `api`: serves HTTP endpoints, websocket observatory feed, and frontend assets

The system is designed for continuous analyst workflow, not one-shot chat. It keeps durable state in SQLite and `/memory` files so browser refreshes do not reset analysis history.

## Architecture

Core runtime and messaging:

- Redis pubsub and shared coordination for agent messaging
- Shared global budget/rate limits for all model calls
- Lane-aware model usage (`interactive` vs `background`)
- Heartbeat-based health checks for each agent

Persistent memory:

- SQLite database at `/memory/posts.db` for:
  - posts and FTS index
  - open questions
  - observatory events/details
  - context documents and snapshots
  - lightweight agent state
- Briefing pack files under `/memory/briefing_packs` for deterministic runtime context

## Context pipeline

The researcher builds layered context in a fixed order:

1. Structural Context (durable regime/system constraints)
2. Current Picture (latest authoritative cycle synthesis)
3. Latest High-Signal Stream Deltas
4. Relevant Prior Posts / Theories

Primary anchors are Critical Threats / ISW Iran Update docs. Iran Monitor briefing/structural inputs are supplemental according to source policy.

## Frontend

Single-page app with tabs:

- Feed
- Theories
- Current Picture
- Chat (UI-pause supported)
- About

Observatory stream is sequence-based and reconnect-safe (gap catch-up by `after_seq`).

## Local development

### Prereqs

- Python 3.11+
- Node 20+
- Redis

### Install

```bash
pip install -r requirements.txt
cd frontend && npm ci
```

### Configure env

Create `.env` from `.env.example` and set required secrets:

- `GROQ_API_KEYS` (comma-separated, supports multi-key rotation)
- `TAVILY_API_KEY` (optional but recommended for discovery fallback)
- Telegram credentials/session values if Telegram monitoring is enabled
- Redis connection values

### Run locally

```bash
./start_all.sh
```

App/API defaults to `http://localhost:8000`.

## Deployment

Primary deployment target is Railway.

- Deployment guide: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- Required token variable for CLI/API operations: `RAILWAY_API_TOKEN` (not `RAILWAY_TOKEN`)

## Repository hygiene

This repo intentionally does **not** track runtime or secret material:

- `.env` is ignored
- `/memory` is ignored
- build/dependency caches are ignored

Never commit API keys, Telegram session strings, or local DB files.

## Health and inspection endpoints

- `/health`
- `/budget/status`
- `/observatory/recent`
- `/context/current-picture`
- `/context/structural`
- `/context/documents`
- `/context/status`
- `/briefing-pack/latest`
- `/briefing-pack/latest/markdown`

## License

No license file is currently defined in this repository.
