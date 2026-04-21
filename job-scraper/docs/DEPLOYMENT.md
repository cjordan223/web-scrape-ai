# Deployment Guide (macOS)

Setup for:

- SearXNG (`:8888`)
- job scraper (Python package)
- dashboard (`:8899`)

## Prerequisites

- macOS
- Docker (OrbStack or Docker Desktop)
- Python 3.12+
- Node.js 18+ (frontend build)

## 1) SearXNG

```bash
mkdir -p ~/Documents/TexTailor
cd ~/Documents/TexTailor

# Add docker-compose.yml + settings.yml
# Then start:
docker compose up -d
curl "http://localhost:8888/search?q=test&format=json"
```

## 2) Python Environment + Scraper

```bash
cd ~/Documents/TexTailor
python3 -m venv venv
source venv/bin/activate
pip install -e ./job-scraper/

cd job-scraper
python -m job_scraper scrape -v
python -m job_scraper stats
```

Default DB path:

- `~/.local/share/job_scraper/jobs.db`

## 3) Launchd Schedule (Scraper)

Create:

- `~/Library/LaunchAgents/com.jobscraper.scrape.plist`

Use your absolute paths for:

- venv python
- working directory
- log output path

Load:

```bash
launchctl load ~/Library/LaunchAgents/com.jobscraper.scrape.plist
launchctl list | grep jobscraper
tail -f ~/.local/share/job_scraper/scrape.log
```

## 4) Dashboard Frontend Build

```bash
cd ~/Documents/TexTailor/dashboard/web
npm install
npm run build
```

## 5) Dashboard Backend Run

```bash
cd ~/Documents/TexTailor
source venv/bin/activate
python dashboard/backend/server.py
```

Open:

- `http://localhost:8899`

## 6) Optional Launchd Service (Dashboard)

Create:

- `~/Library/LaunchAgents/com.jobscraper.dashboard.plist`

Point it to:

- `venv/bin/python`
- `dashboard/backend/server.py`
- dashboard log path

Load with `launchctl load ...`.

## Port Map

| Service | Port | Notes |
|---|---:|---|
| SearXNG | 8888 | Docker |
| Dashboard | 8899 | FastAPI serving React build |
| LLM server | 11434 | Ollama — needed for tailoring and package-chat workflows |

## Optional Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `JOB_SCRAPER_DB` | `~/.local/share/job_scraper/jobs.db` | Override DB file |
| `DASHBOARD_PORT` | `8899` | Dashboard port |
| `DASHBOARD_ENABLE_DB_ADMIN` | `0` | Enable destructive DB admin actions in SQL Console |

## Troubleshooting

- **No results**: verify SearXNG query endpoint and enabled engines.
- **launchd not running**: check plist paths and `launchctl list` exit status.
- **dashboard missing DB**: confirm `JOB_SCRAPER_DB` and file existence.
- **SQL admin actions disabled**: set `DASHBOARD_ENABLE_DB_ADMIN=1` before starting backend.
