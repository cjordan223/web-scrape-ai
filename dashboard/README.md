# Dashboard

Shared control-plane app for:

- scraping workflow (`job-scraper/`)
- tailoring workflow (`tailoring/`)
- operations tooling (DB explorer, SQL console, schedules, admin ops)

## Components

- `backend/` — FastAPI backend (API + static file hosting)
  - `routers/` — domain route registration (`scraping`, `tailoring`, `ops`)
  - `services/` — route handlers by domain
  - `services/jd_fetch.py` — domain-specific JD fetchers (LinkedIn, Ashby, generic fallback)
- `web/` — React + TypeScript frontend (Vite, built to `web/dist/`)
  - `src/views/mobile/` — mobile-first views (auto-redirect on `width < 768`)

## Run

```bash
cd /Users/conner/Documents/SearXNG
source venv/bin/activate
python dashboard/backend/server.py
```

Open `http://localhost:8899`.

## Frontend Development

```bash
cd /Users/conner/Documents/SearXNG/dashboard/web
npm install
npm run dev       # dev server on :5173, proxies API to :8899
npm run build     # production build to dist/
```

## Admin Operations (`/ops/diagnostics/sql`)

The Admin Ops page provides destructive workflow management actions across all domains. Actions fire directly — no feature flag or confirmation phrase required.

### Scraping pipeline actions
- Clear scrape run history (`runs` table)
- Clear parsed jobs (`results` table)
- Clear rejections (`rejected` table)
- Clear URL dedup cache (`seen_urls` table)
- Clear all scraping data (all four tables)

### Tailoring pipeline actions
- Clear runner logs (`output/_runner_logs/`)
- Purge failed/errored run directories
- Purge all tailoring output directories

### Nuclear
- Nuke everything — all DB tables + all tailoring output directories

## Mobile UI (`/m/*`)

Auto-redirected when viewport width < 768px. Three tabs:

- **Ingest** (`/m/ingest`) — paste a job URL, server fetches + LLM parses fields, edit, commit to DB, queue for tailoring. Supports LinkedIn (`currentJobId=` rewritten to `/jobs/view/`), Ashby (embedded `descriptionHtml`), Greenhouse, SmartRecruiters, Microsoft Careers, and any server-rendered board.
- **Jobs** (`/m/jobs`) — browse recent jobs, multi-select + queue for tailoring
- **Docs** (`/m/docs`) — view tailoring output packages, open PDFs

## API Endpoints

See `CLAUDE.md` for the full endpoint reference grouped by domain.
