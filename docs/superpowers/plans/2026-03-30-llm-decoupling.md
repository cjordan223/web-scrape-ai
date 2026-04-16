# Decouple LLM Runtime Management from Shared Infrastructure

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make JobForge a client of inference infrastructure rather than a partial controller of it, so shared endpoints (Ollama, MLX) can serve multiple consumers without interference.

**Architecture:** Replace auto-model-discovery with explicit-or-fail semantics. Remove model reset on provider switch. Gate MLX lifecycle management behind `JOBFORGE_MANAGE_MLX=1`. Rename load/unload to select/deselect with proper empty-state handling.

**Tech Stack:** Python (FastAPI backend), TypeScript/React (frontend), pytest

**Ref:** GitHub issue #9

---

### Task 1: Eliminate blind auto-discovery in `ollama.py`

**Files:**
- Modify: `tailoring/tailor/ollama.py:64-83`
- Test: `tailoring/tests/test_model_resolution.py` (create)

- [ ] **Step 1: Write failing tests for model resolution**

Create `tailoring/tests/test_model_resolution.py`:

```python
"""Tests for LLM model resolution logic."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tailor import ollama, config as cfg


class TestGetLoadedModel(unittest.TestCase):
    def setUp(self):
        ollama._MODEL_CACHE = None

    def tearDown(self):
        ollama._MODEL_CACHE = None

    @patch.object(cfg, "OLLAMA_MODEL", "default")
    def test_default_model_raises_when_no_explicit_override(self):
        """When model is 'default' and no env override, should raise instead of auto-picking."""
        with self.assertRaises(RuntimeError) as ctx:
            ollama.get_loaded_model()
        self.assertIn("No model configured", str(ctx.exception))

    @patch.object(cfg, "OLLAMA_MODEL", "qwen3:32b")
    def test_explicit_model_returns_directly(self):
        result = ollama.get_loaded_model()
        self.assertEqual(result, "qwen3:32b")

    @patch.object(cfg, "OLLAMA_MODEL", "qwen3:32b")
    def test_model_cache_is_populated(self):
        ollama.get_loaded_model()
        self.assertEqual(ollama._MODEL_CACHE, "qwen3:32b")

    @patch.object(cfg, "OLLAMA_MODEL", "")
    def test_empty_model_raises(self):
        with self.assertRaises(RuntimeError):
            ollama.get_loaded_model()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/conner/Documents/JobForge && PYTHONPATH=tailoring python -m pytest tailoring/tests/test_model_resolution.py -v`
Expected: `test_default_model_raises_when_no_explicit_override` FAILS (currently returns first model or "default"), `test_empty_model_raises` FAILS.

- [ ] **Step 3: Implement explicit-or-fail model resolution**

Edit `tailoring/tailor/ollama.py`, replace `get_loaded_model()`:

```python
def get_loaded_model() -> str:
    """Resolve model: explicit override required. Raises if unset.

    Will NOT auto-pick from /v1/models — on a shared inference endpoint,
    the first model could be an embedding model or belong to another app.
    """
    global _MODEL_CACHE
    if _MODEL_CACHE:
        return _MODEL_CACHE
    model = cfg.OLLAMA_MODEL
    if not model or model == "default":
        raise RuntimeError(
            "No model configured for tailoring. "
            "Set TAILOR_LLM_MODEL env var or select a model in the dashboard "
            "(Settings > LLM Providers)."
        )
    _MODEL_CACHE = model
    return _MODEL_CACHE
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/conner/Documents/JobForge && PYTHONPATH=tailoring python -m pytest tailoring/tests/test_model_resolution.py -v`
Expected: All PASS.

- [ ] **Step 5: Run existing ollama tests to check for regressions**

Run: `cd /Users/conner/Documents/JobForge && PYTHONPATH=tailoring python -m pytest tailoring/tests/ -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add tailoring/tailor/ollama.py tailoring/tests/test_model_resolution.py
git commit -m "fix: replace blind auto-model-discovery with explicit-or-fail

Auto-picking the first model from /v1/models on a shared Ollama endpoint
could silently grab an embedding model or a model loaded by another app.
Now raises RuntimeError with actionable guidance when no model is configured."
```

