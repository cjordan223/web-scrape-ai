import json
import tempfile
import unittest
from pathlib import Path

from tailor import config as cfg
from tailor.persona import PersonaStore, _keyword_matches


class TestPersonaVignettes(unittest.TestCase):
    def test_vignette_categories_are_declared_in_skills_inventory(self):
        skills_data = json.loads(cfg.SKILLS_JSON.read_text(encoding="utf-8"))
        declared = {
            category["name"]
            for category in skills_data["skills_inventory"]["core_skills"]
        }
        store = PersonaStore(cfg.PERSONA_DIR)

        orphaned = {
            vignette.path.name: [
                category for category in vignette.skill_categories
                if category not in declared
            ]
            for vignette in store._vignettes
        }
        orphaned = {name: cats for name, cats in orphaned.items() if cats}

        self.assertEqual(orphaned, {})

    def test_vignette_keywords_overlap_declared_category_skills(self):
        skills_data = json.loads(cfg.SKILLS_JSON.read_text(encoding="utf-8"))
        inventory = skills_data["skills_inventory"]
        category_skills = {
            category["name"]: set(category["skills"])
            for category in inventory["core_skills"]
        }
        shared_skill_names = set()
        for key in (
            "programming_languages",
            "databases",
            "frameworks_and_infrastructure",
            "security_tooling",
            "devops_and_cloud",
        ):
            shared_skill_names.update(inventory.get(key, []))
        for values in inventory.get("tools_and_platforms", {}).values():
            shared_skill_names.update(values)

        store = PersonaStore(cfg.PERSONA_DIR)
        missing_overlap = []
        for vignette in store._vignettes:
            allowed_skills = set(shared_skill_names)
            for category in vignette.skill_categories:
                allowed_skills.update(category_skills.get(category, set()))
            allowed_skills = {skill.lower() for skill in allowed_skills}
            if not any(_keyword_matches(keyword, allowed_skills) for keyword in vignette.keywords):
                missing_overlap.append(vignette.path.name)

        self.assertEqual(missing_overlap, [])

    def test_selector_matches_phrase_variants_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            persona = Path(td)
            (persona / "identity.md").write_text("Candidate", encoding="utf-8")
            (persona / "vignettes").mkdir()
            (persona / "vignettes" / "short.md").write_text(
                "---\n"
                "skill_categories: [Cloud Security]\n"
                "company_types: []\n"
                "keywords: [ECS]\n"
                "---\n"
                "Short ECS story.",
                encoding="utf-8",
            )
            (persona / "vignettes" / "long.md").write_text(
                "---\n"
                "skill_categories: [Cloud Security]\n"
                "company_types: []\n"
                "keywords: [AWS ECS deployments]\n"
                "---\n"
                "Longer ECS deployment story with enough text to lose a density tie.",
                encoding="utf-8",
            )

            store = PersonaStore(persona)
            analysis = {
                "requirements": [
                    {
                        "matched_category": "Cloud Security",
                        "matched_skills": ["AWS ECS deployments"],
                    }
                ]
            }

            first = [v.path.stem for v in store.select_vignettes(analysis, 500)]
            second = [v.path.stem for v in store.select_vignettes(analysis, 500)]

        self.assertEqual(first, second)
        self.assertEqual(first, ["short", "long"])

    def test_diverse_selection_uses_primary_category_only(self):
        with tempfile.TemporaryDirectory() as td:
            persona = Path(td)
            (persona / "identity.md").write_text("Candidate", encoding="utf-8")
            (persona / "vignettes").mkdir()
            (persona / "vignettes" / "identity.md").write_text(
                "---\n"
                "skill_categories: [Identity and Access, Cloud Security]\n"
                "company_types: []\n"
                "keywords: []\n"
                "---\n"
                "Identity story.",
                encoding="utf-8",
            )
            (persona / "vignettes" / "cloud.md").write_text(
                "---\n"
                "skill_categories: [Cloud Security]\n"
                "company_types: []\n"
                "keywords: []\n"
                "---\n"
                "Cloud story.",
                encoding="utf-8",
            )

            store = PersonaStore(persona)
            analysis = {
                "requirements": [
                    {"matched_category": "Identity and Access", "matched_skills": []},
                    {"matched_category": "Cloud Security", "matched_skills": []},
                ]
            }
            selected = [
                v.path.stem
                for v in store.select_vignettes(analysis, 500, diverse=True)
            ]

        self.assertEqual(selected, ["identity", "cloud"])


if __name__ == "__main__":
    unittest.main()
