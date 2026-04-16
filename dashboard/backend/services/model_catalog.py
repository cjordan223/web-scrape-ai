"""Model catalog service — merges Ollama metadata + machine telemetry into rich model cards."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Machine profile
# ---------------------------------------------------------------------------

_machine_cache: dict | None = None


def get_machine_profile() -> dict:
    """Return local machine specs (cached after first call)."""
    global _machine_cache
    if _machine_cache is not None:
        return dict(_machine_cache)

    profile: dict = {
        "chip": None,
        "cpu_cores": None,
        "gpu_cores": None,
        "memory_gb": None,
        "os_version": None,
    }
    try:
        r = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=3,
        )
        profile["chip"] = r.stdout.strip() or None
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["sysctl", "-n", "hw.ncpu"],
            capture_output=True, text=True, timeout=3,
        )
        profile["cpu_cores"] = int(r.stdout.strip())
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True, text=True, timeout=3,
        )
        profile["memory_gb"] = round(int(r.stdout.strip()) / (1024**3))
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            capture_output=True, text=True, timeout=5,
        )
        displays = json.loads(r.stdout)
        for item in displays.get("SPDisplaysDataType", []):
            cores = item.get("sppci_cores")
            if cores:
                try:
                    profile["gpu_cores"] = int(cores)
                except (TypeError, ValueError):
                    pass
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["sw_vers", "-productVersion"],
            capture_output=True, text=True, timeout=3,
        )
        profile["os_version"] = f"macOS {r.stdout.strip()}"
    except Exception:
        pass

    _machine_cache = profile
    return dict(profile)


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------


def _ollama_request(
    path: str,
    base_url: str = "http://localhost:11434",
    *,
    method: str = "GET",
    body: dict | None = None,
    timeout: int = 5,
) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method if not data else "POST")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Fit scoring
# ---------------------------------------------------------------------------


def _parse_param_count(param_size_str: str) -> float | None:
    """Parse '30.5B' -> 30.5, '7B' -> 7.0, '500M' -> 0.5"""
    if not param_size_str:
        return None
    s = param_size_str.strip().upper()
    if s.endswith("B"):
        try:
            return float(s[:-1])
        except ValueError:
            return None
    if s.endswith("M"):
        try:
            return float(s[:-1]) / 1000
        except ValueError:
            return None
    return None


def _compute_fit(size_bytes: int, memory_gb: int) -> dict:
    """Compute machine fit based on model weight size vs available unified memory."""
    if not memory_gb or not size_bytes:
        return {"rating": "unknown", "detail": "Insufficient data"}

    size_gb = size_bytes / (1024**3)
    ratio = size_gb / memory_gb

    if ratio < 0.3:
        return {
            "rating": "excellent",
            "detail": f"{size_gb:.1f} GB weights — plenty of headroom on {memory_gb} GB",
        }
    if ratio < 0.5:
        return {
            "rating": "good",
            "detail": f"{size_gb:.1f} GB weights — comfortable fit on {memory_gb} GB",
        }
    if ratio < 0.75:
        return {
            "rating": "caution",
            "detail": f"{size_gb:.1f} GB weights — may compete with other apps on {memory_gb} GB",
        }
    return {
        "rating": "heavy",
        "detail": f"{size_gb:.1f} GB weights — expect swap pressure on {memory_gb} GB",
    }


# ---------------------------------------------------------------------------
# Use-case inference
# ---------------------------------------------------------------------------


def _infer_use_case(name: str, capabilities: list[str]) -> str:
    low = name.lower()
    if any(kw in low for kw in ("coder", "codestral", "deepseek-coder", "starcoder", "qwen2.5-coder", "qwen3-coder")):
        return "coding"
    if any(kw in low for kw in ("embed", "nomic", "bge", "gte", "e5-")):
        return "embeddings"
    if "vision" in capabilities:
        return "vision + chat"
    if "thinking" in capabilities:
        return "reasoning"
    if "tools" in capabilities:
        return "agent / tool use"
    return "general chat"


# ---------------------------------------------------------------------------
# Catalog builder
# ---------------------------------------------------------------------------


def _ollama_models(base_url: str, memory_gb: int) -> list[dict]:
    """Fetch and enrich Ollama models."""
    try:
        tags_data = _ollama_request("/api/tags", base_url)
    except Exception:
        return []

    models = []
    for m in tags_data.get("models", []):
        model_name = m.get("name", m.get("model", "unknown"))
        size_bytes = m.get("size", 0)

        show_data: dict = {}
        model_info: dict = {}
        model_details: dict = m.get("details", {})
        capabilities: list[str] = []
        try:
            show_data = _ollama_request(
                "/api/show", base_url, body={"model": model_name}, timeout=10,
            )
            model_info = show_data.get("model_info", {})
            model_details = show_data.get("details", {}) or model_details
            capabilities = show_data.get("capabilities", [])
        except Exception:
            pass

        family = model_details.get("family", "")
        param_size = model_details.get("parameter_size", "")
        quantization = model_details.get("quantization_level", "")

        context_length = None
        for key, val in model_info.items():
            if "context_length" in key:
                context_length = val
                break

        param_count = _parse_param_count(param_size)
        fit = _compute_fit(size_bytes, memory_gb)
        use_case = _infer_use_case(model_name, capabilities)

        models.append({
            "id": model_name,
            "provider": "ollama",
            "family": family,
            "parameter_size": param_size,
            "parameter_count_b": param_count,
            "quantization": quantization,
            "context_length": context_length,
            "size_bytes": size_bytes,
            "capabilities": capabilities,
            "use_case": use_case,
            "fit": fit,
            "modified_at": m.get("modified_at"),
        })
    return models


# ---------------------------------------------------------------------------
# MLX model discovery (HuggingFace cache + config.json)
# ---------------------------------------------------------------------------

HF_CACHE_DIR = Path.home() / ".cache" / "huggingface" / "hub"


def _mlx_model_config(cache_dir: Path) -> dict | None:
    """Read config.json from a HuggingFace cache model directory."""
    # config.json is inside snapshots/<hash>/config.json
    snapshots = cache_dir / "snapshots"
    if not snapshots.exists():
        return None
    for snap in sorted(snapshots.iterdir(), reverse=True):
        cfg = snap / "config.json"
        if cfg.exists():
            try:
                return json.loads(cfg.read_text())
            except Exception:
                pass
    return None


def _mlx_disk_size(cache_dir: Path) -> int:
    """Compute total disk usage of a cached model directory (bytes)."""
    total = 0
    snapshots = cache_dir / "snapshots"
    if not snapshots.exists():
        return 0
    for snap in snapshots.iterdir():
        if not snap.is_dir():
            continue
        for f in snap.iterdir():
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    return total


def _estimate_params_from_name(name: str) -> tuple[str, float | None]:
    """Try to extract param count from model name like 'Qwen2.5-Coder-32B-Instruct-4bit'.

    Matches '<number>B' but NOT '<number>bit' or '<number>byte'.
    """
    import re
    m = re.search(r'(\d+(?:\.\d+)?)B(?!i)', name)
    if m:
        val = float(m.group(1))
        return f"{val}B" if val == int(val) else f"{val}B", val
    return "", None


def _mlx_models(memory_gb: int) -> list[dict]:
    """Discover MLX models from HuggingFace cache."""
    models = []
    if not HF_CACHE_DIR.exists():
        return models

    for d in sorted(HF_CACHE_DIR.glob("models--mlx-community--*")):
        parts = d.name.split("--", 1)
        if len(parts) < 2:
            continue
        model_id = parts[1].replace("--", "/", 1)

        config = _mlx_model_config(d)
        size_bytes = _mlx_disk_size(d)

        family = ""
        context_length = None
        quant_str = ""
        capabilities: list[str] = ["completion"]

        if config:
            family = config.get("model_type", "")
            context_length = config.get("max_position_embeddings")
            q = config.get("quantization", {})
            if isinstance(q, dict) and q.get("bits"):
                quant_str = f"Q{q['bits']}{'_' + q.get('mode', '') if q.get('mode') else ''}"

        # Infer param size from name
        param_size, param_count = _estimate_params_from_name(model_id)

        # Infer capabilities from name
        name_lower = model_id.lower()
        if "thinking" in name_lower:
            capabilities.append("thinking")
        if "coder" in name_lower or "code" in name_lower:
            capabilities.append("tools")

        fit = _compute_fit(size_bytes, memory_gb)
        use_case = _infer_use_case(model_id, capabilities)

        models.append({
            "id": model_id,
            "provider": "mlx",
            "family": family,
            "parameter_size": param_size,
            "parameter_count_b": param_count,
            "quantization": quant_str,
            "context_length": context_length,
            "size_bytes": size_bytes,
            "capabilities": capabilities,
            "use_case": use_case,
            "fit": fit,
            "modified_at": None,
        })

    return models


def get_catalog(base_url: str = "http://localhost:11434") -> dict:
    """Build full model catalog from Ollama + MLX + machine profile."""
    machine = get_machine_profile()
    memory_gb = machine.get("memory_gb") or 0

    ollama = _ollama_models(base_url, memory_gb)
    mlx = _mlx_models(memory_gb)

    models = ollama + mlx

    # Sort: excellent/good fit first, then by param count descending
    _fit_order = {"excellent": 0, "good": 1, "caution": 2, "heavy": 3, "unknown": 4}
    models.sort(key=lambda x: (
        _fit_order.get(x["fit"]["rating"], 4),
        -(x["parameter_count_b"] or 0),
    ))

    return {"machine": machine, "models": models}


# ---------------------------------------------------------------------------
# Micro-benchmark
# ---------------------------------------------------------------------------

# In-memory cache: model_id -> benchmark result
_benchmark_cache: dict[str, dict] = {}


def _benchmark_ollama(model_id: str, base_url: str) -> dict:
    """Benchmark via Ollama's native /api/generate (returns timing data)."""
    prompt = "Explain what a hash table is in exactly two sentences."
    t0 = time.monotonic()
    resp = _ollama_request(
        "/api/generate",
        base_url,
        body={
            "model": model_id,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 128},
        },
        timeout=120,
    )
    wall_time = time.monotonic() - t0

    load_ns = resp.get("load_duration", 0)
    prompt_eval_ns = resp.get("prompt_eval_duration", 0)
    eval_ns = resp.get("eval_duration", 0)
    eval_count = resp.get("eval_count", 0)
    prompt_eval_count = resp.get("prompt_eval_count", 0)

    tokens_per_sec = (eval_count / (eval_ns / 1e9)) if eval_ns > 0 else 0
    prompt_tokens_per_sec = (
        (prompt_eval_count / (prompt_eval_ns / 1e9)) if prompt_eval_ns > 0 else 0
    )
    time_to_first_token_ms = (load_ns + prompt_eval_ns) / 1e6

    return {
        "ok": True,
        "model": model_id,
        "provider": "ollama",
        "wall_time_s": round(wall_time, 2),
        "time_to_first_token_ms": round(time_to_first_token_ms, 1),
        "generation_tokens_per_sec": round(tokens_per_sec, 1),
        "prompt_eval_tokens_per_sec": round(prompt_tokens_per_sec, 1),
        "eval_tokens": eval_count,
        "prompt_tokens": prompt_eval_count,
        "response_preview": (resp.get("response", "") or "")[:200],
        "cached": False,
    }


