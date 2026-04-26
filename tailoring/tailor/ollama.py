"""Shared OpenAI-compatible LLM client with file-lock mutex."""

from __future__ import annotations

import fcntl
import json
import logging
import re
import time
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Callable, Mapping

import requests
from requests import HTTPError
from requests.exceptions import (
    ChunkedEncodingError,
    ConnectionError as RequestsConnectionError,
    ReadTimeout,
)

from . import config as cfg
from .tracing import utc_now_iso

logger = logging.getLogger(__name__)

# Transient connection-level failures we retry on. HTTP 4xx/5xx responses are
# NOT retried here because those indicate deterministic failures that should
# surface to the caller.
_TRANSIENT_LLM_ERRORS: tuple[type[Exception], ...] = (
    RequestsConnectionError,
    ChunkedEncodingError,
    ReadTimeout,
)
_LLM_REQUEST_MAX_ATTEMPTS = 3
_LLM_REQUEST_BACKOFF_BASE = 1.5


@contextmanager
def _ollama_lock():
    """Acquire an exclusive file lock. Blocks up to LOCK_TIMEOUT seconds."""
    with _file_lock(cfg.LOCK_PATH, cfg.LOCK_TIMEOUT):
        yield


@contextmanager
def _file_lock(lock_path: Path, timeout_seconds: int):
    """Acquire an exclusive file lock. Blocks up to timeout_seconds."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = open(lock_path, "w")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() > deadline:
                fd.close()
                raise TimeoutError(
                    f"Could not acquire LLM lock after {timeout_seconds}s — "
                    "another tailoring or package-chat LLM task may still be running."
                )
            time.sleep(2)
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


_MODEL_CACHE = None


def _auth_headers() -> dict[str, str]:
    """Build auth headers from config. Empty dict when no key is set."""
    if cfg.LLM_API_KEY:
        return {"Authorization": f"Bearer {cfg.LLM_API_KEY}"}
    return {}


def _rv(runtime: Mapping[str, Any] | None, key: str, fallback: Any, *, cast: type | None = None) -> Any:
    """Resolve a runtime override, falling back to a config default."""
    value = (runtime or {}).get(key)
    if value in (None, ""):
        return fallback
    if cast is not None:
        try:
            return cast(value)
        except (TypeError, ValueError):
            return fallback
    return value


def _runtime_provider(runtime: Mapping[str, Any] | None = None) -> str:
    return str(_rv(runtime, "provider", cfg.LLM_PROVIDER or "ollama")).strip().lower()


def _runtime_chat_url(runtime: Mapping[str, Any] | None = None) -> str:
    return str(_rv(runtime, "chat_url", cfg.OLLAMA_URL)).strip()


def _runtime_api_key(runtime: Mapping[str, Any] | None = None) -> str:
    return str(_rv(runtime, "api_key", cfg.LLM_API_KEY)).strip()


def _runtime_timeout(runtime: Mapping[str, Any] | None = None) -> int:
    return _rv(runtime, "timeout", cfg.OLLAMA_TIMEOUT, cast=int)


def _runtime_lock_timeout(runtime: Mapping[str, Any] | None = None) -> int:
    return _rv(runtime, "lock_timeout", cfg.LOCK_TIMEOUT, cast=int)


def _runtime_lock_path(runtime: Mapping[str, Any] | None = None) -> Path:
    value = (runtime or {}).get("lock_path")
    if not value:
        return cfg.LOCK_PATH
    return Path(value)


def _use_file_lock(runtime: Mapping[str, Any] | None = None) -> bool:
    """Only use file lock for local providers (single GPU)."""
    if runtime is not None and "use_lock" in runtime:
        return bool(runtime.get("use_lock"))
    return _runtime_provider(runtime) in ("ollama", "")


def _lock_context(runtime: Mapping[str, Any] | None = None):
    if runtime is None:
        return _ollama_lock() if _use_file_lock() else nullcontext()
    return (
        _file_lock(_runtime_lock_path(runtime), _runtime_lock_timeout(runtime))
        if _use_file_lock(runtime)
        else nullcontext()
    )


def _post_with_retry(
    endpoint: str,
    *,
    json_payload: dict[str, Any],
    headers: dict[str, str],
    connect_timeout: int,
    read_timeout: int,
) -> requests.Response:
    """POST to an LLM endpoint, retrying transient connection failures.

    Retries on ConnectionError/ChunkedEncodingError/ReadTimeout with exponential
    backoff. HTTP 4xx/5xx responses are NOT retried (the caller handles those).
    """
    last_exc: Exception | None = None
    for attempt in range(1, _LLM_REQUEST_MAX_ATTEMPTS + 1):
        try:
            return requests.post(
                endpoint,
                json=json_payload,
                headers=headers,
                timeout=(connect_timeout, read_timeout),
            )
        except _TRANSIENT_LLM_ERRORS as exc:
            last_exc = exc
            if attempt == _LLM_REQUEST_MAX_ATTEMPTS:
                break
            delay = _LLM_REQUEST_BACKOFF_BASE ** attempt
            logger.warning(
                "LLM request to %s failed (%s: %s); retry %d/%d in %.1fs",
                endpoint,
                type(exc).__name__,
                exc,
                attempt,
                _LLM_REQUEST_MAX_ATTEMPTS,
                delay,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


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


def chat(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    model: str | None = None,
    json_mode: bool = False,
    trace: dict[str, Any] | None = None,
    trace_recorder: Callable[[dict[str, Any]], None] | None = None,
    runtime: Mapping[str, Any] | None = None,
    thinking_multiplier: int = 4,
) -> str:
    """Send a chat completion to the LLM with lock protection. Returns raw content string."""
    model_id = model or get_loaded_model()
    effective_user_prompt = user_prompt
    call_id = str(uuid.uuid4())
    started_monotonic = time.monotonic()
    started_at = utc_now_iso()
    endpoint = _runtime_chat_url(runtime)
    timeout_seconds = _runtime_timeout(runtime)
    provider = _runtime_provider(runtime)

    if trace_recorder is not None:
        trace_recorder(
            {
                "event_type": "llm_call_start",
                "call_id": call_id,
                "started_at": started_at,
                "model": model_id,
                "endpoint": endpoint,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                **(trace or {}),
            }
        )

    lock = _lock_context(runtime)
    with lock:
        logger.info("LLM call starting (model=%s, max_tokens=%d)", model_id, max_tokens)
        try:
            is_ollama = provider in ("ollama", "")
            hdrs = {"Authorization": f"Bearer {_runtime_api_key(runtime)}"} if _runtime_api_key(runtime) else {}
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": effective_user_prompt},
            ]

            if is_ollama:
                # Use Ollama native /api/chat — the OpenAI-compat endpoint
                # silently drops thinking model content (Qwen 3 returns empty).
                base = endpoint.split("/v1/")[0].rstrip("/")
                endpoint = f"{base}/api/chat"
                # Qwen 3 thinking models generate chain-of-thought even with
                # think=false (it just leaks into content instead of a separate
                # field). The thinking consumes num_predict budget, so we
                # multiply by 4x to leave room for the actual response.
                # strip_think_tags() removes the thinking text after.
                thinking_headroom = max_tokens * thinking_multiplier
                payload: dict[str, Any] = {
                    "model": model_id,
                    "messages": messages,
                    "stream": False,
                    "think": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": thinking_headroom,
                    },
                }
                if json_mode:
                    payload["format"] = "json"
                resp = _post_with_retry(
                    endpoint,
                    json_payload=payload,
                    headers=hdrs,
                    connect_timeout=30,
                    read_timeout=timeout_seconds,
                )
            else:
                # OpenAI-compatible endpoint for cloud providers
                payload = {
                    "model": model_id,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                if json_mode:
                    payload["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "generic_object",
                            "schema": {
                                "type": "object",
                                "additionalProperties": True,
                            },
                        },
                    }
                resp = _post_with_retry(
                    endpoint,
                    json_payload=payload,
                    headers=hdrs,
                    connect_timeout=30,
                    read_timeout=timeout_seconds,
                )
                if json_mode and resp.status_code == 400:
                    payload.pop("response_format", None)
                    resp = _post_with_retry(
                        endpoint,
                        json_payload=payload,
                        headers=hdrs,
                        connect_timeout=30,
                        read_timeout=timeout_seconds,
                    )

            if resp.status_code >= 400:
                body = resp.text[:600].replace("\n", " ")
                raise HTTPError(
                    f"{resp.status_code} {resp.reason} from {endpoint}; body={body}",
                    response=resp,
                )

            if is_ollama:
                content = resp.json()["message"].get("content") or ""
                # Strip <think>...</think> blocks that leak into content
                # when think=false on Qwen 3 thinking models.
                content = strip_think_tags(content)
            else:
                content = resp.json()["choices"][0]["message"].get("content") or ""
            logger.info("LLM call complete (%d chars returned)", len(content))

            if trace_recorder is not None:
                ended_at = utc_now_iso()
                trace_recorder(
                    {
                        "event_type": "llm_call_success",
                        "call_id": call_id,
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "duration_ms": int((time.monotonic() - started_monotonic) * 1000),
                        "model": model_id,
                        "endpoint": endpoint,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "system_prompt": system_prompt,
                        "user_prompt": user_prompt,
                        "raw_response": content,
                        "response_chars": len(content),
                        "response_parse_kind": (trace or {}).get("response_parse_kind", "raw"),
                        "response_parse_status": (trace or {}).get("response_parse_status", "skipped"),
                        **(trace or {}),
                    }
                )
            return content
        except Exception as e:
            if trace_recorder is not None:
                ended_at = utc_now_iso()
                trace_recorder(
                    {
                        "event_type": "llm_call_error",
                        "call_id": call_id,
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "duration_ms": int((time.monotonic() - started_monotonic) * 1000),
                        "model": model_id,
                        "endpoint": endpoint,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "system_prompt": system_prompt,
                        "user_prompt": user_prompt,
                        "error": str(e),
                        "response_chars": 0,
                        "response_parse_kind": (trace or {}).get("response_parse_kind", "raw"),
                        "response_parse_status": "failed",
                        **(trace or {}),
                    }
                )
            raise


def strip_think_tags(text: str) -> str:
    """Remove Qwen3 <think>...</think> reasoning blocks.

    Handles three cases:
    - Paired tags: <think>...</think>
    - Orphan closing tag (Ollama think=false): everything before </think>
    - Orphan opening tag: <think> to end of text
    """
    # Paired tags first
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Orphan </think> — strip everything up to and including it
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    # Orphan <think> — strip from tag to end
    if "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


def _sanitize_json_text(text: str) -> str:
    """Normalize common model artifacts that break JSON parsing."""
    cleaned = strip_think_tags(text)
    # Remove OpenAI/chat-style control tokens that sometimes leak into content.
    cleaned = re.sub(r"<\|[^|>\n]{1,100}\|>", "", cleaned)
    # Remove trailing partial control tokens (e.g. "<|message|>..." cut mid-stream).
    cleaned = re.sub(r"<\|[^\n]*$", "", cleaned)
    # Unwrap fenced json blocks if present.
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _fix_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ] (common LLM JSON error)."""
    return re.sub(r",\s*([}\]])", r"\1", text)


