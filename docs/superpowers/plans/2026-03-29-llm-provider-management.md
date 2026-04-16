# LLM Provider Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the `/ops/llm` page full control and transparency over local LLM providers (Ollama + MLX), replacing the CLI-only workflow with a browser-based control center.

**Architecture:** New `mlx_manager.py` service handles MLX subprocess lifecycle. Six new API endpoints expose MLX control. Existing `llm_activate_provider` gets smarter URL handling. Frontend reworked into local-provider cards (live status, model picker, start/stop, pull) and cloud-provider cards (unchanged).

**Tech Stack:** Python (subprocess, pathlib), FastAPI, React + TypeScript

**Spec:** `docs/superpowers/specs/2026-03-29-llm-provider-management-design.md`

---

### Task 1: MLX Manager — Core Process Lifecycle

**Files:**
- Create: `dashboard/backend/services/mlx_manager.py`
- Create: `dashboard/backend/tests/test_mlx_manager.py`

- [ ] **Step 1: Write failing tests for status, start, stop**

```python
# dashboard/backend/tests/test_mlx_manager.py
"""Tests for MLX server process management."""
import unittest
from unittest.mock import patch, MagicMock
from services.mlx_manager import status, start, stop, cached_models

class TestMLXStatus(unittest.TestCase):
    def test_status_when_not_running(self):
        result = status()
        self.assertFalse(result["running"])
        self.assertIsNone(result["pid"])
        self.assertIsNone(result["model"])

class TestMLXStartStop(unittest.TestCase):
    @patch("services.mlx_manager.subprocess.Popen")
    def test_start_launches_server(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc
        result = start("mlx-community/Qwen2.5-Coder-32B-Instruct-4bit")
        self.assertTrue(result["ok"])
        self.assertEqual(result["pid"], 12345)
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        self.assertIn("mlx_lm.server", cmd[0])
        self.assertIn("--model", cmd)

    @patch("services.mlx_manager.subprocess.Popen")
    def test_stop_kills_process(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc
        start("mlx-community/Qwen2.5-Coder-32B-Instruct-4bit")
        result = stop()
        self.assertTrue(result["ok"])
        mock_proc.terminate.assert_called_once()

    @patch("services.mlx_manager.subprocess.Popen")
    def test_start_while_running_restarts(self, mock_popen):
        mock_proc1 = MagicMock()
        mock_proc1.pid = 111
        mock_proc1.poll.return_value = None
        mock_proc2 = MagicMock()
        mock_proc2.pid = 222
        mock_proc2.poll.return_value = None
        mock_popen.side_effect = [mock_proc1, mock_proc2]
        start("mlx-community/model-a")
        start("mlx-community/model-b")
        mock_proc1.terminate.assert_called_once()
        self.assertEqual(status()["pid"], 222)

class TestCachedModels(unittest.TestCase):
    @patch("services.mlx_manager.HF_CACHE_DIR")
    def test_cached_models_scans_directory(self, mock_cache):
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            mock_cache.__truediv__ = lambda s, x: type(mock_cache)(td)
            # Create fake model dirs
            os.makedirs(os.path.join(td, "models--mlx-community--Qwen2.5-Coder-32B-Instruct-4bit", "snapshots", "abc123"))
            os.makedirs(os.path.join(td, "models--mlx-community--Llama-3.1-8B-Instruct-4bit", "snapshots", "def456"))
            mock_cache.glob = lambda pattern: [
                type(mock_cache)(os.path.join(td, d))
                for d in os.listdir(td) if d.startswith("models--mlx-community--")
            ]
            result = cached_models()
            ids = [m["id"] for m in result]
            self.assertIn("mlx-community/Qwen2.5-Coder-32B-Instruct-4bit", ids)
            self.assertIn("mlx-community/Llama-3.1-8B-Instruct-4bit", ids)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/conner/Documents/JobForge && source venv/bin/activate && python -m pytest dashboard/backend/tests/test_mlx_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.mlx_manager'`

- [ ] **Step 3: Implement mlx_manager.py**

