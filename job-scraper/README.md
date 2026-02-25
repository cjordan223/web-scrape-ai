# Job Scraper

Python-based job scraper that discovers security job postings via SearXNG, filters them through a multi-stage pipeline, and persists results in SQLite. Includes a full-featured web dashboard. Runs unattended on a launchd schedule.

The current default profile is high-precision:
- remote-only policy
- no internship/new-grad roles
- strict URL canonicalization for dedup
- JD quality guardrails for known shell pages

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     Mac Mini (192.168.1.19)                       │
│                                                                  │
│  ┌────────────┐        ┌─────────────────────────────────────┐   │
│  │ Docker     │  :8888 │ job_scraper (Python package)        │   │
│  │ ┌────────┐ │  JSON  │                                     │   │
│  │ │SearXNG │◄├────────├─ searcher.py   query SearXNG        │   │
│  │ │ (:8080)│ │  API   │      │                              │   │
│  │ └────────┘ │        │      ▼                              │   │
│  └────────────┘        │  fetcher.py    fetch JD HTML→text   │   │
│                        │      │                              │   │
│  ┌────────────┐        │      ▼                              │   │
│  │ launchd    │  cron  │  filters.py    policy pipeline       │   │
│  │ (30 min)   ├────────►      │                              │   │
│  └────────────┘        │      ▼                              │   │
│                        │  dedup.py      SQLite persistence   │   │
│                        │  ~/.local/share/job_scraper/jobs.db │   │
│                        └─────────────────────────────────────┘   │
│                                                                  │
│  ┌────────────────────────────────────────┐                      │
│  │ Dashboard (:8899)                      │                      │
│  │  FastAPI + Alpine.js SPA               │                      │
│  │  7 views: Overview, Jobs, Runs,        │                      │
│  │  Dedup & Growth, Schedules,            │                      │
│  │  DB Explorer, SQL Console              │                      │
│  └────────────────────────────────────────┘                      │
└──────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# From the repo root (SearXNG/)
source venv/bin/activate
pip install -e ./job-scraper/

# Run a scrape
cd job-scraper
python -m job_scraper scrape -v

# Check what's accumulated
python -m job_scraper stats
python -m job_scraper recent -n 20

# Start the dashboard
python dashboard/server.py
# Open http://192.168.1.19:8899
```

SearXNG must be running (`docker compose up -d` from the repo root).

## What It Does

1. Runs configured SearXNG queries (currently 39 default query templates)
2. Crawls configured board targets via Crawl4AI (Ashby + aggregators)
3. Canonicalizes URLs (e.g. strips tracking params for LinkedIn/Lever/Greenhouse)
4. Deduplicates against canonical URLs in SQLite
5. Fetches each unseen URL's page text (best effort)
6. Applies policy + quality + relevance filters
7. Persists passing jobs and rejected-job audit trails

## Filter Pipeline

Every job is evaluated in order. Hard blocks fail fast; title/role checks are soft signals that feed scoring.

| Stage | What it checks | Example rejection |
|-------|---------------|-------------------|
| 1. URL domain | Blocks non-job sites | `dictionary.com`, `wikipedia.org` |
| 2. Title relevance | Soft signal for scoring | Missing security keyword → score penalty |
| 3. Title role | Soft signal for scoring | Missing role word → score penalty + cannot auto-accept |
| 4. Seniority | Soft mismatch signal | "Senior Security Engineer" → score penalty |
| 5. Early-career exclusion | Rejects intern/new-grad/apprenticeship | "Security Engineer Intern" → rejected |
| 6. JD quality | Soft signal for scoring | Shell/noisy JD text lowers confidence |
| 7. Experience | Soft mismatch signal from JD | "8+ years required" → score impact (not hard reject) |
| 8. Content blocklist | Scans title + snippet + JD | "TS/SCI clearance required" → rejected |
| 9. Remote policy | Rejects onsite/hybrid and non-remote | "On-site, Seattle" → rejected |
| 10. Salary floor | If salary found, records threshold fit | "$85K" with `min_salary_k` contributes to review decisions |
| 11. Scoring decision | `accept` / `review` / `reject` | Borderline items go to quarantine review queue |

Each stage produces a `FilterVerdict` with a reason — every job has an audit trail.

## URL Canonicalization + Dedup

Dedup now runs on canonical URLs:
- LinkedIn/Lever/Greenhouse/SimplyHired/Ashby query params are stripped
- common tracking params (`utm_*`, `refid`, `trackingid`, etc.) are removed elsewhere
- this prevents repeats caused only by tracking params changing per run

## CLI Commands

```bash
# Full scrape cycle (queries → dedup → fetch JD → filter → persist)
python -m job_scraper scrape

# Options
python -m job_scraper scrape -v              # verbose/debug logging
python -m job_scraper scrape --dry-run       # don't persist results or mark seen
python -m job_scraper scrape --no-fetch      # skip JD fetching (title filters only)
python -m job_scraper scrape -o results.json # also write JSON to file
python -m job_scraper scrape -c my.yaml      # override config

