import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import typer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tailor import config as cfg
from tailor.__main__ import run
from tailor.selector import select_job
from tailor.selector import SelectedJob
from tailor.validator import ValidationResult


class TestCliRunExit(unittest.TestCase):
    def test_select_job_rejects_non_approved_state(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "jobs.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    board TEXT,
                    seniority TEXT,
                    jd_text TEXT,
                    snippet TEXT,
                    status TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO jobs (id, url, title, board, seniority, jd_text, snippet, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "https://example.com/jobs/1",
                    "Pending Role",
                    "lever",
                    "mid",
                    "Role details",
                    "Summary",
                    "qa_pending",
                ),
            )
            conn.commit()
            conn.close()

            old_db = cfg.DB_PATH
            cfg.DB_PATH = db_path
            try:
                with self.assertRaisesRegex(ValueError, "not QA-approved"):
                    select_job(1)
            finally:
                cfg.DB_PATH = old_db

    def test_select_job_uses_stored_company_for_ingest_urls(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "jobs.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL DEFAULT '',
                    board TEXT,
                    seniority TEXT,
                    jd_text TEXT,
                    snippet TEXT,
                    status TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO jobs (id, url, title, company, board, seniority, jd_text, snippet, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "mobile://ingest/1234",
                    "Mobile Platform Engineer",
                    "ExampleCo",
                    "mobile",
                    "senior",
                    "Role details",
                    "Summary",
                    "qa_approved",
                ),
            )
            conn.commit()
            conn.close()

            old_db = cfg.DB_PATH
            cfg.DB_PATH = db_path
            try:
                job = select_job(1)
            finally:
                cfg.DB_PATH = old_db

            self.assertEqual(job.company, "ExampleCo")
            self.assertNotEqual(job.company.lower(), "ingest")

    def test_run_exits_nonzero_when_resume_never_passes(self):
        job = SelectedJob(
            id=999,
            url="https://example.com/jobs/999",
            title="Role",
            board="lever",
            seniority="mid",
            jd_text="desc",
            snippet="",
            company="example",
        )

        with tempfile.TemporaryDirectory() as td:
            out_root = Path(td)
            resume_tex = out_root / "resume.tex"
            cover_tex = out_root / "cover.tex"
            resume_tex.write_text("resume")
            cover_tex.write_text("cover")

            with (
                patch("tailor.__main__.select_job", return_value=job),
                patch("tailor.__main__.cfg.OUTPUT_DIR", out_root),
                patch("tailor.__main__.cfg.MAX_RETRIES", 2),
                patch("tailor.analyzer.analyze_job", return_value={"requirements": []}),
                patch("tailor.writer.write_resume", return_value=resume_tex),
                patch("tailor.writer.write_cover_letter", return_value=cover_tex),
                patch(
                    "tailor.validator.validate_resume",
                    return_value=ValidationResult(False, ["failed"]),
                ),
                patch(
                    "tailor.validator.validate_cover_letter",
                    return_value=ValidationResult(True, []),
                ),
            ):
                with self.assertRaises(typer.Exit) as ctx:
                    run(job_id=999, skip_analysis=False)
                self.assertEqual(ctx.exception.exit_code, 1)

    def test_run_retries_resume_with_structured_validator_feedback(self):
        job = SelectedJob(
            id=999,
            url="https://example.com/jobs/999",
            title="Role",
            board="lever",
            seniority="mid",
            jd_text="desc",
            snippet="",
            company="example",
        )

        with tempfile.TemporaryDirectory() as td:
            out_root = Path(td)
            resume_tex = out_root / "resume.tex"
            cover_tex = out_root / "cover.tex"
            resume_tex.write_text("resume")
            cover_tex.write_text("cover")

            resume_feedback = []

            def fake_write_resume(job, analysis, output_dir, previous_feedback=None, attempt=1, trace_recorder=None):
                resume_feedback.append(previous_feedback)
                return resume_tex

            resume_validation_results = [
                ValidationResult(
                    False,
                    ["bullet count wrong"],
                    failure_details=[
                        {
                            "category": "bullet_count_mismatch",
                            "message": "expected 14 bullets, found 13",
                            "snippet": "\\resumeItem{Only 13 bullets here}",
                        }
                    ],
                ),
                ValidationResult(True, []),
            ]

            with (
                patch("tailor.__main__.select_job", return_value=job),
                patch("tailor.__main__.cfg.OUTPUT_DIR", out_root),
                patch("tailor.__main__.cfg.MAX_RETRIES", 2),
                patch("tailor.analyzer.analyze_job", return_value={"requirements": []}),
                patch("tailor.writer.write_resume", side_effect=fake_write_resume),
                patch("tailor.writer.write_cover_letter", return_value=cover_tex),
                patch("tailor.validator.validate_resume", side_effect=resume_validation_results),
                patch(
                    "tailor.validator.validate_cover_letter",
                    return_value=ValidationResult(True, []),
                ),
            ):
                run(job_id=999, skip_analysis=False)

            self.assertEqual(resume_feedback[0], None)
            self.assertEqual(
                resume_feedback[1],
                {
                    "source": "validator",
                    "summary": "FAIL — bullet count wrong",
                    "failures": ["bullet count wrong"],
                    "failure_details": [
                        {
                            "category": "bullet_count_mismatch",
                            "message": "expected 14 bullets, found 13",
                            "snippet": "\\resumeItem{Only 13 bullets here}",
                        }
                    ],
                    "cumulative_banned_phrases": [],
                },
            )


if __name__ == "__main__":
    unittest.main()