```python
# dashboard/backend/services/mlx_manager.py
"""MLX server process lifecycle management."""
from __future__ import annotations

import logging
import os
import subprocess
import signal
from pathlib import Path

logger = logging.getLogger(__name__)

MLX_LM_SERVER = "/Users/conner/mlx-env/bin/mlx_lm.server"
MLX_LM_DOWNLOAD = "/Users/conner/mlx-env/bin/mlx_lm.download"
HF_CACHE_DIR = Path.home() / ".cache" / "huggingface" / "hub"
DEFAULT_PORT = 8080

# In-memory state
_proc: subprocess.Popen | None = None
_model: str | None = None
_port: int = DEFAULT_PORT

# Pull state
_pull_proc: subprocess.Popen | None = None
_pull_model: str | None = None
_pull_log: list[str] = []


def status() -> dict:
    """Return current MLX server state."""
    global _proc, _model, _port
    if _proc is not None:
        rc = _proc.poll()
        if rc is not None:
            logger.info("MLX server process %d exited with code %d", _proc.pid, rc)
            _proc = None
    running = _proc is not None
    return {
        "running": running,
        "pid": _proc.pid if running else None,
        "model": _model if running else None,
        "port": _port if running else None,
    }


def start(model: str, port: int = DEFAULT_PORT) -> dict:
    """Start MLX server with the given model. Stops existing server first if running."""
    global _proc, _model, _port
    if _proc is not None and _proc.poll() is None:
        stop()
    _port = port
    _model = model
    cmd = [MLX_LM_SERVER, "--model", model, "--port", str(port)]
    logger.info("Starting MLX server: %s", " ".join(cmd))
    _proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return {"ok": True, "pid": _proc.pid, "model": model, "port": port}


def stop() -> dict:
    """Stop the running MLX server."""
    global _proc, _model
    if _proc is None or _proc.poll() is not None:
        _proc = None
        _model = None
        return {"ok": True, "was_running": False}
    pid = _proc.pid
    logger.info("Stopping MLX server (PID %d)", pid)
    _proc.terminate()
    try:
        _proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _proc.kill()
        _proc.wait(timeout=5)
    _proc = None
    _model = None
    return {"ok": True, "was_running": True, "pid": pid}


def cached_models() -> list[dict]:
    """Scan HuggingFace cache for downloaded MLX models."""
    models = []
    for d in sorted(HF_CACHE_DIR.glob("models--mlx-community--*")):
        name = d.name  # e.g. models--mlx-community--Qwen2.5-Coder-32B-Instruct-4bit
        # Convert dir name to HF model ID
        parts = name.split("--", 1)
        if len(parts) < 2:
            continue
        model_id = parts[1].replace("--", "/", 1)  # mlx-community/Qwen2.5-...
        # Estimate size from snapshots directory
        size_bytes = 0
        snapshots = d / "snapshots"
        if snapshots.exists():
            for root, _dirs, files in os.walk(snapshots):
                for f in files:
                    fp = Path(root) / f
                    if fp.is_file() and not fp.is_symlink():
                        size_bytes += fp.stat().st_size
                    elif fp.is_symlink():
                        target = fp.resolve()
                        if target.exists():
                            size_bytes += target.stat().st_size
        size_gb = round(size_bytes / (1024 ** 3), 1)
        models.append({"id": model_id, "size_gb": size_gb})
    return models


def pull(model_id: str) -> dict:
    """Start downloading a model from HuggingFace in the background."""
    global _pull_proc, _pull_model, _pull_log
    if _pull_proc is not None and _pull_proc.poll() is None:
        return {"ok": False, "error": f"Already pulling {_pull_model}"}
    _pull_model = model_id
    _pull_log = []
    cmd = [MLX_LM_DOWNLOAD, "--model", model_id]
    logger.info("Pulling MLX model: %s", model_id)
    _pull_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return {"ok": True, "model_id": model_id}


def pull_status() -> dict:
    """Return current pull progress."""
    global _pull_proc, _pull_model, _pull_log
    if _pull_proc is None:
        return {"pulling": False, "model_id": None, "progress": []}
    # Drain available output
    if _pull_proc.stdout:
        import select
        while True:
            ready, _, _ = select.select([_pull_proc.stdout], [], [], 0)
            if not ready:
                break
            line = _pull_proc.stdout.readline()
            if not line:
                break
            _pull_log.append(line.rstrip())
            if len(_pull_log) > 50:
                _pull_log = _pull_log[-50:]
    done = _pull_proc.poll() is not None
    result = {
        "pulling": not done,
        "model_id": _pull_model,
        "progress": _pull_log[-20:],
        "exit_code": _pull_proc.returncode if done else None,
    }
    if done:
        _pull_proc = None
    return result


def recover_on_startup():
    """Check if an MLX server is already running on the default port."""
    global _proc, _model, _port
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        sock.connect(("localhost", DEFAULT_PORT))
        sock.close()
        # Port is occupied — try to identify the model via /v1/models
        import urllib.request, json
        try:
            with urllib.request.urlopen(f"http://localhost:{DEFAULT_PORT}/v1/models", timeout=2) as resp:
                data = json.loads(resp.read())
            models = data.get("data", [])
            if models:
                _model = models[0].get("id", "unknown")
                _port = DEFAULT_PORT
                logger.info("Recovered MLX server on port %d, model: %s", DEFAULT_PORT, _model)
        except Exception:
            _model = "unknown"
            _port = DEFAULT_PORT
            logger.info("Recovered MLX server on port %d, model unknown", DEFAULT_PORT)
    except (ConnectionRefusedError, OSError, socket.timeout):
        pass
    finally:
        sock.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/conner/Documents/JobForge && source venv/bin/activate && PYTHONPATH=dashboard/backend python -m pytest dashboard/backend/tests/test_mlx_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/backend/services/mlx_manager.py dashboard/backend/tests/test_mlx_manager.py
git commit -m "feat: add MLX server process manager"
```

