# Dashboard Web (React)

React + TypeScript frontend for the shared dashboard. Built with Vite and served by the FastAPI backend.

## Stack

- React 19
- TypeScript
- Vite
- react-router-dom v7
- axios
- chart.js + react-chartjs-2
- lucide-react

## Run

```bash
cd /Users/conner/Documents/SearXNG/dashboard/web
npm install
npm run dev
```

Dev server runs on `:5173` and calls backend API on `:8899`.

## Build

```bash
npm run build
```

Build output goes to `dist/` and is served by backend static catch-all.

## UI Architecture

The frontend uses hierarchical information architecture:

- Domain -> Workflow Group -> Page
- Shared app shell with breadcrumbs and domain/workflow navigation
- Shared page primitives (`PageHeader`, `PagePrimary`, `PageSecondary`)
- Shared workflow widgets (`WorkflowPanel`, `LoadingState`, `EmptyState`, etc.)

## Routes

- `/home/overview`
- `/scraping/intake/jobs`
- `/scraping/intake/rejected`
- `/scraping/runs`
- `/scraping/quality/dedup`
- `/scraping/quality/schedules`
- `/tailoring/runs`
- `/tailoring/outputs/packages`
- `/ops/data/explorer`
- `/ops/diagnostics/sql`

Legacy routes are redirected.

## Source Structure

```text
src/
├── App.tsx                            # Router map, lazy routes, redirects
├── api.ts                             # API client
├── utils.ts                           # Shared format helpers
├── components/
│   ├── layout/
│   │   └── AppShell.tsx               # Domain/workflow navigation + breadcrumbs
│   ├── workflow/
│   │   ├── PageLayout.tsx
│   │   ├── Panel.tsx
│   │   ├── States.tsx
│   │   ├── ActionBar.tsx
│   │   ├── FilterToolbar.tsx
│   │   ├── LogPanel.tsx
│   │   └── RunTimelineChart.tsx
│   └── VerdictChips.tsx
├── views/domains/
│   ├── home/
│   ├── scraping/
│   ├── tailoring/
│   └── ops/
└── styles/
    └── global.css
```

## API Groups Used by Web

- Overview: `/api/overview`
- Scraping: `/api/jobs`, `/api/rejected`, `/api/runs`, `/api/filters/stats`, `/api/dedup/stats`, `/api/growth`
- Ops: `/api/db/tables`, `/api/db/table/{name}`, `/api/db/query`, `/api/schedules`
- Optional DB admin: `/api/db/admin/status`, `/api/db/admin/action`
- Tailoring: `/api/tailoring/*`, `/api/packages/*`
- Runtime controls: `/api/runtime-controls`
- LLM status: `/api/llm/status`

## DB Admin Safety

DB admin actions (truncate/drop tables) are hidden/disabled unless backend sets:

```bash
export DASHBOARD_ENABLE_DB_ADMIN=1
```

Even when enabled, actions require explicit confirmation phrase entry in UI.
