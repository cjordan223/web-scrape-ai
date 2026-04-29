# SearXNG Workspace

This repo combines three systems that work together:

- **SearXNG** (`/`) — local metasearch instance
- **Job Scraper** (`job-scraper/`) — discovery + filtering + SQLite persistence
- **Tailoring Engine** (`tailoring/`) — JD-to-application package generation
- **Dashboard** (`dashboard/`) — shared control plane for scraping, tailoring, and ops

## Repo Layout

```text
/Users/conner/Documents/TexTailor
├── docker-compose.yml
├── settings.yml
├── dashboard/
│   ├── backend/                 # FastAPI API + static hosting
│   └── web/                     # React SPA (Vite, build output in dist/)
├── job-scraper/
│   ├── job_scraper/             # Scraper package
│   ├── api/                     # Scraping-domain handlers used by dashboard backend
│   └── docs/
├── tailoring/
│   ├── tailor/                  # Tailoring CLI package
│   ├── Baseline-Dox/            # Baseline LaTeX templates
│   ├── output/                  # Generated job packages
│   └── QUALITY_BAR.md
└── venv/
```

## Quick Start

### 1) Start SearXNG

```bash
cd /Users/conner/Documents/TexTailor
docker compose up -d
curl "http://localhost:8888/search?q=test&format=json"
```

### 2) Run scraper once

```bash
source venv/bin/activate
pip install -e ./job-scraper/
cd job-scraper
python -m job_scraper scrape -v
python -m job_scraper stats
```

### 3) Start dashboard

```bash
cd /Users/conner/Documents/TexTailor
source venv/bin/activate
python dashboard/backend/server.py
```

Open: `http://localhost:8899`

## Service Ports

| Service | Port | Notes |
|---|---:|---|
| SearXNG | 8888 | Docker container, JSON API enabled |
| Dashboard | 8899 | FastAPI + React static build |
| LLM server | 11434 | Ollama endpoint for tailoring + LLM review |

## Documentation Index

- Scraper: [`job-scraper/README.md`](job-scraper/README.md)
- Scraper process: [`job-scraper/docs/SCRAPING_PROCESS.md`](job-scraper/docs/SCRAPING_PROCESS.md)
- Scraper consultant brief: [`job-scraper/docs/CONSULTANT_BRIEF.md`](job-scraper/docs/CONSULTANT_BRIEF.md)
- Scraper deployment: [`job-scraper/docs/DEPLOYMENT.md`](job-scraper/docs/DEPLOYMENT.md)
- SearXNG engines: [`job-scraper/docs/ENGINES.md`](job-scraper/docs/ENGINES.md)
- Dashboard overview: [`dashboard/README.md`](dashboard/README.md)
- Dashboard frontend: [`dashboard/web/README.md`](dashboard/web/README.md)
- UI structure notes: [`dashboard/UI_STRUCTURE.md`](dashboard/UI_STRUCTURE.md)
- Tailoring engine: [`tailoring/README.md`](tailoring/README.md)
- Tailoring quality gates: [`tailoring/QUALITY_BAR.md`](tailoring/QUALITY_BAR.md)
