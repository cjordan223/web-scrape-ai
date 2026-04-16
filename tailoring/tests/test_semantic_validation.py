"""Tests for post-analysis semantic validation (issue #13)."""

import unittest

from tailor.semantic_validator import (
    SemanticValidationResult,
    validate_analysis_semantics,
)

# Minimal skills_data fixture with a few real categories and skills
_SKILLS_DATA = {
    "skills_inventory": {
        "core_skills": [
            {
                "name": "Full-Stack Development",
                "skills": ["React.js", "TypeScript", "Python backend development"],
            },
            {
                "name": "Security Engineering",
                "skills": ["Vulnerability remediation automation", "Zero-day response engineering"],
            },
        ],
        "supporting_skills": [],
        "programming_languages": ["Python", "TypeScript", "Java"],
        "databases": ["PostgreSQL", "SQLite"],
        "frameworks_and_infrastructure": ["Flask", "FastAPI", "Docker"],
        "security_tooling": ["CrowdStrike Falcon", "CrowdStrike RTR"],
        "devops_and_cloud": ["AWS", "AWS ECS", "GitHub Actions"],
        "tools_and_platforms": {
            "data_and_ai": ["LangChain", "RAG pipelines"],
        },
    }
}

# Minimal baseline resume LaTeX with realistic structure
_BASELINE_TEX = r"""
\resumeSubheading
  {University of California, Office of the President}{Oakland, CA}
  {Security Engineer}{Jan 2023 -- Present}
\resumeItemListStart
  \resumeItem{Designed and built Coraline, an open-source-ready Dockerized Flask \& React security tool on AWS ECS that ingests and correlates data from five disparate security and IT inventory sources.}
  \resumeItem{Engineered an AI/ML-powered RAG security chatbot using LangChain, vector databases, and NLP techniques.}
\resumeItemListEnd
\resumeSubHeadingListEnd

\resumeSubheading
  {Great Wolf Resorts}{Remote}
  {Security Analyst}{Jun 2021 -- Dec 2022}
\resumeItemListStart
  \resumeItem{Built and maintained Python and PowerShell security automation tools for hybrid Azure tenant management.}
\resumeItemListEnd
\resumeSubHeadingListEnd
"""