def _benchmark_openai(model_id: str, base_url: str) -> dict:
    """Benchmark via OpenAI-compatible /v1/chat/completions (MLX, etc.)."""
    prompt = "Explain what a hash table is in exactly two sentences."
    body = json.dumps({
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 128,
    }).encode()

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=body,
        method="POST",
    )
    req.add_header("Content-Type", "application/json")

    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    wall_time = time.monotonic() - t0

    usage = data.get("usage", {})
    completion_tokens = usage.get("completion_tokens", 0)
    prompt_tokens = usage.get("prompt_tokens", 0)
    reply = ""
    choices = data.get("choices", [])
    if choices:
        reply = (choices[0].get("message") or {}).get("content", "")

    tokens_per_sec = (completion_tokens / wall_time) if wall_time > 0 else 0

    return {
        "ok": True,
        "model": model_id,
        "provider": "mlx",
        "wall_time_s": round(wall_time, 2),
        "time_to_first_token_ms": None,
        "generation_tokens_per_sec": round(tokens_per_sec, 1),
        "prompt_eval_tokens_per_sec": None,
        "eval_tokens": completion_tokens,
        "prompt_tokens": prompt_tokens,
        "response_preview": reply[:200],
        "cached": False,
    }


def run_benchmark(
    model_id: str,
    base_url: str = "http://localhost:11434",
    provider: str = "ollama",
) -> dict:
    """Run a micro-benchmark against an installed model."""
    if model_id in _benchmark_cache:
        return {**_benchmark_cache[model_id], "cached": True}

    try:
        if provider == "mlx":
            result = _benchmark_openai(model_id, "http://localhost:8080")
        else:
            result = _benchmark_ollama(model_id, base_url)
    except Exception as e:
        return {"ok": False, "error": str(e), "model": model_id}

    _benchmark_cache[model_id] = result
    return result
