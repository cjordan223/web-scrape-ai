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
cd /Users/conner/Documents/TexTailor
source venv/bin/activate
python dashboard/backend/server.py

# Frontend dev
cd dashboard/web
npm run dev

# Frontend production build
cd dashboard/web
npm run build

# Restart full stack (SearXNG + build frontend + backend)
./scripts/restart-dashboard.sh

# Tests
source venv/bin/activate
python -m pytest dashboard/backend/tests/test_tailoring_api.py
python -m pytest dashboard/backend/tests/test_package_chat.py
python -m pytest dashboard/backend/tests/test_scrape_scheduler.py
PYTHONPATH=tailoring python -m pytest tailoring/tests/test_ollama_tracing.py
```

## Dashboard Notes

- Backend: `dashboard/backend/`
- Frontend: `dashboard/web/`
- Production UI route base: `http://localhost:8899`

Desktop routes (two domains — Pipeline and Ops):

- `/pipeline/editor` — visual pipeline editor (default landing page, React Flow)
- `/pipeline/ingest` — manual job ingest
- `/pipeline/qa` — QA triage (approve/reject/LLM-review)
- `/pipeline/ready` — ready jobs with queue controls
- `/pipeline/packages` — tailoring output packages
- `/pipeline/applied` — applied applications tracker

- `/ops/inventory` — job inventory
- `/ops/rejected/scraper` — scraper rejections
- `/ops/rejected/qa` — QA rejections
- `/ops/traces` — tailoring LLM trace inspector
- `/ops/llm` — LLM provider management (keys, models)
- `/ops/metrics` — tailoring performance metrics
- `/ops/scraper` — scraper metrics (freshness visuals, tier stats)
- `/ops/system` — system status
- `/ops/admin` — SQL console + bulk ops

Mobile routes (auto-redirect on `width < 768`, defaults to `/m/qa`), tab bar order: Ingest, QA, Jobs, Docs:

- `/m/ingest` — two input modes: **Paste Text** (raw JD → LLM parse) or **URL** (fetch + LLM parse). Both flow into editable fields → commit to DB → queue for tailoring
- `/m/qa` — QA triage: approve/reject/LLM-review pending jobs, scan mobile-jd folder for OCR ingest
- `/m/jobs` — job list with queue controls
- `/m/docs` — tailoring output packages

## Important Backend Behavior

- DB explorer filtering is server-side and column-aware (`/api/db/table/{name}`).
- SQL query endpoint (`/api/db/query`) is SELECT-only.
- Admin page (`/ops/admin`) is a SQL console + bulk ops — fires destructive actions directly, no confirmation phrase.
- Production DB: `jobs` table is the source of truth; `results` is a VIEW (`SELECT *, status AS decision FROM jobs`).
- LLM provider registry in `providers.py`: ollama, gemini, groq, mistral, openrouter, together, custom. Legacy `"lmstudio"`/`"openai"`/`"mlx"` auto-migrate to `"ollama"` on load.
- Applied applications snapshot artifacts into `applied_snapshots` table — survives package deletion.
- LLM model selection is explicit — TexTailor never auto-picks the first model from a shared endpoint. Tailoring will fail with a clear error if no model is configured.

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
- `POST /api/tailoring/ingest/fetch-url`, `POST /api/tailoring/ingest/parse`, `POST /api/tailoring/ingest/commit`, `POST /api/tailoring/ingest/scan-mobile`
- `GET /api/tailoring/qa`, `POST /api/tailoring/qa/approve`, `POST /api/tailoring/qa/reject`, `POST /api/tailoring/qa/permanently-reject`
- `GET /api/tailoring/qa/llm-review`, `POST /api/tailoring/qa/llm-review`, `DELETE /api/tailoring/qa/llm-review`
- `POST /api/tailoring/qa/reset-approved`, `POST /api/tailoring/qa/undo-approve`, `POST /api/tailoring/qa/undo-reject`, `POST /api/tailoring/qa/rollback`
- `GET /api/state-log`

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

Scrapy + Typer CLI: discovery via spiders, processing via item pipelines.

