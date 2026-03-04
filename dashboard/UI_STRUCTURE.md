# UI Structure

Dashboard UI architecture after hierarchical refactor.

## Navigation Hierarchy

```text
Home
└── Overview

Scraping
├── Intake
│   ├── Jobs
│   └── Rejected
├── Runs
│   └── Run List
└── Quality
    ├── Dedup & Growth
    └── Schedules

Tailoring
├── Runs
│   └── Manual & Traces
└── Outputs
    └── Packages

Ops
├── Data
│   └── DB Explorer
└── Diagnostics
    └── Admin Operations
```

## Route Structure

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

Legacy routes (`/jobs`, `/runs`, `/sql`, etc.) redirect to hierarchical routes.

## Frontend Component Layout

```text
dashboard/web/src
├── components/
│   ├── layout/
│   │   └── AppShell.tsx              # Domain/workflow nav + breadcrumbs
│   ├── workflow/
│   │   ├── PageLayout.tsx
│   │   ├── Panel.tsx
│   │   ├── States.tsx
│   │   ├── ActionBar.tsx
│   │   ├── FilterToolbar.tsx
│   │   ├── LogPanel.tsx
│   │   └── RunTimelineChart.tsx
│   ├── Sidebar.tsx                   # Navigation sidebar
│   └── VerdictChips.tsx              # Filter verdict chips
└── views/domains/
    ├── home/
    │   └── OverviewView.tsx
    ├── scraping/
    │   ├── intake/
    │   │   ├── JobsView.tsx
    │   │   └── RejectedView.tsx
    │   ├── runs/
    │   │   └── RunsView.tsx
    │   └── quality/
    │       ├── DedupView.tsx
    │       └── SchedulesView.tsx
    ├── tailoring/
    │   ├── runs/
    │   │   └── TailoringView.tsx
    │   └── outputs/
    │       └── PackagesView.tsx
    └── ops/
        ├── data/
        │   └── ExplorerView.tsx
        └── diagnostics/
            └── SqlConsoleView.tsx    # Admin Operations page
```

## Backend Layout

```text
dashboard/backend
├── app.py                            # Shared state, helpers, module-level config
├── server.py                         # App factory + startup
├── routers/
│   ├── scraping.py
│   ├── tailoring.py
│   └── ops.py
└── services/
    ├── scraping.py                   # Thin shim — imports from job-scraper/api/
    ├── tailoring.py
    └── ops.py
```

Scraping-domain handlers live in `job-scraper/api/scraping_handlers.py` and are imported by `dashboard/backend/services/scraping.py`.