---

### Task 2: Stop resetting model to "default" on provider switch

**Files:**
- Modify: `dashboard/backend/services/tailoring.py:2821-2843` (llm_activate_provider)
- Modify: `dashboard/backend/services/tailoring.py:2763-2774` (llm_unload_model)
- Modify: `dashboard/backend/app.py:505` (_save_runtime_controls — change fallback from "default" to "")

- [ ] **Step 1: Change `llm_activate_provider` to preserve model selection**

In `dashboard/backend/services/tailoring.py`, replace line 2840:
```python
    # Reset model selection when switching providers.
    updates["llm_model"] = "default"
```
with:
```python
    # Preserve model selection — user can change it separately.
    # Only clear if explicitly requested via payload.
    if "model" in payload:
        updates["llm_model"] = str(payload["model"]).strip() or ""
```

- [ ] **Step 2: Change `llm_unload_model` to clear to empty string, not "default"**

In `dashboard/backend/services/tailoring.py`, replace line 2773:
```python
        _save_runtime_controls({"llm_model": "default"})
```
with:
```python
        _save_runtime_controls({"llm_model": ""})
```

- [ ] **Step 3: Update `_save_runtime_controls` to allow empty model (no fallback to "default")**

In `dashboard/backend/app.py`, replace line 505:
```python
        controls["llm_model"] = str(updates["llm_model"] or "default").strip() or "default"
```
with:
```python
        controls["llm_model"] = str(updates["llm_model"] or "").strip()
```

- [ ] **Step 4: Update `_resolve_llm_runtime` to pass through empty model**

In `dashboard/backend/app.py`, replace line 572:
```python
    selected_model = str(controls.get("llm_model") or "default").strip() or "default"
```
with:
```python
    selected_model = str(controls.get("llm_model") or "").strip()
```

- [ ] **Step 5: Update `_DEFAULT_RUNTIME_CONTROLS` to default to empty string**

In `dashboard/backend/app.py`, replace lines 330-333:
```python
    "llm_model": os.environ.get(
        "TAILOR_LLM_MODEL",
        os.environ.get("TAILOR_OLLAMA_MODEL", "default"),
    ),
```
with:
```python
    "llm_model": os.environ.get(
        "TAILOR_LLM_MODEL",
        os.environ.get("TAILOR_OLLAMA_MODEL", ""),
    ),
```

- [ ] **Step 6: Update `llm_models` display logic — stop treating idx==0 as selected**

In `dashboard/backend/services/tailoring.py`, replace line 2728:
```python
                is_selected = model_name == selected or (selected == "default" and idx == 0)
```
with:
```python
                is_selected = model_name == selected
```

And replace line 2741:
```python
                is_selected = model_id == selected or (selected == "default" and idx == 0)
```
with:
```python
                is_selected = model_id == selected
```

- [ ] **Step 7: Run backend tests**

Run: `cd /Users/conner/Documents/JobForge && source venv/bin/activate && python -m pytest dashboard/backend/tests/ -v`
Expected: All PASS.

- [ ] **Step 8: Commit**

```bash
git add dashboard/backend/app.py dashboard/backend/services/tailoring.py
git commit -m "fix: stop resetting model on provider switch, remove auto-pick fallback

Provider activation no longer resets llm_model to 'default'. Model
deselection clears to empty string. The llm_models endpoint no longer
treats the first model as implicitly selected. Combined with the
ollama.py change, this prevents silent model drift on shared endpoints."
```

---

### Task 3: Gate MLX lifecycle management behind opt-in flag

**Files:**
- Modify: `dashboard/backend/services/tailoring.py:2887-2919` (mlx_start, mlx_stop, mlx_pull)
- Modify: `dashboard/backend/app.py:342-344` (recover_on_startup)
- Modify: `dashboard/backend/routers/tailoring.py:52-56` (MLX route registration)

