# UI Structure Snapshot

This document describes the current dashboard UI architecture after the hierarchical refactor.

## Goals

- Organize UI by **domain -> workflow -> page**
- Keep navigation consistent across scraping, tailoring, and ops
- Preserve old links via redirects during migration
- Reuse shared page/workflow primitives to avoid ad-hoc layouts

## Current Navigation Hierarchy

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
    └── SQL Console
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

Legacy routes (`/jobs`, `/runs`, `/sql`, etc.) are redirected to hierarchical routes.

## Frontend Ownership Layout

```text
dashboard/web/src
├── components/
│   ├── layout/
│   │   └── AppShell.tsx
│   └── workflow/
│       ├── PageLayout.tsx
│       ├── Panel.tsx
│       ├── States.tsx
│       ├── ActionBar.tsx
│       ├── FilterToolbar.tsx
│       ├── LogPanel.tsx
│       └── RunTimelineChart.tsx
└── views/domains/
    ├── home/
    ├── scraping/
    │   ├── intake/
    │   ├── runs/
    │   └── quality/
    ├── tailoring/
    │   ├── runs/
    │   └── outputs/
    └── ops/
        ├── data/
        └── diagnostics/
```

## Backend Ownership Layout

```text
dashboard/backend
├── routers/
│   ├── scraping.py
│   ├── tailoring.py
│   └── ops.py
└── services/
    ├── scraping.py
    ├── tailoring.py
    └── ops.py
```

Scraping-domain handlers are imported from `job-scraper/api/scraping_handlers.py` via `dashboard/backend/services/scraping.py`.

## Refactor Status

- Hierarchical IA: complete
- Shared page/workflow primitives: complete
- Route-level code splitting: complete
- SQL Console DB admin controls (feature-flagged): complete
