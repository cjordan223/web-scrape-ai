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


def build_grounding_context(
    *,
    baseline_tex: str | None = None,
    skills_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline_tex = baseline_tex or cfg.RESUME_TEX.read_text(encoding="utf-8")
    skills_data = skills_data or json.loads(cfg.SKILLS_JSON.read_text(encoding="utf-8"))
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

    companies = {item["company"]: item for item in experiences}
    company_terms = {
        "University of California, Office of the President": [
            "Coraline",
            "AWS ECS",
            "Flask",
            "React",
            "five disparate security and IT inventory sources",
            "five separate data sources",
            "hierarchical confidence matching",
            "hierarchical confidence-matching",
            "500 drifted assets",
            "500+ drifted asset records",
            "7,000+ endpoints",
            "LangChain",
            "vector databases",
            "NLP",
            "retrieval accuracy",
            "source attribution",
            "AI governance",
            "audit trails",
            "operational guardrails",
            "review standards",
            "macOS",
            "Windows",
            "CrowdStrike RTR",
            "Defender",
            "runbooks",
            "10,000+ macOS and Windows devices",
            "2,900-user identity portal",
            "MFA providers",
            "network security protocols",
        ],
        "Great Wolf Resorts": [
            "hybrid Azure tenant",
            "Python",
            "PowerShell",
            "endpoint agent updates",
            "patching",
            "BitLocker",
            "10,000+ devices",
            "CrowdStrike RTR",
            "200 hours annually",
            "Microsoft Graph API",
            "10,000+ users",
            "Rapid7",
            "Pandas",
            "NumPy",
            "KnowBe4",
            "25 percent",
            "analytics tooling",
            "agent health monitoring",
        ],
        "Simple.biz": [
            "CI/CD pipelines",
            "automated build and deployment scripts",
            "Selenium",
            "WCAG/ADA",
            "cross-browser",
            "cross-device",
            "30 percent reduction in user-reported issues",
        ],
    }
    approved_projects = {
        "phishfinder": {
            "label": "school capstone project",
            "approved_terms": [
                "PhishFinder",
                "browser extension frontend",
                "Chrome extension",
                "Python backend API",
                "SPF",
                "DKIM",
                "DMARC",
                "NLP",
                "LLM-based classification",
                "real-time URL analysis",
                "Most Innovative Project",
                "2024 Capstone Festival",
            ],
        },
        "rag_chatbot": {
            "label": "internal SecOps knowledge tool",
            "approved_terms": [
                "RAG-based security knowledge chatbot",
                "LangChain",
                "vector databases",
                "retrieval accuracy",
                "source attribution",
                "SecOps knowledge",
                "auditability",
            ],
            "forbidden_terms": [
                "AWS Lambda",
                "Step Functions",
                "SNS",
                "SQS",
                "latency constraints",
                "SLA-backed uptime",
                "alongside Coraline",
                "technical standard for future AI deployments",
            ],
        },
    }
    return {
        "precedence": [
            "Immutable employment facts come from the baseline resume.",
            "Approved optional narrative detail may come from persona files.",
            "Skills inventory authorizes skills claims, not employer-specific implementation history.",
        ],
        "immutable_facts": {
            "candidate_name": skills_data.get("candidate_profile", {}).get("name", "Conner Jordan"),
            "target_roles": skills_data.get("candidate_profile", {}).get("target_roles", []),
            "experience": experiences,
        },
        "approved_sources": {
            "persona_files": sorted(persona_texts.keys()),
            "skills_terms": sorted({_normalize_text(str(term)) for term in approved_skill_terms if str(term).strip()}),
            "company_terms": company_terms,
            "projects": approved_projects,
            "approved_ai_details": [
                "LangChain",
                "vector databases",
                "retrieval accuracy",
                "source attribution",
                "audit trails",
                "operational guardrails",
            ],
            "approved_identity_details": [
                "MFA providers",
                "identity portal",
                "network security protocols",
                "IAM coordination",
            ],
            "approved_compliance_details": [
                "auditability",
                "audit-ready governance",
                "operational guardrails",
            ],
        },
        "high_risk_patterns": {
            "role_title_renamed": {
                "message": "Baseline employer role titles are immutable and must not be rewritten.",
            },
            "unsupported_tool_claim": [
                r"\bTerraform\b",
                r"\bAnsible\b",
                r"\bAzure DevOps\b",
            ],
            "unsupported_compliance_claim": [
                r"\bSOC ?2\b",
                r"\bHIPAA\b",
                r"\bNIST\b",
                r"\bISO 27001\b",
            ],
            "unsupported_identity_stack_claim": [
                r"\bOkta\b",
                r"\bActive Directory\b",
                r"\bSCCM\b",
                r"\bJAMF\b",
                r"\bServiceNow\b",
                r"\bEntra ID\b",
                r"\bPAM\b",
                r"\bzero-trust\b",
            ],
            "unsupported_ai_deployment_claim": [
                r"RAG chatbot.*AWS ECS",
                r"AWS ECS.*RAG chatbot",
                r"\bAWS Lambda\b",
                r"\bStep Functions\b",
                r"\bSNS\b",
                r"\bSQS\b",
                r"\balongside Coraline\b",
                r"\blatency constraints\b",
                r"\bSLA-backed uptime\b",
                r"\btechnical standard for future AI deployments\b",
            ],
            "unsupported_operational_mechanic_claim": [
                r"\bidempotent\b",
                r"\brollback\b",
                r"\bcanary\b",
            ],
            "unsupported_scale_claim": [
                r"\b20\+ internal teams\b",
                r"\bhundreds of devices\b",
            ],
        },
        "forbidden_global_claims": [
            "Do not rename prior job titles to target-role titles.",
            "Do not attach unsupported tools, frameworks, identity platforms, compliance regimes, or deployment topology to prior employer work.",
            "Do not infer implementation mechanics from persona style text.",
        ],
    }


def _terms_for_company(grounding: dict[str, Any], company: str) -> list[str]:
    return list((grounding.get("approved_sources", {}).get("company_terms", {}) or {}).get(company, []))


def _find_company_from_text(text: str, grounding: dict[str, Any]) -> str | None:
    lowered = text.lower()
    for company in (grounding.get("approved_sources", {}).get("company_terms", {}) or {}):
        if company.lower() in lowered:
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
        raw_rewrites = item.get("bullet_rewrites", [])
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
    enriched = dict(strategy or {})
    raw_structure = enriched.get("structure", []) or []
    if isinstance(raw_structure, str):
        try:
            raw_structure = json.loads(raw_structure)
        except Exception:
            raw_structure = []
    structure = []
    for paragraph in raw_structure:
        item = dict(paragraph)
        sources = item.get("experience_sources", [])
        if not isinstance(sources, list):
            sources = [sources]
        approved_terms: list[str] = []
        for source in sources:
            text = str(source)
            for company in (grounding.get("approved_sources", {}).get("company_terms", {}) or {}):
                if company.lower() in text.lower():
                    approved_terms.extend(_terms_for_company(grounding, company))
            for project_key, project in (grounding.get("approved_sources", {}).get("projects", {}) or {}).items():
                if project_key.replace("_", " ") in text.lower():
                    approved_terms.extend(project.get("approved_terms", []))
        item["allowed_evidence"] = sorted({_normalize_text(term) for term in approved_terms if term})
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
    lines = ["## Grounding Contract"]
    lines.append("Precedence:")
    for rule in grounding.get("precedence", []):
        lines.append(f"- {rule}")
    lines.append("Immutable employer facts:")
    for exp in immutable:
        lines.append(f"- {exp['company']} | role: {exp['role']} | dates: {exp['dates']}")
    lines.append("Forbidden global claim classes:")
    for rule in grounding.get("forbidden_global_claims", []):
        lines.append(f"- {rule}")
    return "\n".join(lines)
