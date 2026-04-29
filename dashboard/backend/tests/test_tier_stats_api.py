"""Tests for /api/scraper/metrics/tier-stats rollup endpoint."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as server  # noqa: E402


def _seed_tier_stats_db(db_path: Path, *, duplicate_columns: bool = True, fingerprint_table: bool = True) -> None:
    conn = sqlite3.connect(db_path)
    duplicate_schema = """
            duplicate_url INTEGER DEFAULT 0,
            duplicate_ats_id INTEGER DEFAULT 0,
            duplicate_fingerprint INTEGER DEFAULT 0,
            duplicate_similar INTEGER DEFAULT 0,
            duplicate_content INTEGER DEFAULT 0,
            reposts INTEGER DEFAULT 0,
            changed_postings INTEGER DEFAULT 0,
    """ if duplicate_columns else ""
    duplicate_values = "2, 1, 1, 3, 0, 0, 0," if duplicate_columns else ""
    fingerprint_schema = """
        CREATE TABLE job_fingerprints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            canonical_url TEXT,
            ats_provider TEXT,
            ats_job_id TEXT,
            company_norm TEXT,
            title_norm TEXT,
            location_bucket TEXT,
            remote_flag TEXT,
            salary_bucket TEXT,
            fingerprint TEXT,
            content_hash TEXT,
            duplicate_status TEXT,
            duplicate_of_job_id INTEGER
        );
    """ if fingerprint_table else ""
    fingerprint_insert = """
        INSERT INTO job_fingerprints (
            job_id, canonical_url, ats_provider, ats_job_id, company_norm,
            title_norm, location_bucket, remote_flag, salary_bucket,
            fingerprint, content_hash, duplicate_status, duplicate_of_job_id
        )
            VALUES (
                1, 'https://job-boards.greenhouse.io/example/jobs/12345',
                'greenhouse', '12345', 'example', 'platform-engineer',
                'us-remote', 'true', 'unknown',
                'example|platform-engineer|us-remote|true|unknown',
                'abc123', 'changed_posting', 99
            );
    """ if fingerprint_table else ""
    conn.executescript(
        f"""
        {fingerprint_schema}
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
{duplicate_schema}
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
                '{{"health": "green", "summary": "healthy run", "flags": [], "recommendations": []}}',
                datetime('now', '-1 day', '+5 minutes')
            );
        INSERT INTO jobs (url, title, company, board, source, status, run_id, created_at)
            VALUES
            ('https://example.test/a', 'Platform Engineer', 'Example', 'greenhouse', 'greenhouse', 'qa_pending', 'r1', datetime('now')),
            ('https://example.test/b', 'Rejected Engineer', 'Example', 'lever', 'lever', 'rejected', 'r1', datetime('now'));
        INSERT INTO jobs (id, url, title, company, board, source, status, run_id, created_at)
            VALUES
            (99, 'https://example.test/original', 'Platform Engineer Original', 'Example', 'greenhouse', 'greenhouse', 'qa_pending', 'old-run', datetime('now', '-10 days'));
        INSERT INTO run_tier_stats VALUES
            ('r1', 'searxng', 'discovery', 40, 10, {duplicate_values} 5, 8, 2, 0, 10, 5, 1200);
        {fingerprint_insert}
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
                self.assertEqual(data["by_source"][0]["duplicate_url"], 2)
                self.assertEqual(data["by_source"][0]["duplicate_similar"], 3)
            finally:
                server.DB_PATH = old_db

    def test_tier_stats_endpoint_handles_legacy_duplicate_columns_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.db"
            _seed_tier_stats_db(db_path, duplicate_columns=False)
            old_db = server.DB_PATH
            server.DB_PATH = str(db_path)
            try:
                client = TestClient(server.app)
                resp = client.get("/api/scraper/metrics/tier-stats?since=7d")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["by_source"][0]["duplicate_url"], 0)
                self.assertEqual(data["by_source"][0]["duplicate_similar"], 0)
                detail_resp = client.get("/api/scraper/reports/r1")
                self.assertEqual(detail_resp.status_code, 200)
                detail = detail_resp.json()["report"]
                self.assertEqual(detail["tier_stats"][0]["duplicate_url"], 0)
                self.assertEqual(detail["tier_stats"][0]["duplicate_similar"], 0)
            finally:
                server.DB_PATH = old_db

    def test_scraper_report_detail_handles_missing_fingerprint_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.db"
            _seed_tier_stats_db(db_path, fingerprint_table=False)
            old_db = server.DB_PATH
            server.DB_PATH = str(db_path)
            try:
                client = TestClient(server.app)
                detail_resp = client.get("/api/scraper/reports/r1")
                self.assertEqual(detail_resp.status_code, 200)
                job = detail_resp.json()["report"]["jobs"][0]
                self.assertIn("duplicate_status", job)
                self.assertIsNone(job["duplicate_status"])
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
                matched = next(j for j in detail["jobs"] if j["id"] == 1)
                self.assertEqual(matched["duplicate_status"], "changed_posting")
                self.assertEqual(matched["duplicate_of_job_id"], 99)
                self.assertEqual(matched["duplicate_of_title"], "Platform Engineer Original")
                self.assertEqual(matched["ats_provider"], "greenhouse")
                self.assertEqual(matched["ats_job_id"], "12345")
                self.assertEqual(matched["location_bucket"], "us-remote")
            finally:
                server.DB_PATH = old_db


if __name__ == "__main__":
    unittest.main()
