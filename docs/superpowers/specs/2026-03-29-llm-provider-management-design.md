# LLM Provider Management — Design Spec

## Problem

Switching from LM Studio to Ollama + MLX lost the single-pane control and transparency LM Studio provided. Currently: no live status, no server lifecycle management, no model switching from the UI. Users must SSH in and run CLI commands to manage MLX.

## Goal

The `/ops/llm` page becomes the control center for all LLM providers. For local providers (Ollama, MLX), it shows live status, manages server lifecycle, and handles model switching — all from the browser. Cloud providers keep their existing key/test/activate flow.

## Design

### Backend: `dashboard/backend/services/mlx_manager.py`

New module that manages the MLX server process:

- **start(model, port=8080)** — launches `/Users/conner/mlx-env/bin/mlx_lm.server --model <model> --port <port>` as a subprocess. Tracks PID. If already running, stops first then starts (seamless model switch).
- **stop()** — kills the running process.
- **status()** — returns `{running, pid, model, port}`. Verifies process is actually alive (not just PID stale).
- **cached_models()** — scans `~/.cache/huggingface/hub/models--mlx-community--*` directories, returns list of model IDs available to serve immediately.
- **pull(model_id)** — runs `mlx_lm.download --model <model_id>` as a background subprocess. Streams stdout for progress.
- **pull_status()** — returns `{pulling, model_id, output_tail}` for the active download.

State is in-memory (PID tracking + subprocess reference). No persistence needed — if the backend restarts, the MLX process either still exists (re-discover by PID file or port check) or it doesn't.

### New API Endpoints

```
GET  /api/llm/mlx/status          → {running, pid, model, port}
POST /api/llm/mlx/start           → {model: "mlx-community/Qwen2.5-Coder-32B-Instruct-4bit"}
POST /api/llm/mlx/stop
GET  /api/llm/mlx/models          → [{id, size_gb}]
POST /api/llm/mlx/pull            → {model_id: "mlx-community/..."}
GET  /api/llm/mlx/pull/status     → {pulling, model_id, progress}
```

### Existing Endpoint Changes

- `llm_activate_provider` — when activating MLX, auto-set `llm_base_url` to `http://localhost:8080` (the MLX default port). Same for Ollama → `http://localhost:11434`.
- `llm_models` — for MLX provider, hit `/v1/models` on the MLX server (same as cloud providers) instead of Ollama's `/api/tags`.

### Frontend: Reworked LlmProvidersView

The page has two sections:

**1. Local Providers (Ollama, MLX)** — expanded cards with:
- Live status dot (green/red), polled every 5 seconds
- Currently loaded model name
- Model dropdown (Ollama: from `/api/tags`; MLX: from cached models endpoint)
  - Selecting a model starts/restarts the server automatically for MLX
  - For Ollama, uses existing load/unload API
- "Activate" button — sets this as the provider for tailoring runs
- Pull model input — text field for model name/HF repo ID + "Pull" button
  - Shows download progress inline when pulling
- MLX only: explicit Start/Stop button (Ollama manages its own lifecycle)

**2. Cloud Providers** — unchanged cards with key input, test, activate.

**Active provider banner** stays at the top, showing which provider + model the tailoring pipeline will use.

### What "Activate" Means

"Activate" = "use this for the next tailoring run." Both Ollama and MLX can be *running* simultaneously. Only one is *active* for the pipeline. This separation is the foundation for future per-task routing.

### Edge Cases

- MLX process dies unexpectedly: status polling detects it, UI shows red dot. No auto-restart.
- Switch model while tailoring is running: block with error ("tailoring run in progress").
- Pull a model that's already cached: no-op, return success.
- Backend restart: check if port 8080 is occupied on startup, recover MLX state if found.

### Not In Scope

- Per-task provider routing (future work)
- GPU memory monitoring (nice to have, not blocking)
- Multiple simultaneous MLX servers on different ports