class TestSemanticValidation(unittest.TestCase):
    def _make_analysis(self, requirements: list[dict]) -> dict:
        return {
            "company_name": "TestCo",
            "role_title": "Software Engineer",
            "company_context": {},
            "requirements": requirements,
            "grounding_contract": {},
            "tone_notes": "",
            "summary_angle": "",
        }

    def test_valid_analysis_passes_clean(self):
        analysis = self._make_analysis([
            {
                "jd_requirement": "Build web apps",
                "matched_category": "Full-Stack Development",
                "matched_skills": ["React.js", "TypeScript"],
                "evidence": "At University of California, Office of the President: Designed and built Coraline, an open-source-ready Dockerized Flask & React security tool on AWS ECS",
                "priority": "high",
                "allowed_evidence": {},
            },
        ])
        repaired, result = validate_analysis_semantics(
            analysis, skills_data=_SKILLS_DATA, baseline_tex=_BASELINE_TEX,
        )
        self.assertTrue(result.clean)
        self.assertEqual(len(repaired["requirements"]), 1)
        self.assertEqual(repaired["requirements"][0]["matched_skills"], ["React.js", "TypeScript"])

    def test_unsupported_skill_is_dropped(self):
        analysis = self._make_analysis([
            {
                "jd_requirement": "Kubernetes orchestration",
                "matched_category": "Full-Stack Development",
                "matched_skills": ["React.js", "Kubernetes", "Terraform"],
                "evidence": "At University of California, Office of the President: Designed and built Coraline, an open-source-ready Dockerized Flask & React security tool on AWS ECS",
                "priority": "high",
                "allowed_evidence": {},
            },
        ])
        repaired, result = validate_analysis_semantics(
            analysis, skills_data=_SKILLS_DATA, baseline_tex=_BASELINE_TEX,
        )
        self.assertFalse(result.clean)
        # Kubernetes and Terraform should be dropped; React.js kept
        self.assertEqual(repaired["requirements"][0]["matched_skills"], ["React.js"])
        dropped = [i for i in result.issues if i.action == "dropped_skill"]
        self.assertEqual(len(dropped), 2)
        self.assertIn("Kubernetes", dropped[0].message)
        self.assertIn("Terraform", dropped[1].message)

    def test_fabricated_evidence_is_flagged(self):
        analysis = self._make_analysis([
            {
                "jd_requirement": "Cloud infrastructure",
                "matched_category": "Full-Stack Development",
                "matched_skills": ["AWS"],
                "evidence": "Led migration of 500 microservices to Kubernetes at Netflix, reducing costs by 40%",
                "priority": "medium",
                "allowed_evidence": {},
            },
        ])
        repaired, result = validate_analysis_semantics(
            analysis, skills_data=_SKILLS_DATA, baseline_tex=_BASELINE_TEX,
        )
        self.assertFalse(result.clean)
        evidence_issues = [i for i in result.issues if i.field == "evidence"]
        self.assertEqual(len(evidence_issues), 1)
        self.assertIn("does not match baseline", evidence_issues[0].message)

    def test_requirement_dropped_when_no_valid_skills_and_bad_evidence(self):
        analysis = self._make_analysis([
            {
                "jd_requirement": "Build ML pipelines",
                "matched_category": "Full-Stack Development",
                "matched_skills": ["Kubernetes", "Terraform"],  # both invalid
                "evidence": "Deployed ML models to production at FakeCorp",  # bad evidence
                "priority": "high",
                "allowed_evidence": {},
            },
            {
                "jd_requirement": "Web development",
                "matched_category": "Full-Stack Development",
                "matched_skills": ["React.js"],
                "evidence": "At University of California, Office of the President: Designed and built Coraline, an open-source-ready Dockerized Flask & React security tool on AWS ECS",
                "priority": "high",
                "allowed_evidence": {},
            },
        ])
        repaired, result = validate_analysis_semantics(
            analysis, skills_data=_SKILLS_DATA, baseline_tex=_BASELINE_TEX,
        )
        # First requirement should be dropped entirely
        self.assertEqual(len(repaired["requirements"]), 1)
        self.assertEqual(repaired["requirements"][0]["jd_requirement"], "Web development")
        dropped_reqs = [i for i in result.issues if i.action == "dropped_requirement"]
        self.assertEqual(len(dropped_reqs), 1)

    def test_unknown_category_is_flagged(self):
        analysis = self._make_analysis([
            {
                "jd_requirement": "Quantum computing",
                "matched_category": "Quantum Engineering",
                "matched_skills": ["Python"],
                "evidence": "At Great Wolf Resorts: Built and maintained Python and PowerShell security automation tools",
                "priority": "low",
                "allowed_evidence": {},
            },
        ])
        repaired, result = validate_analysis_semantics(
            analysis, skills_data=_SKILLS_DATA, baseline_tex=_BASELINE_TEX,
        )
        category_issues = [i for i in result.issues if i.field == "matched_category"]
        self.assertEqual(len(category_issues), 1)
        self.assertIn("Quantum Engineering", category_issues[0].message)
        # Requirement kept (has valid skill + valid evidence)
        self.assertEqual(len(repaired["requirements"]), 1)

    def test_evidence_without_company_citation_flagged(self):
        analysis = self._make_analysis([
            {
                "jd_requirement": "Security automation",
                "matched_category": "Security Engineering",
                "matched_skills": ["Vulnerability remediation automation"],
                "evidence": "Built security automation tools for hybrid Azure tenant management",
                "priority": "high",
                "allowed_evidence": {},
            },
        ])
        repaired, result = validate_analysis_semantics(
            analysis, skills_data=_SKILLS_DATA, baseline_tex=_BASELINE_TEX,
        )
        evidence_issues = [i for i in result.issues if i.field == "evidence"]
        self.assertEqual(len(evidence_issues), 1)

    def test_empty_evidence_flagged(self):
        analysis = self._make_analysis([
            {
                "jd_requirement": "API design",
                "matched_category": "Full-Stack Development",
                "matched_skills": ["React.js"],
                "evidence": "",
                "priority": "medium",
                "allowed_evidence": {},
            },
        ])
        repaired, result = validate_analysis_semantics(
            analysis, skills_data=_SKILLS_DATA, baseline_tex=_BASELINE_TEX,
        )
        evidence_issues = [i for i in result.issues if i.field == "evidence"]
        self.assertTrue(len(evidence_issues) >= 1)

    def test_skill_matching_is_case_insensitive(self):
        analysis = self._make_analysis([
            {
                "jd_requirement": "Frontend",
                "matched_category": "Full-Stack Development",
                "matched_skills": ["react.js", "TYPESCRIPT"],  # different case
                "evidence": "At University of California, Office of the President: Designed and built Coraline, an open-source-ready Dockerized Flask & React security tool on AWS ECS",
                "priority": "high",
                "allowed_evidence": {},
            },
        ])
        repaired, result = validate_analysis_semantics(
            analysis, skills_data=_SKILLS_DATA, baseline_tex=_BASELINE_TEX,
        )
        # Both should pass despite case differences
        skills_issues = [i for i in result.issues if i.action == "dropped_skill"]
        self.assertEqual(len(skills_issues), 0)


if __name__ == "__main__":
    unittest.main()
