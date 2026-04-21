"""Analyze a JD and map requirements to skills inventory + soul evidence."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Callable

from . import config as cfg
from .grounding import (
    build_grounding_context,
    enrich_analysis_with_grounding,
    grounding_prompt_block,
    write_grounding_artifacts,
)
from .ollama import chat_expect_json
from .persona import get_store as get_persona
from .selector import SelectedJob
from .semantic_validator import validate_analysis_semantics

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a job application strategist. You will receive a job description and a candidate's skills inventory + professional persona. Your task is to produce a structured mapping that a LaTeX tailoring system will consume.

RULES:
1. Only reference skills that exist in the provided skills_inventory. Do NOT hallucinate skills the candidate does not have.
2. Map each JD requirement to the best matching skill categories and specific skills.
3. Select evidence anchors from the BASELINE RESUME provided. You MUST quote or closely paraphrase a specific bullet from the resume and cite the company name. Do NOT fabricate metrics, percentages, or outcomes not present in the baseline.
3a. Treat baseline employer names, role titles, and dates as immutable facts. Never reinterpret a past employer role as the target role.
3b. Persona text may add narrative emphasis only. It does NOT authorize new tools, compliance frameworks, identity stacks, deployment topology, or operational mechanics unless explicitly stated in source truth.
4. Identify the company name and exact role title from the JD. The company_name MUST be the real hiring employer, NOT the job board or aggregator the post is hosted on. If the JD is posted via LinkedIn, Dice, Indeed, Glassdoor, Working Nomads, Hacker News, RemoteOK, Jobgether, Greenhouse, Lever, or Ashby, ignore those and find the employer named in the JD body (e.g. "About Acme" / "At Acme, we build…"). Use proper capitalization as the company presents itself (e.g. "Stripe", "Apex Systems", "Arcadia" — never "stripe", "apexsystems", "arcadia"). If the JD is from a staffing agency (Kforce, Apex Systems, TEKsystems, Robert Half, Insight Global, etc.) and does not name the end client, use the staffing agency name itself. NEVER emit a bare aggregator/board name like "jobs", "dice", "linkedin", or "workingnomads".
5. Note any tone adjustments needed based on the JD's language and culture signals.
6. Extract company context: what the company builds/does, what engineering challenges the team likely faces, and what the company seems to value based on JD language. This will be used to personalize the cover letter opening.
7. Classify the company type as one of: large_tech, security_focused, startup, enterprise_regulated, platform_devops, or other. This drives voice adaptation.

Respond with ONLY a JSON object — no other text, no markdown fences:
{
  "company_name": "string",
  "role_title": "string",
  "company_context": {
    "what_they_build": "1-2 sentences about the company's product/mission based on JD signals",
    "engineering_challenges": "what this team likely cares about (scale, security depth, velocity, compliance, etc.)",
    "company_type": "large_tech|security_focused|startup|enterprise_regulated|platform_devops|other",
    "cover_letter_hook": "a specific, non-generic opening angle that references what the company does"
  },
  "requirements": [
    {
      "jd_requirement": "what the JD asks for",
      "matched_category": "skill category name from inventory",
      "matched_skills": ["specific skill 1", "specific skill 2"],
      "evidence": "quote or close paraphrase of a specific baseline resume bullet (cite company name)",
      "priority": "high|medium|low",
      "allowed_evidence": {
        "source_company": "company named in evidence",
        "immutable_role": "baseline role title for that company",
        "approved_terms": ["specific grounded terms already present in source truth"],
        "forbidden_categories": ["categories of claim drift to avoid for this requirement"]
      }
    }
  ],
  "tone_notes": "any adjustments to cover letter tone based on JD signals",
  "summary_angle": "1-sentence guidance on how to angle the professional summary for this role"
}"""


def _coerce_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("[") and raw.endswith("]"):
            try:
                decoded = json.loads(raw)
            except Exception:
                decoded = None
            if decoded is not None:
                return _coerce_string_list(decoded)
        items = re.split(r"[,;\n]+", raw)
    elif value is None:
        return []
    else:
        items = [value]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip().strip("\"'")
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(text)
    return normalized


def normalize_analysis(analysis: dict) -> dict:
    normalized = dict(analysis or {})
    company_context = normalized.get("company_context")
    normalized["company_context"] = company_context if isinstance(company_context, dict) else {}

    requirements = normalized.get("requirements")
    if not isinstance(requirements, list):
        requirements = []
    cleaned_requirements: list[dict] = []
    for req in requirements:
        if not isinstance(req, dict):
            continue
        cleaned = dict(req)
        cleaned["matched_skills"] = _coerce_string_list(req.get("matched_skills"))
        allowed = req.get("allowed_evidence")
        if not isinstance(allowed, dict):
            allowed = {}
        cleaned["allowed_evidence"] = {
            "source_company": allowed.get("source_company"),
            "immutable_role": allowed.get("immutable_role"),
            "approved_terms": _coerce_string_list(allowed.get("approved_terms")),
            "forbidden_categories": _coerce_string_list(allowed.get("forbidden_categories")),
        }
        priority = str(req.get("priority", "medium")).lower().strip()
        cleaned["priority"] = priority if priority in {"high", "medium", "low"} else "medium"
        cleaned_requirements.append(cleaned)
    normalized["requirements"] = cleaned_requirements
    grounding_contract = normalized.get("grounding_contract")
    normalized["grounding_contract"] = grounding_contract if isinstance(grounding_contract, dict) else {}
    return normalized


