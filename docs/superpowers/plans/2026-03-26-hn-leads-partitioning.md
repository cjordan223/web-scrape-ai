# HN Leads Partitioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route HN Hiring jobs to a new `lead` status so they're browsable without polluting the QA/tailoring pipeline.

**Architecture:** Add a source-aware status override in the scraper storage pipeline, a new read-only backend endpoint, and a lightweight frontend view. No schema changes — `status` is already free-text.

**Tech Stack:** Python (Scrapy pipeline, FastAPI), TypeScript/React, SQLite

---

### Task 1: Storage pipeline — route HN jobs to `lead` status

**Files:**
- Modify: `job-scraper/job_scraper/pipelines/storage.py:32-43`
- Test: `job-scraper/tests/test_storage_pipeline.py` (create)

- [ ] **Step 1: Write the failing test**

Create `job-scraper/tests/test_storage_pipeline.py`:

```python
"""Tests for the storage pipeline lead-status routing."""
from unittest.mock import MagicMock

from job_scraper.pipelines.storage import SQLitePipeline


def _make_pipeline() -> tuple[SQLitePipeline, MagicMock]:
    db = MagicMock()
    p = SQLitePipeline(db=db, run_id="test-run")
    return p, db


def _item(source: str = "searxng", status: str | None = None) -> dict:
    base = {
        "url": "https://example.com/job",
        "title": "Engineer",
        "company": "Acme",
        "source": source,
    }
    if status:
        base["status"] = status
    return base


def test_hn_hiring_gets_lead_status():
    p, db = _make_pipeline()
    item = _item(source="hn_hiring")
    p.process_item(item, spider=MagicMock())
    job = db.insert_job.call_args[0][0]
    assert job["status"] == "lead"


def test_hn_hiring_rejected_stays_rejected():
    p, db = _make_pipeline()
    item = _item(source="hn_hiring", status="rejected")
    p.process_item(item, spider=MagicMock())
    job = db.insert_job.call_args[0][0]
    assert job["status"] == "rejected"


def test_non_hn_source_unchanged():
    p, db = _make_pipeline()
    item = _item(source="searxng")
    p.process_item(item, spider=MagicMock())
    job = db.insert_job.call_args[0][0]
    assert "status" not in job or job.get("status") != "lead"


def test_non_hn_source_preserves_existing_status():
    p, db = _make_pipeline()
    item = _item(source="ashby", status="rejected")
    p.process_item(item, spider=MagicMock())
    job = db.insert_job.call_args[0][0]
    assert job["status"] == "rejected"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/conner/Documents/JobForge/job-scraper && python -m pytest tests/test_storage_pipeline.py -v`
Expected: `test_hn_hiring_gets_lead_status` FAILS (status will be unset, defaulting to `qa_pending` in db.py)

- [ ] **Step 3: Implement the status override**

In `job-scraper/job_scraper/pipelines/storage.py`, add the lead routing after line 34 (`job["run_id"] = self._run_id`):

```python
    def process_item(self, item, spider):
        job = dict(item)
        job["run_id"] = self._run_id
        # Route HN Hiring jobs to 'lead' status (skip QA — thin JD content)
        if job.get("source") == "hn_hiring" and job.get("status") != "rejected":
            job["status"] = "lead"
        try:
            self._db.insert_job(job)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/conner/Documents/JobForge/job-scraper && python -m pytest tests/test_storage_pipeline.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/pipelines/storage.py job-scraper/tests/test_storage_pipeline.py
git commit -m "feat: route HN Hiring jobs to 'lead' status in storage pipeline"
```

---

### Task 2: Backend — add `GET /api/leads` endpoint

**Files:**
- Modify: `dashboard/backend/routers/tailoring.py:8-63` (add route)
- Modify: `dashboard/backend/services/tailoring.py` (add handler, after `tailoring_qa_list` around line 1688)

- [ ] **Step 1: Add the route**

In `dashboard/backend/routers/tailoring.py`, add to the `ROUTES` list (after line 58, before the closing bracket):

```python
    ("GET", "/api/leads", "leads_list"),
```