def _append_missing_braces(candidate: str) -> str:
    """Best-effort fix for truncated objects by balancing braces outside strings."""
    depth = 0
    in_string = False
    escape = False
    for ch in candidate:
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    if depth > 0:
        return candidate + ("}" * depth)
    return candidate


def extract_json(text: str) -> dict:
    """Extract the first JSON object from model output with tolerant recovery."""
    text = _sanitize_json_text(text)
    if not text:
        raise ValueError("Empty response while expecting JSON")

    decoder = json.JSONDecoder()
    starts = [i for i, ch in enumerate(text) if ch == "{"]
    if not starts:
        raise ValueError(f"No JSON object found in response: {text[:200]}")

    first_error: Exception | None = None
    for start in starts:
        candidate = text[start:]
        try:
            obj, _ = decoder.raw_decode(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception as e:  # noqa: BLE001
            if first_error is None:
                first_error = e
            # Repair attempts in order of likelihood:
            for repaired in (
                _fix_trailing_commas(candidate),
                _append_missing_braces(candidate),
                _append_missing_braces(_fix_trailing_commas(candidate)),
            ):
                try:
                    obj = json.loads(repaired)
                    if isinstance(obj, dict):
                        return obj
                except Exception:  # noqa: BLE001
                    pass

    raise ValueError(
        f"Could not parse JSON object in response: {text[:200]}"
        + (f" ({first_error})" if first_error else "")
    )


def extract_latex(text: str) -> str:
    """Extract LaTeX content from LLM output. Looks for \\documentclass...\\end{document}."""
    text = strip_think_tags(text)
    # Try to find a complete LaTeX document
    m = re.search(r"(\\documentclass.*?\\end\{document\})", text, re.DOTALL)
    if m:
        return m.group(1)
    # Fallback: if wrapped in ```latex ... ```
    m = re.search(r"```(?:latex|tex)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    raise ValueError(f"No LaTeX document found in response (len={len(text)})")


def chat_expect_json(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    trace: dict[str, Any] | None = None,
    trace_recorder: Callable[[dict[str, Any]], None] | None = None,
    model: str | None = None,
    runtime: Mapping[str, Any] | None = None,
    thinking_multiplier: int = 4,
) -> dict[str, Any]:
    """Get JSON from chat with compatibility + repair fallback for weaker models."""
    raw = chat(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        model=model,
        json_mode=True,
        trace=trace,
        trace_recorder=trace_recorder,
        runtime=runtime,
        thinking_multiplier=thinking_multiplier,
    )
    try:
        return extract_json(raw)
    except Exception:
        regen_trace = dict(trace or {})
        regen_trace["phase"] = f"{regen_trace.get('phase', 'unknown')}_json_regen"
        regen_prompt = (
            "Return one complete, valid JSON object only. "
            "No prose, no markdown fences, no comments.\n\n"
            "Follow this target schema and constraints exactly:\n"
            f"{system_prompt[:3000]}\n\n"
            "Now solve the original task again and emit valid JSON.\n\n"
            f"{user_prompt[:12000]}"
        )
        regenerated = chat(
            system_prompt="You are a strict JSON generator.",
            user_prompt=regen_prompt,
            max_tokens=max_tokens,
            temperature=0.0,
            model=model,
            json_mode=True,
            trace=regen_trace,
            trace_recorder=trace_recorder,
            runtime=runtime,
        )
        return extract_json(regenerated)
