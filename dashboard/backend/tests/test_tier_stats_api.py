"""Tests for /api/scraper/metrics/tier-stats rollup endpoint."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as server  # noqa: E402


def _seed_tier_stats_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT,
            completed_at TEXT,
            elapsed REAL,
            raw_count INTEGER DEFAULT 0,
            dedup_count INTEGER DEFAULT 0,
            filtered_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            errors TEXT,
            status TEXT,
            net_new INTEGER DEFAULT 0,
            gate_mode TEXT,
            rotation_group INTEGER
        );
        CREATE TABLE run_tier_stats (
            run_id TEXT,
            source TEXT,
            tier TEXT,
            raw_hits INTEGER DEFAULT 0,
            dedup_drops INTEGER DEFAULT 0,
            filter_drops INTEGER DEFAULT 0,
            llm_rejects INTEGER DEFAULT 0,
            llm_uncertain_low INTEGER DEFAULT 0,
            stored_pending INTEGER DEFAULT 0,
            stored_lead INTEGER DEFAULT 0
        );
        INSERT INTO runs (run_id, started_at, status, net_new, gate_mode, rotation_group)
            VALUES ('r1', datetime('now', '-1 day'), 'completed', 12, 'normal', 0);
        INSERT INTO run_tier_stats VALUES
            ('r1', 'searxng', 'discovery', 40, 10, 5, 8, 2, 10, 5);
        """
    )
    conn.commit()
    conn.close()


class TestTierStatsAPI(unittest.TestCase):
    def test_tier_stats_endpoint_returns_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.db"
            _seed_tier_stats_db(db_path)
            old_db = server.DB_PATH
            server.DB_PATH = str(db_path)
            try:
                client = TestClient(server.app)
                resp = client.get("/api/scraper/metrics/tier-stats?since=7d")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertIn("per_run", data)
                self.assertIn("by_source", data)
                self.assertIn("daily_net_new", data)
                self.assertEqual(len(data["per_run"]), 1)
                self.assertEqual(data["by_source"][0]["source"], "searxng")
                self.assertEqual(data["by_source"][0]["tier"], "discovery")
            finally:
                server.DB_PATH = old_db


if __name__ == "__main__":
    unittest.main()