- [ ] **Step 2: Write the handler**

In `dashboard/backend/services/tailoring.py`, add after the `tailoring_qa_list` function (after line 1688):

```python
def leads_list(
    limit: int = Query(200, ge=1, le=2000),
    search: str | None = Query(None),
):
    _sync_app_state()
    search = search if isinstance(search, str) else None
    conn = get_db()
    try:
        available = {
            "company": _results_has_column(conn, "company"),
            "location": _results_has_column(conn, "location"),
        }
        clauses = ["decision = 'lead'"]
        params: list[object] = []
        if search:
            q = f"%{search.strip()}%"
            search_fields = [
                "COALESCE(title, '')",
                "COALESCE(url, '')",
            ]
            if available["company"]:
                search_fields.append("COALESCE(company, '')")
            if available["location"]:
                search_fields.append("COALESCE(location, '')")
            clauses.append("(" + " OR ".join(f"{field} LIKE ?" for field in search_fields) + ")")
            params.extend([q] * len(search_fields))
        where = "WHERE " + " AND ".join(clauses)
        total = conn.execute(f"SELECT COUNT(*) FROM results {where}", tuple(params)).fetchone()[0]
        select_cols = [
            "id",
            "title",
            "url",
            "board",
            "created_at",
            "jd_text",
            "company" if available["company"] else "NULL AS company",
            "location" if available["location"] else "NULL AS location",
        ]
        query_params = [*params, max(1, min(int(limit), 2000))]
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} "
            f"FROM results {where} "
            "ORDER BY id DESC LIMIT ?",
            tuple(query_params),
        ).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            # Truncate jd_text to snippet for list display
            jd = d.pop("jd_text", None) or ""
            d["snippet"] = jd[:300].strip()
            items.append(d)
        return {"items": items, "count": len(items), "total": total}
    finally:
        conn.close()
```

- [ ] **Step 3: Verify the endpoint loads**

Run: `cd /Users/conner/Documents/JobForge && source venv/bin/activate && python -c "from dashboard.backend.services.tailoring import leads_list; print('OK')"`
Expected: `OK` (no import errors)

- [ ] **Step 4: Commit**

```bash
git add dashboard/backend/routers/tailoring.py dashboard/backend/services/tailoring.py
git commit -m "feat: add GET /api/leads endpoint for browsing HN leads"
```

---

### Task 3: Frontend — add API function and Leads view

**Files:**
- Modify: `dashboard/web/src/api.ts` (add `getLeads`)
- Create: `dashboard/web/src/views/domains/tailoring/leads/LeadsView.tsx`
- Modify: `dashboard/web/src/App.tsx` (add route)
- Modify: `dashboard/web/src/components/layout/AppShell.tsx` (add nav item)

- [ ] **Step 1: Add API function**

In `dashboard/web/src/api.ts`, add after the `getQAPending` function (after line 261):

```typescript
    getLeads: async (limit?: number, params?: Record<string, any>) => {
        const { data } = await apiClient.get('/leads', { params: { limit, ...(params || {}) } });
        return data;
    },
```

- [ ] **Step 2: Create LeadsView component**

Create `dashboard/web/src/views/domains/tailoring/leads/LeadsView.tsx`:

