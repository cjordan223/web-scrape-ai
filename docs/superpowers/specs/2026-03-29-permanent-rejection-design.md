# Permanent Rejection ("Dead Jobs") Design

## Problem

Jobs in the QA-approved backlog often expire before the user reviews them. After the 14-day `seen_urls` TTL expires, these dead URLs can resurface through the scraper pipeline. The user needs a way to permanently block specific URLs from ever re-entering the pipeline, and to remove them from all active review/candidacy stages immediately.

## Scope

- Permanent URL-level blocking (not employer/company-level)
- New `permanently_rejected` status in the `jobs` table
- New `permanently_rejected` flag on `seen_urls` table
- API endpoint for the action
- UI action available in QAView, JobInventoryTab, and any job detail context

## Database Changes

### `seen_urls` table (in `job-scraper/job_scraper/db.py`)

Add column:

```sql
ALTER TABLE seen_urls ADD COLUMN permanently_rejected INTEGER NOT NULL DEFAULT 0;
```

Added to `_ensure_tables()` schema as well so new databases get the column.

### `is_seen()` function (in `db.py`)

Modified to return `True` immediately if `permanently_rejected = 1`, bypassing TTL logic entirely.

### `jobs` table

New status value: `permanently_rejected`. No schema change needed — `status` is TEXT.

## API

### `POST /api/tailoring/qa/permanently-reject`

**Request:** `{ "job_ids": [int, ...] }`

**Behavior for each job:**
1. Validates job exists and is in an eligible status (`qa_pending`, `qa_approved`, `qa_rejected`, `lead`)
2. Sets `jobs.status = 'permanently_rejected'`
3. Sets `seen_urls.permanently_rejected = 1` for the job's URL
4. Cancels any queued tailoring items for these job IDs
5. Stops active tailoring job if one of these is currently running
6. Resets ready_bucket to default
7. Logs state change to `job_state_log` with action `'permanently_reject'`

**Response:** `{ "updated": int, "skipped": int }`

## Frontend

### `api.ts`

New method:
```typescript
permanentlyRejectQA: async (jobIds: number[]) => {
    const { data } = await apiClient.post('/tailoring/qa/permanently-reject', { job_ids: jobIds });
    return data;
}
```

### QAView (`qa/QAView.tsx`)

- Add "Permanently Reject" action alongside existing Approve/Reject
- Available for single jobs and bulk selection
- Visually distinct (red/destructive styling)

### JobInventoryTab (`runs/JobInventoryTab.tsx`)

- Add "Permanently Reject" action for selected jobs
- Available in the same action bar as queue/bucket controls

### Visual treatment

- Button uses destructive/red styling to distinguish from regular reject
- No confirmation modal needed (consistent with existing reject behavior, and the action is undoable via direct DB if needed)

## Scraper Pipeline Integration

No changes needed in the filter or storage pipelines. The dedup pipeline already calls `is_seen()` — with the flag check added there, permanently rejected URLs are dropped at dedup before they reach any filter stage.

## Migration

`ALTER TABLE ADD COLUMN ... DEFAULT 0` is safe in SQLite — existing rows get the default value. The migration runs in `_ensure_tables()` alongside the existing schema setup.

## Files to modify

1. `job-scraper/job_scraper/db.py` — schema, `is_seen()`, `mark_permanently_rejected()`
2. `dashboard/backend/services/tailoring.py` — `tailoring_qa_permanently_reject()` handler
3. `dashboard/backend/routers/tailoring.py` — new endpoint
4. `dashboard/web/src/api.ts` — new API method
5. `dashboard/web/src/views/domains/tailoring/qa/QAView.tsx` — UI action
6. `dashboard/web/src/views/domains/tailoring/runs/JobInventoryTab.tsx` — UI action
