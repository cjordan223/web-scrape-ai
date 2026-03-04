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

# Frontend production build
cd dashboard/web
npm run build
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

Mobile routes (auto-redirect on `width < 768`):

- `/m/ingest` — URL-based job ingestion (fetch + LLM parse + commit + queue)
- `/m/jobs` — job list with queue controls
- `/m/docs` — tailoring output packages

## Important Backend Behavior

- DB explorer filtering is server-side and column-aware (`/api/db/table/{name}`).
- SQL query endpoint (`/api/db/query`) is SELECT-only.
- Admin ops page (`/ops/diagnostics/sql`) fires destructive actions directly — no feature flag, no confirmation phrase.

### API endpoints by domain

**Scraping** (`routers/scraping.py`):
- `GET /api/overview`
- `GET /api/jobs`, `GET /api/jobs/{id}`
- `GET /api/rejected`, `GET /api/rejected/stats`, `POST /api/rejected/{id}/approve`
- `GET /api/runs`, `GET /api/runs/active`, `GET /api/runs/{run_id}`, `GET /api/runs/{run_id}/logs`
- `POST /api/runs/{run_id}/terminate`
- `GET /api/dedup/stats`, `GET /api/growth`, `GET /api/filters/stats`
- `POST /api/scrape/run`, `GET /api/scrape/runner/status`

**Tailoring** (`routers/tailoring.py`):
- `GET /api/tailoring/runner/status` — includes `queue` field (list of pending jobs)
- `GET /api/tailoring/jobs/recent`, `GET /api/tailoring/jobs/{job_id}`
- `POST /api/tailoring/run`, `POST /api/tailoring/run-latest`
- `POST /api/tailoring/queue` — enqueue jobs `{ jobs: [{job_id, skip_analysis?}...] }`; auto-starts first if idle
- `GET /api/tailoring/queue` — current queue contents
- `DELETE /api/tailoring/queue` — clear all queued jobs
- `DELETE /api/tailoring/queue/{index}` — remove one queued job by index
- `GET /api/tailoring/runs`, `GET /api/tailoring/runs/{slug}`, `GET /api/tailoring/runs/{slug}/trace`
- `GET /api/tailoring/runs/{slug}/artifact/{name}`
- `GET /api/packages`, `GET /api/packages/{slug}`
- `POST /api/packages/{slug}/latex/{doc_type}`, `POST /api/packages/{slug}/compile/{doc_type}`
- `GET /api/packages/{slug}/diff-preview/{doc_type}`
- `GET /api/llm/status`, `GET /api/llm/models`
- `POST /api/llm/models/load`, `POST /api/llm/models/unload`
- `POST /api/tailoring/ingest/fetch-url` — fetch JD text from URL (domain-specific extractors)
- `POST /api/tailoring/ingest/parse` — LLM-extract structured fields from JD text
- `POST /api/tailoring/ingest/commit` — insert manual job into DB

**Ops** (`routers/ops.py`):
- `GET /api/db/schema`, `GET /api/db/tables`, `GET /api/db/table/{name}`, `GET /api/db/query`, `GET /api/db/size`
- `GET /api/db/admin/status`, `POST /api/db/admin/action` (legacy, requires `DASHBOARD_ENABLE_DB_ADMIN=1`)
- `GET /api/ops/status`, `POST /api/ops/action` (current unified ops — no flag required)
- `GET /api/schedules`, `GET /api/schedules/{label}/log`
- `GET /api/runtime-controls`, `POST /api/runtime-controls`

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
- `tailor/ollama.py` — LLM client; auto-discovers loaded model from `/v1/models` (override via `TAILOR_LMSTUDIO_MODEL`)
- `tailor/selector.py` — interactive job selection for CLI

## Environment

- Host: macOS machine (LAN-accessed dashboard)
- Ports:
  - SearXNG `8888`
  - Dashboard `8899`
  - LLM endpoint `1234`
