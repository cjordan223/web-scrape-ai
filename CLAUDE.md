# CLAUDE.md — Project Context

## Repo Summary

This workspace combines:

1. **SearXNG** at repo root (Docker, port `8888`)
2. **Job scraper package** in `job-scraper/`
3. **Shared dashboard** in `dashboard/` (FastAPI backend + React frontend)
4. **Tailoring engine** in `tailoring/`

## Core Runtime Flow

- SearXNG provides search results.
- Scraper runs query + crawl + dedup + filter pipeline.
- Results persist to SQLite (`~/.local/share/job_scraper/jobs.db`).
- Dashboard reads/controls scraping and tailoring workflows.

## Common Commands

```bash
# Scraper
source venv/bin/activate
cd job-scraper
python -m job_scraper scrape -v
python -m job_scraper stats
python -m job_scraper recent -n 20

# Dashboard backend
cd /Users/conner/Documents/SearXNG
source venv/bin/activate
python dashboard/backend/server.py

# Frontend dev
cd dashboard/web
npm run dev
```

## Dashboard Notes

- Backend: `dashboard/backend/`
- Frontend: `dashboard/web/`
- Production UI route base: `http://localhost:8899`

Hierarchical routes:

- `/home/overview`
- `/scraping/intake/jobs`
- `/scraping/intake/rejected`
- `/scraping/runs`
- `/scraping/quality/dedup`
- `/scraping/quality/schedules`
- `/tailoring/runs`
- `/tailoring/outputs/packages`
- `/ops/data/explorer`
- `/ops/diagnostics/sql`

## Important Backend Behavior

- DB explorer filtering is server-side and column-aware (`/api/db/table/{name}`).
- SQL query endpoint (`/api/db/query`) is SELECT-only.
- Optional DB admin endpoints:
  - `GET /api/db/admin/status`
  - `POST /api/db/admin/action`

DB admin actions require `DASHBOARD_ENABLE_DB_ADMIN=1`.

## Scraper Package Layout (high-level)

- `job_scraper/searcher.py` — SearXNG querying
- `job_scraper/crawler.py` — crawl targets + extraction
- `job_scraper/fetcher.py` — page/JD retrieval
- `job_scraper/filters.py` — policy pipeline
- `job_scraper/dedup.py` — SQLite persistence
- `job_scraper/llm_reviewer.py` — LLM review stage
- `job_scraper/urlnorm.py` — URL canonicalization

## Tailoring Package Layout (high-level)

- `tailor/analyzer.py` — JD requirement extraction
- `tailor/writer.py` — strategy/draft/QA prompt pipeline
- `tailor/validator.py` — hard gates
- `tailor/compiler.py` — pdflatex wrapper
- `tailor/tracing.py` — per-call trace logging

## Environment

- Host: macOS machine (LAN-accessed dashboard)
- Ports:
  - SearXNG `8888`
  - Dashboard `8899`
  - LLM endpoint `1234`
