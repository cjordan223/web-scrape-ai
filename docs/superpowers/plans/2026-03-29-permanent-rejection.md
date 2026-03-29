# Permanent Rejection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to permanently reject expired jobs so they never resurface through the scraper pipeline.

**Architecture:** Add a `permanently_rejected` column to `seen_urls` so `is_seen()` always returns `True` for blocked URLs. New `permanently_rejected` status in `jobs` table. One new API endpoint, called from QAView and JobInventoryTab.

**Tech Stack:** Python/SQLite (backend), React/TypeScript (frontend)

---

### Task 1: Add `permanently_rejected` column to `seen_urls` and update `is_seen()`

**Files:**
- Modify: `job-scraper/job_scraper/db.py:10-14` (schema)
- Modify: `job-scraper/job_scraper/db.py:89-132` (migration)
- Modify: `job-scraper/job_scraper/db.py:143-153` (is_seen)
- Modify: `job-scraper/job_scraper/db.py:155-161` (new method)

- [ ] **Step 1: Update `_SCHEMA` to include `permanently_rejected` column**

In `db.py`, update the `seen_urls` CREATE TABLE statement (line 10-14):

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_urls (
    url TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    permanently_rejected INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_seen_urls_first_seen ON seen_urls(first_seen);
```

- [ ] **Step 2: Add migration for existing databases**

In `_migrate_schema()`, add a new migration block after the existing runs migration (after line 132):

```python
# Add permanently_rejected column to seen_urls if missing
try:
    cols = {r[1] for r in self._conn.execute("PRAGMA table_info(seen_urls)")}
    if cols and "permanently_rejected" not in cols:
        self._conn.execute(
            "ALTER TABLE seen_urls ADD COLUMN permanently_rejected INTEGER NOT NULL DEFAULT 0"
        )
        self._conn.commit()
except Exception:
    pass
```

- [ ] **Step 3: Update `is_seen()` to respect `permanently_rejected` flag**

Replace the `is_seen()` method (lines 143-153):

```python
def is_seen(self, url: str, ttl_days: int = 14) -> bool:
    row = self._conn.execute(
        "SELECT first_seen, permanently_rejected FROM seen_urls WHERE url = ?", (url,)
    ).fetchone()
    if row is None:
        return False
    if row["permanently_rejected"]:
        return True
    first = datetime.fromisoformat(row["first_seen"])
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - first).days
    return age < ttl_days
```

- [ ] **Step 4: Add `mark_permanently_rejected()` method**

Add after `mark_seen()` (after line 161):

```python
def mark_permanently_rejected(self, url: str) -> None:
    now = _now()
    self._conn.execute(
        "INSERT INTO seen_urls (url, first_seen, last_seen, permanently_rejected) "
        "VALUES (?, ?, ?, 1) "
        "ON CONFLICT(url) DO UPDATE SET permanently_rejected = 1, last_seen = ?",
        (url, now, now, now),
    )
```

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/db.py
git commit -m "feat: add permanently_rejected flag to seen_urls with TTL bypass"
```

---

### Task 2: Add backend endpoint for permanent rejection

**Files:**
- Modify: `dashboard/backend/services/tailoring.py:1819-1846` (add new handler after `tailoring_qa_reject`)
- Modify: `dashboard/backend/routers/tailoring.py:55` (add route)

- [ ] **Step 1: Add `tailoring_qa_permanently_reject()` handler**

In `dashboard/backend/services/tailoring.py`, add after the `tailoring_qa_reject` function (after line 1846):

