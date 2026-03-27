# HN Leads Partitioning

**Date:** 2026-03-26
**Goal:** Separate HN Hiring jobs from the main QA/tailoring pipeline so they serve as browsable leads rather than blocking the tailoring queue with thin JD content.

## Context

HN "Who's Hiring" jobs are the highest-approval-rate source (37.3%, 268 of 718) but fundamentally different from other sources:

- **Average JD length: 1,109 chars** (vs. 4,406 for other sources). 94% are under 2K chars.
- **Zero successful URL follows** — all 718 HN jobs store the HN comment URL, not a real job posting page. The spider tries to follow URLs in comments but they're company homepages or dead links.
- **Tailoring failures** — thin JD text causes the analyzer to map 1 requirement instead of 5-10, the LLM hallucinates claims to fill the gap, and the validator correctly rejects them. Each failed attempt burns ~10-15 min on retries.
- **QA approval is valid** — these are real companies with real roles. They're good leads, just not tailoring-ready.

Overnight, 10 HN jobs were queued for tailoring. 3 processed (all failed quality gates), 7 sat idle. The user had to manually clear the queue in the morning.

## Design

### New status: `lead`

A new `status` value `'lead'` for jobs that are promising finds but lack sufficient JD content for tailoring. Currently this means all HN Hiring jobs that pass the hard filter.

### Pipeline change

In `job-scraper/job_scraper/db.py`, when persisting a job: if `source == 'hn_hiring'` and the job was not rejected by the hard filter, set `status = 'lead'` instead of `'qa_pending'`.

- Hard filter still runs — title blocklist, content blocklist, seniority, geo, salary floor all apply. The 47 HN jobs that currently get `rejected` will continue to be rejected.
- No changes to: hard filter logic, dedup, text extraction, or any other pipeline stage.
- No changes to how any other source is processed.

### Backend

New endpoint: `GET /api/leads`

- Returns jobs where `status = 'lead'`
- Supports query params: `limit`, `search` (title/company text match), `board` (for future lead sources)
- Same response shape as the QA list for frontend consistency
- Read-only — no approve/reject/queue actions

Leads are not tailoring-eligible. The existing `_job_is_qa_ready()` check gates on `status = 'qa_approved'`, so leads cannot be queued for tailoring. This requires no code change — it's already enforced.

### Frontend

New "Leads" tab in the tailoring domain (`/tailoring/leads` or a tab within an existing view).

- Simple list: company, title, location, HN comment snippet (first ~200 chars)
- Each row links out to the HN comment URL (opens in new tab) so the user can find the actual job posting
- Search/filter by company or title
- No queue button, no approve/reject actions
- When the user finds a lead worth pursuing, they use the existing mobile ingest flow (`/m/ingest`) to paste the real job URL or JD text, creating a separate `qa_approved` job that enters the normal tailoring pipeline

### What doesn't change

- Hard filter pipeline (still runs on HN jobs)
- QA view and workflow (HN jobs no longer appear here)
- Tailoring queue and runner
- Mobile ingest flow
- Job Inventory tab (only shows `qa_approved`, unchanged)
- All other sources: ashby, greenhouse, lever, searxng, usajobs, remoteok

## Migration

Existing HN jobs in the database:

- 268 with `status = 'qa_approved'` — update to `'lead'`
- 1 with `status = 'qa_pending'` — update to `'lead'`
- 402 with `status = 'qa_rejected'` — update to `'lead'` (they were QA-rejected due to thin content, not because they were bad leads)
- 47 with `status = 'rejected'` — leave as `rejected` (hard filter rejections are valid)

One-time SQL:
```sql
UPDATE jobs SET status = 'lead'
WHERE board = 'hn_hiring' AND status IN ('qa_approved', 'qa_pending', 'qa_rejected');
```

## Future considerations (not in scope)

- Auto-enrichment: spider follows careers page links and attempts title matching to find real JD
- Extending `lead` status to other thin-JD sources (e.g. `searxng|ashby` with 46-char avg JD)
- Lead-to-ingest shortcut in the dashboard (pre-fill ingest form with company/title from the lead)
