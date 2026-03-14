# Deployment Guide

This project deploys a minimal current-picture app to Railway.

## Services

Run only:

- `researcher`
- `api`

`start_all.sh` already reflects this runtime scope.

## Required Infrastructure

- Railway backend service
- Redis
- Persistent volume mounted at `/memory`

## Required Environment Variables

- `GROQ_API_KEY` or `GROQ_API_KEYS`
- `REDIS_URL`
- `UI_CURRENT_PICTURE_ENABLED=true`
- `UI_CURRENT_PICTURE_INTERVAL_SEC=10800`
- `UI_CURRENT_PICTURE_SOURCE_URL=https://www.iranmonitor.org/api/export-prompt`
- `UI_CURRENT_PICTURE_STYLE_PROMPT=do phd level analysis n draw insights. write in fluffy paragraphs but not formal, like how u would say to a friend`

Recommended free-tier safe values:

- `UI_CURRENT_PICTURE_FRAME_MODEL=fast`
- `UI_CURRENT_PICTURE_PROSE_MODEL=standard`
- `UI_CURRENT_PICTURE_VERIFY_MODEL=fast`
- `UI_CURRENT_PICTURE_FRAME_MAX_TOKENS=220`
- `UI_CURRENT_PICTURE_PROSE_MAX_TOKENS=550`
- `UI_CURRENT_PICTURE_VERIFY_MAX_TOKENS=140`
- `UI_CURRENT_PICTURE_PROMPT_CHAR_LIMIT=2800`

For GitHub Actions deploy:

- repo secret `RAILWAY_API_TOKEN`

## Deploy Flow

1. Push to `main`
2. GitHub Actions workflow deploys backend to Railway
3. Wait for Railway deployment status `SUCCESS`

## Post-Deploy Verification

1. `GET /health` returns `200` and `researcher: ok`
2. `GET /current-picture/latest` returns:
   - `404` warmup on first boot until first generation, then
   - `200` with `generated_at`, `content`, `stale`
3. `GET /context/current-picture` returns `410` (deprecated route)
4. Frontend shows only `CURRENT PICTURE` and `ABOUT` tabs

## Security Notes

- Never commit `.env`, `/memory`, keys, or tokens
- Rotate keys immediately if exposed
- Keep GitHub secret scanning enabled
