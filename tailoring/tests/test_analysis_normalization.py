import json
import tempfile
import unittest
from pathlib import Path

from tailor.analyzer import load_cached_analysis, normalize_analysis
from tailor.selector import SelectedJob


class TestAnalysisNormalization(unittest.TestCase):
    def test_normalize_analysis_coerces_string_matched_skills_to_list(self):
        analysis = {
            "company_context": {"company_type": "platform_devops"},
            "requirements": [
                {
                    "jd_requirement": "Build deployment tooling",
                    "matched_category": "DevSecOps",
                    "matched_skills": "CI/CD pipelines, Infrastructure as Code, Operational reliability practices",
                    "priority": "HIGH",
                }
            ],
        }

        normalized = normalize_analysis(analysis)

        self.assertEqual(
            normalized["requirements"][0]["matched_skills"],
            ["CI/CD pipelines", "Infrastructure as Code", "Operational reliability practices"],
        )
        self.assertEqual(normalized["requirements"][0]["priority"], "high")

    def test_load_cached_analysis_normalizes_legacy_string_matched_skills(self):
        job = SelectedJob(
            id=441,
            url="https://example.com/job/441",
            title="Role",
            board="workday",
            seniority="mid",
            jd_text="desc",
            snippet="desc",
            company="example",
        )

        payload = {
            "_job_id": 441,
            "_job_url": "https://example.com/job/441",
            "company_context": {"company_type": "platform_devops"},
            "requirements": [
                {
                    "matched_skills": "Docker, Kubernetes, ArgoCD",
                    "priority": "medium",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "analysis.json").write_text(json.dumps(payload), encoding="utf-8")
            analysis = load_cached_analysis(job, out)

        self.assertIsNotNone(analysis)
        self.assertEqual(analysis["requirements"][0]["matched_skills"], ["Docker", "Kubernetes", "ArgoCD"])


if __name__ == "__main__":
    unittest.main()