def _compute_input_hash(job: SelectedJob) -> str:
    """SHA-256 hash of the LLM prompt inputs for cache validation."""
    jd_text = job.jd_text or job.snippet or ""
    skills_text = cfg.SKILLS_JSON.read_text() if cfg.SKILLS_JSON.exists() else ""
    baseline_text = cfg.RESUME_TEX.read_text() if cfg.RESUME_TEX.exists() else ""
    combined = f"{jd_text}\n---\n{skills_text}\n---\n{baseline_text}"
    return hashlib.sha256(combined.encode()).hexdigest()


def load_cached_analysis(job: SelectedJob, output_dir: Path) -> dict | None:
    """Return cached analysis only if it matches the selected job and inputs haven't changed."""
    cache_path = output_dir / "analysis.json"
    if not cache_path.exists():
        return None

    try:
        analysis = json.loads(cache_path.read_text())
    except Exception:
        logger.warning("Ignoring unreadable analysis cache at %s", cache_path)
        return None

    # Invalidate cache if it's missing required fields needed by downstream grounding rules.
    if "company_context" not in analysis:
        logger.info("Invalidating analysis cache at %s (missing company_context)", cache_path)
        return None

    cache_job_id = analysis.get("_job_id")
    cache_job_url = analysis.get("_job_url")
    if cache_job_id != job.id or cache_job_url != job.url:
        logger.warning(
            "Ignoring stale analysis cache at %s (cached job_id=%r, current job_id=%r)",
            cache_path, cache_job_id, job.id
        )
        return None

    # Invalidate if inputs (JD, skills, baseline) have changed since the analysis was cached.
    cached_hash = analysis.get("_input_hash")
    if cached_hash and cached_hash != _compute_input_hash(job):
        logger.info("Invalidating analysis cache at %s (input hash mismatch — JD, skills, or baseline changed)", cache_path)
        return None

    grounding = build_grounding_context()
    analysis = enrich_analysis_with_grounding(normalize_analysis(analysis), grounding)
    analysis, _ = validate_analysis_semantics(analysis)
    logger.info("Using cached analysis from %s", cache_path)
    return analysis


def _find_prior_analysis(job: SelectedJob, output_dir: Path) -> dict | None:
    """Search prior run directories for a valid cached analysis for this job.

    Output dirs follow the pattern: output/<slug>/ or output/<slug>-<timestamp>/.
    We check the current dir first, then scan siblings in reverse chronological order.
    """
    cached = load_cached_analysis(job, output_dir)
    if cached is not None:
        return cached

    # Search sibling directories that share this job's slug prefix
    parent = output_dir.parent
    if not parent.is_dir():
        return None
    slug = job.slug
    candidates = sorted(
        (d for d in parent.iterdir() if d.is_dir() and d != output_dir and d.name.startswith(slug)),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for prior_dir in candidates[:5]:  # check at most 5 recent runs
        cached = load_cached_analysis(job, prior_dir)
        if cached is not None:
            logger.info("Reusing analysis from prior run: %s", prior_dir.name)
            return cached
    return None


def analyze_job(
    job: SelectedJob,
    output_dir: Path,
    trace_recorder: Callable[[dict], None] | None = None,
) -> dict:
    """Analyze a JD against skills inventory. Returns structured mapping dict.

    Searches the current and prior run directories for a valid cached analysis
    (validated by job_id, job_url, and input hash). Falls back to LLM if no
    valid cache is found.
    """
    cache_path = output_dir / "analysis.json"
    cached = _find_prior_analysis(job, output_dir)
    if cached is not None:
        # Copy the valid cache into the current output dir for downstream use
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cached, indent=2))
        return cached

    skills_data = cfg.read_json_cached(cfg.SKILLS_JSON)
    persona_text = get_persona().for_analysis()
    baseline_resume = cfg.read_cached(cfg.RESUME_TEX)
    grounding = build_grounding_context(baseline_tex=baseline_resume, skills_data=skills_data)

    jd_text = job.jd_text or job.snippet or ""
    if not jd_text.strip():
        raise ValueError(f"Job {job.id} has no JD text or snippet to analyze")

    user_prompt = (
        f"## Job Description\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"URL: {job.url}\n\n"
        f"{jd_text[:8000]}\n\n"
        f"## Baseline Resume (source of truth for evidence — quote from HERE, not from memory)\n"
        f"```latex\n{baseline_resume}\n```\n\n"
        f"## Candidate Skills Inventory\n"
        f"{json.dumps(skills_data['skills_inventory'], indent=2)}\n\n"
        f"{grounding_prompt_block(grounding)}\n\n"
        f"## Candidate Persona\n"
        f"{persona_text}"
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
    analysis = enrich_analysis_with_grounding(normalize_analysis(analysis), grounding)
    analysis, validation = validate_analysis_semantics(
        analysis, skills_data=skills_data, baseline_tex=baseline_resume,
    )
    analysis["_job_id"] = job.id
    analysis["_job_url"] = job.url
    analysis["_input_hash"] = _compute_input_hash(job)

    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(analysis, indent=2))
    write_grounding_artifacts(output_dir, grounding=grounding, analysis=analysis)
    if not validation.clean:
        logger.info(
            "Analysis saved with %d semantic repair(s) to %s (%d requirements kept)",
            len(validation.issues), cache_path, len(analysis.get("requirements", [])),
        )
    else:
        logger.info("Analysis saved to %s (%d requirements mapped)", cache_path, len(analysis.get("requirements", [])))
    return analysis
