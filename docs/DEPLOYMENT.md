# Deployment Guide

This project is intended to run cloud-first on Railway with persistent storage mounted at `/memory`.

## 1. Deployment model

Recommended model:

1. Push code to GitHub
2. Railway service connected to GitHub repo (`main` or release branch)
3. Railway builds and deploys on push

This avoids manual local-only deploy drift.

## 2. Required infrastructure

- Railway project/service
- Redis service (or external Redis)
- Persistent volume mounted to `/memory`

Without `/memory`, posts/context/history are lost on restart.

## 3. Environment variables

Set these in Railway service variables:

- `GROQ_API_KEYS` (comma-separated list for key rotation)
- `TAVILY_API_KEY` (if enabled)
- `REDIS_HOST`
- `REDIS_PORT`
- `REDIS_PASSWORD` (if used)
- `DEFAULT_MODE` (recommended `light` for free-tier safety)
- `RAILWAY_API_TOKEN` only for CLI/API tooling actions, not app runtime

Optional but useful strict-saver values:

- `CONTEXT_DISCOVERY_INTERVAL_SEC=1200`
- `CONTEXT_MAX_STALENESS_SEC=21600`
- `BRIEF_PACK_COMPILE_TICK_SEC=60`
- `BRIEF_PACK_MAX_AGE_SEC=5400`

## 4. Build and start

Railway should use repository root.

- Build uses project Dockerfile/runtime setup
- Start command should execute:

```bash
./start_all.sh
```

`start_all.sh` launches agents + API in one service process group.

## 5. One-time database init

`start_all.sh` already runs:

```bash
python scripts/init_db.py
```

No separate migration job is required for current schema path.

## 6. Post-deploy verification

Run these checks after each deploy:

1. `GET /health` returns all agents `ok`
2. `GET /context/status` returns valid snapshot/provider state
3. `GET /briefing-pack/latest` returns current pack
4. `GET /observatory/recent` returns sequenced events
5. Frontend loads and tabs render correctly

## 7. Branch and release workflow

Recommended:

1. Work on feature branch
2. Open PR to `main`
3. Merge after review/checks
4. Railway auto-deploys from `main`

If branch protection is enabled on `main`, direct pushes are restricted by policy.

## 8. Rollback

If deploy regresses:

1. Roll back Railway service to previous successful deployment
2. Re-check `/health` and `/context/status`
3. Inspect observatory stream for errors

Data on `/memory` remains if the same persistent volume is retained.

## 9. Security notes

- Never commit `.env`, `/memory`, or API keys
- Rotate Groq/Tavily/Telegram credentials if exposed
- Keep repository secret scanning enabled
