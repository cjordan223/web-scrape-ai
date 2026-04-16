"""Post-analysis semantic validation for skills and evidence.

Runs after analysis generation + grounding enrichment, before downstream
strategy/draft stages consume the output. Catches structurally valid but
semantically incorrect analysis entries — the most common LLM hallucination
mode in this pipeline.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config as cfg
from .grounding import _extract_resume_companies

logger = logging.getLogger(__name__)


@dataclass
class SemanticIssue:
    requirement_index: int
    field: str
    message: str
    action: str  # "dropped_skill", "flagged_evidence", "dropped_requirement"


@dataclass
class SemanticValidationResult:
    issues: list[SemanticIssue] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return len(self.issues) == 0


def _build_skill_index(skills_data: dict[str, Any]) -> set[str]:
    """Build a lowercase set of every valid skill term from the inventory."""
    terms: set[str] = set()
    inventory = skills_data.get("skills_inventory", {})

    for bucket in inventory.get("core_skills", []) + inventory.get("supporting_skills", []):
        for skill in bucket.get("skills", []):
            terms.add(skill.strip().lower())

    for key in ("programming_languages", "databases", "frameworks_and_infrastructure",
                "security_tooling", "devops_and_cloud"):
        for item in inventory.get(key, []):
            terms.add(item.strip().lower())

    for items in inventory.get("tools_and_platforms", {}).values():
        for item in items:
            terms.add(item.strip().lower())

    return terms


def _build_category_index(skills_data: dict[str, Any]) -> set[str]:
    """Build a lowercase set of every valid category name."""
    categories: set[str] = set()
    inventory = skills_data.get("skills_inventory", {})
    for bucket in inventory.get("core_skills", []) + inventory.get("supporting_skills", []):
        name = bucket.get("name", "").strip()
        if name:
            categories.add(name.lower())
    return categories


def _extract_baseline_bullets(baseline_tex: str) -> list[str]:
    """Extract all resume bullet texts, lowercased and whitespace-normalized."""
    companies = _extract_resume_companies(baseline_tex)
    bullets: list[str] = []
    for company in companies:
        for bullet in company.get("bullets", []):
            bullets.append(re.sub(r"\s+", " ", bullet).strip().lower())
    return bullets


def _evidence_matches_baseline(evidence: str, baseline_bullets: list[str], company_names: list[str]) -> bool:
    """Check that evidence text plausibly references actual baseline content.

    Passes if:
    - Evidence mentions a known company name, AND
    - At least one baseline bullet shares a non-trivial substring (8+ chars)
      with the evidence text.
    """
    if not evidence or len(evidence.strip()) < 10:
        return False

    ev_lower = evidence.lower()

    # Must cite a real company
    mentions_company = any(name.lower() in ev_lower for name in company_names)
    if not mentions_company:
        return False

    # Must overlap with at least one baseline bullet
    for bullet in baseline_bullets:
        # Find longest common substring via sliding window of 8-char chunks
        for i in range(len(bullet) - 7):
            chunk = bullet[i : i + 8]
            if chunk in ev_lower:
                return True

    return False


def validate_analysis_semantics(
    analysis: dict[str, Any],
    *,
    skills_data: dict[str, Any] | None = None,
    baseline_tex: str | None = None,
) -> tuple[dict[str, Any], SemanticValidationResult]:
    """Validate and repair analysis output semantically.

    Returns (repaired_analysis, result) where invalid skills are dropped
    and requirements with no valid skills or bad evidence are flagged.
    """
    skills_data = skills_data or json.loads(cfg.SKILLS_JSON.read_text())
    baseline_tex = baseline_tex or cfg.RESUME_TEX.read_text()

    skill_index = _build_skill_index(skills_data)
    category_index = _build_category_index(skills_data)
    baseline_bullets = _extract_baseline_bullets(baseline_tex)
    company_names = [c["company"] for c in _extract_resume_companies(baseline_tex)]

    result = SemanticValidationResult()
    repaired = dict(analysis)
    repaired_requirements: list[dict[str, Any]] = []

    for i, req in enumerate(analysis.get("requirements", [])):
        repaired_req = dict(req)

        # --- Validate matched_skills against inventory ---
        original_skills = req.get("matched_skills", [])
        valid_skills: list[str] = []
        for skill in original_skills:
            if skill.strip().lower() in skill_index:
                valid_skills.append(skill)
            else:
                result.issues.append(SemanticIssue(
                    requirement_index=i,
                    field="matched_skills",
                    message=f"Skill not in inventory: {skill!r}",
                    action="dropped_skill",
                ))
        repaired_req["matched_skills"] = valid_skills

        # --- Validate matched_category ---
        category = req.get("matched_category", "")
        if category and category.strip().lower() not in category_index:
            result.issues.append(SemanticIssue(
                requirement_index=i,
                field="matched_category",
                message=f"Category not in inventory: {category!r}",
                action="flagged_evidence",
            ))

        # --- Validate evidence against baseline ---
        evidence = req.get("evidence", "")
        if not _evidence_matches_baseline(evidence, baseline_bullets, company_names):
            result.issues.append(SemanticIssue(
                requirement_index=i,
                field="evidence",
                message=f"Evidence does not match baseline resume: {evidence[:80]!r}",
                action="flagged_evidence",
            ))

        # Drop requirement only if it has zero valid skills AND bad evidence
        has_valid_skills = len(valid_skills) > 0
        has_valid_evidence = _evidence_matches_baseline(evidence, baseline_bullets, company_names)

        if not has_valid_skills and not has_valid_evidence:
            result.issues.append(SemanticIssue(
                requirement_index=i,
                field="requirement",
                message=f"Requirement has no valid skills and ungrounded evidence — dropped",
                action="dropped_requirement",
            ))
            continue

        repaired_requirements.append(repaired_req)

    repaired["requirements"] = repaired_requirements

    if result.issues:
        logger.warning(
            "Semantic validation found %d issue(s) in analysis: %s",
            len(result.issues),
            "; ".join(issue.message for issue in result.issues),
        )

    return repaired, result
