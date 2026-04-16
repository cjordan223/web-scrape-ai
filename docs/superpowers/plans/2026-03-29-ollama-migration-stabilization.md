# Ollama/MLX Migration Stabilization Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 12 failing backend tests and 1 failing tracing test caused by incomplete Ollama/MLX migration, stale DB schema assumptions, and a missing import.

**Architecture:** The failures break into 5 root causes: (1) missing `_SCRAPE_SCHEDULER_TIMER` in `services/ops.py`, (2) tracing test mocks returning OpenAI response shape instead of Ollama native, (3) three dashboard LLM call sites still parsing `choices[0]` instead of provider-aware parsing, (4) test DB helpers creating `results` table with `decision` column when the real schema uses `jobs` table with `status` column, (5) test fixtures using stale LM Studio URLs/provider names. Fixes are ordered so that each task produces a passing subset before moving to the next.

**Tech Stack:** Python, FastAPI, SQLite, pytest, unittest.mock

---

### Task 1: Fix the `_SCRAPE_SCHEDULER_TIMER` ImportError (unblocks 1 test)

This is the import error that crashes `app.py` at line 1610 and directly fails `test_terminate_run_clears_stale_active_state`. The variable was removed from `services/ops.py` but `app.py` still references it.

**Files:**
- Modify: `dashboard/backend/app.py:1608-1614`

- [ ] **Step 1: Read the `_scrape_schedule_status` function**

Confirm `app.py:1608-1614` imports `_SCRAPE_SCHEDULER_TIMER` from `services.ops`.

- [ ] **Step 2: Check if any scheduler timer exists in ops.py**

```bash
grep -n "SCHEDULER\|Timer\|timer" dashboard/backend/services/ops.py
```

If no scheduler timer exists at all, the function should return a safe fallback indicating no in-process schedule is active.

- [ ] **Step 3: Fix the function to not import the removed symbol**

Replace the function body to avoid the missing import. The function should return `{"loaded": False, "interval_minutes": interval}` since the in-process timer was removed:

```python
def _scrape_schedule_status() -> dict:
    """Check if the in-process scrape schedule is active."""
    controls = _load_runtime_controls()
    interval = controls.get("schedule_interval_minutes")
    return {"loaded": False, "interval_minutes": interval}
```

- [ ] **Step 4: Run the previously-crashing test**

```bash
source venv/bin/activate && python -m pytest -v dashboard/backend/tests/test_tailoring_api.py::TestTailoringAPI::test_terminate_run_clears_stale_active_state
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/backend/app.py
git commit -m "fix: remove stale _SCRAPE_SCHEDULER_TIMER import from app.py"
```

---

### Task 2: Fix the tracing test mock to return Ollama-native response shape (unblocks 1 test)

`tailoring/tests/test_ollama_tracing.py` mocks `requests.post` returning `{"choices": [{"message": {"content": ...}}]}` but `ollama.py` now parses native Ollama format `{"message": {"content": ...}}` when `LLM_PROVIDER` is `"ollama"` or `""`.

**Files:**
- Modify: `tailoring/tests/test_ollama_tracing.py:19-26`

- [ ] **Step 1: Update the FakeResp to return Ollama-native shape**

The `FakeResp.json()` method at line 25 should return:

```python
def json(self):
    return {"message": {"content": "ok response"}}
```

This matches the native `/api/chat` response shape that `ollama.py:188` expects.

- [ ] **Step 2: Run the tracing tests**

```bash
source venv/bin/activate && PYTHONPATH=tailoring python -m pytest -v tailoring/tests/test_ollama_tracing.py
```

Expected: 2 passed

- [ ] **Step 3: Commit**

```bash
git add tailoring/tests/test_ollama_tracing.py
git commit -m "fix: update tracing test mock to use Ollama-native response shape"
```

---

### Task 3: Add provider-aware LLM response parsing to dashboard backend (unblocks 3 tests indirectly)

Three call sites in `services/tailoring.py` parse `cdata["choices"][0]["message"]["content"]` (OpenAI format). When the provider is Ollama and using native `/api/chat`, the response shape is `{"message": {"content": ...}}`. These sites use `urllib.request.urlopen` (not the shared `ollama.py` client), so they need a local helper to extract content from either response shape.

**Files:**
- Modify: `dashboard/backend/services/tailoring.py:1284, 1604, 2165`

