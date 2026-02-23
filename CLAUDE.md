# CLAUDE.md — Project Context

## What This Repo Is

Two things in one directory:

1. **SearXNG instance** — a Dockerized metasearch engine on `localhost:8888`
2. **`job_scraper` package** — Python package that uses SearXNG to discover, filter, and persist security job postings
3. **Dashboard** — FastAPI + Alpine.js SPA providing full visibility into scraper data, DB contents, scheduled jobs, and raw SQL access

The scraper is the primary consumer of SearXNG. It runs every 30 min via launchd, accumulates results in SQLite at `~/.local/share/job_scraper/jobs.db`.

## How to Run

```bash
source venv/bin/activate
python -m job_scraper scrape -v      # full cycle (SearXNG + Crawl4AI)
python -m job_scraper scrape -v --no-crawl  # SearXNG only
python -m job_scraper stats          # check DB totals
python -m job_scraper recent -n 20   # recent results
python dashboard/server.py           # start dashboard on :8899
```

SearXNG must be running (`docker compose up -d`) on port 8888. Crawl4AI requires Playwright browsers (`playwright install chromium`).

## Package Layout

- `job_scraper/__init__.py` — `scrape_jobs()` is the public API. Orchestrates: query → crawl → merge → dedup → fetch → filter → persist.
- `job_scraper/searcher.py` — builds queries from templates, hits SearXNG JSON API, rate-limits between queries
- `job_scraper/crawler.py` — Crawl4AI-based board crawler. Hits company job pages, extracts listing URLs via per-board regex patterns, returns `SearchResult` list merged with SearXNG results before dedup.
- `job_scraper/fetcher.py` — fetches job URLs, strips HTML to plain text via stdlib HTMLParser
- `job_scraper/filters.py` — 7-stage pipeline: url_domain → title_relevance → title_role → seniority → experience → blocklist → remote. Each stage returns a FilterVerdict.
- `job_scraper/dedup.py` — `JobStore` class wraps SQLite. Three tables: `seen_urls` (dedup), `results` (passing jobs), `runs` (run metadata with timing/counts/status).
- `job_scraper/config.py` — Pydantic models for config. `load_config()` reads `config.default.yaml` and deep-merges user overrides.
- `job_scraper/config.default.yaml` — 15 query templates, crawl targets, filter keywords/blocklists, search settings. This is the main knob to tune.
- `job_scraper/models.py` — `Seniority`, `JobBoard` enums, `SearchResult`, `FilterVerdict`, `JobResult`, `ScrapeRun`
- `job_scraper/__main__.py` — Typer CLI with `scrape`, `stats`, `recent` commands

## Dashboard

- `dashboard/server.py` — FastAPI backend (~750 lines). Reads SQLite read-only. Also reads `~/Library/LaunchAgents/*.plist` for schedule monitoring.
- `dashboard/index.html` — Single-file SPA (~1550 lines, Alpine.js + Chart.js).

**7 views:**
1. **Overview** — 6 metric cards (total jobs, URLs seen, today, dedup ratio, last run, DB size), run health strip (last 20 runs), cumulative growth chart, daily discovery bar chart, board/seniority doughnuts
2. **Jobs** — filterable/sortable table with board, seniority, title/URL search, run_id filter, date range. Expandable rows show filter verdicts + JD text. "NEW" badge for latest run.
3. **Runs** — stats cards (avg duration, success rate, avg jobs/run), duration timeline chart, expandable rows showing per-run jobs + error panel. Paginated.
4. **Dedup & Growth** — dedup funnel, URL frequency distribution, daily uniqueness rate, daily new jobs chart, filter verdict breakdown
5. **Schedules** — all launchd agents from `~/Library/LaunchAgents/` with live status from `launchctl`, config details, built-in log viewer
6. **DB Explorer** — generic table browser for any SQLite table, column sorting, per-column filters, row detail modal, copy as JSON
7. **SQL Console** — raw SELECT queries with preset shortcuts, query history (localStorage), auto-rendered results table

**API endpoints** (17 total):
- Overview: `/api/overview`
- Jobs: `/api/jobs`, `/api/jobs/{id}`
- Runs: `/api/runs`, `/api/runs/active`, `/api/runs/{run_id}`
- Filters: `/api/filters/stats`
- Dedup: `/api/dedup/stats`, `/api/growth`
- DB: `/api/db/tables`, `/api/db/table/{name}`, `/api/db/query`, `/api/db/size`
- Schedules: `/api/schedules`, `/api/schedules/{label}/log`

## Key Design Decisions

- **Two discovery sources** — SearXNG (search-based) + Crawl4AI (crawl-based). Results merge before dedup; everything downstream is source-agnostic.
- **Crawl4AI limited to server-rendered boards** — Greenhouse and Lever are JS SPAs that don't yield links. Ashby boards render server-side and work reliably.
- **No LLM calls** — scraper discovers and filters only. LLM analysis is in job-pipeline-v2.
- **All passing jobs returned** — not first-match. Downstream decides which to process.
- **SQLite for everything** — dedup + results + run history in one DB file. No external services.
- **No external orchestrators** — launchd for scheduling, not Docker-based schedulers. Simpler, zero friction.
- **Word-boundary regex** — title keyword matching uses `\b` to prevent substring false positives (e.g. "soc" inside "Associate").
- **Blocklist checks title+snippet+JD** — catches clearance requirements even without JD fetch.
- **Filter verdicts** — every job gets an audit trail of why it passed/failed each stage.
- **Dashboard reads DB read-only** — no write operations, no conflicts with scraper.
- **SQL Console is SELECT-only** — dangerous keywords blocked, LIMIT 1000 enforced, read-only pragma.

## Downstream

`job-pipeline-v2` (separate repo at `~/Documents/AI-pipelines/job-pipeline-v2/`) will import from this package or query `jobs.db` directly for LLM analysis and resume tailoring.

## Environment

- Mac Mini at 192.168.1.19
- Python 3.14 in `./venv/`
- SearXNG in Docker on port 8888
- Dashboard on port 8899
- Scheduling via launchd (com.jobscraper.scrape, every 30 min)
- Logs at `~/.local/share/job_scraper/scrape.log`
- 1TB storage attached (DB can grow freely)