---

### Task 2: API Endpoints for MLX Management

**Files:**
- Modify: `dashboard/backend/routers/tailoring.py` (add 6 routes)
- Modify: `dashboard/backend/services/tailoring.py` (add 6 handler functions)

- [ ] **Step 1: Add routes to tailoring router**

Add these lines to the `ROUTES` list in `dashboard/backend/routers/tailoring.py` after the existing `llm/providers/test` entry:

```python
    ("GET", "/api/llm/mlx/status", "mlx_status"),
    ("POST", "/api/llm/mlx/start", "mlx_start"),
    ("POST", "/api/llm/mlx/stop", "mlx_stop"),
    ("GET", "/api/llm/mlx/models", "mlx_models"),
    ("POST", "/api/llm/mlx/pull", "mlx_pull"),
    ("GET", "/api/llm/mlx/pull/status", "mlx_pull_status"),
```

- [ ] **Step 2: Add handler functions to services/tailoring.py**

Add before the catch-all route comment at the end of the file (before line 2823):

```python
# ---------------------------------------------------------------------------
# Routes — API: MLX Server Management
# ---------------------------------------------------------------------------

def mlx_status():
    """Return MLX server status."""
    from services.mlx_manager import status
    return status()


def mlx_start(payload: dict = Body(...)):
    """Start MLX server with a model. Restarts if already running."""
    from services.mlx_manager import start
    model = payload.get("model")
    if not model:
        return JSONResponse({"ok": False, "error": "model required"}, 400)
    port = int(payload.get("port", 8080))
    return start(model, port)


def mlx_stop():
    """Stop the running MLX server."""
    from services.mlx_manager import stop
    return stop()


def mlx_models():
    """List cached MLX models available to serve."""
    from services.mlx_manager import cached_models
    return {"models": cached_models()}


def mlx_pull(payload: dict = Body(...)):
    """Start downloading a model from HuggingFace."""
    from services.mlx_manager import pull
    model_id = payload.get("model_id")
    if not model_id:
        return JSONResponse({"ok": False, "error": "model_id required"}, 400)
    return pull(model_id)


def mlx_pull_status():
    """Return current model download progress."""
    from services.mlx_manager import pull_status
    return pull_status()
```

- [ ] **Step 3: Fix activate_provider to auto-set base_url for local providers**

In `llm_activate_provider` in `services/tailoring.py` (around line 2778), replace:

```python
    if provider not in ("ollama", "mlx", "custom"):
        updates["llm_base_url"] = PROVIDERS[provider]["base_url"]
    elif provider == "custom":
```

with:

```python
    if provider == "ollama":
        updates["llm_base_url"] = PROVIDERS["ollama"]["base_url"]
    elif provider == "mlx":
        updates["llm_base_url"] = PROVIDERS["mlx"]["base_url"]
    elif provider == "custom":
```

