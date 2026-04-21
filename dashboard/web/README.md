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
cd /Users/conner/Documents/TexTailor/dashboard/web
npm install
npm run dev
```

Dev server runs on `:5173` and calls backend API on `:8899`.

## Build

```bash
npm run build
```

Build output goes to `dist/` and is served by the backend static catch-all.

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
├── api.ts                             # API client (all backend calls)
├── utils.ts                           # Shared format helpers (fmt, timeAgo, etc.)
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
│   ├── Sidebar.tsx                    # Navigation sidebar
│   └── VerdictChips.tsx               # Filter verdict chip component
├── views/domains/
│   ├── home/
│   ├── scraping/
│   ├── tailoring/
│   └── ops/
└── styles/
    └── global.css
```

## API Groups Used

- Overview: `/api/overview`
- Scraping: `/api/jobs`, `/api/rejected`, `/api/runs`, `/api/filters/stats`, `/api/dedup/stats`, `/api/growth`, `/api/scrape/run`, `/api/scrape/runner/status`
- Tailoring: `/api/tailoring/*`, `/api/packages/*`
- LLM: `/api/llm/status`, `/api/llm/models`, `/api/llm/models/load`, `/api/llm/models/unload`
- Ops: `/api/db/tables`, `/api/db/table/{name}`, `/api/db/query`, `/api/schedules`, `/api/ops/status`, `/api/ops/action`
- Runtime controls: `/api/runtime-controls`
