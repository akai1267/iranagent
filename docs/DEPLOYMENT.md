# Deployment Guide

This project deploys a backend service to Railway that also serves the built frontend bundle.

The current frontend product surface is the GTM demo:

- `INTEL`
- `ABOUT`

## What Is Actually Deployed

The deployed container still starts:

- `researcher`
- `api`

The GTM demo frontend itself is mock-backed and does not depend on live API data for the main `INTEL` experience. The backend remains present because it is already the production serving path for the frontend bundle.

## Services

Runtime entrypoint:

- [start_all.sh](/Users/arham/iranagent/start_all.sh)

Container build path:

- [Dockerfile](/Users/arham/iranagent/Dockerfile)

Railway deploy workflow:

- [.github/workflows/deploy-railway-backend.yml](/Users/arham/iranagent/.github/workflows/deploy-railway-backend.yml)

## Required Infrastructure

- Railway backend service
- Redis
- Persistent volume mounted at `/memory`

## Required Environment Variables

The legacy backend runtime still expects:

- `GROQ_API_KEY` or `GROQ_API_KEYS`
- `REDIS_URL`

If you still want the background researcher features active, keep the current-picture-related env vars configured as well. They are no longer required for the GTM demo UI itself, but they are still relevant to the existing backend process.

For GitHub Actions deploy:

- repo secret `RAILWAY_API_TOKEN`

## Deploy Flow

1. Push to `main`
2. GitHub Actions deploys the backend service to Railway
3. Railway builds the frontend bundle inside the Docker image
4. The FastAPI service serves the compiled frontend assets
5. Wait for deployment status `SUCCESS`

## Post-Deploy Verification

1. Open the production app root and confirm the header says `GTM Leads Research Analyst`
2. Confirm the top-level tabs are `INTEL` and `ABOUT`
3. Confirm the `INTEL` tab renders:
   - executive read on the left
   - research workspace on the right
   - `Export Clay CSV` button in the workspace header
4. Confirm `Export Clay CSV` downloads a file named like `gtm-leads-clay-export-YYYY-MM-DD.csv`
5. Confirm `GET /health` still returns `200`

## Security Notes

- Never commit `.env`, `/memory`, keys, or tokens
- Rotate keys immediately if exposed
- Keep GitHub secret scanning enabled
