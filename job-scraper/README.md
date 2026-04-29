# Job Scraper

Python scraper that discovers security jobs via SearXNG and crawler targets, evaluates each posting through a policy pipeline, and stores accepted/rejected outcomes in SQLite.

## What It Does

1. Runs configured direct ATS spiders for known companies
2. Runs SearXNG discovery queries for broader coverage
3. Normalizes job items from each source
4. Extracts usable JD text
5. Deduplicates against historical URLs
6. Applies hard filters and discovery-tier LLM relevance checks
7. Persists pending, QA, rejected, and lead outcomes with run metadata

For the full end-to-end operational flow, see
[`docs/SCRAPING_PROCESS.md`](docs/SCRAPING_PROCESS.md).

For an outside-review handoff, see
[`docs/CONSULTANT_BRIEF.md`](docs/CONSULTANT_BRIEF.md).

## Quick Start

```bash
cd /Users/conner/Documents/TexTailor
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
python -m job_scraper scrape --spider ashby
python -m job_scraper scrape --tiers workhorse,discovery
python -m job_scraper scrape --tiers workhorse --rotation-group 2 --run-index 30
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
- `jobs` — canonical job records for pending, QA, lead, and rejected outcomes
- `job_fingerprints` — canonical URL, ATS ID, normalized field fingerprint,
  content hash, and duplicate status metadata
- `runs` — run metadata and status
- `run_tier_stats` — source/tier counters for each run, including duplicate
  class counters

Compatibility views:

- `results` — legacy view over `jobs`
- `rejected` — rejected-job subset view over `jobs`

## Config

Default config:

- `job_scraper/config.default.yaml`

The current CLI loads this default file directly.

Important knobs:

- direct ATS board list
- SearXNG query templates
- remote requirement
- location policy
- salary floor
- seniority exclusions
- pipeline order
- scheduler cadence and rotation profile
- discovery-tier LLM gate behavior

## Dashboard Integration

The shared dashboard lives at repo root in `dashboard/` and reads scraper data.

- Backend: `dashboard/backend/`
- Frontend: `dashboard/web/`

Run dashboard:

```bash
cd /Users/conner/Documents/TexTailor
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
│   ├── CONSULTANT_BRIEF.md
│   ├── ENGINES.md
│   └── SCRAPING_PROCESS.md
└── job_scraper/
    ├── __main__.py
    ├── config.default.yaml
    ├── config.py
    ├── db.py
    ├── scrape_profile.py
    ├── settings.py
    ├── spiders/
    └── pipelines/
```
