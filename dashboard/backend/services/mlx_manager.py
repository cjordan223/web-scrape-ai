"""MLX server process lifecycle management."""
from __future__ import annotations

import json
import logging
import os
import select
import socket
import subprocess
import tempfile
import urllib.request
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


def _mlx_log_path() -> Path:
    override = os.environ.get("TEXTAILOR_MLX_LOG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "job_scraper" / "mlx_server.log"


def _open_mlx_log():
    path = _mlx_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return open(path, "a")
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "mlx_server.log"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return open(fallback, "a")


def _probe_server(port: int = DEFAULT_PORT) -> tuple[bool, str | None]:
    """Return whether an MLX-compatible server is responding and its first model ID."""
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/v1/models", timeout=2) as resp:
            data = json.loads(resp.read())
        models_list = data.get("data", [])
        model = models_list[0].get("id") if models_list else None
        return True, model
    except Exception:
        return False, None


def status() -> dict:
    """Return current MLX server state."""
    global _proc, _model, _port
    if _proc is not None:
        rc = _proc.poll()
        if rc is not None:
            logger.info("MLX server process %d exited with code %d", _proc.pid, rc)
            _proc = None
    running = _proc is not None
    pid = _proc.pid if running else None

    if not running:
        responding, discovered_model = _probe_server(_port)
        if responding:
            running = True
            if discovered_model:
                _model = discovered_model

    return {
        "running": running,
        "pid": pid,
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
    mlx_log = _open_mlx_log()
    _proc = subprocess.Popen(
        cmd,
        stdout=mlx_log,
        stderr=subprocess.STDOUT,
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
    """Scan HuggingFace cache for downloaded MLX models.

    Uses only directory listing (no os.walk) to avoid timeout on large caches.
    """
    models = []
    if not HF_CACHE_DIR.exists():
        return models
    for d in sorted(HF_CACHE_DIR.glob("models--mlx-community--*")):
        name = d.name
        parts = name.split("--", 1)
        if len(parts) < 2:
            continue
        model_id = parts[1].replace("--", "/", 1)
        models.append({"id": model_id})
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
    if _pull_proc.stdout:
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
    global _model, _port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        sock.connect(("localhost", DEFAULT_PORT))
        sock.close()
        responding, discovered_model = _probe_server(DEFAULT_PORT)
        if responding:
            _model = discovered_model or "unknown"
            _port = DEFAULT_PORT
            logger.info("Recovered MLX server on port %d, model: %s", DEFAULT_PORT, _model)
        else:
            _model = "unknown"
            _port = DEFAULT_PORT
            logger.info("Recovered MLX server on port %d, model unknown", DEFAULT_PORT)
    except (ConnectionRefusedError, OSError, socket.timeout):
        pass
    finally:
        sock.close()
