# Dashboard

Shared control-plane app for:

- scraping workflow (`job-scraper/`)
- tailoring workflow (`tailoring/`)
- operations tooling (DB explorer, SQL console, schedules)

## Components

- `backend/` — FastAPI backend (API + static file hosting)
  - `routers/` — domain route registration (`scraping`, `tailoring`, `ops`)
  - `services/` — route handlers by domain
- `web/` — React + TypeScript frontend

## Run

```bash
cd /Users/conner/Documents/SearXNG
source venv/bin/activate
python dashboard/backend/server.py
```

Open `http://localhost:8899`.

## Frontend Development

```bash
cd /Users/conner/Documents/SearXNG/dashboard/web
npm install
npm run dev
```

## Optional: DB Admin Actions (Destructive)

DB admin actions in **Ops -> SQL Console** are disabled by default.

Enable explicitly:

```bash
export DASHBOARD_ENABLE_DB_ADMIN=1
```

Available admin actions:

- delete all rows from all user tables
- delete rows from selected tables
- drop selected tables

Safety controls:

- server-side feature flag required
- confirmation phrase required for each action
- unknown table names are rejected server-side
