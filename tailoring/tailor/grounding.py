"""Structured grounding contract for tailoring.

This module centralizes immutable candidate facts, approved supporting evidence,
and high-risk claim patterns that must stay bounded to source truth.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import config as cfg


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_resume_companies(tex: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"\\resumeSubheading\s*"
        r"\{\s*(?P<company>[^}]*)\s*\}\s*"
        r"\{\s*(?P<location>[^}]*)\s*\}\s*"
        r"\{\s*(?P<role>[^}]*)\s*\}\s*"
        r"\{\s*(?P<dates>[^}]*)\s*\}"
        r"(?P<body>.*?)(?=(?:\\resumeSubheading\s*\{)|\\resumeSubHeadingListEnd|\\section\{|\\end\{document\})",
        re.DOTALL,
    )
    companies: list[dict[str, Any]] = []
    for match in pattern.finditer(tex):
        body = match.group("body")
        bullets = [_normalize_text(b) for b in re.findall(r"\\resumeItem\{(.*?)\}", body, re.DOTALL)]
        companies.append(
            {
                "company": _normalize_text(match.group("company")),
                "location": _normalize_text(match.group("location")),
                "role": _normalize_text(match.group("role")),
                "dates": _normalize_text(match.group("dates")),
                "bullets": bullets,
            }
        )
    return companies


def _load_persona_texts() -> dict[str, str]:
    texts: dict[str, str] = {}
    if cfg.PERSONA_DIR.is_dir():
        for path in sorted(cfg.PERSONA_DIR.glob("*.md")):
            texts[path.stem] = path.read_text(encoding="utf-8")
        for path in sorted((cfg.PERSONA_DIR / "vignettes").glob("*.md")):
            texts[f"vignette:{path.stem}"] = path.read_text(encoding="utf-8")
    elif cfg.SOUL_MD.exists():
        texts["soul"] = cfg.SOUL_MD.read_text(encoding="utf-8")
    return texts


def _normalize_string_list(values: object, *, context: str) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{context} must be a list of strings")
    normalized: list[str] = []
    for item in values:
        if not isinstance(item, str):
            raise ValueError(f"{context} must contain only strings")
        text = _normalize_text(item)
        if text:
            normalized.append(text)
    return normalized


def _validate_projects(raw_projects: object) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_projects, dict):
        raise ValueError("approved_sources.projects must be an object")
    projects: dict[str, dict[str, Any]] = {}
    for key, value in raw_projects.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("approved_sources.projects keys must be non-empty strings")
        if not isinstance(value, dict):
            raise ValueError(f"approved_sources.projects.{key} must be an object")
        label = value.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"approved_sources.projects.{key}.label must be a non-empty string")
        project: dict[str, Any] = {
            "label": _normalize_text(label),
            "approved_terms": _normalize_string_list(
                value.get("approved_terms", []),
                context=f"approved_sources.projects.{key}.approved_terms",
            ),
        }
        forbidden_terms = value.get("forbidden_terms")
        if forbidden_terms is not None:
            project["forbidden_terms"] = _normalize_string_list(
                forbidden_terms,
                context=f"approved_sources.projects.{key}.forbidden_terms",
            )
        match_keywords = value.get("match_keywords")
        if match_keywords is not None:
            project["match_keywords"] = [
                kw.lower()
                for kw in _normalize_string_list(
                    match_keywords,
                    context=f"approved_sources.projects.{key}.match_keywords",
                )
            ]
        projects[key.strip()] = project
    return projects


def _validate_grounding_file(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Grounding config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Grounding config is not valid JSON: {path} ({exc})") from exc

    if not isinstance(raw, dict):
        raise ValueError("Grounding config root must be an object")
    version = raw.get("version")
    if version != 1:
        raise ValueError(f"Unsupported grounding config version: {version!r}")

    precedence = _normalize_string_list(raw.get("precedence", []), context="precedence")
    forbidden_global_claims = _normalize_string_list(
        raw.get("forbidden_global_claims", []),
        context="forbidden_global_claims",
    )

    approved_sources = raw.get("approved_sources")
    if not isinstance(approved_sources, dict):
        raise ValueError("approved_sources must be an object")

    raw_company_terms = approved_sources.get("company_terms")
    if not isinstance(raw_company_terms, dict):
        raise ValueError("approved_sources.company_terms must be an object")
    company_terms: dict[str, list[str]] = {}
    for company, terms in raw_company_terms.items():
        if not isinstance(company, str) or not company.strip():
            raise ValueError("approved_sources.company_terms keys must be non-empty strings")
        company_terms[_normalize_text(company)] = _normalize_string_list(
            terms,
            context=f"approved_sources.company_terms.{company}",
        )

    raw_company_aliases = approved_sources.get("company_aliases", {}) or {}
    if not isinstance(raw_company_aliases, dict):
        raise ValueError("approved_sources.company_aliases must be an object")
    company_aliases: dict[str, list[str]] = {}
    for company, aliases in raw_company_aliases.items():
        if not isinstance(company, str) or not company.strip():
            raise ValueError("approved_sources.company_aliases keys must be non-empty strings")
        company_aliases[_normalize_text(company)] = [
            a.lower()
            for a in _normalize_string_list(
                aliases,
                context=f"approved_sources.company_aliases.{company}",
            )
        ]

    high_risk_patterns = raw.get("high_risk_patterns")
    if not isinstance(high_risk_patterns, dict):
        raise ValueError("high_risk_patterns must be an object")
    if not isinstance(high_risk_patterns.get("role_title_renamed"), dict):
        raise ValueError("high_risk_patterns.role_title_renamed must be an object")
    rename_msg = high_risk_patterns["role_title_renamed"].get("message")
    if not isinstance(rename_msg, str) or not rename_msg.strip():
        raise ValueError("high_risk_patterns.role_title_renamed.message must be a non-empty string")

    validated_patterns: dict[str, Any] = {
        "role_title_renamed": {"message": _normalize_text(rename_msg)},
    }
    for rule_name, patterns in high_risk_patterns.items():
        if rule_name == "role_title_renamed":
            continue
        validated_patterns[rule_name] = _normalize_string_list(
            patterns,
            context=f"high_risk_patterns.{rule_name}",
        )

    return {
        "version": version,
        "precedence": precedence,
        "approved_sources": {
            "company_terms": company_terms,
            "company_aliases": company_aliases,
            "projects": _validate_projects(approved_sources.get("projects", {})),
            "approved_ai_details": _normalize_string_list(
                approved_sources.get("approved_ai_details", []),
                context="approved_sources.approved_ai_details",
            ),
            "approved_identity_details": _normalize_string_list(
                approved_sources.get("approved_identity_details", []),
                context="approved_sources.approved_identity_details",
            ),
            "approved_compliance_details": _normalize_string_list(
                approved_sources.get("approved_compliance_details", []),
                context="approved_sources.approved_compliance_details",
            ),
        },
        "high_risk_patterns": validated_patterns,
        "forbidden_global_claims": forbidden_global_claims,
    }


def _load_grounding_contract(path: Path | None = None) -> dict[str, Any]:
    grounding_path = path or cfg.GROUNDING_CONFIG
    return _validate_grounding_file(grounding_path)


_GROUNDING_CACHE: dict[str, dict[str, Any]] = {}


def clear_grounding_cache() -> None:
    """Clear the run-scoped grounding cache (call at run start)."""
    _GROUNDING_CACHE.clear()


def _grounding_cache_key(baseline_tex: str, skills_json: str) -> str:
    """Hash actual content so different inputs never collide."""
    import hashlib
    h = hashlib.sha1(baseline_tex.encode(), usedforsecurity=False)
    h.update(skills_json.encode())
    return h.hexdigest()


def build_grounding_context(
    *,
    baseline_tex: str | None = None,
    skills_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline_tex = baseline_tex or cfg.read_cached(cfg.RESUME_TEX)
    skills_data = skills_data or cfg.read_json_cached(cfg.SKILLS_JSON)
    cache_key = _grounding_cache_key(baseline_tex, json.dumps(skills_data, sort_keys=True))
    if cache_key in _GROUNDING_CACHE:
        return _GROUNDING_CACHE[cache_key]
    grounding_contract = _load_grounding_contract()
    persona_texts = _load_persona_texts()
    experiences = _extract_resume_companies(baseline_tex)

    approved_skill_terms: list[str] = []
    inventory = skills_data.get("skills_inventory", {})
    for bucket in inventory.get("core_skills", []) + inventory.get("supporting_skills", []):
        approved_skill_terms.extend(bucket.get("skills", []))
    approved_skill_terms.extend(inventory.get("programming_languages", []))
    approved_skill_terms.extend(inventory.get("databases", []))
    approved_skill_terms.extend(inventory.get("frameworks_and_infrastructure", []))
    approved_skill_terms.extend(inventory.get("security_tooling", []))
    approved_skill_terms.extend(inventory.get("devops_and_cloud", []))
    for items in inventory.get("tools_and_platforms", {}).values():
        approved_skill_terms.extend(items)
    result = {
        "version": grounding_contract["version"],
        "precedence": grounding_contract["precedence"],
        "immutable_facts": {
            "candidate_name": skills_data.get("candidate_profile", {}).get("name", "Conner Jordan"),
            "target_roles": skills_data.get("candidate_profile", {}).get("target_roles", []),
            "experience": experiences,
        },
        "approved_sources": {
            "persona_files": sorted(persona_texts.keys()),
            "skills_terms": sorted({_normalize_text(str(term)) for term in approved_skill_terms if str(term).strip()}),
            **grounding_contract["approved_sources"],
        },
        "high_risk_patterns": grounding_contract["high_risk_patterns"],
        "forbidden_global_claims": grounding_contract["forbidden_global_claims"],
    }
    _GROUNDING_CACHE[cache_key] = result
    return result


def _terms_for_company(grounding: dict[str, Any], company: str) -> list[str]:
    return list((grounding.get("approved_sources", {}).get("company_terms", {}) or {}).get(company, []))


def _find_company_from_text(text: str, grounding: dict[str, Any]) -> str | None:
    lowered = text.lower()
    approved = grounding.get("approved_sources", {})
    company_aliases = approved.get("company_aliases", {}) or {}
    for company in (approved.get("company_terms", {}) or {}):
        if company.lower() in lowered:
            return company
        for alias in company_aliases.get(company, []) or []:
            if alias and alias.lower() in lowered:
                return company
    return None


def _approved_terms_for_requirement(req: dict[str, Any], grounding: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    company = _find_company_from_text(str(req.get("evidence", "")), grounding)
    if company:
        terms.extend(_terms_for_company(grounding, company))
    terms.extend(req.get("matched_skills") or [])
    return sorted({_normalize_text(str(term)) for term in terms if str(term).strip()})


def enrich_analysis_with_grounding(analysis: dict[str, Any], grounding: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(analysis or {})
    requirements = []
    for req in enriched.get("requirements", []) or []:
        item = dict(req)
        company = _find_company_from_text(str(item.get("evidence", "")), grounding)
        item["allowed_evidence"] = {
            "source_company": company,
            "immutable_role": (
                next(
                    (exp["role"] for exp in grounding.get("immutable_facts", {}).get("experience", []) if exp["company"] == company),
                    None,
                )
                if company
                else None
            ),
            "approved_terms": _approved_terms_for_requirement(item, grounding),
            "forbidden_categories": [
                "role_title_renamed",
                "unsupported_tool_claim",
                "unsupported_compliance_claim",
                "unsupported_identity_stack_claim",
                "unsupported_ai_deployment_claim",
                "unsupported_operational_mechanic_claim",
            ],
        }
        requirements.append(item)
    enriched["requirements"] = requirements
    enriched["grounding_contract"] = {
        "precedence": grounding.get("precedence", []),
        "immutable_employers": [
            {"company": exp["company"], "role": exp["role"], "dates": exp["dates"]}
            for exp in grounding.get("immutable_facts", {}).get("experience", [])
        ],
        "forbidden_global_claims": grounding.get("forbidden_global_claims", []),
    }
    return enriched


def enrich_resume_strategy_with_grounding(strategy: dict[str, Any], grounding: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(strategy or {})
    entries = []
    for entry in enriched.get("experience_rewrites", []) or []:
        item = dict(entry)
        company = str(item.get("company", "")).strip()
        immutable_role = next(
            (exp["role"] for exp in grounding.get("immutable_facts", {}).get("experience", []) if exp["company"] == company),
            None,
        )
        raw_rewrites = item.get("bullet_rewrites") or []
        if isinstance(raw_rewrites, str):
            try:
                raw_rewrites = json.loads(raw_rewrites)
            except Exception:
                raw_rewrites = []
        bullet_rewrites = []
        for rewrite in raw_rewrites if isinstance(raw_rewrites, list) else []:
            rw = dict(rewrite)
            rw["allowed_evidence"] = {
                "immutable_role": immutable_role,
                "approved_terms": _terms_for_company(grounding, company),
                "approved_metrics": [
                    term
                    for term in _terms_for_company(grounding, company)
                    if re.search(r"\d", term)
                ],
            }
            bullet_rewrites.append(rw)
        item["bullet_rewrites"] = bullet_rewrites
        item["allowed_evidence"] = {
            "company": company,
            "immutable_role": immutable_role,
            "approved_terms": _terms_for_company(grounding, company),
        }
        entries.append(item)
    enriched["experience_rewrites"] = entries
    enriched["grounding_rules"] = grounding.get("forbidden_global_claims", [])
    return enriched


def enrich_cover_strategy_with_grounding(strategy: dict[str, Any], grounding: dict[str, Any]) -> dict[str, Any]:
    """Attach per-source allowed_evidence to each cover paragraph.

    Crucially, `allowed_evidence` is scoped BY SOURCE rather than unioned into a
    flat list. Unioning lets the LLM combine terms from separate projects under
    the same employer (e.g. claiming the RAG chatbot runs on AWS ECS because
    both live under UCOP). Per-source scoping makes the boundaries explicit.
    """
    enriched = dict(strategy or {})
    raw_structure = enriched.get("structure", []) or []
    if isinstance(raw_structure, str):
        try:
            raw_structure = json.loads(raw_structure)
        except Exception:
            raw_structure = []
    company_terms = grounding.get("approved_sources", {}).get("company_terms", {}) or {}
    company_aliases = grounding.get("approved_sources", {}).get("company_aliases", {}) or {}
    projects = grounding.get("approved_sources", {}).get("projects", {}) or {}

    def _source_matches_company(source_str_lower: str, company_name: str) -> bool:
        company_lower = company_name.lower()
        if company_lower in source_str_lower:
            return True
        for alias in company_aliases.get(company_name, []) or []:
            alias_lower = alias.lower()
            if alias_lower and alias_lower in source_str_lower:
                return True
        return False
    structure = []
    for paragraph in raw_structure:
        item = dict(paragraph)
        sources = item.get("experience_sources", [])
        if not isinstance(sources, list):
            sources = [sources]
        allowed_by_source: dict[str, list[str]] = {}
        narrative_text = " ".join(
            str(item.get(k, "")) for k in ("narrative_angle", "theme", "focus", "connection_to_role")
        ).lower()
        for source in sources:
            source_str = str(source).strip()
            if not source_str:
                continue
            source_terms: list[str] = []
            # Employer-level terms when the source names a known company
            # (match the full company name OR any configured alias like
            # "UCOP", "GWR").
            source_str_lower = source_str.lower()
            for company, terms in company_terms.items():
                if _source_matches_company(source_str_lower, company):
                    source_terms.extend(terms)
                    break
            # Project-level terms when the paragraph's narrative or source
            # string mentions a known project key. A project's terms are
            # only added when that project is explicitly referenced — this
            # prevents Coraline terms from bleeding into a rag_chatbot
            # paragraph and vice versa.
            #
            # Matching tries project_key.replace("_", " ") first, then any
            # project-provided match_keywords. Keywords are needed because
            # the strategy LLM rarely writes the exact key (e.g. it writes
            # "RAG security chatbot" rather than "rag chatbot") so a literal
            # key match misses common phrasings.
            scope_text = f"{source_str.lower()} {narrative_text}"
            for project_key, project in projects.items():
                project_label = project_key.replace("_", " ")
                triggers = [project_label]
                triggers.extend(project.get("match_keywords", []) or [])
                if any(trigger and trigger in scope_text for trigger in triggers):
                    source_terms.extend(project.get("approved_terms", []))
            if source_terms:
                allowed_by_source[source_str] = sorted(
                    {_normalize_text(term) for term in source_terms if term}
                )
        item["allowed_evidence_by_source"] = allowed_by_source
        # Keep a flat list for backwards compatibility with any consumer that
        # iterates over `allowed_evidence`, but the per-source mapping above
        # is what the LLM should be reading.
        item["allowed_evidence"] = sorted(
            {term for terms in allowed_by_source.values() for term in terms}
        )
        structure.append(item)
    enriched["structure"] = structure
    enriched["grounding_rules"] = grounding.get("forbidden_global_claims", [])
    return enriched


def build_grounding_audit(
    *,
    grounding: dict[str, Any],
    analysis: dict[str, Any] | None = None,
    resume_strategy: dict[str, Any] | None = None,
    cover_strategy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit: dict[str, Any] = {
        "precedence": grounding.get("precedence", []),
        "immutable_experience": grounding.get("immutable_facts", {}).get("experience", []),
        "requirements": [],
        "resume_rewrites": [],
        "cover_paragraphs": [],
    }
    if analysis:
        for req in analysis.get("requirements", []) or []:
            audit["requirements"].append(
                {
                    "jd_requirement": req.get("jd_requirement"),
                    "evidence": req.get("evidence"),
                    "allowed_evidence": req.get("allowed_evidence", {}),
                }
            )
    if resume_strategy:
        for entry in resume_strategy.get("experience_rewrites", []) or []:
            audit["resume_rewrites"].append(
                {
                    "company": entry.get("company"),
                    "allowed_evidence": entry.get("allowed_evidence", {}),
                    "bullet_rewrites": [
                        {
                            "baseline_topic": rw.get("baseline_topic"),
                            "jd_requirement_addressed": rw.get("jd_requirement_addressed"),
                            "allowed_evidence": rw.get("allowed_evidence", {}),
                        }
                        for rw in entry.get("bullet_rewrites", []) or []
                    ],
                }
            )
    if cover_strategy:
        for paragraph in cover_strategy.get("structure", []) or []:
            audit["cover_paragraphs"].append(
                {
                    "focus": paragraph.get("focus"),
                    "experience_sources": paragraph.get("experience_sources"),
                    "allowed_evidence": paragraph.get("allowed_evidence", []),
                }
            )
    return audit


def write_grounding_artifacts(
    output_dir: Path,
    *,
    grounding: dict[str, Any],
    analysis: dict[str, Any] | None = None,
    resume_strategy: dict[str, Any] | None = None,
    cover_strategy: dict[str, Any] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "grounding.json").write_text(json.dumps(grounding, indent=2), encoding="utf-8")
    audit = build_grounding_audit(
        grounding=grounding,
        analysis=analysis,
        resume_strategy=resume_strategy,
        cover_strategy=cover_strategy,
    )
    (output_dir / "grounding_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")


def grounding_prompt_block(grounding: dict[str, Any]) -> str:
    immutable = grounding.get("immutable_facts", {}).get("experience", [])
    approved = grounding.get("approved_sources", {})
    projects = approved.get("projects", {}) or {}
    lines = ["## Grounding Contract"]
    lines.append("Precedence:")
    for rule in grounding.get("precedence", []):
        lines.append(f"- {rule}")
    lines.append("Immutable employer facts:")
    for exp in immutable:
        lines.append(f"- {exp['company']} | role: {exp['role']} | dates: {exp['dates']}")
    if projects:
        lines.append("Discrete projects (do not mix implementation details between them):")
        for project_key, project in projects.items():
            label = project.get("label", project_key)
            lines.append(f"- {project_key} — {label}")
            forbidden = project.get("forbidden_terms") or []
            if forbidden:
                lines.append(
                    f"  forbidden in {project_key} context: {', '.join(forbidden)}"
                )
    lines.append("Forbidden global claim classes:")
    for rule in grounding.get("forbidden_global_claims", []):
        lines.append(f"- {rule}")
    return "\n".join(lines)