- [ ] **Step 4: Add startup recovery call**

In `dashboard/backend/app.py`, find where the app initializes (after the FastAPI app is created) and add:

```python
from services.mlx_manager import recover_on_startup
recover_on_startup()
```

- [ ] **Step 5: Test endpoints manually**

Run: `source venv/bin/activate && python dashboard/backend/server.py`
Then:
```bash
curl -s http://localhost:8899/api/llm/mlx/status | python3 -m json.tool
curl -s http://localhost:8899/api/llm/mlx/models | python3 -m json.tool
```
Expected: status returns `{running: false, ...}`, models returns your 6 cached models.

- [ ] **Step 6: Commit**

```bash
git add dashboard/backend/routers/tailoring.py dashboard/backend/services/tailoring.py dashboard/backend/app.py
git commit -m "feat: add MLX management API endpoints"
```

---

### Task 3: Frontend API Client Methods

**Files:**
- Modify: `dashboard/web/src/api.ts`

- [ ] **Step 1: Add MLX API methods**

Add after the existing `testLlmProvider` method:

```typescript
    // MLX management
    getMlxStatus: async () => {
        const { data } = await apiClient.get('/llm/mlx/status');
        return data;
    },
    startMlx: async (model: string, port = 8080) => {
        const { data } = await apiClient.post('/llm/mlx/start', { model, port });
        return data;
    },
    stopMlx: async () => {
        const { data } = await apiClient.post('/llm/mlx/stop');
        return data;
    },
    getMlxModels: async () => {
        const { data } = await apiClient.get('/llm/mlx/models');
        return data;
    },
    pullMlxModel: async (model_id: string) => {
        const { data } = await apiClient.post('/llm/mlx/pull', { model_id });
        return data;
    },
    getMlxPullStatus: async () => {
        const { data } = await apiClient.get('/llm/mlx/pull/status');
        return data;
    },
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/web/src/api.ts
git commit -m "feat: add MLX management API methods to frontend client"
```

---

### Task 4: Reworked LlmProvidersView — Local Provider Cards

**Files:**
- Modify: `dashboard/web/src/views/domains/ops/LlmProvidersView.tsx`

- [ ] **Step 1: Rewrite the providers view**

Replace the entire content of `LlmProvidersView.tsx` with a view that has two sections: local providers and cloud providers. The local provider cards (Ollama, MLX) get:

- Live status indicator (green dot = running, red dot = offline), polled every 5 seconds
- Currently loaded model name displayed prominently
- Model dropdown: for MLX, populated from `getMlxModels()` (cached HF models); for Ollama, from `getLlmModels()`
- Selecting a model from the MLX dropdown calls `startMlx(model)` which auto-restarts the server
- For Ollama, selecting a model calls `loadLlmModel(identifier)`
- "Activate" button — calls `activateLlmProvider`, sets this as the pipeline provider
- Start/Stop toggle button for MLX (calls `startMlx`/`stopMlx`)
- Pull model section: text input for HF model ID + "Pull" button that calls `pullMlxModel`
  - When a pull is active, show progress lines from `getMlxPullStatus()` polled every 2 seconds
  - For Ollama, this input calls the existing pull mechanism if one exists, or is omitted

Cloud provider cards stay exactly as they are now: key input, test connection, activate.

Active provider banner at the top stays, showing `{provider label} — {model name}`.

Key implementation details:

```typescript
// Status polling — 5 second interval for local providers
useEffect(() => {
    const interval = setInterval(async () => {
        const mlxSt = await api.getMlxStatus();
        setMlxStatus(mlxSt);
        // Ollama status via existing getLlmStatus
        const ollamaSt = await api.getLlmStatus();
        setOllamaStatus(ollamaSt);
    }, 5000);
    return () => clearInterval(interval);
}, []);

// MLX model switch — seamless restart behind the scenes
const handleMlxModelSelect = async (model: string) => {
    setMlxSwitching(true);
    await api.startMlx(model);
    // Poll until server is up
    const poll = setInterval(async () => {
        const st = await api.getMlxStatus();
        if (st.running) {
            setMlxStatus(st);
            setMlxSwitching(false);
            clearInterval(poll);
        }
    }, 1000);
    // Timeout after 30s
    setTimeout(() => { clearInterval(poll); setMlxSwitching(false); }, 30000);
};

// Pull progress polling
useEffect(() => {
    if (!pulling) return;
    const interval = setInterval(async () => {
        const st = await api.getMlxPullStatus();
        setPullProgress(st.progress);
        if (!st.pulling) {
            setPulling(false);
            // Refresh cached models list
            const models = await api.getMlxModels();
            setMlxCachedModels(models.models);
        }
    }, 2000);
    return () => clearInterval(interval);
}, [pulling]);
```

