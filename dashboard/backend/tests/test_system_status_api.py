"""Tests for /api/scraper/system/status endpoint."""
import os
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as server  # noqa: E402


class TestSystemStatusAPI(unittest.TestCase):
    def test_status_endpoint_returns_schema(self):
        client = TestClient(server.app)
        resp = client.get("/api/scraper/system/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        for key in ("scheduler", "profile", "llm_gate", "tiers", "feature_flags"):
            self.assertIn(key, data)

        self.assertIn("enabled", data["scheduler"])
        self.assertIn("cadence", data["scheduler"])
        self.assertIn("rotation_groups", data["profile"])
        self.assertIn("seen_ttl_days", data["profile"])

        tiers = {row["tier"] for row in data["tiers"]}
        self.assertIn("workhorse", tiers)
        self.assertIn("discovery", tiers)
        self.assertIn("lead", tiers)

    def test_scheduler_enabled_reflects_env_var(self):
        old = os.environ.get("TEXTAILOR_SCRAPE_SCHEDULER")
        os.environ["TEXTAILOR_SCRAPE_SCHEDULER"] = "1"
        try:
            client = TestClient(server.app)
            resp = client.get("/api/scraper/system/status")
            self.assertTrue(resp.json()["scheduler"]["enabled"])
        finally:
            if old is None:
                os.environ.pop("TEXTAILOR_SCRAPE_SCHEDULER", None)
            else:
                os.environ["TEXTAILOR_SCRAPE_SCHEDULER"] = old


if __name__ == "__main__":
    unittest.main()
