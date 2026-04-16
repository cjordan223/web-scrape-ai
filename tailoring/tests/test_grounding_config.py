import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tailor import grounding


class TestGroundingConfig(unittest.TestCase):
    def setUp(self) -> None:
        grounding.clear_grounding_cache()

    def tearDown(self) -> None:
        grounding.clear_grounding_cache()

    def test_build_grounding_context_loads_external_config(self):
        custom_config = {
            "version": 1,
            "precedence": ["Rule A", "Rule B"],
            "approved_sources": {
                "company_terms": {
                    "Example Corp": ["Alpha System", "Beta Tool"]
                },
                "projects": {
                    "project_x": {
                        "label": "example project",
                        "approved_terms": ["Project X", "Example Metric"],
                        "forbidden_terms": ["Invented Tool"],
                    }
                },
                "approved_ai_details": ["Retrieval"],
                "approved_identity_details": ["MFA"],
                "approved_compliance_details": ["Auditability"],
            },
            "high_risk_patterns": {
                "role_title_renamed": {"message": "Do not rename roles."},
                "unsupported_tool_claim": ["\\bTerraform\\b"],
            },
            "forbidden_global_claims": ["Do not invent employer facts."],
        }

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "grounding.json"
            path.write_text(json.dumps(custom_config), encoding="utf-8")
            with patch.object(grounding.cfg, "GROUNDING_CONFIG", path):
                context = grounding.build_grounding_context()

        self.assertEqual(context["version"], 1)
        self.assertEqual(context["precedence"], ["Rule A", "Rule B"])
        self.assertEqual(
            context["approved_sources"]["company_terms"]["Example Corp"],
            ["Alpha System", "Beta Tool"],
        )
        self.assertEqual(
            context["approved_sources"]["projects"]["project_x"]["forbidden_terms"],
            ["Invented Tool"],
        )
        self.assertEqual(
            context["high_risk_patterns"]["role_title_renamed"]["message"],
            "Do not rename roles.",
        )
        self.assertEqual(
            context["forbidden_global_claims"],
            ["Do not invent employer facts."],
        )

    def test_load_grounding_contract_rejects_invalid_schema(self):
        invalid_config = {
            "version": 1,
            "precedence": "not-a-list",
            "approved_sources": {},
            "high_risk_patterns": {},
            "forbidden_global_claims": [],
        }

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "grounding.json"
            path.write_text(json.dumps(invalid_config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "precedence must be a list of strings"):
                grounding._load_grounding_contract(path)

    def test_load_grounding_contract_rejects_missing_file(self):
        missing = Path("/tmp/does-not-exist-grounding-config.json")
        with self.assertRaisesRegex(ValueError, "Grounding config not found"):
            grounding._load_grounding_contract(missing)


if __name__ == "__main__":
    unittest.main()