- [ ] **Step 1: Add a response-content extraction helper**

Near the existing `_strip_llm_fences` helper, add:

```python
def _extract_llm_content(cdata: dict) -> str:
    """Extract content from either OpenAI or Ollama-native response shape."""
    # Ollama native /api/chat: {"message": {"content": "..."}}
    if "message" in cdata and isinstance(cdata["message"], dict):
        return cdata["message"].get("content") or ""
    # OpenAI-compatible: {"choices": [{"message": {"content": "..."}}]}
    choices = cdata.get("choices")
    if choices and isinstance(choices, list):
        return choices[0].get("message", {}).get("content") or ""
    return ""
```

- [ ] **Step 2: Replace the three `choices[0]` references**

At lines 1284, 1604, and 2165, change:

```python
raw = _strip_llm_fences(cdata["choices"][0]["message"]["content"])
```

to:

```python
raw = _strip_llm_fences(_extract_llm_content(cdata))
```

- [ ] **Step 3: Run the test suite to verify no regressions**

```bash
source venv/bin/activate && python -m pytest -v dashboard/backend/tests/test_tailoring_api.py -k "qa_approve or qa_llm_review"
```

These tests mock `urllib.request.urlopen` with OpenAI-style responses — they should still pass since `_extract_llm_content` handles both shapes.

- [ ] **Step 4: Commit**

```bash
git add dashboard/backend/services/tailoring.py
git commit -m "fix: add provider-aware LLM response parsing in dashboard backend"
```

---

### Task 4: Update test DB helpers to match the real schema (unblocks 8 tests)

The test helper `_create_results_db` creates a `results` table with `decision` column, but:
- The real scraper schema uses `jobs` table with `status` column
- `tailoring_ingest_commit` INSERTs into `jobs` table
- `_ensure_workflow_schema` migrates `jobs.status`, not `results.decision`
- `_purge_tailoring_ingest_jobs` checks for `results` table but the ops action path also needs `jobs`

The QA and ready endpoints still query `results` with `decision`, which means either (a) the real DB has a `results` view/alias, or (b) those endpoints are broken in production too. Check the actual DB to determine which pattern to follow.

**Files:**
- Modify: `dashboard/backend/tests/test_tailoring_api.py:17-105`

- [ ] **Step 1: Check if a view or alias exists for `results`**

```bash
sqlite3 ~/.local/share/job_scraper/jobs.db ".schema results"
```

Check whether `results` is a table, a view over `jobs`, or has the column `decision` vs `status`.

- [ ] **Step 2: Check which column name the QA/ready endpoints use**

```bash
grep -n "decision\|\.status" dashboard/backend/services/tailoring.py | head -30
```

Determine whether the production endpoints use `decision` or `status` column.

- [ ] **Step 3: Update `_create_results_db` to create both tables matching real schema**

The helper must create whatever tables the code actually queries. Based on the investigation:

1. If the code queries `results` table with `decision` column: keep the existing helper but ALSO create a `jobs` table for the ingest commit path.
2. If the code queries `jobs` table with `status` column: update the helper to create the correct schema.

The safest approach: create both a `results` table (for endpoints that query it) and a `jobs` table (for endpoints that write to it), matching the real DB's column names.

Create a new helper `_create_test_db` that:
- Creates `results` table with the columns the QA/ready endpoints expect
- Creates `jobs` table with the columns `tailoring_ingest_commit` expects
- Includes `approved_jd_text` column when `with_approved_jd_text=True`

```python
def _create_test_db(self, db_path: Path, *, with_approved_jd_text: bool = False) -> None:
    conn = sqlite3.connect(db_path)
    # results table — queried by QA list, ready list, job detail, etc.
    conn.execute(
        """
        CREATE TABLE results (
            id INTEGER PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            board TEXT,
            seniority TEXT,
            experience_years INTEGER,
            salary_k INTEGER,
            score INTEGER,
            decision TEXT,
            snippet TEXT,
            query TEXT,
            jd_text TEXT,
            filter_verdicts TEXT,
            run_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX idx_results_url_run ON results(url, run_id)")
    if with_approved_jd_text:
        conn.execute("ALTER TABLE results ADD COLUMN approved_jd_text TEXT")
    # jobs table — used by ingest commit, workflow status checks
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            company TEXT NOT NULL DEFAULT '',
            board TEXT,
            location TEXT,
            seniority TEXT,
            salary_text TEXT,
            jd_text TEXT,
            approved_jd_text TEXT,
            snippet TEXT,
            query TEXT,
            source TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            rejection_stage TEXT,
            rejection_reason TEXT,
            experience_years INTEGER,
            salary_k REAL,
            score REAL,
            filter_verdicts TEXT,
            run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
```

