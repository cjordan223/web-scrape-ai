"""SQLite-backed deduplication and results persistence."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import JobResult

_DEFAULT_DB = Path(
    os.environ.get("JOB_SCRAPER_DB", str(Path.home() / ".local" / "share" / "job_scraper" / "jobs.db"))
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_urls (
    url TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    board TEXT,
    seniority TEXT,
    experience_years INTEGER,
    snippet TEXT,
    query TEXT,
    jd_text TEXT,
    filter_verdicts TEXT,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(url, run_id)
);

CREATE INDEX IF NOT EXISTS idx_results_run_id ON results(run_id);
CREATE INDEX IF NOT EXISTS idx_results_created_at ON results(created_at);
CREATE INDEX IF NOT EXISTS idx_results_board ON results(board);

CREATE TABLE IF NOT EXISTS runs (
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
);

CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);
"""


class JobStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    # --- Dedup ---

    def is_seen(self, url: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_urls WHERE url = ?", (url,)
        ).fetchone()
        return row is not None

    def mark_seen(self, url: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT INTO seen_urls (url, first_seen, last_seen)
               VALUES (?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET last_seen = excluded.last_seen""",
            (url, now, now),
        )
        self._conn.commit()

    # --- Results ---

    def save_result(self, job: JobResult, run_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        verdicts_json = json.dumps([v.model_dump() for v in job.filter_verdicts])
        self._conn.execute(
            """INSERT INTO results
               (url, title, board, seniority, experience_years, snippet, query, jd_text, filter_verdicts, run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(url, run_id) DO NOTHING""",
            (
                job.url, job.title, job.board.value, job.seniority.value,
                job.experience_years, job.snippet, job.query,
                job.jd_text, verdicts_json, run_id, now,
            ),
        )
        self._conn.commit()

    def save_results(self, jobs: list[JobResult], run_id: str) -> None:
        for job in jobs:
            self.save_result(job, run_id)

    def result_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM results").fetchone()
        return row[0] if row else 0

    def seen_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM seen_urls").fetchone()
        return row[0] if row else 0

    # --- Runs ---

    def start_run(self, run_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO runs (run_id, started_at, status) VALUES (?, ?, 'running')",
            (run_id, now),
        )
        self._conn.commit()

    def finish_run(
        self, run_id: str, *, raw: int, dedup: int, filtered: int, errors: list[str]
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        started = self._conn.execute(
            "SELECT started_at FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        elapsed = None
        if started:
            start_dt = datetime.fromisoformat(started["started_at"])
            elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()
        errors_json = json.dumps(errors) if errors else None
        self._conn.execute(
            """UPDATE runs SET completed_at = ?, elapsed = ?, raw_count = ?,
               dedup_count = ?, filtered_count = ?, error_count = ?,
               errors = ?, status = 'complete'
               WHERE run_id = ?""",
            (now, elapsed, raw, dedup, filtered, len(errors), errors_json, run_id),
        )
        self._conn.commit()

    def fail_run(self, run_id: str, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """UPDATE runs SET completed_at = ?, status = 'failed',
               errors = ?, error_count = 1 WHERE run_id = ?""",
            (now, json.dumps([error]), run_id),
        )
        self._conn.commit()

    def recent_results(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM results ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
