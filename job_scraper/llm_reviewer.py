"""LLM-based common-sense review of job postings via local OpenAI-compatible server."""

from __future__ import annotations

import json
import logging
import re

import requests

from .config import LLMReviewConfig
from .models import FilterVerdict

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a job posting filter for a cybersecurity job search. Review the posting and decide if it passes ALL criteria:
1. The role is primarily an information/cybersecurity position — not physical security, not "security" in name only
2. The seniority is entry-to-mid level (roughly 0–4 years experience), even if the title is ambiguous
3. The remote option appears genuine, not a token mention buried in fine print for an essentially on-site role

Respond with ONLY a JSON object — no other text:
{"pass": true, "reason": "brief reason under 15 words"}
or
{"pass": false, "reason": "brief reason under 15 words"}"""


def llm_review(
    title: str,
    snippet: str,
    jd_text: str | None,
    config: LLMReviewConfig,
) -> FilterVerdict:
    """Call local LLM for a common-sense pass/fail review of a job posting."""
    user_content = (
        f"Title: {title}\n"
        f"Snippet: {snippet}\n\n"
        f"Job Description:\n{(jd_text or '')[:config.jd_max_chars]}"
    )

    try:
        resp = requests.post(
            config.url,
            json={
                "model": config.model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "max_tokens": 150,
                "temperature": 0.0,
            },
            timeout=config.timeout,
        )
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
