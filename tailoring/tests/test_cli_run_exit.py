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
                CREATE TABLE results (
                    id INTEGER PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    board TEXT,
                    seniority TEXT,
                    jd_text TEXT,
                    snippet TEXT,
                    decision TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO results (id, url, title, board, seniority, jd_text, snippet, decision)
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


if __name__ == "__main__":
    unittest.main()
