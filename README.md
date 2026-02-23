# SearXNG + Job Scraper

A self-hosted [SearXNG](https://github.com/searxng/searxng) metasearch engine, a Python-based job scraper that discovers security job postings, and a full-featured web dashboard for monitoring everything. Runs unattended on a launchd schedule.

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
│  │ launchd    │  cron  │  filters.py    7-stage pipeline     │   │
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
│                                                                  │
│  ┌────────────────────────────────────────┐                      │
│  │ Downstream (separate repos)            │                      │
│  │  job-pipeline-v2 reads jobs.db         │                      │
│  │  → LLM analysis → resume tailoring    │                      │
│  └────────────────────────────────────────┘                      │
└──────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Start SearXNG
cd ~/Documents/SearXNG
docker compose up -d

# 2. Activate venv and install the scraper
source venv/bin/activate
pip install -e .

# 3. Run a scrape
python -m job_scraper scrape -v

# 4. Check what's accumulated
python -m job_scraper stats
python -m job_scraper recent -n 20

# 5. Start the dashboard
python dashboard/server.py
# Open http://192.168.1.19:8899
```

## Job Scraper

### What It Does

1. Sends 15 search queries to SearXNG across 7 job boards + open web
2. Deduplicates against all previously seen URLs (SQLite)
3. Fetches each new job's full description (HTML → plain text)
4. Runs a 7-stage filter pipeline on every result
5. Stores passing jobs in SQLite — accumulates across runs

### Filter Pipeline

Every job is evaluated in order. Fails fast on the first rejection.

| Stage | What it checks | Example rejection |
|-------|---------------|-------------------|
| 1. URL domain | Blocks non-job sites | `dictionary.com`, `wikipedia.org` |
| 2. Title relevance | Must contain a security keyword | "Marketing Manager" → rejected |
| 3. Title role | Must contain a job-role word | "SECURITY Definition" → rejected |
| 4. Seniority | Rejects excluded levels | "Senior Security Engineer" → rejected |
| 5. Experience | Parses years from JD text | "8+ years required" → rejected (max 4) |
| 6. Content blocklist | Scans title + snippet + JD | "TS/SCI clearance required" → rejected |
| 7. Remote | Optional: require remote keywords | Only runs if `require_remote: true` |

Each stage produces a `FilterVerdict` with a reason — every job has an audit trail.

### CLI Commands

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

### Python API

```python
from job_scraper import scrape_jobs

run = scrape_jobs()                     # uses default config
run = scrape_jobs(mark_seen=False)      # dry run
run = scrape_jobs(fetch_jd=False)       # skip JD fetching

print(run.filtered_count)               # jobs that passed filters
for job in run.jobs:
    print(job.title, job.url, job.seniority)
```

### Database

Location: `~/.local/share/job_scraper/jobs.db` (override with `JOB_SCRAPER_DB` env var)

Three tables:

**`seen_urls`** — every URL ever encountered (for dedup)
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

Query it directly:
```bash
sqlite3 ~/.local/share/job_scraper/jobs.db "SELECT title, board, seniority, created_at FROM results ORDER BY created_at DESC LIMIT 10"
```

### Scheduling

Runs via launchd every 30 minutes. The plist is at `~/Library/LaunchAgents/com.jobscraper.scrape.plist`:

```bash
launchctl list | grep jobscraper          # check status
tail -f ~/.local/share/job_scraper/scrape.log  # watch output
```

At ~15 queries per run with 1s delay, each run takes ~30 seconds. Results accumulate in the SQLite DB. Downstream tools (job-pipeline-v2, LLM analysis) read from the DB independently.

### Configuration

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
  seniority_exclude: [senior, staff, principal, lead, manager, director]
  max_experience_years: 4
  content_blocklist: [clearance, ts/sci, polygraph, ...]
  url_domain_blocklist: [dictionary.com, wikipedia.org, ...]
  require_remote: false
  fetch_jd: true
  jd_max_chars: 15000

queries:
  - board: greenhouse
    board_site: "boards.greenhouse.io"
    title_phrase: "security engineer"
  # ... 15 queries across 7 boards + open web
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

### API Endpoints

17 endpoints, all read-only:

```
GET /api/overview              — stats, trend, boards, seniority, run health, DB size
GET /api/jobs                  — paginated, filterable (board, seniority, search, url, run_id, dates)
GET /api/jobs/{id}             — single job with filter verdicts + JD text
GET /api/runs                  — paginated with per-run job counts + aggregate stats
GET /api/runs/active           — is a scrape currently running?
GET /api/runs/{run_id}         — single run detail with all its jobs
GET /api/filters/stats         — verdict breakdown by filter stage
GET /api/dedup/stats           — dedup funnel, daily new rate, uniqueness per run
GET /api/growth                — cumulative time-series for results + seen_urls
GET /api/db/tables             — all tables with row counts + column info
GET /api/db/table/{name}       — generic paginated table browser
GET /api/db/query?sql=...      — read-only SQL (SELECT only, LIMIT 1000, 5s timeout)
GET /api/db/size               — DB file size on disk
GET /api/schedules             — all launchd agents with config + runtime status
GET /api/schedules/{label}/log — tail a scheduled job's log file
```

### Running the Dashboard

```bash
source venv/bin/activate
python dashboard/server.py
# Listens on 0.0.0.0:8899 (configurable via DASHBOARD_PORT env var)
```

## File Structure

```
SearXNG/
├── docker-compose.yml          # SearXNG container
├── settings.yml                # SearXNG engine config
├── pyproject.toml              # pip-installable package
├── job_scraper/
│   ├── __init__.py             # Public API: scrape_jobs()
│   ├── __main__.py             # CLI: python -m job_scraper
│   ├── config.py               # Pydantic config models + YAML loader
│   ├── config.default.yaml     # 15 queries, filter rules, search settings
│   ├── models.py               # Seniority, JobBoard, JobResult, ScrapeRun
│   ├── searcher.py             # SearXNG query builder + executor
│   ├── fetcher.py              # HTML → plain text extraction
│   ├── dedup.py                # SQLite job store (dedup + results + runs)
│   └── filters.py              # 7-stage filter pipeline
├── dashboard/
│   ├── server.py               # FastAPI backend (17 endpoints, ~750 lines)
│   └── index.html              # Alpine.js + Chart.js SPA (7 views, ~1550 lines)
├── docs/
│   ├── DEPLOYMENT.md           # Full setup guide
│   └── ENGINES.md              # SearXNG engine reference
├── venv/                       # Python 3.14 virtualenv
├── CLAUDE.md                   # AI assistant context
└── README.md
```

## SearXNG Instance

### Docker

```bash
docker compose up -d            # start
docker compose down             # stop
docker compose logs -f searxng  # logs
docker compose pull && docker compose up -d  # update
```

- **Port:** `8888` (host) → `8080` (container)
- **Settings:** `./settings.yml` mounted into container
- **Limiter:** disabled (private instance)
- **JSON API:** enabled (`search.formats: [html, json]`)

### MCP Server

The venv also includes the `searXNG` MCP package for AI agent integration:

```bash
source venv/bin/activate
python -m searXNG --instance-url http://localhost:8888
```

Exposes a `web_search` tool over MCP stdio protocol.

### Network

- **Host:** `192.168.1.19`
- **SearXNG:** port `8888`
- **Dashboard:** port `8899`
- **LLM server:** port `8800` (separate, used by job-pipeline-v2)