For the visual layout, follow the existing card pattern in the current view but add the status dot and model controls. Local provider cards should be visually distinct (slightly larger) from cloud cards.

- [ ] **Step 2: Build and verify**

Run: `cd /Users/conner/Documents/JobForge/dashboard/web && npm run build`
Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 3: Manual test in browser**

Open `http://localhost:8899/ops/llm`. Verify:
- Ollama card shows green dot (if Ollama is running) with model name
- MLX card shows red dot (server not running) with cached models in dropdown
- Cloud provider cards unchanged
- "Activate" works for both local providers

- [ ] **Step 4: Commit**

```bash
git add dashboard/web/src/views/domains/ops/LlmProvidersView.tsx
git commit -m "feat: rework LLM providers page with local provider management"
```

---

### Task 5: Integration Test — Full MLX Lifecycle

**Files:**
- Create: `dashboard/backend/tests/test_mlx_endpoints.py`

- [ ] **Step 1: Write integration test**

```python
# dashboard/backend/tests/test_mlx_endpoints.py
"""Integration tests for MLX management endpoints."""
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


class TestMLXEndpoints(unittest.TestCase):
    def setUp(self):
        # Reset mlx_manager state between tests
        import services.mlx_manager as mgr
        mgr._proc = None
        mgr._model = None
        mgr._pull_proc = None

    def _get_client(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from app import app
        return TestClient(app)

    def test_status_returns_not_running(self):
        client = self._get_client()
        resp = client.get("/api/llm/mlx/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["running"])

    def test_cached_models_returns_list(self):
        client = self._get_client()
        resp = client.get("/api/llm/mlx/models")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("models", data)
        self.assertIsInstance(data["models"], list)

    @patch("services.mlx_manager.subprocess.Popen")
    def test_start_stop_lifecycle(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc
        client = self._get_client()

        # Start
        resp = client.post("/api/llm/mlx/start", json={"model": "mlx-community/test-model"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

        # Status should show running
        resp = client.get("/api/llm/mlx/status")
        self.assertTrue(resp.json()["running"])

        # Stop
        resp = client.post("/api/llm/mlx/stop")
        self.assertTrue(resp.json()["ok"])

    def test_start_without_model_returns_400(self):
        client = self._get_client()
        resp = client.post("/api/llm/mlx/start", json={})
        self.assertEqual(resp.status_code, 400)

    def test_pull_without_model_id_returns_400(self):
        client = self._get_client()
        resp = client.post("/api/llm/mlx/pull", json={})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/conner/Documents/JobForge && source venv/bin/activate && PYTHONPATH=dashboard/backend python -m pytest dashboard/backend/tests/test_mlx_endpoints.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add dashboard/backend/tests/test_mlx_endpoints.py
git commit -m "test: add MLX management endpoint integration tests"
```

---

### Task 6: Production Build + Smoke Test

- [ ] **Step 1: Production frontend build**

Run: `cd /Users/conner/Documents/JobForge/dashboard/web && npm run build`
Expected: Clean build, no errors.

- [ ] **Step 2: Restart backend and smoke test**

Run: `source venv/bin/activate && python dashboard/backend/server.py`

Then in browser:
1. Go to `/ops/llm`
2. Verify Ollama card shows live status
3. Verify MLX card shows cached models dropdown
4. Select a model from MLX dropdown — server should start (green dot appears)
5. Click "Activate" on MLX — banner updates
6. Switch model — seamless restart, green dot stays
7. Stop MLX — red dot appears
8. Switch back to Ollama — activate, verify tailoring can run

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete LLM provider management UI with MLX lifecycle control"
```