# Show accumulated stats
python -m job_scraper stats

# Show recent results
python -m job_scraper recent
python -m job_scraper recent -n 50
```

## Python API

```python
from job_scraper import scrape_jobs

run = scrape_jobs()                     # uses default config
run = scrape_jobs(mark_seen=False)      # dry run
run = scrape_jobs(fetch_jd=False)       # skip JD fetching

print(run.filtered_count)               # jobs that passed filters
for job in run.jobs:
    print(job.title, job.url, job.seniority)
```

## Database

Location: `~/.local/share/job_scraper/jobs.db` (override with `JOB_SCRAPER_DB` env var)

Three tables:

**`seen_urls`** — every canonical URL ever encountered (for dedup)
```
url TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT
```

**`results`** — jobs that passed all filters (accumulated across runs)
```
id, url, title, board, seniority, experience_years,
snippet, query, jd_text, filter_verdicts, run_id, created_at
```

**`runs`** — metadata for each scrape run
```
run_id, started_at, completed_at, elapsed,
raw_count, dedup_count, filtered_count, error_count, errors, status
```

## Scheduling

Runs via launchd every 30 minutes. The plist is at `~/Library/LaunchAgents/com.jobscraper.scrape.plist`:

```bash
launchctl list | grep jobscraper          # check status
tail -f ~/.local/share/job_scraper/scrape.log  # watch output
```

## Configuration

Default config is in `job_scraper/config.default.yaml`. Override with `--config`:

```yaml
search:
  searx_url: "http://localhost:8888/search"
  timeout: 15
  max_results_per_query: 20
  engines: "google,bing,duckduckgo"
  time_range: "month"       # how far back to search
  request_delay: 1.0        # seconds between queries

filter:
  title_keywords: [security, cyber, appsec, devsecops, ...]
  title_role_words: [engineer, analyst, architect, ...]
  seniority_exclude: [senior, staff, principal]
  max_experience_years: 7
  content_blocklist: [clearance, ts/sci, polygraph, ...]
  url_domain_blocklist: [dictionary.com, wikipedia.org, ...]
  require_remote: true
  min_salary_k: 95
  score_accept_threshold: 1
  score_reject_threshold: -3
  fetch_jd: true
  jd_max_chars: 15000

queries:
  - board: greenhouse
    board_site: "boards.greenhouse.io"
    title_phrase: "security engineer"
  # ... 39 query templates across direct-board and open-web searches
```

## Dashboard

FastAPI backend + single-file Alpine.js SPA at `http://192.168.1.19:8899`.

### Views

| View | What it shows |
|------|---------------|
| **Overview** | 6 metric cards, run health strip (last 20 runs color-coded), cumulative growth chart, daily discovery bar chart, board & seniority doughnuts |
| **Jobs** | Filterable/sortable table with board, seniority, title/URL search, run_id filter, date range. Expandable rows for filter verdicts + JD text. "NEW" badge on latest-run jobs |
| **Runs** | Stats cards (avg duration, success rate, avg jobs/run), duration timeline chart. Click any run to expand: see all jobs found + errors |
| **Dedup & Growth** | Dedup funnel visualization, URL frequency distribution, daily uniqueness rate, daily new jobs chart, filter verdict breakdown by stage |
| **Schedules** | All launchd agents from `~/Library/LaunchAgents/` with live status via `launchctl`. Expand for config details + built-in log viewer with configurable tail length |
| **DB Explorer** | Browse any SQLite table with column sorting, per-column filters, row detail modal, and "Copy as JSON" export |
| **SQL Console** | Raw SELECT queries with Cmd+Enter, 6 preset query shortcuts, query history saved to localStorage, auto-rendered results table |

### Running the Dashboard

```bash
source venv/bin/activate
python job-scraper/dashboard/server.py
# Listens on 0.0.0.0:8899 (configurable via DASHBOARD_PORT env var)
```

## File Structure

```
job-scraper/
├── pyproject.toml              # pip-installable package
├── TUNING_NOTES.txt            # Filter tuning guide
├── job_scraper/
│   ├── __init__.py             # Public API: scrape_jobs()
│   ├── __main__.py             # CLI: python -m job_scraper
│   ├── config.py               # Pydantic config models + YAML loader
│   ├── config.default.yaml     # query templates, filter rules, search settings
│   ├── models.py               # Seniority, JobBoard, JobResult, ScrapeRun
│   ├── searcher.py             # SearXNG query builder + executor
│   ├── fetcher.py              # HTML → plain text extraction
│   ├── dedup.py                # SQLite job store (dedup + results + runs)
│   ├── filters.py              # policy + relevance filter pipeline
│   ├── llm_reviewer.py         # LLM-based review stage
│   └── urlnorm.py              # URL canonicalization for stable dedup
├── dashboard/
│   ├── server.py               # FastAPI backend (17 endpoints, ~750 lines)
│   └── index.html              # Alpine.js + Chart.js SPA (7 views, ~1550 lines)
└── docs/
    └── DEPLOYMENT.md           # Full setup guide
```
