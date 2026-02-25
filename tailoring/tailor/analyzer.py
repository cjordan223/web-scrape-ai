"""Analyze a JD and map requirements to skills inventory + soul evidence."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from . import config as cfg
from .ollama import chat_expect_json
from .selector import SelectedJob

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a job application strategist. You will receive a job description and a candidate's skills inventory + professional persona. Your task is to produce a structured mapping that a LaTeX tailoring system will consume.

RULES:
1. Only reference skills that exist in the provided skills_inventory. Do NOT hallucinate skills the candidate does not have.
2. Map each JD requirement to the best matching skill categories and specific skills.
3. Select evidence anchors from the persona that best demonstrate each matched skill.
4. Identify the company name and exact role title from the JD.
5. Note any tone adjustments needed based on the JD's language and culture signals.

Respond with ONLY a JSON object — no other text, no markdown fences:
{
  "company_name": "string",
  "role_title": "string",
  "requirements": [
    {
      "jd_requirement": "what the JD asks for",
      "matched_category": "skill category name from inventory",
      "matched_skills": ["specific skill 1", "specific skill 2"],
      "evidence": "brief description of candidate evidence supporting this",
      "priority": "high|medium|low"
    }
  ],
  "tone_notes": "any adjustments to cover letter tone based on JD signals",
  "skills_line_recommendation": "which condensed skills line format (full/5/3) best fits this role",
  "summary_angle": "1-sentence guidance on how to angle the professional summary for this role"
}"""


def load_cached_analysis(job: SelectedJob, output_dir: Path) -> dict | None:
    """Return cached analysis only if it matches the selected job."""
    cache_path = output_dir / "analysis.json"
    if not cache_path.exists():
        return None

    try:
        analysis = json.loads(cache_path.read_text())
    except Exception:
        logger.warning("Ignoring unreadable analysis cache at %s", cache_path)
        return None

    cache_job_id = analysis.get("_job_id")
    cache_job_url = analysis.get("_job_url")
    if cache_job_id != job.id or cache_job_url != job.url:
        logger.warning(
            "Ignoring stale analysis cache at %s (cached job_id=%r, current job_id=%r)",
            cache_path, cache_job_id, job.id
        )
        return None

    logger.info("Using cached analysis from %s", cache_path)
    return analysis


def analyze_job(
    job: SelectedJob,
    output_dir: Path,
    trace_recorder: Callable[[dict], None] | None = None,
) -> dict:
    """Analyze a JD against skills inventory. Returns structured mapping dict.

    Caches result to output_dir/analysis.json — skips LLM if cache exists.
    """
    cache_path = output_dir / "analysis.json"
    cached = load_cached_analysis(job, output_dir)
    if cached is not None:
        return cached

    skills_data = json.loads(cfg.SKILLS_JSON.read_text())
    soul_text = cfg.SOUL_MD.read_text()

    jd_text = job.jd_text or job.snippet or ""
    if not jd_text.strip():
        raise ValueError(f"Job {job.id} has no JD text or snippet to analyze")

    user_prompt = (
        f"## Job Description\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"URL: {job.url}\n\n"
        f"{jd_text[:8000]}\n\n"
        f"## Candidate Skills Inventory\n"
        f"{json.dumps(skills_data['skills_inventory'], indent=2)}\n\n"
        f"## Candidate Persona\n"
        f"{soul_text[:4000]}"
    )

    analysis = chat_expect_json(
        _SYSTEM_PROMPT,
        user_prompt,
        max_tokens=4096,
        temperature=0.2,
        trace={
            "doc_type": "analysis",
            "phase": "analysis",
            "attempt": 0,
            "response_parse_kind": "json",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
    )
    analysis["_job_id"] = job.id
    analysis["_job_url"] = job.url

    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(analysis, indent=2))
    logger.info("Analysis saved to %s (%d requirements mapped)", cache_path, len(analysis.get("requirements", [])))
    return analysis
