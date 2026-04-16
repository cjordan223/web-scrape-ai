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
cd /Users/conner/Documents/JobForge
source venv/bin/activate
python dashboard/backend/server.py

# Frontend dev
cd dashboard/web
npm run dev

# Frontend production build
cd dashboard/web
npm run build

# Tests
source venv/bin/activate
python -m pytest dashboard/backend/tests/test_tailoring_api.py
PYTHONPATH=tailoring python -m pytest tailoring/tests/test_ollama_tracing.py
```

## Dashboard Notes

- Backend: `dashboard/backend/`
- Frontend: `dashboard/web/`
- Production UI route base: `http://localhost:8899`

Desktop routes (two domains — Pipeline and Ops):

- `/pipeline/editor` — pipeline editor (default landing page)
- `/pipeline/ingest` — manual job ingest
- `/pipeline/qa` — QA triage (approve/reject/LLM-review)
- `/pipeline/leads` — HN Hiring leads browser
- `/pipeline/ready` — ready jobs with queue controls
- `/pipeline/packages` — tailoring output packages
- `/pipeline/applied` — applied applications tracker

- `/ops/inventory` — job inventory
- `/ops/rejected/scraper` — scraper rejections
- `/ops/rejected/qa` — QA rejections
- `/ops/traces` — tailoring LLM trace inspector
- `/ops/llm` — LLM provider management (keys, models)
- `/ops/admin` — admin operations + DB explorer

Mobile routes (auto-redirect on `width < 768`), tab bar order: Ingest, QA, Jobs, Docs:

- `/m/ingest` — two input modes: **Paste Text** (raw JD → LLM parse) or **URL** (fetch + LLM parse). Both flow into editable fields → commit to DB → queue for tailoring
- `/m/qa` — QA triage: approve/reject/LLM-review pending jobs, scan mobile-jd folder for OCR ingest
- `/m/jobs` — job list with queue controls
- `/m/docs` — tailoring output packages

## Important Backend Behavior

- DB explorer filtering is server-side and column-aware (`/api/db/table/{name}`).
- SQL query endpoint (`/api/db/query`) is SELECT-only.
- Admin ops page (`/ops/admin`) fires destructive actions directly — no feature flag, no confirmation phrase.
- Production DB: `jobs` table is the source of truth; `results` is a VIEW (`SELECT *, status AS decision FROM jobs`).
- LLM provider registry in `providers.py`: ollama, mlx, gemini, groq, mistral, openrouter, together, custom. Legacy `"lmstudio"`/`"openai"` auto-migrate to `"ollama"` on load.
- Applied applications snapshot artifacts into `applied_snapshots` table — survives package deletion.
- LLM model selection is explicit — JobForge never auto-picks the first model from a shared endpoint. Tailoring will fail with a clear error if no model is configured.

### API endpoints by domain

**Scraping** (`routers/scraping.py`):
- `GET /api/overview`
- `GET /api/jobs`, `GET /api/jobs/{job_id}`
- `GET /api/rejected`, `GET /api/rejected/stats`, `GET /api/rejected/{rejected_id}`, `POST /api/rejected/{rejected_id}/approve`
- `GET /api/runs`, `GET /api/runs/active`, `GET /api/runs/{run_id}`, `GET /api/runs/{run_id}/logs`
- `POST /api/runs/{run_id}/terminate`
- `GET /api/dedup/stats`, `GET /api/growth`, `GET /api/filters/stats`
- `POST /api/scrape/run`, `GET /api/scrape/runner/status`, `GET /api/scrape/sources`

