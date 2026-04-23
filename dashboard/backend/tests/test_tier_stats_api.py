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
            ,
            rotation_members TEXT,
            trigger_source TEXT DEFAULT 'scheduled',
            llm_review TEXT,
            llm_review_at TEXT
        );
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            title TEXT,
            company TEXT,
            board TEXT,
            source TEXT,
            status TEXT,
            rejection_stage TEXT,
            rejection_reason TEXT,
            seniority TEXT,
            experience_years INTEGER,
            salary_k REAL,
            score REAL,
            run_id TEXT,
            created_at TEXT
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
            llm_overflow INTEGER DEFAULT 0,
            stored_pending INTEGER DEFAULT 0,
            stored_lead INTEGER DEFAULT 0,
            duration_ms INTEGER
        );
        INSERT INTO runs (
            run_id, started_at, completed_at, elapsed, raw_count, dedup_count,
            filtered_count, error_count, status, net_new, gate_mode,
            rotation_group, rotation_members, trigger_source, llm_review, llm_review_at
        )
            VALUES (
                'r1', datetime('now', '-1 day'), datetime('now', '-1 day', '+4 minutes'),
                240, 40, 30, 12, 0, 'completed', 12, 'normal', 0,
                '["greenhouse", "lever"]', 'scheduled',
                '{"health": "green", "summary": "healthy run", "flags": [], "recommendations": []}',
                datetime('now', '-1 day', '+5 minutes')
            );
        INSERT INTO jobs (url, title, company, board, source, status, run_id, created_at)
            VALUES
            ('https://example.test/a', 'Platform Engineer', 'Example', 'greenhouse', 'greenhouse', 'qa_pending', 'r1', datetime('now')),
            ('https://example.test/b', 'Rejected Engineer', 'Example', 'lever', 'lever', 'rejected', 'r1', datetime('now'));
        INSERT INTO run_tier_stats VALUES
            ('r1', 'searxng', 'discovery', 40, 10, 5, 8, 2, 0, 10, 5, 1200);
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

    def test_scraper_reports_endpoint_returns_list_and_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.db"
            _seed_tier_stats_db(db_path)
            old_db = server.DB_PATH
            server.DB_PATH = str(db_path)
            try:
                client = TestClient(server.app)
                reports_resp = client.get("/api/scraper/reports?limit=10")
                self.assertEqual(reports_resp.status_code, 200)
                reports = reports_resp.json()["items"]
                self.assertEqual(len(reports), 1)
                self.assertEqual(reports[0]["run_id"], "r1")
                self.assertEqual(reports[0]["summary"]["net_new"], 12)
                self.assertEqual(reports[0]["summary"]["jobs"], 2)
                self.assertEqual(reports[0]["review_health"], "green")

                detail_resp = client.get("/api/scraper/reports/r1")
                self.assertEqual(detail_resp.status_code, 200)
                detail = detail_resp.json()["report"]
                self.assertEqual(detail["review"]["summary"], "healthy run")
                self.assertEqual(detail["rotation_members"], ["greenhouse", "lever"])
                self.assertEqual(len(detail["tier_stats"]), 1)
                self.assertEqual(len(detail["jobs"]), 2)
            finally:
                server.DB_PATH = old_db


if __name__ == "__main__":
    unittest.main()