```tsx
import { useState, useEffect, useCallback } from 'react';
import { api } from '../../../../api';
import { timeAgo } from '../../../../utils';

interface Lead {
    id: number;
    title?: string;
    url?: string;
    board?: string;
    created_at?: string;
    company?: string;
    location?: string;
    snippet?: string;
}

const PANEL_BG = 'rgba(19, 24, 31, 0.97)';

export default function LeadsView() {
    const [leads, setLeads] = useState<Lead[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');

    const fetchLeads = useCallback(async () => {
        try {
            const res = await api.getLeads(2000, {
                search: search || undefined,
            });
            const items = res.items || [];
            setLeads(items);
            setTotal(res.total ?? items.length);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, [search]);

    useEffect(() => {
        fetchLeads();
        const interval = setInterval(fetchLeads, 60000);
        return () => clearInterval(interval);
    }, [fetchLeads]);

    if (loading) {
        return <div className="view-container"><div className="loading"><div className="spinner" /></div></div>;
    }

    return (
        <div style={{ height: 'calc(100vh - 56px)', overflow: 'hidden', background: 'var(--surface)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
                <div style={{
                    padding: '14px 16px',
                    borderBottom: '1px solid rgba(100, 160, 220, 0.16)',
                    background: PANEL_BG,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <span style={{
                            fontFamily: 'var(--font)',
                            fontSize: '.94rem',
                            fontWeight: 700,
                            color: '#f4ede8',
                        }}>
                            Leads
                        </span>
                        <span style={{
                            fontFamily: 'var(--font)',
                            fontSize: '.76rem',
                            fontWeight: 500,
                            color: 'rgba(233, 220, 210, 0.78)',
                        }}>
                            HN Hiring finds — browse and ingest when ready. {total} leads.
                        </span>
                    </div>
                </div>

                <div style={{
                    padding: '10px 14px',
                    borderBottom: '1px solid rgba(100, 160, 220, 0.12)',
                    background: 'linear-gradient(180deg, rgba(100, 160, 220, 0.05), rgba(19, 24, 31, 0.98))',
                }}>
                    <input
                        type="text"
                        placeholder="Search by company or title..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        style={{
                            width: '100%',
                            padding: '8px 12px',
                            fontFamily: 'var(--font)',
                            fontSize: '.82rem',
                            background: 'rgba(31, 39, 52, 0.7)',
                            border: '1px solid rgba(100, 160, 220, 0.18)',
                            borderRadius: '8px',
                            color: '#eef3ff',
                            outline: 'none',
                        }}
                    />
                </div>

                <div style={{ flex: 1, overflowY: 'auto', padding: '0' }}>
                    {leads.length === 0 ? (
                        <div style={{
                            padding: '40px 20px',
                            textAlign: 'center',
                            fontFamily: 'var(--font)',
                            fontSize: '.84rem',
                            color: 'rgba(233, 220, 210, 0.5)',
                        }}>
                            No leads found.
                        </div>
                    ) : (
                        leads.map((lead) => (
                            <div
                                key={lead.id}
                                style={{
                                    padding: '12px 16px',
                                    borderBottom: '1px solid rgba(255,255,255,0.04)',
                                    cursor: 'pointer',
                                }}
                                onClick={() => lead.url && window.open(lead.url, '_blank')}
                            >
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '4px' }}>
                                    <span style={{
                                        fontFamily: 'var(--font)',
                                        fontSize: '.84rem',
                                        fontWeight: 700,
                                        color: '#eef3ff',
                                    }}>
                                        {lead.company || 'Unknown'}
                                    </span>
                                    <span style={{
                                        fontFamily: 'var(--font)',
                                        fontSize: '.7rem',
                                        color: 'rgba(233, 220, 210, 0.45)',
                                    }}>
                                        {lead.created_at ? timeAgo(lead.created_at) : ''}
                                    </span>
                                </div>
                                <div style={{
                                    fontFamily: 'var(--font)',
                                    fontSize: '.8rem',
                                    color: 'rgba(233, 220, 210, 0.7)',
                                    marginBottom: '4px',
                                }}>
                                    {lead.title || 'Untitled'}
                                    {lead.location ? ` · ${lead.location}` : ''}
                                </div>
                                {lead.snippet && (
                                    <div style={{
                                        fontFamily: 'var(--font)',
                                        fontSize: '.74rem',
                                        color: 'rgba(233, 220, 210, 0.4)',
                                        lineHeight: '1.4',
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        display: '-webkit-box',
                                        WebkitLineClamp: 2,
                                        WebkitBoxOrient: 'vertical',
                                    }}>
                                        {lead.snippet}
                                    </div>
                                )}
                            </div>
                        ))
                    )}
                </div>
            </div>
        </div>
    );
}
```

- [ ] **Step 3: Add route in App.tsx**

In `dashboard/web/src/App.tsx`, add the lazy import after line 22 (after `AppliedView`):

```typescript
const LeadsView = lazy(() => import('./views/domains/tailoring/leads/LeadsView'));
```