**Tailoring** (`routers/tailoring.py`):
- `GET /api/tailoring/runner/status`, `POST /api/tailoring/runner/stop`
- `GET /api/tailoring/ready`, `POST /api/tailoring/ready/bucket`, `POST /api/tailoring/ready/queue-bucket`
- `GET /api/tailoring/rejected`
- `GET /api/tailoring/jobs/recent`, `GET /api/tailoring/jobs/{job_id}`, `GET /api/tailoring/jobs/{job_id}/briefing`
- `POST /api/tailoring/run`, `POST /api/tailoring/run-latest`
- `POST /api/tailoring/queue`, `GET /api/tailoring/queue`, `DELETE /api/tailoring/queue`, `DELETE /api/tailoring/queue/{index}`
- `GET /api/tailoring/runs`, `GET /api/tailoring/runs/{slug}`, `GET /api/tailoring/runs/{slug}/trace`, `GET /api/tailoring/runs/{slug}/artifact/{name}`
- `GET /api/packages`, `GET /api/packages/{slug}`, `DELETE /api/packages/{slug}`, `GET /api/packages/{slug}/download.zip`
- `POST /api/packages/{slug}/reject`, `POST /api/packages/{slug}/dead`, `POST /api/packages/{slug}/apply`
- `POST /api/packages/{slug}/regenerate/cover`
- `POST /api/packages/{slug}/latex/{doc_type}`, `POST /api/packages/{slug}/compile/{doc_type}`
- `GET /api/packages/{slug}/diff-preview/{doc_type}`
- `POST /api/packages/{slug}/chat`, `GET /api/packages/{slug}/chat`, `DELETE /api/packages/{slug}/chat`
- `GET /api/applied`, `GET /api/applied/{application_id}`, `POST /api/applied/{application_id}/tracking`, `GET /api/applied/{application_id}/artifact/{name}`
- `GET /api/llm/status`, `GET /api/llm/models`, `POST /api/llm/models/select`, `POST /api/llm/models/deselect` (legacy aliases: `/load`, `/unload`)
- `GET /api/llm/providers`, `POST /api/llm/providers/key`, `POST /api/llm/providers/activate`, `POST /api/llm/providers/test`
- `GET /api/llm/infrastructure`, `GET /api/llm/catalog`, `POST /api/llm/chat`, `POST /api/llm/benchmark`
- `GET /api/llm/mlx/status`, `POST /api/llm/mlx/start`, `POST /api/llm/mlx/stop`, `GET /api/llm/mlx/models`, `POST /api/llm/mlx/pull`, `GET /api/llm/mlx/pull/status`
- `POST /api/tailoring/ingest/fetch-url`, `POST /api/tailoring/ingest/parse`, `POST /api/tailoring/ingest/commit`, `POST /api/tailoring/ingest/scan-mobile`
- `GET /api/tailoring/qa`, `POST /api/tailoring/qa/approve`, `POST /api/tailoring/qa/reject`, `POST /api/tailoring/qa/permanently-reject`
- `GET /api/tailoring/qa/llm-review`, `POST /api/tailoring/qa/llm-review`, `DELETE /api/tailoring/qa/llm-review`
- `POST /api/tailoring/qa/reset-approved`, `POST /api/tailoring/qa/undo-approve`, `POST /api/tailoring/qa/undo-reject`, `POST /api/tailoring/qa/rollback`
- `GET /api/leads`, `GET /api/state-log`

**Ops** (`routers/ops.py`):
- `GET /api/db/schema`, `GET /api/db/tables`, `GET /api/db/table/{name}`, `GET /api/db/query`, `GET /api/db/size`
- `GET /api/db/admin/status`, `POST /api/db/admin/action` (legacy, requires `DASHBOARD_ENABLE_DB_ADMIN=1`)
- `GET /api/ops/status`, `POST /api/ops/action` (current unified ops — no flag required)
- `GET /api/runtime-controls`, `POST /api/runtime-controls`
- `POST /api/tailoring/archive`, `GET /api/tailoring/archives`, `GET /api/tailoring/archives/{archive_id}`
- `GET /api/ops/pipeline/packages`, `GET /api/ops/pipeline/trace/{archive_id}/{slug}`
- `GET /api/ops/tailoring/metrics`
- `GET /api/scraper/config`, `POST /api/scraper/config`
- `GET /api/scraper/pipeline/stats`

## Scraper Package Layout (high-level)

Scrapy-style layout: discovery via spiders, processing via item pipelines.

- `job_scraper/config.py` — config models + YAML loader
- `job_scraper/db.py` — SQLite persistence (seen_urls, jobs, rejected, runs)
- `job_scraper/fetcher.py` — page/JD retrieval
- `job_scraper/items.py` — Scrapy item definitions
- `job_scraper/settings.py` — Scrapy settings
- `job_scraper/spiders/` — discovery sources: `searxng`, `ashby`, `greenhouse`, `lever`, `hn_hiring`, `remoteok`, `usajobs`, `generic`, `aggregator`
- `job_scraper/pipelines/` — processing stages: `dedup`, `text_extraction`, `hard_filter`, `storage`

## Tailoring Package Layout (high-level)

- `tailor/analyzer.py` — JD requirement extraction
- `tailor/writer.py` — strategy/draft/QA prompt pipeline
- `tailor/validator.py` — hard gates
- `tailor/compiler.py` — pdflatex wrapper
- `tailor/tracing.py` — per-call trace logging
- `tailor/ollama.py` — LLM client with file-lock mutex; requires explicit model via `TAILOR_LLM_MODEL` (no auto-discovery)
- `tailor/grounding.py` — structured grounding contract for tailoring
- `tailor/persona.py` — persona memory hierarchy (load, score, inject per stage)
- `tailor/selector.py` — interactive job selection for CLI
- `tailor/config.py` — paths, model config, constants

## Environment

- Host: macOS machine (LAN-accessed dashboard)
- Ports:
  - SearXNG `8888`
  - Dashboard `8899`
  - LLM endpoint `11434` (Ollama)
- `JOBFORGE_MANAGE_MLX=1` — opt-in to MLX server lifecycle management (start/stop/pull) from the dashboard. Without this, MLX endpoints are read-only.
