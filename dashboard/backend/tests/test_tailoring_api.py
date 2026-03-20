import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as server


class TestTailoringAPI(unittest.TestCase):
    def _create_results_db(self, db_path: Path, *, with_approved_jd_text: bool = False) -> None:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE results (
                id INTEGER PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                board TEXT,
                seniority TEXT,
                experience_years INTEGER,
                salary_k INTEGER,
                score INTEGER,
                decision TEXT,
                snippet TEXT,
                query TEXT,
                jd_text TEXT,
                filter_verdicts TEXT,
                run_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE UNIQUE INDEX idx_results_url_run ON results(url, run_id)")
        if with_approved_jd_text:
            conn.execute("ALTER TABLE results ADD COLUMN approved_jd_text TEXT")
        conn.commit()
        conn.close()

    def _create_runs_table(self, db_path: Path) -> None:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                elapsed REAL,
                raw_count INTEGER DEFAULT 0,
                dedup_count INTEGER DEFAULT 0,
                filtered_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                errors TEXT,
                status TEXT NOT NULL DEFAULT 'running'
            )
            """
        )
        conn.commit()
        conn.close()

    def _insert_result(
        self,
        db_path: Path,
        *,
        job_id: int,
        title: str,
        url: str,
        decision: str = "qa_approved",
        snippet: str = "Short summary",
        jd_text: str = "Detailed JD text",
    ) -> None:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO results (
                id, url, title, board, seniority, experience_years, salary_k, score,
                decision, snippet, query, jd_text, filter_verdicts, run_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                url,
                title,
                "example",
                "senior",
                None,
                None,
                None,
                decision,
                snippet,
                "search-query",
                jd_text,
                None,
                f"run-{job_id}",
                "2026-03-14T00:00:00Z",
            ),
        )
        conn.commit()
        conn.close()

    def _create_complete_package(self, root: Path, slug: str, *, job_id: int, title: str = "Role", company: str = "ExampleCo") -> Path:
        run_dir = root / slug
        run_dir.mkdir(parents=True)
        (run_dir / "meta.json").write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "title": title,
                    "company": company,
                    "job_title": title,
                    "company_name": company,
                    "url": f"https://example.com/jobs/{job_id}",
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "analysis.json").write_text(json.dumps({"role_title": title, "key_requirements": ["Python", "Security"]}), encoding="utf-8")
        (run_dir / "resume_strategy.json").write_text(json.dumps({"summary_strategy": "Lead with builder-operator experience."}), encoding="utf-8")
        (run_dir / "cover_strategy.json").write_text(json.dumps({"opening_angle": "Lead with the company challenge."}), encoding="utf-8")
        (run_dir / "Conner_Jordan_Resume.tex").write_text("resume tex", encoding="utf-8")
        (run_dir / "Conner_Jordan_Cover_Letter.tex").write_text("cover tex", encoding="utf-8")
        (run_dir / "Conner_Jordan_Resume.pdf").write_bytes(b"%PDF-resume")
        (run_dir / "Conner_Jordan_Cover_Letter.pdf").write_bytes(b"%PDF-cover")
        (run_dir / "llm_trace.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"event_type": "doc_attempt_result", "doc_type": "resume", "status": "passed", "attempt": 1, "timestamp": "2026-02-24T10:00:00+00:00"}),
                    json.dumps({"event_type": "validation_result", "doc_type": "resume", "passed": True, "attempt": 1, "timestamp": "2026-02-24T10:01:00+00:00"}),
                    json.dumps({"event_type": "doc_attempt_result", "doc_type": "cover", "status": "passed", "attempt": 1, "timestamp": "2026-02-24T10:02:00+00:00"}),
                    json.dumps({"event_type": "validation_result", "doc_type": "cover", "passed": True, "attempt": 1, "timestamp": "2026-02-24T10:03:00+00:00"}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return run_dir

    def test_tailoring_routes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "123-foo-role-2026-02-24"
            run_dir.mkdir(parents=True)

            (run_dir / "meta.json").write_text(json.dumps({"job_id": 123, "title": "Role"}), encoding="utf-8")
            (run_dir / "analysis.json").write_text("{}", encoding="utf-8")
            (run_dir / "llm_trace.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"event_type": "doc_attempt_result", "doc_type": "resume", "status": "passed", "attempt": 1, "timestamp": "2026-02-24T10:00:00+00:00"}),
                        json.dumps({"event_type": "validation_result", "doc_type": "resume", "passed": True, "attempt": 1, "timestamp": "2026-02-24T10:01:00+00:00"}),
                        json.dumps({"event_type": "doc_attempt_result", "doc_type": "cover", "status": "passed", "attempt": 1, "timestamp": "2026-02-24T10:02:00+00:00"}),
                        json.dumps({"event_type": "validation_result", "doc_type": "cover", "passed": True, "attempt": 1, "timestamp": "2026-02-24T10:03:00+00:00"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            old = server.TAILORING_OUTPUT_DIR
            server.TAILORING_OUTPUT_DIR = root
            client = TestClient(server.app)
            try:
                resp = client.get("/api/tailoring/runs")
                self.assertEqual(resp.status_code, 200)
                runs = resp.json()["runs"]
                self.assertEqual(len(runs), 1)
                self.assertEqual(runs[0]["status"], "complete")

                slug = runs[0]["slug"]
                resp = client.get(f"/api/tailoring/runs/{slug}/trace?doc_type=resume")
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(all(e.get("doc_type") == "resume" for e in resp.json()["events"]))

                resp = client.get(f"/api/tailoring/runs/{slug}/artifact/meta.json")
                self.assertEqual(resp.status_code, 200)

                resp = client.get(f"/api/tailoring/runs/{slug}/artifact/../../etc/passwd")
                self.assertIn(resp.status_code, (400, 404))

                resp = client.get("/api/packages?status=all")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(len(resp.json()["items"]), 1)

                resp = client.get(f"/api/packages/{slug}")
                self.assertEqual(resp.status_code, 200)
                self.assertIn("job_context", resp.json())

                resp = client.post(
                    f"/api/packages/{slug}/latex/resume",
                    json={"content": "test latex"},
                )
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json()["ok"])

                with patch("app._compile_tex_in_place", return_value=(True, None)):
                    resp = client.post(f"/api/packages/{slug}/compile/resume")
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json()["ok"])
                self.assertIsNone(resp.json()["error"])

                compile_error = "pdflatex pass 1 failed:\n! Missing } inserted."
                with patch("app._compile_tex_in_place", return_value=(False, compile_error)):
                    resp = client.post(f"/api/packages/{slug}/compile/resume")
                self.assertEqual(resp.status_code, 422)
                self.assertFalse(resp.json()["ok"])
                self.assertEqual(resp.json()["error"], compile_error)

                fake_regen = {
                    "ok": True,
                    "validation": {
                        "passed": True,
                        "failures": [],
                        "metrics": {"char_ratio": 0.95},
                    },
                }

                class FakeCompletedProcess:
                    def __init__(self, stdout: str):
                        self.returncode = 0
                        self.stdout = stdout
                        self.stderr = ""

                with patch("app._resolve_llm_runtime", return_value={
                    "chat_url": "http://127.0.0.1:1234/v1/chat/completions",
                    "models_url": "http://127.0.0.1:1234/v1/models",
                    "selected_model": "test-model",
                }), patch("app.subprocess.run", return_value=FakeCompletedProcess(json.dumps(fake_regen))), patch("app._compile_tex_in_place", return_value=(True, None)):
                    resp = client.post(f"/api/packages/{slug}/regenerate/cover")
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json()["ok"])
                self.assertEqual(resp.json()["pdf_name"], "Conner_Jordan_Cover_Letter.pdf")
                self.assertIn("detail", resp.json())
            finally:
                server.TAILORING_OUTPUT_DIR = old

    def test_llm_status_and_models_support_openai_compatible_provider(self):
        with tempfile.TemporaryDirectory() as td:
            old_controls = server.RUNTIME_CONTROLS_PATH
            server.RUNTIME_CONTROLS_PATH = Path(td) / "runtime_controls.json"
            server._save_runtime_controls(
                {
                    "llm_provider": "openai",
                    "llm_base_url": "http://127.0.0.1:4000",
                    "llm_model": "model-b",
                }
            )
            client = TestClient(server.app)

            class FakeResponse:
                def __init__(self, payload: dict):
                    self._payload = json.dumps(payload).encode("utf-8")

                def read(self):
                    return self._payload

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            def fake_urlopen(url, timeout=0):
                self.assertEqual(url, "http://127.0.0.1:4000/v1/models")
                return FakeResponse({"data": [{"id": "model-a"}, {"id": "model-b"}]})

            try:
                with patch("services.tailoring.urllib.request.urlopen", side_effect=fake_urlopen):
                    status = client.get("/api/llm/status")
                    self.assertEqual(status.status_code, 200)
                    self.assertEqual(status.json()["provider"], "openai")
                    self.assertEqual(status.json()["url"], "http://127.0.0.1:4000")
                    self.assertEqual(status.json()["selected_model"], "model-b")
                    self.assertFalse(status.json()["capabilities"]["manage_models"])

                    models = client.get("/api/llm/models")
                    self.assertEqual(models.status_code, 200)
                    body = models.json()
                    self.assertEqual(body["provider"], "openai")
                    self.assertEqual(body["models"][0]["state"], "available")
                    self.assertEqual(body["models"][1]["state"], "loaded")
            finally:
                server.RUNTIME_CONTROLS_PATH = old_controls

    def test_job_detail_prefers_approved_jd_text(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "jobs.db"
            self._create_results_db(db_path, with_approved_jd_text=True)
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                INSERT INTO results (
                    id, url, title, board, seniority, experience_years, salary_k, score,
                    decision, snippet, query, jd_text, filter_verdicts, run_id, created_at, approved_jd_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "https://example.com/jobs/1",
                    "Security Engineer",
                    "example",
                    "senior",
                    None,
                    None,
                    None,
                    "qa_approved",
                    "Short summary",
                    None,
                    "Raw scraped JD with noise",
                    None,
                    "run-1",
                    "2026-03-14T00:00:00Z",
                    "ROLE SUMMARY\nClean approved JD",
                ),
            )
            conn.commit()
            conn.close()

            old_db = server.DB_PATH
            server.DB_PATH = str(db_path)
            client = TestClient(server.app)
            try:
                resp = client.get("/api/tailoring/jobs/1")
                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertEqual(body["jd_text"], "ROLE SUMMARY\nClean approved JD")
                self.assertEqual(body["snippet"], "Short summary")
            finally:
                server.DB_PATH = old_db

    def test_workflow_schema_migrates_legacy_decisions(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "jobs.db"
            self._create_results_db(db_path, with_approved_jd_text=False)
            self._insert_result(
                db_path,
                job_id=1,
                title="Legacy Accept",
                url="https://example.com/jobs/1",
                decision="accept",
            )
            self._insert_result(
                db_path,
                job_id=2,
                title="Legacy Manual",
                url="manual://ingest/2",
                decision="manual",
            )
            self._insert_result(
                db_path,
                job_id=3,
                title="Legacy Approved",
                url="manual://ingest/3",
                decision="manual_approved",
            )

            old_db = server.DB_PATH
            server.DB_PATH = str(db_path)
            client = TestClient(server.app)
            try:
                qa_resp = client.get("/api/tailoring/qa")
                ready_resp = client.get("/api/tailoring/ready")
                self.assertEqual(qa_resp.status_code, 200)
                self.assertEqual(ready_resp.status_code, 200)
                self.assertEqual({item["id"] for item in qa_resp.json()["items"]}, {1, 2})
                self.assertEqual([item["id"] for item in ready_resp.json()["items"]], [3])

                conn = sqlite3.connect(db_path)
                rows = conn.execute("SELECT id, decision FROM results ORDER BY id").fetchall()
                conn.close()
                self.assertEqual(
                    rows,
                    [
                        (1, "qa_pending"),
                        (2, "qa_pending"),
                        (3, "qa_approved"),
                    ],
                )
            finally:
                server.DB_PATH = old_db

    def test_tailoring_run_and_queue_require_qa_approval(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "jobs.db"
            self._create_results_db(db_path, with_approved_jd_text=False)
            self._insert_result(
                db_path,
                job_id=10,
                title="Pending Job",
                url="https://example.com/jobs/10",
                decision="qa_pending",
            )

            old_db = server.DB_PATH
            server.DB_PATH = str(db_path)
            client = TestClient(server.app)
            try:
                queue_resp = client.post("/api/tailoring/queue", json={"jobs": [{"job_id": 10}]})
                run_resp = client.post("/api/tailoring/run", json={"job_id": 10, "skip_analysis": False})

                self.assertEqual(queue_resp.status_code, 409)
                self.assertEqual(queue_resp.json()["decision"], "qa_pending")
                self.assertEqual(run_resp.status_code, 409)
                self.assertEqual(run_resp.json()["decision"], "qa_pending")
            finally:
                server.DB_PATH = old_db

    def test_tailoring_queue_detects_duplicate_open_jobs(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "jobs.db"
            self._create_results_db(db_path, with_approved_jd_text=False)
            self._insert_result(
                db_path,
                job_id=20,
                title="Approved Job",
                url="https://example.com/jobs/20",
                decision="qa_approved",
            )

            old_db = server.DB_PATH
            server.DB_PATH = str(db_path)
            client = TestClient(server.app)
            try:
                with patch.object(server, "_process_tailoring_queue", return_value=None):
                    first = client.post("/api/tailoring/queue", json={"jobs": [{"job_id": 20}]})
                    second = client.post("/api/tailoring/queue", json={"jobs": [{"job_id": 20}]})

                self.assertEqual(first.status_code, 200)
                self.assertEqual(first.json()["queued"], 1)
                self.assertEqual(second.status_code, 200)
                self.assertEqual(second.json()["queued"], 0)
                self.assertEqual(len(second.json()["duplicates"]), 1)
                self.assertEqual(second.json()["duplicates"][0]["job_id"], 20)

                conn = sqlite3.connect(db_path)
                row = conn.execute(
                    "SELECT COUNT(*), MIN(status), MAX(status) FROM tailoring_queue_items WHERE job_id = ?",
                    (20,),
                ).fetchone()
                conn.close()
                self.assertEqual(row, (1, "queued", "queued"))
            finally:
                server.DB_PATH = old_db

    def test_tailoring_queue_reconciles_stale_running_items(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "jobs.db"
            self._create_results_db(db_path, with_approved_jd_text=False)
            self._insert_result(
                db_path,
                job_id=30,
                title="Approved Job",
                url="https://example.com/jobs/30",
                decision="qa_approved",
            )

            old_db = server.DB_PATH
            old_runner = dict(server._TAILORING_RUNNER)
            server.DB_PATH = str(db_path)
            server._TAILORING_RUNNER.update(
                {
                    "proc": None,
                    "log_handle": None,
                    "job": None,
                    "queue_item_id": None,
                    "started_at": None,
                    "ended_at": None,
                    "exit_code": None,
                    "log_path": None,
                    "cmd": None,
                    "stop_reason": None,
                }
            )
            server._ensure_workflow_schema(force=True)

            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                INSERT INTO tailoring_queue_items (
                    job_id, skip_analysis, status, created_at, updated_at, started_at
                ) VALUES (?, ?, 'running', ?, ?, ?)
                """,
                (30, 0, "2026-03-14T00:00:00Z", "2026-03-14T00:00:00Z", "2026-03-14T00:00:10Z"),
            )
            conn.commit()
            conn.close()

            client = TestClient(server.app)
            try:
                resp = client.get("/api/tailoring/queue")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["count"], 0)
                self.assertIsNone(resp.json()["active_item"])

                conn = sqlite3.connect(db_path)
                row = conn.execute(
                    "SELECT status, error, finished_at FROM tailoring_queue_items WHERE job_id = ?",
                    (30,),
                ).fetchone()
                conn.close()
                self.assertEqual(row[0], "failed")
                self.assertIn("state was lost", row[1])
                self.assertIsNotNone(row[2])
            finally:
                server.DB_PATH = old_db
                server._TAILORING_RUNNER.clear()
                server._TAILORING_RUNNER.update(old_runner)

    def test_manual_ingest_commit_creates_qa_pending_job_and_audit_row(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "jobs.db"
            self._create_results_db(db_path, with_approved_jd_text=False)

            old_db = server.DB_PATH
            server.DB_PATH = str(db_path)
            client = TestClient(server.app)
            try:
                resp = client.post(
                    "/api/tailoring/ingest/commit",
                    json={
                        "title": "Manual Security Job",
                        "company": "ExampleCo",
                        "jd_text": "Detailed job description",
                        "snippet": "Short summary",
                    },
                )
                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                self.assertTrue(payload["ok"])

                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT id, decision, query, url FROM results WHERE id = ?",
                    (payload["job_id"],),
                ).fetchone()
                log_row = conn.execute(
                    "SELECT action, new_state FROM job_state_log WHERE job_id = ? ORDER BY id DESC LIMIT 1",
                    (payload["job_id"],),
                ).fetchone()
                conn.close()

                self.assertEqual(row["decision"], "qa_pending")
                self.assertEqual(row["query"], "manual-ingest")
                self.assertTrue(str(row["url"]).startswith("manual://ingest/"))
                self.assertEqual(log_row["action"], "ingest_manual")
                self.assertEqual(log_row["new_state"], "qa_pending")
            finally:
                server.DB_PATH = old_db

    def test_qa_approve_polishes_and_persists_cleaned_jd(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "jobs.db"
            self._create_results_db(db_path, with_approved_jd_text=False)
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                INSERT INTO results (
                    id, url, title, board, seniority, experience_years, salary_k, score,
                    decision, snippet, query, jd_text, filter_verdicts, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "https://example.com/jobs/1",
                    "Senior Security Engineer",
                    "example",
                    "senior",
                    None,
                    None,
                    None,
                    "qa_pending",
                    "Old snippet",
                    None,
                    "About us: We are amazing. Follow us on LinkedIn. What You'll Do Build detections. "
                    "Required Qualifications SIEM experience. Medical dental vision included.",
                    None,
                    "run-1",
                    "2026-03-14T00:00:00Z",
                ),
            )
            conn.commit()
            conn.close()

            old_db = server.DB_PATH
            server.DB_PATH = str(db_path)
            client = TestClient(server.app)

            class FakeResponse:
                def __init__(self, payload: dict):
                    self._payload = json.dumps(payload).encode("utf-8")

                def read(self):
                    return self._payload

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            def fake_urlopen(req, timeout=0):
                url = req if isinstance(req, str) else req.full_url
                if url.endswith("/v1/models"):
                    return FakeResponse({"data": [{"id": "model-1"}]})
                self.assertEqual(url, "http://127.0.0.1:4000/v1/chat/completions")
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "requirements_summary": "Detection-focused security engineering role covering SIEM and threat content development.",
                                            "approved_jd_text": "ROLE SUMMARY\nDetection engineering role.\n\nCORE RESPONSIBILITIES\n- Build detections.\n\nREQUIRED QUALIFICATIONS\n- SIEM experience.",
                                            "removed_noise": ["LinkedIn follow text", "benefits boilerplate"],
                                        }
                                    )
                                }
                            }
                        ]
                    }
                )

            try:
                with (
                    patch("services.tailoring._resolve_llm_runtime", return_value={
                        "models_url": "http://127.0.0.1:4000/v1/models",
                        "chat_url": "http://127.0.0.1:4000/v1/chat/completions",
                        "selected_model": "default",
                    }),
                    patch("services.tailoring.urllib.request.urlopen", side_effect=fake_urlopen),
                    patch(
                        "services.tailoring._polish_job_description",
                        return_value=(
                            "Detection-focused security engineering role covering SIEM and threat content development.",
                            "ROLE SUMMARY\nDetection engineering role.\n\nCORE RESPONSIBILITIES\n- Build detections.\n\nREQUIRED QUALIFICATIONS\n- SIEM experience.",
                            True,
                        ),
                    ),
                ):
                    resp = client.post("/api/tailoring/qa/approve", json={"job_ids": [1]})
                    self.assertEqual(resp.status_code, 200)
                    payload = resp.json()
                    self.assertTrue(payload["ok"])
                    self.assertTrue(payload["approved"][0]["polished"])

                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cols = [row["name"] for row in conn.execute("PRAGMA table_info(results)").fetchall()]
                row = conn.execute("SELECT decision, snippet, approved_jd_text FROM results WHERE id = 1").fetchone()
                conn.close()

                self.assertIn("approved_jd_text", cols)
                self.assertEqual(row["decision"], "qa_approved")
                self.assertIn("Detection-focused security engineering role", row["snippet"])
                self.assertIn("ROLE SUMMARY", row["approved_jd_text"])
                self.assertNotIn("LinkedIn", row["approved_jd_text"])
            finally:
                server.DB_PATH = old_db

    def test_qa_llm_review_queue_uses_loaded_model_and_reports_progress(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "jobs.db"
            output_dir = root / "tailoring-output"
            output_dir.mkdir()

            self._create_results_db(db_path, with_approved_jd_text=False)
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                INSERT INTO results (
                    id, url, title, board, seniority, experience_years, salary_k, score,
                    decision, snippet, query, jd_text, filter_verdicts, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "https://example.com/jobs/1",
                    "Application Security Engineer",
                    "example",
                    "senior",
                    None,
                    None,
                    None,
                    "qa_pending",
                    "Security role",
                    None,
                    "Build detections, harden CI, and support cloud security reviews.",
                    None,
                    "run-1",
                    "2026-03-14T00:00:00Z",
                ),
            )
            conn.commit()
            conn.close()

            old_db = server.DB_PATH
            old_output_dir = server.TAILORING_OUTPUT_DIR
            server.DB_PATH = str(db_path)
            server.TAILORING_OUTPUT_DIR = output_dir
            with server._QA_LLM_REVIEW_LOCK:
                server._QA_LLM_REVIEW_RUNNER.update(
                    {
                        "thread": None,
                        "batch_id": 0,
                        "started_at": None,
                        "ended_at": None,
                        "active_job_id": None,
                        "active_started_at": None,
                        "resolved_model": None,
                        "items": [],
                    }
                )

            client = TestClient(server.app)

            class FakeResponse:
                def __init__(self, payload: dict):
                    self._payload = json.dumps(payload).encode("utf-8")

                def read(self):
                    return self._payload

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            chat_calls: list[str] = []

            def fake_urlopen(req, timeout=0):
                url = req if isinstance(req, str) else req.full_url
                if url.endswith("/v1/models"):
                    return FakeResponse({"data": [
                        {"id": "meta/llama-3.3-70b"},
                        {"id": "qwen/qwen3-coder-next"},
                    ]})
                if url.endswith("/api/v0/models"):
                    return FakeResponse({"data": [
                        {"id": "meta/llama-3.3-70b", "state": "not-loaded", "type": "llm"},
                        {"id": "qwen/qwen3-coder-next", "state": "loaded", "type": "llm"},
                    ]})
                if url.endswith("/v1/chat/completions"):
                    payload = json.loads(req.data.decode("utf-8"))
                    chat_calls.append(payload["model"])
                    self.assertEqual(payload["model"], "qwen/qwen3-coder-next")
                    return FakeResponse(
                        {
                            "choices": [
                                {
                                    "message": {
                                        "content": json.dumps(
                                            {
                                                "pass": True,
                                                "reason": "Strong application security fit",
                                                "confidence": 0.88,
                                                "top_matches": ["detections", "cloud security"],
                                                "gaps": [],
                                            }
                                        )
                                    }
                                }
                            ]
                        }
                    )
                raise AssertionError(f"Unexpected urlopen call: {url}")

            try:
                with (
                    patch("services.tailoring.urllib.request.urlopen", side_effect=fake_urlopen),
                    patch(
                        "services.tailoring._polish_job_description",
                        return_value=("Security role summary", "ROLE SUMMARY\nSecurity role", True),
                    ),
                ):
                    resp = client.post("/api/tailoring/qa/llm-review", json={"job_ids": [1]})
                    self.assertEqual(resp.status_code, 200)
                    body = resp.json()
                    self.assertTrue(body["ok"])
                    self.assertEqual(body["queued"], 1)

                    status = None
                    deadline = server.time.time() + 5
                    while server.time.time() < deadline:
                        status_resp = client.get("/api/tailoring/qa/llm-review")
                        self.assertEqual(status_resp.status_code, 200)
                        status = status_resp.json()
                        if not status["running"] and status["summary"]["completed"] == 1:
                            break
                        server.time.sleep(0.05)

                self.assertIsNotNone(status)
                self.assertEqual(status["summary"]["passed"], 1)
                self.assertEqual(status["summary"]["completed"], 1)
                self.assertEqual(status["resolved_model"], "qwen/qwen3-coder-next")
                self.assertEqual(chat_calls, ["qwen/qwen3-coder-next"])

                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT decision, snippet, approved_jd_text FROM results WHERE id = 1").fetchone()
                conn.close()

                self.assertEqual(row["decision"], "qa_approved")
                self.assertEqual(row["snippet"], "Security role summary")
                self.assertEqual(row["approved_jd_text"], "ROLE SUMMARY\nSecurity role")
            finally:
                with server._QA_LLM_REVIEW_LOCK:
                    thread = server._QA_LLM_REVIEW_RUNNER.get("thread")
                if thread is not None:
                    thread.join(timeout=1)
                with server._QA_LLM_REVIEW_LOCK:
                    server._QA_LLM_REVIEW_RUNNER.update(
                        {
                            "thread": None,
                            "batch_id": 0,
                            "started_at": None,
                            "ended_at": None,
                            "active_job_id": None,
                            "active_started_at": None,
                            "resolved_model": None,
                            "items": [],
                        }
                    )
                server.DB_PATH = old_db
                server.TAILORING_OUTPUT_DIR = old_output_dir

    def test_qa_llm_review_queue_reports_when_no_model_is_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "jobs.db"
            output_dir = root / "tailoring-output"
            output_dir.mkdir()

            self._create_results_db(db_path, with_approved_jd_text=False)
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                INSERT INTO results (
                    id, url, title, board, seniority, experience_years, salary_k, score,
                    decision, snippet, query, jd_text, filter_verdicts, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "https://example.com/jobs/1",
                    "Security Engineer",
                    "example",
                    "senior",
                    None,
                    None,
                    None,
                    "qa_pending",
                    "Security role",
                    None,
                    "Review pipelines and cloud controls.",
                    None,
                    "run-1",
                    "2026-03-14T00:00:00Z",
                ),
            )
            conn.commit()
            conn.close()

            old_db = server.DB_PATH
            old_output_dir = server.TAILORING_OUTPUT_DIR
            server.DB_PATH = str(db_path)
            server.TAILORING_OUTPUT_DIR = output_dir
            with server._QA_LLM_REVIEW_LOCK:
                server._QA_LLM_REVIEW_RUNNER.update(
                    {
                        "thread": None,
                        "batch_id": 0,
                        "started_at": None,
                        "ended_at": None,
                        "active_job_id": None,
                        "active_started_at": None,
                        "resolved_model": None,
                        "items": [],
                    }
                )

            client = TestClient(server.app)

            class FakeResponse:
                def __init__(self, payload: dict):
                    self._payload = json.dumps(payload).encode("utf-8")

                def read(self):
                    return self._payload

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            def fake_urlopen(req, timeout=0):
                url = req if isinstance(req, str) else req.full_url
                if url.endswith("/v1/models"):
                    return FakeResponse({"data": [
                        {"id": "meta/llama-3.3-70b"},
                        {"id": "qwen/qwen3-coder-next"},
                    ]})
                if url.endswith("/api/v0/models"):
                    return FakeResponse({"data": [
                        {"id": "meta/llama-3.3-70b", "state": "not-loaded", "type": "llm"},
                        {"id": "qwen/qwen3-coder-next", "state": "not-loaded", "type": "llm"},
                    ]})
                raise AssertionError(f"Unexpected urlopen call: {url}")

            try:
                with patch("services.tailoring.urllib.request.urlopen", side_effect=fake_urlopen):
                    resp = client.post("/api/tailoring/qa/llm-review", json={"job_ids": [1]})
                    self.assertEqual(resp.status_code, 200)
                    self.assertTrue(resp.json()["ok"])

                    status = None
                    deadline = server.time.time() + 5
                    while server.time.time() < deadline:
                        status_resp = client.get("/api/tailoring/qa/llm-review")
                        self.assertEqual(status_resp.status_code, 200)
                        status = status_resp.json()
                        if not status["running"] and status["summary"]["completed"] == 1:
                            break
                        server.time.sleep(0.05)

                self.assertIsNotNone(status)
                self.assertEqual(status["summary"]["errors"], 1)
                self.assertIn("No LLM model is loaded", status["items"][0]["reason"])

                conn = sqlite3.connect(db_path)
                row = conn.execute("SELECT decision FROM results WHERE id = 1").fetchone()
                conn.close()
                self.assertEqual(row[0], "qa_pending")
            finally:
                with server._QA_LLM_REVIEW_LOCK:
                    thread = server._QA_LLM_REVIEW_RUNNER.get("thread")
                if thread is not None:
                    thread.join(timeout=1)
                with server._QA_LLM_REVIEW_LOCK:
                    server._QA_LLM_REVIEW_RUNNER.update(
                        {
                            "thread": None,
                            "batch_id": 0,
                            "started_at": None,
                            "ended_at": None,
                            "active_job_id": None,
                            "active_started_at": None,
                            "resolved_model": None,
                            "items": [],
                        }
                    )
                server.DB_PATH = old_db
                server.TAILORING_OUTPUT_DIR = old_output_dir

    def test_clear_tailoring_runs_removes_tailoring_ingest_jobs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "jobs.db"
            output_dir = root / "tailoring-output"
            output_dir.mkdir()
            (output_dir / "_runner_logs").mkdir()
            (output_dir / "job-1-run").mkdir()

            self._create_results_db(db_path, with_approved_jd_text=False)
            conn = sqlite3.connect(db_path)
            conn.executemany(
                """
                INSERT INTO results (
                    id, url, title, board, seniority, experience_years, salary_k, score,
                    decision, snippet, query, jd_text, filter_verdicts, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        1,
                        "manual://ingest/1234",
                        "Manual Ingest Job",
                        "qa_pending",
                        None,
                        None,
                        None,
                        None,
                        "manual",
                        "Manual job",
                        "manual-ingest",
                        "Manual body",
                        None,
                        "manual-ingest",
                        "2026-03-14T00:00:00Z",
                    ),
                    (
                        2,
                        "mobile://ingest/5678",
                        "Mobile Ingest Job",
                        "manual",
                        None,
                        None,
                        None,
                        None,
                        "qa_pending",
                        "Mobile job",
                        "mobile-ingest",
                        "Mobile body",
                        None,
                        "mobile-ingest",
                        "2026-03-14T00:05:00Z",
                    ),
                    (
                        3,
                        "https://example.com/jobs/3",
                        "Scraped Job",
                        "example",
                        None,
                        None,
                        None,
                        None,
                        "qa_approved",
                        "Scraped summary",
                        "search-query",
                        "Scraped body",
                        None,
                        "run-3",
                        "2026-03-14T00:10:00Z",
                    ),
                ],
            )
            conn.commit()
            conn.close()

            old_db = server.DB_PATH
            old_output_dir = server.TAILORING_OUTPUT_DIR
            server.DB_PATH = str(db_path)
            server.TAILORING_OUTPUT_DIR = output_dir
            client = TestClient(server.app)
            try:
                resp = client.post("/api/ops/action", json={"action": "clear_tailoring_runs"})
                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["removed_jobs"], 2)
                self.assertEqual(payload["removed"], ["job-1-run"])

                conn = sqlite3.connect(db_path)
                rows = conn.execute("SELECT id, url FROM results ORDER BY id").fetchall()
                conn.close()

                self.assertEqual(rows, [(3, "https://example.com/jobs/3")])
                self.assertFalse((output_dir / "job-1-run").exists())
                self.assertTrue((output_dir / "_runner_logs").exists())
            finally:
                server.DB_PATH = old_db
                server.TAILORING_OUTPUT_DIR = old_output_dir

    def test_active_runs_reconciles_stale_running_row(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "jobs.db"
            self._create_runs_table(db_path)

            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                INSERT INTO runs (run_id, started_at, status)
                VALUES (?, ?, ?)
                """,
                ("run-stale", "2026-03-14T01:00:00Z", "running"),
            )
            conn.commit()
            conn.close()

            old_db = server.DB_PATH
            old_runner = dict(server._SCRAPE_RUNNER)
            server.DB_PATH = str(db_path)
            server._SCRAPE_RUNNER.update({
                "proc": None,
                "log_handle": None,
                "started_at": None,
                "ended_at": None,
                "exit_code": None,
                "log_path": None,
                "cmd": None,
                "options": {},
            })
            client = TestClient(server.app)
            try:
                with patch.object(
                    server,
                    "_get_launchctl_status",
                    return_value={"loaded": False, "pid": None, "last_exit": 0, "running": False},
                ):
                    resp = client.get("/api/runs/active")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["active"], False)

                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT status, completed_at, errors, error_count FROM runs WHERE run_id = ?",
                    ("run-stale",),
                ).fetchone()
                conn.close()

                self.assertEqual(row["status"], "failed")
                self.assertIsNotNone(row["completed_at"])
                self.assertIn("no live scrape process", row["errors"])
                self.assertEqual(row["error_count"], 1)
            finally:
                server.DB_PATH = old_db
                server._SCRAPE_RUNNER.clear()
                server._SCRAPE_RUNNER.update(old_runner)

    def test_terminate_run_clears_stale_active_state(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "jobs.db"
            self._create_runs_table(db_path)

            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                INSERT INTO runs (run_id, started_at, status)
                VALUES (?, ?, ?)
                """,
                ("run-stale", "2026-03-14T01:00:00Z", "running"),
            )
            conn.commit()
            conn.close()

            old_db = server.DB_PATH
            old_runner = dict(server._SCRAPE_RUNNER)
            server.DB_PATH = str(db_path)
            server._SCRAPE_RUNNER.update({
                "proc": None,
                "log_handle": None,
                "started_at": None,
                "ended_at": None,
                "exit_code": None,
                "log_path": None,
                "cmd": None,
                "options": {},
            })
            client = TestClient(server.app)
            try:
                with patch.object(
                    server,
                    "_get_launchctl_status",
                    return_value={"loaded": False, "pid": None, "last_exit": 0, "running": False},
                ):
                    resp = client.post("/api/runs/run-stale/terminate")
                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                self.assertTrue(payload["ok"])
                self.assertTrue(payload["reconciled_run"])
                self.assertFalse(payload["terminated_process"])

                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT status, completed_at, errors, error_count FROM runs WHERE run_id = ?",
                    ("run-stale",),
                ).fetchone()
                conn.close()

                self.assertEqual(row["status"], "failed")
                self.assertIsNotNone(row["completed_at"])
                self.assertIn("terminated by user", row["errors"])
                self.assertEqual(row["error_count"], 1)
            finally:
                server.DB_PATH = old_db
                server._SCRAPE_RUNNER.clear()
                server._SCRAPE_RUNNER.update(old_runner)

    def test_apply_package_creates_durable_snapshot_and_surfaces_applied_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "jobs.db"
            output_dir = root / "tailoring-output"
            output_dir.mkdir()

            self._create_results_db(db_path)
            self._insert_result(
                db_path,
                job_id=1,
                title="Senior Security Engineer",
                url="https://example.com/jobs/1",
                jd_text="ROLE SUMMARY\nStrong JD body",
            )
            slug = "1-exampleco-senior-security-engineer-2026-03-15"
            self._create_complete_package(output_dir, slug, job_id=1, title="Senior Security Engineer", company="ExampleCo")

            old_db = server.DB_PATH
            old_output_dir = server.TAILORING_OUTPUT_DIR
            server.DB_PATH = str(db_path)
            server.TAILORING_OUTPUT_DIR = output_dir
            client = TestClient(server.app)
            try:
                resp = client.post(
                    f"/api/packages/{slug}/apply",
                    json={
                        "application_url": "https://company.example/apply/1",
                        "follow_up_at": "2026-03-20T16:30:00Z",
                        "notes": "Submitted through company site",
                    },
                )
                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                self.assertTrue(payload["ok"])
                self.assertTrue(payload["created"])
                application_id = payload["application"]["id"]

                package_list = client.get("/api/packages?status=all")
                self.assertEqual(package_list.status_code, 200)
                self.assertEqual(package_list.json()["items"][0]["applied"]["id"], application_id)

                package_detail = client.get(f"/api/packages/{slug}")
                self.assertEqual(package_detail.status_code, 200)
                self.assertEqual(package_detail.json()["summary"]["applied"]["id"], application_id)

                recent_jobs = client.get("/api/tailoring/ready")
                self.assertEqual(recent_jobs.status_code, 200)
                self.assertEqual(recent_jobs.json()["items"][0]["applied"]["id"], application_id)

                shutil.rmtree(output_dir / slug)

                applied_detail = client.get(f"/api/applied/{application_id}")
                self.assertEqual(applied_detail.status_code, 200)
                body = applied_detail.json()
                self.assertEqual(body["summary"]["package_slug"], slug)
                self.assertEqual(body["summary"]["company_name"], "ExampleCo")
                self.assertEqual(body["job_context"]["jd_text"], "ROLE SUMMARY\nStrong JD body")
                self.assertEqual(body["latex"]["resume"], "resume tex")

                artifact = client.get(f"/api/applied/{application_id}/artifact/Conner_Jordan_Resume.pdf")
                self.assertEqual(artifact.status_code, 200)
                self.assertEqual(artifact.content, b"%PDF-resume")
            finally:
                server.DB_PATH = old_db
                server.TAILORING_OUTPUT_DIR = old_output_dir

    def test_apply_package_is_idempotent_and_tracking_updates_do_not_mutate_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "jobs.db"
            output_dir = root / "tailoring-output"
            output_dir.mkdir()

            self._create_results_db(db_path)
            self._insert_result(
                db_path,
                job_id=5,
                title="Application Security Engineer",
                url="https://example.com/jobs/5",
                jd_text="JD for application security engineer",
            )
            slug = "5-exampleco-appsec-engineer-2026-03-15"
            self._create_complete_package(output_dir, slug, job_id=5, title="Application Security Engineer", company="ExampleCo")

            old_db = server.DB_PATH
            old_output_dir = server.TAILORING_OUTPUT_DIR
            server.DB_PATH = str(db_path)
            server.TAILORING_OUTPUT_DIR = output_dir
            client = TestClient(server.app)
            try:
                first = client.post(
                    f"/api/packages/{slug}/apply",
                    json={"application_url": "https://company.example/apply/5", "notes": "first snapshot"},
                )
                self.assertEqual(first.status_code, 200)
                first_payload = first.json()
                self.assertTrue(first_payload["created"])
                application_id = first_payload["application"]["id"]

                second = client.post(
                    f"/api/packages/{slug}/apply",
                    json={"application_url": "https://company.example/apply/changed", "notes": "second snapshot"},
                )
                self.assertEqual(second.status_code, 200)
                second_payload = second.json()
                self.assertFalse(second_payload["created"])
                self.assertEqual(second_payload["application"]["id"], application_id)

                conn = sqlite3.connect(db_path)
                row_counts = conn.execute(
                    "SELECT (SELECT COUNT(*) FROM applied_applications), (SELECT COUNT(*) FROM applied_snapshots)"
                ).fetchone()
                conn.close()
                self.assertEqual(row_counts, (1, 1))

                update = client.post(
                    f"/api/applied/{application_id}/tracking",
                    json={
                        "status": "follow_up",
                        "follow_up_at": "2026-03-22T09:00:00Z",
                        "application_url": "https://company.example/apply/updated",
                        "notes": "Need to follow up next week",
                    },
                )
                self.assertEqual(update.status_code, 200)
                self.assertTrue(update.json()["ok"])
                self.assertEqual(update.json()["application"]["status"], "follow_up")

                detail = client.get(f"/api/applied/{application_id}")
                self.assertEqual(detail.status_code, 200)
                body = detail.json()
                self.assertEqual(body["summary"]["status"], "follow_up")
                self.assertEqual(body["summary"]["application_url"], "https://company.example/apply/updated")
                self.assertEqual(body["summary"]["notes"], "Need to follow up next week")
                self.assertEqual(body["latex"]["resume"], "resume tex")

                package_detail = client.get(f"/api/packages/{slug}")
                self.assertEqual(package_detail.status_code, 200)
                self.assertEqual(package_detail.json()["summary"]["applied"]["status"], "follow_up")

                artifact = client.get(f"/api/applied/{application_id}/artifact/Conner_Jordan_Cover_Letter.pdf")
                self.assertEqual(artifact.status_code, 200)
                self.assertEqual(artifact.content, b"%PDF-cover")
            finally:
                server.DB_PATH = old_db
                server.TAILORING_OUTPUT_DIR = old_output_dir


if __name__ == "__main__":
    unittest.main()