- `job_scraper/config.py` — config models + YAML loader (Pydantic)
- `job_scraper/db.py` — SQLite persistence (seen_urls, jobs, rejected, runs)
- `job_scraper/fetcher.py` — page/JD retrieval
- `job_scraper/items.py` — Scrapy item definitions
- `job_scraper/salary_policy.py` — salary validation logic
- `job_scraper/settings.py` — Scrapy settings
- `job_scraper/spiders/` — active spiders: `searxng`, `ashby`, `greenhouse`, `lever`, `workable`, `generic`, `aggregator`
- `job_scraper/pipelines/` — processing stages: `text_extraction` → `dedup` → `hard_filter` → `llm_relevance` → `storage` (plus `tier_stats` helper)

## Tailoring Package Layout (high-level)

- `tailor/analyzer.py` — JD requirement extraction (with hash-based caching)
- `tailor/writer.py` — strategy/draft/QA prompt pipeline (largest module, ~2.2K LOC)
- `tailor/validator.py` — hard gates (section order, bullet counts, grounding claims, PDF fit)
- `tailor/semantic_validator.py` — semantic validation of analysis against skill inventory
- `tailor/compiler.py` — pdflatex wrapper
- `tailor/tracing.py` — per-call trace logging
- `tailor/ollama.py` — multi-provider LLM client with file-lock mutex; requires explicit model via `TAILOR_LLM_MODEL` (no auto-discovery). Supports thinking models (Qwen3 4x token multiplier).
- `tailor/grounding.py` — structured grounding contract (baseline resume > persona > skills inventory)
- `tailor/persona.py` — persona memory hierarchy (load, score, inject per stage). Reads from `persona/` dir, falls back to `soul.md`.
- `tailor/selector.py` — job selection from DB for CLI
- `tailor/metrics.py` — run metrics computation
- `tailor/config.py` — paths, model config, constants

## Dashboard Backend Services

- `services/tailoring.py` — main business logic (3.4K LOC): job processing, QA, LLM review, packages, applied tracking
- `services/ops.py` — DB admin, runtime controls, metrics
- `services/package_chat.py` — LLM-powered package refinement chat (history in `{slug}/.chat_history.json`)
- `services/model_catalog.py` — Ollama model discovery, catalog, and benchmarking
- `services/archive.py` — tailoring run archival
- `services/scraper_config.py` — scraper YAML config persistence
- `services/mobile_jd.py` — mobile JD scanning/OCR via Tesseract
- `services/jd_fetch.py` — domain-specific JD fetchers (LinkedIn, Ashby, generic)
- `services/llm_keys.py` — secure API key storage (`~/.local/share/textailor/llm_keys.json`)
- `services/audit.py` — state change audit trail (`state_log` table)
- `services/scraping.py` — shim loader for `job-scraper/api/scraping_handlers.py`
- `services/scrape_scheduler.py` — background scraper scheduling
- `services/run_reviewer.py` — post-run review helpers

## Frontend Stack

React 19 + TypeScript 5.9 + Vite 8 + React Router v7. Pipeline editor uses @xyflow/react. Icons via lucide-react. All routes lazy-loaded with code splitting. No state management library (local component state only). API client in `src/api.ts` (90+ methods). Shared layout primitives in `src/components/workflow/`.

## Environment

- Host: macOS machine (LAN-accessed dashboard)
- Ports:
  - SearXNG `8888`
  - Dashboard `8899` (`DASHBOARD_PORT`)
  - LLM endpoint `11434` (Ollama)
  - Frontend dev `5173`
- `DASHBOARD_RELOAD=1` — enable uvicorn hot-reload (disabled by default for stable LAN serving)
- `TAILOR_LLM_MODEL` — explicit model ID for tailoring (required, no auto-pick). Fallback: `TAILOR_OLLAMA_MODEL`.
- `TAILOR_LLM_URL` — chat endpoint (default: `http://localhost:11434/v1/chat/completions`). Fallback: `TAILOR_OLLAMA_URL`.
- `TAILOR_LLM_PROVIDER` — provider type: `ollama` (default), or cloud provider name.
- `TAILOR_LLM_API_KEY` — auth token for cloud providers.
