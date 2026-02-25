# Deployment Guide

Full setup for SearXNG + job_scraper + dashboard on a fresh macOS server.

## Prerequisites

- macOS with Docker (OrbStack or Docker Desktop)
- Python 3.12+ (3.14 used in dev)
- ~500MB disk (DB grows slowly)

## 1. SearXNG

```bash
mkdir ~/Documents/SearXNG && cd ~/Documents/SearXNG

# Create settings.yml (customize engines, safe_search, etc.)
# See https://docs.searxng.org/admin/settings.html

# docker-compose.yml only has the searxng service:
docker compose up -d
# Verify: curl http://localhost:8888/search?q=test&format=json
```

SearXNG listens on **port 8888** (maps to container's 8080).

## 2. job_scraper

```bash
cd ~/Documents/SearXNG
python -m venv venv
source venv/bin/activate
pip install -e ./job-scraper/
```

### Config

Default config is in `job-scraper/job_scraper/config.default.yaml`. Override with a user config:

```bash
cd job-scraper
python -m job_scraper scrape --config my_config.yaml
```

Default policy behavior:
- `require_remote: true` (onsite/hybrid is rejected)
- internship/new-grad/apprenticeship postings are rejected
- salary parsing ignores `401k`-style benefits text
- URL dedup canonicalizes tracking-heavy URLs (LinkedIn/Lever/Greenhouse/etc.)

### Test run

```bash
cd ~/Documents/SearXNG/job-scraper
python -m job_scraper scrape -v    # full cycle with verbose logging
python -m job_scraper stats        # DB totals
python -m job_scraper recent -n 20 # last 20 jobs
```

### Database

SQLite at `~/.local/share/job_scraper/jobs.db`. Core tables:

| Table | Purpose |
|---|---|
| `seen_urls` | Dedup — every canonicalized URL encountered |
| `results` | Accepted jobs with full JD text + filter verdicts |
| `rejected` | Hard-blocked jobs with rejection stage/reason |
| `quarantine` | Borderline `review` jobs from scoring |
| `runs` | Run metadata — timing, counts, status |

Override DB path with `JOB_SCRAPER_DB` env var.

## 3. Scheduling (launchd)

Create `~/Library/LaunchAgents/com.jobscraper.scrape.plist`:

Replace `your-username` in the example below with your macOS username.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jobscraper.scrape</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/your-username/Documents/SearXNG/venv/bin/python</string>
        <string>-m</string>
        <string>job_scraper</string>
        <string>scrape</string>
        <string>-v</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/your-username/Documents/SearXNG/job-scraper</string>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>StandardOutPath</key>
    <string>/Users/your-username/.local/share/job_scraper/scrape.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/your-username/.local/share/job_scraper/scrape.log</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.jobscraper.scrape.plist
launchctl list | grep jobscraper   # verify it's loaded
```

Manage:

```bash
launchctl unload ~/Library/LaunchAgents/com.jobscraper.scrape.plist  # stop
launchctl load   ~/Library/LaunchAgents/com.jobscraper.scrape.plist  # start
tail -f ~/.local/share/job_scraper/scrape.log                        # watch
```

The dashboard's **Schedules** view also shows live status and logs for all launchd agents.

## 4. Dashboard

```bash
cd ~/Documents/SearXNG
source venv/bin/activate
python job-scraper/dashboard/server.py
# Open http://192.168.1.19:8899
```

Dependencies (already in venv): `fastapi`, `uvicorn`.

### What the Dashboard Provides

7 views in a single-page app:

| View | Purpose |
|------|---------|
| Overview | Metric cards, run health strip, growth + daily charts, board/seniority breakdowns |
| Jobs | Filterable/sortable table with expandable rows (filter verdicts, JD text) |
| Runs | Run stats, duration timeline, click-to-expand showing per-run jobs + errors |
| Dedup & Growth | Dedup funnel, URL frequency, uniqueness rate, filter analytics |
| Schedules | Live launchd agent monitoring with log viewer |
| DB Explorer | Browse any SQLite table with sorting, filtering, row detail modal |
| SQL Console | Raw SELECT queries with presets and history |

### Run as a persistent service (launchd)

Create `~/Library/LaunchAgents/com.jobscraper.dashboard.plist`:

Replace `your-username` in the example below with your macOS username.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jobscraper.dashboard</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/your-username/Documents/SearXNG/venv/bin/python</string>
        <string>server.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/your-username/Documents/SearXNG/job-scraper/dashboard</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/your-username/.local/share/job_scraper/dashboard.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/your-username/.local/share/job_scraper/dashboard.log</string>
</dict>
</plist>
```

Dashboard listens on **port 8899** (configurable via `DASHBOARD_PORT` env var).

## Port Map

| Service | Port | Notes |
|---|---|---|
| SearXNG | 8888 | Docker, host-mapped from container :8080 |
| Dashboard | 8899 | Native Python, FastAPI + uvicorn |

## Environment Variables

| Var | Default | Purpose |
|---|---|---|
| `JOB_SCRAPER_DB` | `~/.local/share/job_scraper/jobs.db` | Override DB path |
| `DASHBOARD_PORT` | `8899` | Dashboard listen port |

## Troubleshooting

**Scrape finds 0 new results**: Normal after the first run — SearXNG returns the same ~150 results for the same queries. New jobs trickle in as boards update.

**SearXNG returns empty results**: Check that engines are enabled in `settings.yml` and that Google/Bing aren't rate-limiting. Run `curl "http://localhost:8888/search?q=test&format=json"` to test.

**launchd not running**: Check `launchctl list | grep jobscraper`. If exit code is non-zero, check `~/.local/share/job_scraper/scrape.log`. Common issue: venv path wrong in plist. The dashboard's Schedules view also shows exit codes for all agents.

**DB locked**: Only one writer at a time. If the scraper and dashboard collide, the dashboard uses read-only mode (`?mode=ro`) so it won't conflict.

**Dashboard can't find DB**: Set `JOB_SCRAPER_DB` env var to the correct path, or ensure `~/.local/share/job_scraper/jobs.db` exists.