- [ ] **Step 1: Add gate check to MLX mutation endpoints**

In `dashboard/backend/services/tailoring.py`, add a helper above the MLX section (before `mlx_status`):

```python
def _mlx_management_enabled() -> bool:
    """Check if MLX lifecycle management is enabled (opt-in)."""
    return os.environ.get("JOBFORGE_MANAGE_MLX", "").strip() in ("1", "true", "yes")
```

- [ ] **Step 2: Gate `mlx_start`**

Replace `mlx_start`:
```python
def mlx_start(payload: dict = Body(...)):
    """Start MLX server with a model. Requires JOBFORGE_MANAGE_MLX=1."""
    if not _mlx_management_enabled():
        return JSONResponse(
            {"ok": False, "error": "MLX lifecycle management is disabled. Set JOBFORGE_MANAGE_MLX=1 to enable."},
            403,
        )
    from services.mlx_manager import start
    model = payload.get("model")
    if not model:
        return JSONResponse({"ok": False, "error": "model required"}, 400)
    port = int(payload.get("port", 8080))
    return start(model, port)
```

- [ ] **Step 3: Gate `mlx_stop`**

Replace `mlx_stop`:
```python
def mlx_stop():
    """Stop the running MLX server. Requires JOBFORGE_MANAGE_MLX=1."""
    if not _mlx_management_enabled():
        return JSONResponse(
            {"ok": False, "error": "MLX lifecycle management is disabled. Set JOBFORGE_MANAGE_MLX=1 to enable."},
            403,
        )
    from services.mlx_manager import stop
    return stop()
```

- [ ] **Step 4: Gate `mlx_pull`**

Replace `mlx_pull`:
```python
def mlx_pull(payload: dict = Body(...)):
    """Start downloading a model from HuggingFace. Requires JOBFORGE_MANAGE_MLX=1."""
    if not _mlx_management_enabled():
        return JSONResponse(
            {"ok": False, "error": "MLX lifecycle management is disabled. Set JOBFORGE_MANAGE_MLX=1 to enable."},
            403,
        )
    from services.mlx_manager import pull
    model_id = payload.get("model_id")
    if not model_id:
        return JSONResponse({"ok": False, "error": "model_id required"}, 400)
    return pull(model_id)
```

- [ ] **Step 5: Gate startup recovery**

In `dashboard/backend/app.py`, replace lines 342-344:
```python
# Recover MLX server state if one is already running on the default port.
from services.mlx_manager import recover_on_startup
recover_on_startup()
```
with:
```python
# Recover MLX server state if one is already running on the default port.
if os.environ.get("JOBFORGE_MANAGE_MLX", "").strip() in ("1", "true", "yes"):
    from services.mlx_manager import recover_on_startup
    recover_on_startup()
```

- [ ] **Step 6: Run MLX tests**

Run: `cd /Users/conner/Documents/JobForge && source venv/bin/activate && python -m pytest dashboard/backend/tests/test_mlx_endpoints.py -v`
Expected: `test_start_stop_lifecycle` now gets 403 (test needs update). Update the test to set env var.

- [ ] **Step 7: Update MLX endpoint tests to set the env var**

In `dashboard/backend/tests/test_mlx_endpoints.py`, add to the class:
```python
@classmethod
def setUpClass(cls):
    os.environ["JOBFORGE_MANAGE_MLX"] = "1"

@classmethod
def tearDownClass(cls):
    os.environ.pop("JOBFORGE_MANAGE_MLX", None)
```

And add a test for the gate:
```python
def test_start_blocked_without_flag(self):
    os.environ.pop("JOBFORGE_MANAGE_MLX", None)
    client = self._get_client()
    resp = client.post("/api/llm/mlx/start", json={"model": "test"})
    self.assertEqual(resp.status_code, 403)
    os.environ["JOBFORGE_MANAGE_MLX"] = "1"
```

