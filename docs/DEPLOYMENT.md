# Deployment Guide

There are now two deployment paths in this repo:

1. **GitHub Pages** for the frontend-only GTM demo
2. **Railway** for the legacy backend/container path

For the current product surface, GitHub Pages is the correct default because the app is a static frontend demo.

## Recommended Path: GitHub Pages

Workflow:

- [.github/workflows/deploy-github-pages.yml](../.github/workflows/deploy-github-pages.yml)

Expected public URL:

- `https://akai1267.github.io/gtmdemo/`

Notes:

- the workflow passes Vite an explicit `--base` flag on CI so assets resolve correctly under the repo path
- local development still uses `/`
- if Pages has never been enabled on the repo before, GitHub may require enabling Pages with `Source: GitHub Actions` once in repository settings

## Legacy Path: Railway

The repo still contains the legacy backend runtime and Railway workflow, but it no longer runs automatically on push.

## Services

Runtime entrypoint:

- [start_all.sh](../start_all.sh)

Container build path:

- [Dockerfile](../Dockerfile)

Railway deploy workflow:

- [.github/workflows/deploy-railway-backend.yml](../.github/workflows/deploy-railway-backend.yml)

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

1. Trigger the Railway workflow manually
2. GitHub Actions deploys the backend service to Railway
3. Railway builds the frontend bundle inside the Docker image
4. The FastAPI service serves the compiled frontend assets
5. Wait for deployment status `SUCCESS`

## Post-Deploy Verification

### GitHub Pages

1. Open the public Pages URL and confirm the header says `GTM Leads Research Analyst`
2. Confirm the top-level tabs are `INTEL` and `ABOUT`
3. Confirm the `INTEL` tab renders:
   - executive read on the left
   - research workspace on the right
   - `Export Clay CSV` button in the workspace header
4. Confirm `Export Clay CSV` downloads a file named like `gtm-leads-clay-export-YYYY-MM-DD.csv`

### Railway

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
