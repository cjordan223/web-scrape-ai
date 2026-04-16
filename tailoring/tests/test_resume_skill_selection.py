import unittest

from tailor.writer import _select_resume_skills


class TestResumeSkillSelection(unittest.TestCase):
    def setUp(self):
        self.baseline_skills = {
            "Languages": ["Python", "TypeScript", "Go"],
            "Security Tooling": ["Vulnerability management", "SIEM"],
            "AI/ML and Research": ["RAG pipelines", "NLP"],
            "Frameworks and Infrastructure": ["Flask", "React.js"],
            "DevOps and CI/CD": ["CI/CD pipelines", "AWS/GCP/Azure"],
            "Databases": ["PostgreSQL", "SQLite", "vector databases"],
        }
        self.skills_data = {
            "skills_inventory": {
                "core_skills": [
                    {
                        "name": "AI-Native Development",
                        "skills": ["RAG pipelines", "LangChain", "Vector databases"],
                    },
                    {
                        "name": "Security Automation",
                        "skills": ["API-driven security workflows", "Runbook-driven automation"],
                    },
                ],
                "supporting_skills": [],
                "programming_languages": ["Python", "TypeScript", "Go"],
                "databases": ["PostgreSQL", "SQLite", "vector databases"],
                "frameworks_and_infrastructure": ["Flask", "React.js", "FastAPI"],
                "security_tooling": ["CrowdStrike RTR", "SIEM", "Vulnerability management"],
                "devops_and_cloud": ["CI/CD pipelines", "AWS/GCP/Azure", "GitHub Actions", "Terraform"],
                "tools_and_platforms": {
                    "data_and_ai": ["LangChain", "RAG pipelines", "NLP"],
                    "api_and_enterprise": ["Microsoft Graph API"],
                },
            }
        }

    def test_fixed_categories_reorder_without_dropping_items(self):
        analysis = {
            "requirements": [
                {
                    "matched_category": "Full-Stack Development",
                    "matched_skills": ["Go", "vector databases"],
                    "priority": "high",
                }
            ]
        }

        selected = _select_resume_skills(
            analysis,
            baseline_skills=self.baseline_skills,
            skills_data=self.skills_data,
        )

        self.assertEqual(selected["Languages"], ["Go", "Python", "TypeScript"])
        self.assertEqual(selected["Databases"], ["vector databases", "PostgreSQL", "SQLite"])

    def test_flexible_categories_promote_grounded_inventory_additions(self):
        analysis = {
            "requirements": [
                {
                    "matched_category": "DevSecOps",
                    "matched_skills": ["GitHub Actions", "Terraform"],
                    "priority": "high",
                },
                {
                    "matched_category": "Security Automation",
                    "matched_skills": ["CrowdStrike RTR"],
                    "priority": "medium",
                },
            ]
        }

        selected = _select_resume_skills(
            analysis,
            baseline_skills=self.baseline_skills,
            skills_data=self.skills_data,
        )

        self.assertEqual(selected["DevOps and CI/CD"], ["GitHub Actions", "Terraform"])
        self.assertIn("CrowdStrike RTR", selected["Security Tooling"])

    def test_selection_is_case_insensitive_and_stable(self):
        analysis = {
            "requirements": [
                {
                    "matched_category": "AI-Native Development",
                    "matched_skills": ["langchain", "RAG PIPELINES"],
                    "priority": "high",
                }
            ]
        }

        first = _select_resume_skills(
            analysis,
            baseline_skills=self.baseline_skills,
            skills_data=self.skills_data,
        )
        second = _select_resume_skills(
            analysis,
            baseline_skills=self.baseline_skills,
            skills_data=self.skills_data,
        )

        self.assertEqual(first, second)
        self.assertEqual(first["AI/ML and Research"], ["RAG pipelines", "LangChain"])


if __name__ == "__main__":
    unittest.main()