```python
def tailoring_qa_permanently_reject(payload: dict = Body(...)):
    _sync_app_state()
    job_ids = payload.get("job_ids") or []
    if payload.get("job_id"):
        job_ids = [payload["job_id"]]
    if not job_ids:
        return JSONResponse({"ok": False, "error": "job_id or job_ids required"}, 400)

    conn = get_db_write()
    try:
        from services.audit import log_state_change
        updated = 0
        for jid in job_ids:
            row = conn.execute("SELECT decision, url FROM results WHERE id=?", (jid,)).fetchone()
            if not row:
                continue
            old_decision = _normalize_decision(row["decision"])
            if old_decision in ("permanently_rejected",):
                continue
            _cancel_tailoring_queue_items(job_ids=[int(jid)], statuses=("queued",), reason="Job permanently rejected.")
            _stop_active_tailoring_job([int(jid)], "Job permanently rejected.")
            _set_ready_bucket_for_job_ids_in_conn(conn, [int(jid)], _DEFAULT_READY_BUCKET)
            conn.execute("UPDATE jobs SET status='permanently_rejected' WHERE id=?", (jid,))
            # Mark URL as permanently rejected in seen_urls so it never re-enters the pipeline
            conn.execute(
                "INSERT INTO seen_urls (url, first_seen, last_seen, permanently_rejected) "
                "VALUES (?, ?, ?, 1) "
                "ON CONFLICT(url) DO UPDATE SET permanently_rejected = 1, last_seen = ?",
                (row["url"], _now_utc(), _now_utc(), _now_utc()),
            )
            log_state_change(conn, job_id=jid, job_url=row["url"],
                             old_state=old_decision, new_state="permanently_rejected",
                             action="permanently_reject")
            updated += 1
        conn.commit()
        return {"ok": True, "updated": updated, "skipped": len(job_ids) - updated}
    finally:
        conn.close()
```

Note: Check what the UTC timestamp helper is called in tailoring.py — it may be `_now_utc()` or imported differently. Match the existing pattern. If the module uses a local `_now_utc` or imports one, use that. Otherwise define inline: `datetime.now(timezone.utc).isoformat()`.

- [ ] **Step 2: Register the route**

In `dashboard/backend/routers/tailoring.py`, add after line 55 (the `qa/reject` route):

```python
    ("POST", "/api/tailoring/qa/permanently-reject", "tailoring_qa_permanently_reject"),
```

- [ ] **Step 3: Verify the handler is exported**

The handlers dict in `app.py` or wherever it assembles the route handlers needs to include `tailoring_qa_permanently_reject`. Check how `tailoring_qa_reject` gets into that dict and follow the same pattern. The service module likely uses `globals()` export — if so, the new function is automatically available.

- [ ] **Step 4: Commit**

```bash
git add dashboard/backend/services/tailoring.py dashboard/backend/routers/tailoring.py
git commit -m "feat: add POST /api/tailoring/qa/permanently-reject endpoint"
```

---

### Task 3: Add frontend API method

**Files:**
- Modify: `dashboard/web/src/api.ts:318-321` (add after `rejectQA`)

- [ ] **Step 1: Add `permanentlyRejectQA` method**

In `dashboard/web/src/api.ts`, add after the `rejectQA` method (after line 321):

```typescript
    permanentlyRejectQA: async (jobIds: number[]) => {
        const { data } = await apiClient.post('/tailoring/qa/permanently-reject', { job_ids: jobIds });
        return data;
    },
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/web/src/api.ts
git commit -m "feat: add permanentlyRejectQA API method"
```

---

### Task 4: Add permanent reject action to QAView

**Files:**
- Modify: `dashboard/web/src/views/domains/tailoring/qa/QAView.tsx`

- [ ] **Step 1: Add `handlePermanentlyReject` handler**

In `QAView.tsx`, add after the `handleReject` function (after line 539):

```typescript
    const handlePermanentlyReject = async (ids: number[]) => {
        if (!ids.length) return;
        setBusy('reject');
        try {
            await api.permanentlyRejectQA(ids);
            removeFromList(ids);
        } catch (err) {
            console.error(err);
        } finally {
            setBusy(null);
        }
    };
```

- [ ] **Step 2: Add bulk "Permanently Reject" button**

In the bulk action bar (after the "Reject Selected" button, after line 659), add:

```tsx
                        <button
                            className="btn btn-sm"
                            disabled={!!busy || selected.size === 0}
                            onClick={() => handlePermanentlyReject(Array.from(selected))}
                            style={{ flex: 1, background: 'rgba(140, 20, 20, 0.85)', color: '#fff', border: '1px solid rgba(200, 40, 40, 0.4)', fontFamily: 'var(--font)', fontWeight: 700, minHeight: '38px' }}
                        >
                            {busy === 'reject' ? 'Rejecting...' : `Dead (${selected.size})`}
                        </button>
```

- [ ] **Step 3: Update QADetailPanel to accept `onPermanentlyReject`**

