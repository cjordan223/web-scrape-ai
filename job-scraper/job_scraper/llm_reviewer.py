"""LLM-based common-sense review of job postings via local OpenAI-compatible server."""

from __future__ import annotations

import fcntl
import json
import logging
import re
import time
from pathlib import Path

import requests

from .config import LLMReviewConfig
from .models import FilterVerdict

_LOCK_PATH = Path.home() / ".local" / "share" / "job_scraper" / "ollama.lock"
_LOCK_TIMEOUT = 300  # seconds

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a job posting filter for a tech job search. Review the posting and decide if it passes ALL criteria:
1. The role is a genuine technical position in one of these areas: cybersecurity/infosec, infrastructure, cloud engineering, platform engineering, DevOps, SRE, software engineering, AI/ML engineering, or application engineering. Reject physical security, sales, marketing, or non-technical roles.
2. Seniority can be mid-to-senior individual contributor, but reject explicit staff/principal/lead and people-management/executive roles (manager/director/head/VP/CISO). Do not infer management from vague wording.
3. The role must include a clear remote option for candidates in the US. "City/Office OR Remote (USA)" is acceptable. Reject onsite-only, hybrid-only, or remote roles limited to non-US regions (Europe/EMEA/APAC/etc).
4. Reject internship, co-op, apprenticeship, fellowship, and new-grad programs.
5. Reject closed/expired postings, generic listing pages, and apply/login shells that are not active canonical job descriptions.
6. Reject only when criteria are explicitly violated. If uncertain but the posting appears technical and US-remote eligible, pass.

Respond with ONLY a JSON object — no other text:
{"pass": true, "reason": "brief reason under 15 words"}
or
{"pass": false, "reason": "brief reason under 15 words"}"""


_MODEL_CACHE = None


def _get_active_model(config: LLMReviewConfig) -> str:
    """Resolve model: explicit config override, else first model from /v1/models."""
    global _MODEL_CACHE
    if _MODEL_CACHE:
        return _MODEL_CACHE
    if config.model and config.model != "default":
        _MODEL_CACHE = config.model
        return _MODEL_CACHE
    try:
        models_url = config.url.replace("/chat/completions", "/models")
        resp = requests.get(models_url, timeout=5)
        resp.raise_for_status()
        models = resp.json().get("data", [])
        if not models:
            return config.model
        # Pick first available model when no explicit override is set.
        _MODEL_CACHE = models[0]["id"]
        return _MODEL_CACHE
    except Exception as e:
        logger.debug("Could not fetch models for dynamic selection: %s", e)
        return config.model


def llm_review(
    title: str,
    snippet: str,
    jd_text: str | None,
    config: LLMReviewConfig,
) -> FilterVerdict:
    """Call local LLM for a common-sense pass/fail review of a job posting."""
    model_id = _get_active_model(config)
    user_content = (
        f"Title: {title}\n"
        f"Snippet: {snippet}\n\n"
        f"Job Description:\n{(jd_text or '')[:config.jd_max_chars]}"
    )

    try:
        # Acquire shared LLM lock to prevent concurrent LLM sessions
        _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd = open(_LOCK_PATH, "w")
        deadline = time.monotonic() + _LOCK_TIMEOUT
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    fd.close()
                    raise TimeoutError("LLM lock timeout")
                time.sleep(2)
        try:
            resp = requests.post(
                config.url,
                json={
                    "model": model_id,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "max_tokens": 150,
                    "temperature": 0.0,
                },
                timeout=config.timeout,
            )
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        logger.debug("LLM raw response for '%s': %s", title, content[:300])
        passed, reason = _parse_response(content)
        return FilterVerdict(stage="llm_review", passed=passed, reason=reason)

    except Exception as exc:
        logger.warning("LLM review failed for '%s': %s", title, exc)
        if config.fail_open:
            return FilterVerdict(
                stage="llm_review", passed=True,
                reason=f"server unavailable, fail open ({type(exc).__name__})",
            )
        return FilterVerdict(
            stage="llm_review", passed=False,
            reason=f"server unavailable ({type(exc).__name__})",
        )


def _parse_response(text: str) -> tuple[bool, str]:
    """Extract pass/reason from LLM response. Strips Qwen3 <think> tags."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    for m in re.finditer(r"\{[^{}]+\}", text, re.DOTALL):
        try:
            data = json.loads(m.group(0))
            if "pass" in data:
                return bool(data["pass"]), str(data.get("reason", ""))
        except json.JSONDecodeError:
            continue
    logger.warning("Could not parse LLM response: %r", text[:200])
    return False, f"unparseable response: {text[:80]}"