Add the route after line 151 (after the `/pipeline/applied` route):

```typescript
          <Route path="/pipeline/leads" element={<LazyRoute><LeadsView /></LazyRoute>} />
```

- [ ] **Step 4: Add nav item in AppShell.tsx**

In `dashboard/web/src/components/layout/AppShell.tsx`, add `Lightbulb` to the lucide-react import (line 3-13):

```typescript
import {
  GitBranch,
  Briefcase,
  XCircle,
  Package,
  Terminal,
  FileCheck,
  ClipboardPaste,
  CheckSquare,
  Workflow,
  Lightbulb,
} from 'lucide-react';
```

Add the Leads nav item after the QA entry (after line 41):

```typescript
      { label: 'Leads', to: '/pipeline/leads', icon: Lightbulb, desc: 'HN finds — browse & ingest' },
```

- [ ] **Step 5: Build and verify**

Run: `cd /Users/conner/Documents/JobForge/dashboard/web && npm run build`
Expected: Build succeeds with no errors

- [ ] **Step 6: Commit**

```bash
git add dashboard/web/src/api.ts dashboard/web/src/views/domains/tailoring/leads/LeadsView.tsx dashboard/web/src/App.tsx dashboard/web/src/components/layout/AppShell.tsx
git commit -m "feat: add Leads view for browsing HN Hiring leads"
```

---

### Task 4: Migrate existing HN jobs to `lead` status

**Files:**
- None (one-time SQL migration)

- [ ] **Step 1: Verify current HN job counts**

Run:
```bash
sqlite3 ~/.local/share/job_scraper/jobs.db "SELECT status, COUNT(*) FROM jobs WHERE board='hn_hiring' GROUP BY status;"
```
Expected: Shows `qa_approved`, `qa_pending`, `qa_rejected`, `rejected` counts

- [ ] **Step 2: Run the migration**

Run:
```bash
sqlite3 ~/.local/share/job_scraper/jobs.db "UPDATE jobs SET status = 'lead' WHERE board = 'hn_hiring' AND status IN ('qa_approved', 'qa_pending', 'qa_rejected');"
```

- [ ] **Step 3: Verify migration**

Run:
```bash
sqlite3 ~/.local/share/job_scraper/jobs.db "SELECT status, COUNT(*) FROM jobs WHERE board='hn_hiring' GROUP BY status;"
```
Expected: Shows `lead` (671) and `rejected` (47)

- [ ] **Step 4: Verify QA view is clean**

Start the dashboard and check `/pipeline/qa` — no HN jobs should appear.
Check `/pipeline/leads` — all migrated HN jobs should appear.

---

### Task 5: End-to-end verification

- [ ] **Step 1: Verify the scraper pipeline routes new HN jobs correctly**

Run the HN spider in dry-run mode to confirm new jobs would get `lead` status:

```bash
cd /Users/conner/Documents/JobForge/job-scraper && python -m pytest tests/test_storage_pipeline.py -v
```

Expected: All 4 tests pass

- [ ] **Step 2: Verify leads endpoint returns data**

With the dashboard running:

```bash
curl -s http://localhost:8899/api/leads | python3 -m json.tool | head -30
```

Expected: JSON with `items`, `count`, `total` fields. Items should have HN jobs.

- [ ] **Step 3: Verify QA endpoint excludes leads**

```bash
curl -s 'http://localhost:8899/api/tailoring/qa?limit=5' | python3 -m json.tool | head -10
```

Expected: No HN Hiring jobs in the response.

- [ ] **Step 4: Verify tailoring queue rejects leads**

Attempt to queue a lead for tailoring (pick any lead ID from step 2):

```bash
curl -s -X POST http://localhost:8899/api/tailoring/queue -H 'Content-Type: application/json' -d '{"jobs":[{"job_id": LEAD_ID}]}' | python3 -m json.tool
```

Expected: Error or skip — the job is not `qa_approved` so it should be rejected.

- [ ] **Step 5: Final commit if any adjustments were needed**

```bash
git add -A && git status
```

If clean, no commit needed. If adjustments were made, commit them.
