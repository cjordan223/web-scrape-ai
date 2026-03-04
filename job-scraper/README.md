# Job Scraper

Python scraper that discovers security jobs via SearXNG and crawler targets, evaluates each posting through a policy pipeline, and stores accepted/rejected outcomes in SQLite.

## What It Does

1. Runs configured search templates
2. Crawls configured board/aggregator targets
3. Canonicalizes URLs for stable dedup
4. Deduplicates against historical URLs
5. Fetches page text (best effort)
6. Applies filtering/scoring pipeline
7. Persists accepted jobs, rejected jobs, and run metadata

## Quick Start

```bash
cd /Users/conner/Documents/SearXNG
source venv/bin/activate
pip install -e ./job-scraper/

cd job-scraper
python -m job_scraper scrape -v
python -m job_scraper stats
python -m job_scraper recent -n 20
```

SearXNG must be running on `:8888`.

## CLI

```bash
python -m job_scraper scrape
python -m job_scraper scrape -v
python -m job_scraper scrape --dry-run
python -m job_scraper scrape --no-fetch
python -m job_scraper scrape -c my_config.yaml
python -m job_scraper stats
python -m job_scraper recent -n 50
```

## Filter Pipeline

The pipeline records stage-by-stage verdicts for auditability.

- URL domain quality checks
- source quality checks
- title relevance and role signals
- seniority + early-career exclusions
- JD quality/presence signals
- experience and salary checks
- content blocklist checks
- remote/location policy checks
- final scoring + optional LLM review

See tuning notes: [`TUNING_NOTES.txt`](TUNING_NOTES.txt)

## Database

Default path:

- `~/.local/share/job_scraper/jobs.db`

Override with `JOB_SCRAPER_DB`.

Core tables:

- `seen_urls` — canonical URL dedup history
- `results` — accepted jobs
- `rejected` — rejected jobs with stage/reason
- `runs` — run metadata and status

## Config

Default config:

- `job_scraper/config.default.yaml`

Override with `--config`.

Important knobs:

- remote requirement
- location policy
- salary floor
- seniority exclusions
- scoring thresholds
- LLM review behavior
- crawl/search target lists

## Dashboard Integration

The shared dashboard lives at repo root in `dashboard/` and reads scraper data.

- Backend: `dashboard/backend/`
- Frontend: `dashboard/web/`

Run dashboard:

```bash
cd /Users/conner/Documents/SearXNG
source venv/bin/activate
python dashboard/backend/server.py
```

## Package Layout

```text
job-scraper/
├── pyproject.toml
├── TUNING_NOTES.txt
├── api/                           # scraping-domain handlers for dashboard
├── docs/
│   ├── DEPLOYMENT.md
│   └── ENGINES.md
└── job_scraper/
    ├── __main__.py
    ├── config.default.yaml
    ├── config.py
    ├── models.py
    ├── searcher.py
    ├── crawler.py
    ├── fetcher.py
    ├── dedup.py
    ├── filters.py
    ├── llm_reviewer.py
    └── urlnorm.py
```