- [ ] **Step 8: Run all MLX tests again**

Run: `cd /Users/conner/Documents/JobForge && source venv/bin/activate && python -m pytest dashboard/backend/tests/test_mlx_endpoints.py dashboard/backend/tests/test_mlx_manager.py -v`
Expected: All PASS.

- [ ] **Step 9: Commit**

```bash
git add dashboard/backend/services/tailoring.py dashboard/backend/app.py dashboard/backend/tests/test_mlx_endpoints.py
git commit -m "feat: gate MLX lifecycle management behind JOBFORGE_MANAGE_MLX flag

MLX start/stop/pull endpoints now return 403 unless JOBFORGE_MANAGE_MLX=1
is set. Status and cached-models endpoints remain ungated (read-only).
Startup recovery is also gated. This prevents JobForge from controlling
a shared MLX server by default."
```

---

### Task 4: Rename load/unload to select/deselect in API and frontend

**Files:**
- Modify: `dashboard/backend/routers/tailoring.py:45-46`
- Modify: `dashboard/backend/services/tailoring.py:2753-2774`
- Modify: `dashboard/web/src/api.ts:238-244`
- Modify: `dashboard/web/src/views/domains/ops/LlmProvidersView.tsx:167-172`

- [ ] **Step 1: Add new route names, keep old as aliases**

In `dashboard/backend/routers/tailoring.py`, replace lines 45-46:
```python
    ("POST", "/api/llm/models/load", "llm_load_model"),
    ("POST", "/api/llm/models/unload", "llm_unload_model"),
```
with:
```python
    ("POST", "/api/llm/models/select", "llm_select_model"),
    ("POST", "/api/llm/models/deselect", "llm_deselect_model"),
    # Legacy aliases — keep for backward compat until frontend is updated
    ("POST", "/api/llm/models/load", "llm_select_model"),
    ("POST", "/api/llm/models/unload", "llm_deselect_model"),
```

- [ ] **Step 2: Rename handler functions in services/tailoring.py**

Rename `llm_load_model` to `llm_select_model` and `llm_unload_model` to `llm_deselect_model`:

Replace:
```python
def llm_load_model(payload: dict = Body(...)):
    _sync_app_state()
    """Select a model. Ollama loads on-demand — just persist the selection."""
```
with:
```python
def llm_select_model(payload: dict = Body(...)):
    _sync_app_state()
    """Select a model for this app. Ollama loads on-demand — just persist the selection."""
```

Replace:
```python
def llm_unload_model(payload: dict = Body(...)):
    _sync_app_state()
    """Clear model selection. Ollama auto-unloads after idle timeout."""
```
with:
```python
def llm_deselect_model(payload: dict = Body(...)):
    _sync_app_state()
    """Clear model selection for this app. Does NOT unload from the server."""
```

- [ ] **Step 3: Update frontend API client**

In `dashboard/web/src/api.ts`, replace:
```typescript
    loadLlmModel: async (identifier: string) => {
        const { data } = await apiClient.post('/llm/models/load', { identifier });
```
with:
```typescript
    selectLlmModel: async (identifier: string) => {
        const { data } = await apiClient.post('/llm/models/select', { identifier });
```

And replace:
```typescript
    unloadLlmModel: async (identifier: string) => {
        const { data } = await apiClient.post('/llm/models/unload', { identifier });
```
with:
```typescript
    deselectLlmModel: async (identifier: string) => {
        const { data } = await apiClient.post('/llm/models/deselect', { identifier });
```

- [ ] **Step 4: Update frontend view to use renamed API**

In `dashboard/web/src/views/domains/ops/LlmProvidersView.tsx`, replace:
```typescript
      await api.loadLlmModel(identifier);
```
with:
```typescript
      await api.selectLlmModel(identifier);
```

- [ ] **Step 5: Build frontend to verify**

Run: `cd /Users/conner/Documents/JobForge/dashboard/web && npm run build`
Expected: Build succeeds with no errors.

