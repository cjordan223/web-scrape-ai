"""Shared OpenAI-compatible LLM client with file-lock mutex."""

from __future__ import annotations

import fcntl
import json
import logging
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

import requests
from requests import HTTPError

from . import config as cfg
from .tracing import utc_now_iso

logger = logging.getLogger(__name__)


@contextmanager
def _ollama_lock():
    """Acquire an exclusive file lock. Blocks up to LOCK_TIMEOUT seconds."""
    cfg.LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = open(cfg.LOCK_PATH, "w")
    deadline = time.monotonic() + cfg.LOCK_TIMEOUT
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() > deadline:
                fd.close()
                raise TimeoutError(
                    f"Could not acquire LLM lock after {cfg.LOCK_TIMEOUT}s — "
                    "is the scraper's LLM review running?"
                )
            time.sleep(2)
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


_MODEL_CACHE = None

def get_loaded_model() -> str:
    """Resolve model: explicit override, else first model from /v1/models."""
    global _MODEL_CACHE
    if _MODEL_CACHE:
        return _MODEL_CACHE
    if cfg.OLLAMA_MODEL and cfg.OLLAMA_MODEL != "default":
        _MODEL_CACHE = cfg.OLLAMA_MODEL
        return _MODEL_CACHE
    try:
        resp = requests.get(cfg.OLLAMA_MODELS_URL, timeout=10)
        resp.raise_for_status()
        models = resp.json().get("data", [])
        if not models:
            return cfg.OLLAMA_MODEL
        # Pick first available model from the server when no explicit override is set.
        _MODEL_CACHE = models[0]["id"]
        return _MODEL_CACHE
    except Exception as e:
        logger.warning(f"Could not fetch models from {cfg.OLLAMA_MODELS_URL}: {e}")
        return cfg.OLLAMA_MODEL


def chat(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    json_mode: bool = False,
    trace: dict[str, Any] | None = None,
    trace_recorder: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    """Send a chat completion to the LLM with lock protection. Returns raw content string."""
    model_id = get_loaded_model()
    effective_user_prompt = user_prompt
    # Qwen reasoning-capable models often emit long chain-of-thought unless disabled.
    # Use /no_think control token so structured outputs remain parseable.
    if "qwen" in model_id.lower() and "/no_think" not in effective_user_prompt:
        effective_user_prompt = f"{effective_user_prompt}\n\n/no_think"
    call_id = str(uuid.uuid4())
    started_monotonic = time.monotonic()
    started_at = utc_now_iso()

    if trace_recorder is not None:
        trace_recorder(
            {
                "event_type": "llm_call_start",
                "call_id": call_id,
                "started_at": started_at,
                "model": model_id,
                "endpoint": cfg.OLLAMA_URL,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                **(trace or {}),
            }
        )

    with _ollama_lock():
        logger.info("LLM call starting (model=%s, max_tokens=%d)", model_id, max_tokens)
        try:
            payload: dict[str, Any] = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": effective_user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if json_mode:
                # LM Studio/OpenAI-compatible structured output mode.
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
            resp = requests.post(cfg.OLLAMA_URL, json=payload, timeout=cfg.OLLAMA_TIMEOUT)
            if json_mode and resp.status_code == 400:
                # Some OpenAI-compatible servers/models reject response_format.
                # Retry once without it so model experiments remain portable.
                payload.pop("response_format", None)
                resp = requests.post(cfg.OLLAMA_URL, json=payload, timeout=cfg.OLLAMA_TIMEOUT)
            if resp.status_code >= 400:
                body = resp.text[:600].replace("\n", " ")
                raise HTTPError(
                    f"{resp.status_code} {resp.reason} from {cfg.OLLAMA_URL}; body={body}",
                    response=resp,
                )
            content = resp.json()["choices"][0]["message"]["content"]
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
                        "endpoint": cfg.OLLAMA_URL,
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
                        "endpoint": cfg.OLLAMA_URL,
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
    """Remove Qwen3 <think>...</think> reasoning blocks."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def extract_json(text: str) -> dict:
    """Extract the first JSON object from LLM output (after stripping think tags)."""
    text = strip_think_tags(text)
    # Find outermost braces
    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in response: {text[:200]}")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError(f"Unclosed JSON object in response: {text[:200]}")


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
) -> dict[str, Any]:
    """Get JSON from chat with compatibility + repair fallback for weaker models."""
    raw = chat(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        json_mode=True,
        trace=trace,
        trace_recorder=trace_recorder,
    )
    try:
        return extract_json(raw)
    except Exception:
        repair_trace = dict(trace or {})
        repair_trace["phase"] = f"{repair_trace.get('phase', 'unknown')}_json_repair"
        repair_source = raw[:6000]
        repair_prompt = (
            "Return one complete, valid JSON object only. "
            "No prose, no markdown fences, no comments. "
            "If any fields are unknown, use empty strings, empty lists, or null.\n\n"
            "Target schema and constraints:\n"
            f"{system_prompt[:3000]}\n\n"
            "Model output to normalize (may be malformed/truncated):\n"
            f"{repair_source}"
        )
        repaired = chat(
            system_prompt="You are a strict JSON formatter.",
            user_prompt=repair_prompt,
            max_tokens=min(max_tokens, 2200),
            temperature=0.0,
            json_mode=True,
            trace=repair_trace,
            trace_recorder=trace_recorder,
        )
        return extract_json(repaired)
