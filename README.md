# GTM Leads Research Analyst

This repository now ships a frontend-first demo for a GTM lead-research product.

The live UI has two tabs:

- `INTEL`
- `ABOUT`

The `INTEL` tab is a split-pane operator surface:

- left: a concise executive read for the last 7 days
- right: a deeper research workspace with active questions, opportunity patterns, watched accounts, and Clay CSV export

The demo is intentionally mock-backed. It does not require a live backend intelligence pipeline to render.

## Product Shape

The frontend is designed to show what an AI-assisted GTM research console could feel like before live crawling, scoring, or CRM sync exists.

Key characteristics:

- warm editorial UI instead of generic dashboard chrome
- local mock snapshot as the data source
- account-level Clay export generated client-side
- no dependency on `/current-picture/latest` or other backend endpoints for the main demo flow

## Runtime Scope

The repo still contains the minimal backend runtime from the prior app:

- `researcher`
- `api`

That backend remains deployable, but the GTM demo frontend is self-contained and does not rely on it for the `INTEL` tab.

## Demo Data Model

The demo is driven by a local snapshot object in:

- [frontend/src/data/gtmIntelMock.js](frontend/src/data/gtmIntelMock.js)

That snapshot powers:

- the executive summary
- the research workspace
- the watched accounts module
- the Clay CSV export

Docs for the demo contract live in:

- [docs/gtm-leads-prd.md](docs/gtm-leads-prd.md)
- [docs/gtm-leads-ux-spec.md](docs/gtm-leads-ux-spec.md)
- [docs/gtm-leads-mock-data-schema.md](docs/gtm-leads-mock-data-schema.md)
- [docs/gtm-leads-clay-export-spec.md](docs/gtm-leads-clay-export-spec.md)

## Clay Export

The `Export Clay CSV` button downloads a client-side CSV with one row per company.

It is intended as:

- a Clay-ready base table for enrichment
- an account-level export, not a contact list
- a bridge between research and downstream outbound workflow

## Local Run

### Prereqs

- Python 3.11+
- Node 20+
- Redis if you also want the backend running

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

For frontend-only work:

```bash
cd frontend
npm ci
npm run dev
```

## Deployment

Primary static hosting target:

- GitHub Pages via [.github/workflows/deploy-github-pages.yml](.github/workflows/deploy-github-pages.yml)

Legacy backend hosting target:

- Railway via [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

For GitHub Pages, the frontend build automatically uses the repo-name base path on CI, so the public URL for this repo will be:

- `https://akai1267.github.io/gtmdemo/`

## Secrets and Public Repo Safety

This repo is safe to keep public **only if** secrets stay out of git:

- `.env` is ignored
- `/memory` is ignored
- API keys should live in Railway/GitHub secrets, not tracked files

Run a quick scan before pushing if needed:

```bash
rg -n "gsk_|RAILWAY_API_TOKEN|BEGIN PRIVATE KEY|api[_-]?key" .
```
