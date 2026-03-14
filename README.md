# Iran War Monitor AI Agentic Analyst

Multi-agent Iran conflict intelligence system with persistent context memory, briefing-pack runtime state, observatory tracing, and quota-aware LLM orchestration.

## What this is

This project runs a coordinated backend of four agents plus one API service:

- `monitor`: ingests RSS, X (via Nitter RSS), and Telegram sources into a scored stream
- `orchestrator`: triages signal priority and routes tasks/interrupts
- `researcher`: builds layered context, updates theories, writes posts, answers queries
- `source_monitor`: evaluates source quality and proposes source list improvements
- `api`: serves HTTP endpoints, websocket observatory feed, and frontend assets

The system is designed for continuous analyst workflow, not one-shot chat. It keeps durable state in SQLite and `/memory` files so browser refreshes do not reset analysis history, and it compiles a persistent briefing pack that the researcher reads as runtime truth.

## Architecture

Core runtime and messaging:

- Redis pubsub and shared coordination for agent messaging
- Shared global budget/rate limits for all model calls
- Lane-aware model usage (`interactive` vs `background`)
- Heartbeat-based health checks for each agent

Persistent memory:

- SQLite database at `/memory/posts.db` for:
  - posts and FTS index
  - internal claim provenance for posts
  - open questions
  - observatory events/details
  - context documents and snapshots
  - lightweight agent state
- Briefing pack files under `/memory/briefing_packs` for deterministic runtime context

Writer pipeline:

- config-first researcher contract and template system
- hidden-provenance post generation (`frame -> prose -> verifier`)
- current-picture generation (`frame -> prose -> verifier`)
- UI current-picture tab refresh from IranMonitor export prompt every 3 hours
- file-backed editorial briefs instead of hardcoded example-heavy style prompting

## Context pipeline

The researcher builds layered context in a fixed order:

1. Structural Context (durable regime/system constraints)
2. Current Picture (latest authoritative cycle synthesis)
3. Latest High-Signal Stream Deltas
4. Relevant Prior Posts / Theories

Primary anchors are Critical Threats / ISW Iran Update docs. Iran Monitor briefing/structural inputs are supplemental according to source policy.

## Researcher behavior

The researcher does not write directly from raw stream lines. It reads a persistent briefing pack assembled from:

1. structural context
2. current picture
3. latest material stream deltas
4. prompt-eligible prior posts and theories

Post generation uses a staged pipeline:

1. internal frame generation
2. public prose generation
3. verifier pass against evidence ledger and freshness state

Public prose is paragraph-first and analyst-oriented. Provenance is stored internally through `evidence_refs` and `claim_map`, not exposed inline as visible `[E#]` tags in the writing itself.

## Frontend

Single-page app with tabs:

- Feed
- Theories
- Current Picture
- Chat (UI-pause supported)
- About

Observatory stream is sequence-based and reconnect-safe (gap catch-up by `after_seq`).
The `Current Picture` tab reads `/current-picture/latest` (IranMonitor prompt export + Groq rewrite).

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

Researcher-specific knobs:

- `WRITER_PIPELINE_V2=true`
- `RESEARCHER_EDITORIAL_BRIEF_PATH=/config/editorial_brief.md`
- `RESEARCHER_CURRENT_PICTURE_BRIEF_PATH=/config/current_picture_brief.md`
- `UI_CURRENT_PICTURE_ENABLED=true`
- `UI_CURRENT_PICTURE_INTERVAL_SEC=10800`
- `UI_CURRENT_PICTURE_SOURCE_URL=https://www.iranmonitor.org/api/export-prompt`

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
- `/posts`
- `/posts/{id}/evidence`
- `/current-picture/latest`
- `/context/structural`
- `/context/documents`
- `/context/status`
- `/briefing-pack/latest`
- `/briefing-pack/latest/markdown`

## License

No license file is currently defined in this repository.