Update all test methods to call `_create_test_db` instead of `_create_results_db` where the test exercises endpoints that need both tables.

- [ ] **Step 4: Update `_insert_result` to also insert into `jobs` for tests that need it**

For tests that exercise ingest/ops paths, insert into both tables. OR — just ensure the `jobs` table exists; the ingest endpoint inserts into `jobs` itself.

- [ ] **Step 5: Fix `test_manual_ingest_commit` — the test creates `results` but ingest writes to `jobs`**

The test at line 577 just needs the `jobs` table to exist. Using the updated `_create_test_db` should be sufficient since it creates both tables. Verify the ingest commit writes to `jobs` and the test reads from `results` — these are different tables, so the assertion at line 601 (`SELECT id, decision, query, url FROM results`) will need to query `jobs` instead:

```python
row = conn.execute(
    "SELECT id, status, query, url FROM jobs WHERE id = ?",
    (payload["job_id"],),
).fetchone()
```

And check `status` instead of `decision`:
```python
self.assertEqual(row["status"], "qa_pending")
```

- [ ] **Step 6: Fix `test_workflow_schema_migrates_legacy_decisions`**

This test expects `_ensure_workflow_schema` to migrate `decision` values. But the migration only runs on the `jobs` table `status` column. The test needs to insert into the `jobs` table with legacy `status` values (`accept`, `manual`, `manual_approved`) and then check that they got migrated. Also: the QA endpoint queries `results.decision`, not `jobs.status`, so the test's assertion about QA returning those items needs to reflect the actual endpoint behavior.

Review the exact endpoint queries and update the test data and assertions to match.

- [ ] **Step 7: Fix `test_clear_tailoring_runs_removes_tailoring_ingest_jobs`**

The ops action's `_purge_tailoring_ingest_jobs` queries `results` (which will exist with the updated helper), but the action also touches other code paths that may require `jobs`. Ensure both tables are created.

- [ ] **Step 8: Fix `test_apply_package_creates_durable_snapshot_and_surfaces_applied_summary`**

The test at line 1289 asserts `client.get("/api/tailoring/ready")` returns the job. The ready endpoint queries `results` with `decision = 'qa_approved'`. The test inserts with `decision="qa_approved"` so this should work IF the table is created correctly. The actual failure is `IndexError: list index out of range` — the ready list returns empty. This is likely because `_ensure_workflow_schema` runs on the test DB and either (a) the `applied_applications` table doesn't exist (the NOT EXISTS subquery fails), or (b) the ready endpoint's additional clauses filter out the result.

Debug by checking what `_ensure_workflow_schema` does to the test DB and whether the `applied_applications` table gets created. The `_APPLIED_DB_SCHEMA` (line 370) should create it. If the `jobs` table doesn't exist, the migration at lines 376-393 is skipped, so the `results` table `decision` values stay as-is.

The root cause may be that the ready endpoint requires additional workflow tables (`tailoring_ready_bucket_state`) created by `_ensure_workflow_schema`. Since the test DB has no `jobs` table, the whole migration might silently skip the part that creates the `applied_applications` table. Check and fix.

- [ ] **Step 9: Run all 12 tests**

```bash
source venv/bin/activate && python -m pytest -v dashboard/backend/tests/test_tailoring_api.py
```

Expected: 18 passed

- [ ] **Step 10: Commit**

```bash
git add dashboard/backend/tests/test_tailoring_api.py
git commit -m "fix: update test DB helpers to match real schema (jobs table + status column)"
```

---

### Task 5: Fix test fixtures with stale LM Studio URLs and provider names (unblocks 3 tests)

**Files:**
- Modify: `dashboard/backend/tests/test_tailoring_api.py`

- [ ] **Step 1: Fix `test_tailoring_routes` regenerate mock**

At line 229, the mock returns `"chat_url": "http://127.0.0.1:1234/v1/chat/completions"`. Update to use Ollama defaults and add the required `provider` key:

```python
with patch("app._resolve_llm_runtime", return_value={
    "provider": "ollama",
    "base_url": "http://localhost:11434",
    "chat_url": "http://localhost:11434/v1/chat/completions",
    "models_url": "http://localhost:11434/v1/models",
    "selected_model": "test-model",
    "manage_models": True,
    "api_key": "",
})
```

Also fix the empty `analysis.json` — the test writes `{}` which causes a 409. Write a minimal valid analysis:

```python
(run_dir / "analysis.json").write_text(
    json.dumps({"role_title": "Role", "key_requirements": ["Python"]}),
    encoding="utf-8",
)
```

Also: the test patches `app.subprocess.run` but the actual code calls `subprocess.run` inside `services.tailoring`. The correct patch target is `services.tailoring.subprocess.run`. Similarly, `_compile_tex_in_place` may need patching on `services.tailoring` instead of `app`.

Check which module the function is called from and patch accordingly.

- [ ] **Step 2: Fix `test_llm_status_and_models_support_openai_compatible_provider`**

At line 246, the test saves `"llm_provider": "openai"` but `_load_runtime_controls` auto-migrates `"openai"` → `"ollama"`. Use a valid non-local provider name instead (e.g., `"groq"` or `"custom"`):

```python
server._save_runtime_controls(
    {
        "llm_provider": "groq",
        "llm_base_url": "https://api.groq.com/openai/v1",
        "llm_model": "model-b",
    }
)
```

Then update assertions:
- `provider` → `"groq"` (not `"openai"`)
- `url` → `"https://api.groq.com/openai/v1"` (or whatever the provider's base_url is)
- `manage_models` → `False` (non-local providers don't manage models)

The `fake_urlopen` should match the URL used by `_resolve_llm_runtime` for that provider.

- [ ] **Step 3: Fix `test_qa_llm_review_*` tests — remove `/api/v0/models` mock**

At lines 809 and 975, the tests mock `/api/v0/models` (LM Studio-era model management endpoint). The current backend uses `/api/tags` for Ollama model management. Update the mock to respond to `/api/tags` instead:

```python
if url.endswith("/api/tags"):
    return FakeResponse({"models": [
        {"name": "meta/llama-3.3-70b"},
        {"name": "qwen/qwen3-coder-next"},
    ]})
```

For the "loaded model" test, Ollama treats all pulled models as loaded (on-demand), so all models from `/api/tags` are available. The `_resolve_llm_model_id` function picks the first one.

For the "no model loaded" test (line 968), simulate an empty `/api/tags` response:

```python
if url.endswith("/api/tags"):
    return FakeResponse({"models": []})
```

- [ ] **Step 4: Run all tests**

```bash
source venv/bin/activate && python -m pytest -v dashboard/backend/tests/test_tailoring_api.py
```

Expected: 18 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/backend/tests/test_tailoring_api.py
git commit -m "fix: update test fixtures to use Ollama/MLX defaults instead of LM Studio"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run both test suites**

```bash
source venv/bin/activate && python -m pytest -v dashboard/backend/tests/test_tailoring_api.py
source venv/bin/activate && PYTHONPATH=tailoring python -m pytest -v tailoring/tests/test_ollama_tracing.py
```

Expected: all 18 backend tests pass, all 2 tracing tests pass.

- [ ] **Step 2: Spot-check the dashboard starts cleanly**

```bash
source venv/bin/activate && timeout 5 python dashboard/backend/server.py 2>&1 || true
```

Confirm no import errors on startup.

- [ ] **Step 3: Commit any final adjustments if needed**

---

## Failure Root Cause Summary

| # Tests | Root Cause | Fix |
|---------|-----------|-----|
| 1 | `_SCRAPE_SCHEDULER_TIMER` removed from ops.py but still imported in app.py | Remove dead import, return safe fallback |
| 1 | Tracing test mocks return OpenAI shape, code expects Ollama native | Update mock to `{"message": {"content": ...}}` |
| 3 | Dashboard LLM calls parse `choices[0]` instead of provider-aware | Add `_extract_llm_content()` helper |
| ~8 | Test DB creates `results`/`decision` but code uses `jobs`/`status` | Update test helpers to create both tables |
| 3 | Test fixtures use port 1234, provider "openai", `/api/v0/models` | Update to Ollama defaults, current API paths |

Note: Several tests fail for multiple reasons (e.g., both stale DB schema AND stale fixtures), so fixing them requires completing multiple tasks.
