"""Model catalog service — merges Ollama metadata + machine telemetry into rich model cards."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request

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


def get_catalog(base_url: str = "http://localhost:11434") -> dict:
    """Build full model catalog from Ollama + machine profile."""
    machine = get_machine_profile()
    memory_gb = machine.get("memory_gb") or 0

    models = _ollama_models(base_url, memory_gb)

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


def run_benchmark(
    model_id: str,
    base_url: str = "http://localhost:11434",
    provider: str = "ollama",
) -> dict:
    """Run a micro-benchmark against an installed model."""
    if model_id in _benchmark_cache:
        return {**_benchmark_cache[model_id], "cached": True}

    try:
        result = _benchmark_ollama(model_id, base_url)
    except Exception as e:
        return {"ok": False, "error": str(e), "model": model_id}

    _benchmark_cache[model_id] = result
    return result