Update the `QADetailPanel` function signature (lines 190-199):

```typescript
function QADetailPanel({
    detail,
    busy,
    onApprove,
    onReject,
    onPermanentlyReject,
}: {
    detail: any;
    busy: 'approve' | 'reject' | 'llm-review' | null;
    onApprove: (id: number) => void;
    onReject: (id: number) => void;
    onPermanentlyReject: (id: number) => void;
}) {
```

- [ ] **Step 4: Add per-job "Dead" button in QADetailPanel**

After the existing "Reject" button (after line 308), add:

```tsx
                    <button
                        className="btn btn-sm"
                        disabled={!!busy}
                        onClick={() => onPermanentlyReject(detail.id)}
                        style={{ background: 'rgba(140, 20, 20, 0.85)', color: '#fff', border: '1px solid rgba(200, 40, 40, 0.4)' }}
                    >
                        Dead
                    </button>
```

- [ ] **Step 5: Pass `onPermanentlyReject` prop to QADetailPanel**

Update the QADetailPanel usage (around line 1215-1220):

```tsx
                                                    <QADetailPanel
                                                        detail={detail}
                                                        busy={busy}
                                                        onApprove={(id) => handleApprove([id])}
                                                        onReject={(id) => handleReject([id])}
                                                        onPermanentlyReject={(id) => handlePermanentlyReject([id])}
                                                    />
```

- [ ] **Step 6: Commit**

```bash
git add dashboard/web/src/views/domains/tailoring/qa/QAView.tsx
git commit -m "feat: add permanent reject action to QA view"
```

---

### Task 5: Add permanent reject action to JobInventoryTab

**Files:**
- Modify: `dashboard/web/src/views/domains/tailoring/runs/JobInventoryTab.tsx:553-567`

- [ ] **Step 1: Add "Dead" button next to existing "Reject" button**

In `JobInventoryTab.tsx`, after the existing "Reject" button block (after line 567), add:

```tsx
                            <button
                                className="btn btn-ghost btn-sm"
                                onClick={async () => {
                                    if (!confirm(`Permanently reject ${selectedIds.size} job(s)? These URLs will never re-enter the pipeline.`)) return;
                                    try {
                                        await api.permanentlyRejectQA(Array.from(selectedIds));
                                        await loadReadyJobs();
                                        setSelectedIds(new Set());
                                        setFocusedJobId(0);
                                    } catch { }
                                }}
                                style={{ fontSize: '.68rem', color: 'rgba(200, 40, 40, 0.9)' }}
                            >
                                Dead ({selectedIds.size})
                            </button>
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/web/src/views/domains/tailoring/runs/JobInventoryTab.tsx
git commit -m "feat: add permanent reject action to job inventory"
```

---

### Task 6: Manual smoke test

- [ ] **Step 1: Start the backend**

```bash
cd /Users/conner/Documents/JobForge
source venv/bin/activate
python dashboard/backend/server.py
```

- [ ] **Step 2: Verify migration ran**

```bash
sqlite3 ~/.local/share/job_scraper/jobs.db "PRAGMA table_info(seen_urls);"
```

Expected: should show `permanently_rejected` column.

- [ ] **Step 3: Test the endpoint**

Pick a `qa_pending` or `qa_approved` job ID and test:

```bash
curl -X POST http://localhost:8899/api/tailoring/qa/permanently-reject \
  -H 'Content-Type: application/json' \
  -d '{"job_ids": [<test_id>]}'
```

Expected: `{"ok": true, "updated": 1, "skipped": 0}`

- [ ] **Step 4: Verify seen_urls flag was set**

```bash
sqlite3 ~/.local/share/job_scraper/jobs.db \
  "SELECT url, permanently_rejected FROM seen_urls WHERE permanently_rejected = 1 LIMIT 5;"
```

- [ ] **Step 5: Verify job status changed**

```bash
sqlite3 ~/.local/share/job_scraper/jobs.db \
  "SELECT id, status FROM jobs WHERE id = <test_id>;"
```

Expected: `permanently_rejected`

- [ ] **Step 6: Build frontend and verify buttons appear**

```bash
cd /Users/conner/Documents/JobForge/dashboard/web
npm run build
```

Open the dashboard, navigate to QA view and Job Inventory, verify the "Dead" buttons render.