- [ ] **Step 6: Commit**

```bash
git add dashboard/backend/routers/tailoring.py dashboard/backend/services/tailoring.py \
  dashboard/web/src/api.ts dashboard/web/src/views/domains/ops/LlmProvidersView.tsx
git commit -m "refactor: rename load/unload model to select/deselect

Clarifies that these endpoints control JobForge's model preference, not
the server's model lifecycle. Old /load and /unload paths kept as aliases."
```

---

### Task 5: Update frontend to reflect MLX gate and empty model state

**Files:**
- Modify: `dashboard/web/src/views/domains/ops/LlmProvidersView.tsx`

- [ ] **Step 1: Handle empty/unset model display**

In `LlmProvidersView.tsx`, replace lines 223-227:
```typescript
  const activeModelLabel = activeProvider === 'mlx'
    ? (mlxStatus.model || 'none')
    : activeProvider === 'ollama'
      ? (ollamaSelectedModel !== 'default' ? ollamaSelectedModel : ollamaModels[0]?.id || 'none')
      : '';
```
with:
```typescript
  const activeModelLabel = activeProvider === 'mlx'
    ? (mlxStatus.model || 'none')
    : ollamaSelectedModel || 'not configured';
```

- [ ] **Step 2: Add "no model selected" option to Ollama dropdown**

Replace lines 303-312 (the Ollama select element):
```tsx
                  <select
                    value={ollamaSelectedModel}
                    onChange={e => handleOllamaModelSelect(e.target.value)}
                    style={selectStyle}
                  >
                    {ollamaModels.length === 0 && <option value="">No models available</option>}
                    {ollamaModels.map(m => (
                      <option key={m.id} value={m.id}>{m.id}</option>
                    ))}
                  </select>
```
with:
```tsx
                  <select
                    value={ollamaSelectedModel}
                    onChange={e => handleOllamaModelSelect(e.target.value)}
                    style={selectStyle}
                  >
                    <option value="">Select a model...</option>
                    {ollamaModels.map(m => (
                      <option key={m.id} value={m.id}>{m.id}</option>
                    ))}
                  </select>
```

- [ ] **Step 3: Show "management disabled" state for MLX when flag is off**

In the MLX action buttons section (around line 358), after the `{isMlx && mlxStatus.running && (` stop button block, add a disabled state indicator. Replace the `{isMlx && (` pull model section (lines 317-354) with a conditional:

```tsx
              {isMlx && !mlxSwitching && !mlxStatus.running && testResults[p.id]?.error?.includes('lifecycle management is disabled') && (
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.75rem', fontStyle: 'italic' }}>
                  MLX management disabled. Set JOBFORGE_MANAGE_MLX=1 to enable start/stop/pull.
                </div>
              )}
```

Add this block just before the existing `{isMlx && (` pull model section (do not replace the pull section — add above it).

- [ ] **Step 4: Build frontend**

Run: `cd /Users/conner/Documents/JobForge/dashboard/web && npm run build`
Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
git add dashboard/web/src/views/domains/ops/LlmProvidersView.tsx
git commit -m "fix: update LLM view for empty model state and MLX gate feedback

Shows 'not configured' when no model is selected instead of auto-picking
first model. Adds hint when MLX management is disabled."
```

---

### Task 6: Update CLAUDE.md and runtime_controls docs

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add JOBFORGE_MANAGE_MLX to Environment section**

In `CLAUDE.md`, in the Environment section (after the Ports block), add:

```markdown
- `JOBFORGE_MANAGE_MLX=1` — opt-in to MLX server lifecycle management (start/stop/pull) from the dashboard. Without this, MLX endpoints are read-only.
```

- [ ] **Step 2: Update the "Important Backend Behavior" section**

Add a bullet:
```markdown
- LLM model selection is explicit — JobForge never auto-picks the first model from a shared endpoint. Tailoring will fail with a clear error if no model is configured.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document JOBFORGE_MANAGE_MLX flag and explicit model requirement"
```
