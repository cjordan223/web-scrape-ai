"""SQLite-backed deduplication and results persistence."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import JobResult
from .urlnorm import canonicalize_job_url

_DEFAULT_DB = Path(
    os.environ.get("JOB_SCRAPER_DB", str(Path.home() / ".local" / "share" / "job_scraper" / "jobs.db"))
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_urls (
    url TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_seen_urls_first_seen ON seen_urls(first_seen);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    source TEXT DEFAULT '',
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
    status TEXT NOT NULL DEFAULT 'running',
    trigger_source TEXT NOT NULL DEFAULT 'scheduled'
);

CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);

CREATE TABLE IF NOT EXISTS rejected (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    board TEXT,
    snippet TEXT,
    rejection_stage TEXT NOT NULL,
    rejection_reason TEXT NOT NULL,
    filter_verdicts TEXT,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(url, run_id)
);

CREATE INDEX IF NOT EXISTS idx_rejected_run_id ON rejected(run_id);
CREATE INDEX IF NOT EXISTS idx_rejected_stage ON rejected(rejection_stage);
CREATE INDEX IF NOT EXISTS idx_rejected_created_at ON rejected(created_at);

CREATE TABLE IF NOT EXISTS quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    board TEXT,
    snippet TEXT,
    score INTEGER NOT NULL,
    decision TEXT NOT NULL,
    signals TEXT,
    filter_verdicts TEXT,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(url, run_id)
);

CREATE INDEX IF NOT EXISTS idx_quarantine_run_id ON quarantine(run_id);
CREATE INDEX IF NOT EXISTS idx_quarantine_score ON quarantine(score);
CREATE INDEX IF NOT EXISTS idx_quarantine_created_at ON quarantine(created_at);

CREATE TABLE IF NOT EXISTS applied_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_slug TEXT NOT NULL UNIQUE,
    job_id INTEGER,
    job_title TEXT,
    company_name TEXT,
    job_url TEXT,
    application_url TEXT,
    applied_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'applied',
    follow_up_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status_updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_applied_applications_job_id ON applied_applications(job_id);
CREATE INDEX IF NOT EXISTS idx_applied_applications_status ON applied_applications(status);
CREATE INDEX IF NOT EXISTS idx_applied_applications_applied_at ON applied_applications(applied_at);
CREATE INDEX IF NOT EXISTS idx_applied_applications_updated_at ON applied_applications(updated_at);

CREATE TABLE IF NOT EXISTS job_state_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    job_url TEXT,
    old_state TEXT,
    new_state TEXT,
    action TEXT NOT NULL,
    source TEXT DEFAULT 'dashboard',
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_state_log_job_id ON job_state_log(job_id);
CREATE INDEX IF NOT EXISTS idx_state_log_created_at ON job_state_log(created_at);

CREATE TABLE IF NOT EXISTS tailoring_queue_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    skip_analysis INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    run_slug TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tailoring_queue_items_status_id ON tailoring_queue_items(status, id);
CREATE INDEX IF NOT EXISTS idx_tailoring_queue_items_job_id ON tailoring_queue_items(job_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tailoring_queue_items_open_job
ON tailoring_queue_items(job_id)
WHERE status IN ('queued', 'running');

CREATE TABLE IF NOT EXISTS applied_snapshots (
    application_id INTEGER PRIMARY KEY REFERENCES applied_applications(id) ON DELETE CASCADE,
    meta TEXT,
    job_context TEXT,
    analysis TEXT,
    resume_strategy TEXT,
    cover_strategy TEXT,
    resume_tex TEXT,
    cover_tex TEXT,
    resume_pdf BLOB,
    cover_pdf BLOB,
    llm_trace TEXT,
    created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS protect_applied_results_before_update
BEFORE UPDATE ON results
FOR EACH ROW
WHEN EXISTS (
    SELECT 1
    FROM applied_applications aa
    WHERE aa.job_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'Applied job rows are protected from inventory writes');
END;

CREATE TRIGGER IF NOT EXISTS protect_applied_results_before_delete
BEFORE DELETE ON results
FOR EACH ROW
WHEN EXISTS (
    SELECT 1
    FROM applied_applications aa
    WHERE aa.job_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'Applied job rows are protected from inventory writes');
END;

CREATE TRIGGER IF NOT EXISTS protect_applied_queue_before_insert
BEFORE INSERT ON tailoring_queue_items
FOR EACH ROW
WHEN EXISTS (
    SELECT 1
    FROM applied_applications aa
    WHERE aa.job_id = NEW.job_id
)
BEGIN
    SELECT RAISE(ABORT, 'Applied jobs cannot be re-queued');
END;

CREATE TRIGGER IF NOT EXISTS protect_applied_queue_before_update
BEFORE UPDATE ON tailoring_queue_items
FOR EACH ROW
WHEN EXISTS (
    SELECT 1
    FROM applied_applications aa
    WHERE aa.job_id = COALESCE(NEW.job_id, OLD.job_id)
)
BEGIN
    SELECT RAISE(ABORT, 'Applied jobs cannot be re-queued');
END;
"""


class JobStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Apply incremental schema migrations for existing DBs."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(results)")}
        if "salary_k" not in cols:
            self._conn.execute("ALTER TABLE results ADD COLUMN salary_k INTEGER")
            self._conn.commit()
        if "score" not in cols:
            self._conn.execute("ALTER TABLE results ADD COLUMN score INTEGER")
            self._conn.commit()
        if "decision" not in cols:
            self._conn.execute("ALTER TABLE results ADD COLUMN decision TEXT")
            self._conn.commit()
        if "source" not in cols:
            self._conn.execute("ALTER TABLE results ADD COLUMN source TEXT DEFAULT ''")
            self._conn.commit()
        run_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(runs)")}
        if "trigger_source" not in run_cols:
            self._conn.execute("ALTER TABLE runs ADD COLUMN trigger_source TEXT NOT NULL DEFAULT 'scheduled'")
            self._conn.commit()

        # Ensure job_state_log table exists for existing DBs
        existing_tables = {
            row[0]
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "job_state_log" not in existing_tables:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS job_state_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    job_url TEXT,
                    old_state TEXT,
                    new_state TEXT,
                    action TEXT NOT NULL,
                    source TEXT DEFAULT 'dashboard',
                    detail TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_state_log_job_id ON job_state_log(job_id);
                CREATE INDEX IF NOT EXISTS idx_state_log_created_at ON job_state_log(created_at);
                """
            )
        if "tailoring_queue_items" not in existing_tables:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tailoring_queue_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    skip_analysis INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'queued',
                    run_slug TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tailoring_queue_items_status_id ON tailoring_queue_items(status, id);
                CREATE INDEX IF NOT EXISTS idx_tailoring_queue_items_job_id ON tailoring_queue_items(job_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tailoring_queue_items_open_job
                ON tailoring_queue_items(job_id)
                WHERE status IN ('queued', 'running');
                """
            )
        self._conn.execute(
            """
            UPDATE results
            SET decision = CASE
                WHEN decision IN ('accept', 'manual') THEN 'qa_pending'
                WHEN decision = 'manual_approved' THEN 'qa_approved'
                ELSE decision
            END
            WHERE decision IN ('accept', 'manual', 'manual_approved')
            """
        )
        self._conn.commit()

    @staticmethod
    def _normalize_result_decision(decision: str | None) -> str | None:
        if decision in {"accept", "manual"}:
            return "qa_pending"
        if decision == "manual_approved":
            return "qa_approved"
        return decision

    def _log_state_change(
        self,
        *,
        job_id: int | None,
        job_url: str | None,
        old_state: str | None,
        new_state: str | None,
        action: str,
        detail: dict | None = None,
    ) -> None:
        detail_json = json.dumps(detail) if detail else None
        self._conn.execute(
            """
            INSERT INTO job_state_log (job_id, job_url, old_state, new_state, action, source, detail, created_at)
            VALUES (?, ?, ?, ?, ?, 'scraper', ?, ?)
            """,
            (
                job_id,
                job_url,
                old_state,
                new_state,
                action,
                detail_json,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    # --- Dedup ---

    def is_seen(self, url: str, ttl_days: int | None = None) -> bool:
        canonical = canonicalize_job_url(url)
        if ttl_days is not None:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            row = self._conn.execute(
                """SELECT 1
                   FROM seen_urls
                   WHERE (url = ? OR url = ?
                          OR (instr(url, '?') > 0 AND substr(url, 1, instr(url, '?') - 1) = ?))
                     AND first_seen >= ?
                   LIMIT 1""",
                (url, canonical, canonical, cutoff),
            ).fetchone()
        else:
            row = self._conn.execute(
                """SELECT 1
                   FROM seen_urls
                   WHERE url = ?
                      OR url = ?
                      OR (instr(url, '?') > 0 AND substr(url, 1, instr(url, '?') - 1) = ?)
                   LIMIT 1""",
                (url, canonical, canonical),
            ).fetchone()
        return row is not None

    def mark_seen(self, url: str) -> None:
        canonical = canonicalize_job_url(url)
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT INTO seen_urls (url, first_seen, last_seen)
               VALUES (?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET last_seen = excluded.last_seen""",
            (canonical, now, now),
        )
        self._conn.commit()

    # --- Results ---

    def save_result(self, job: JobResult, run_id: str, *, commit: bool = True, source: str = "") -> bool:
        now = datetime.now(timezone.utc).isoformat()
        verdicts_json = json.dumps([v.model_dump() for v in job.filter_verdicts])
        url = canonicalize_job_url(job.url)
        decision = self._normalize_result_decision(job.decision)
        cur = self._conn.execute(
            """INSERT INTO results
               (url, title, board, seniority, experience_years, salary_k, score, decision, snippet, query, jd_text, filter_verdicts, source, run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(url, run_id) DO NOTHING""",
            (
                url, job.title, job.board.value, job.seniority.value,
                job.experience_years, job.salary_k, job.score, decision,
                job.snippet, job.query, job.jd_text, verdicts_json, source, run_id, now,
            ),
        )
        if cur.rowcount > 0:
            self._log_state_change(
                job_id=cur.lastrowid,
                job_url=url,
                old_state=None,
                new_state=decision,
                action="ingest_scrape",
                detail={"run_id": run_id, "source": source or job.source or "", "query": job.query},
            )
        if commit:
            self._conn.commit()
        return cur.rowcount > 0

    def save_results(self, jobs: list[JobResult], run_id: str) -> int:
        inserted = 0
        for job in jobs:
            if self.save_result(job, run_id, commit=False, source=getattr(job, "source", "")):
                inserted += 1
        self._conn.commit()
        return inserted

    # --- Rejected ---

    def save_rejected(
        self,
        url: str,
        title: str,
        snippet: str,
        board: str,
        rejection_stage: str,
        rejection_reason: str,
        filter_verdicts: list,
        run_id: str,
    ) -> None:
        url = canonicalize_job_url(url)
        now = datetime.now(timezone.utc).isoformat()
        verdicts_json = json.dumps([v.model_dump() for v in filter_verdicts])
        self._conn.execute(
            """INSERT INTO rejected
               (url, title, board, snippet, rejection_stage, rejection_reason, filter_verdicts, run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(url, run_id) DO NOTHING""",
            (url, title, board, snippet, rejection_stage, rejection_reason, verdicts_json, run_id, now),
        )
        self._conn.commit()

    def save_rejected_batch(self, items: list[tuple], run_id: str) -> None:
        """items: list of (SearchResult, stage, reason, verdicts)"""
        now = datetime.now(timezone.utc).isoformat()
        for r, stage, reason, verdicts in items:
            url = canonicalize_job_url(r.url)
            verdicts_json = json.dumps([v.model_dump() for v in verdicts])
            self._conn.execute(
                """INSERT INTO rejected
                   (url, title, board, snippet, rejection_stage, rejection_reason, filter_verdicts, run_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(url, run_id) DO NOTHING""",
                (url, r.title, r.board.value, r.snippet, stage, reason, verdicts_json, run_id, now),
            )
        self._conn.commit()

    def result_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM results").fetchone()
        return row[0] if row else 0

    # --- Quarantine ---

    def save_quarantine_batch(self, items: list[tuple], run_id: str) -> None:
        """items: list of (SearchResult, score, decision, signals, verdicts)"""
        now = datetime.now(timezone.utc).isoformat()
        for r, score, decision, signals, verdicts in items:
            url = canonicalize_job_url(r.url)
            verdicts_json = json.dumps([v.model_dump() for v in verdicts])
            signals_json = json.dumps(signals)
            self._conn.execute(
                """INSERT INTO quarantine
                   (url, title, board, snippet, score, decision, signals, filter_verdicts, run_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(url, run_id) DO NOTHING""",
                (url, r.title, r.board.value, r.snippet, score, decision, signals_json, verdicts_json, run_id, now),
            )
        self._conn.commit()

    def seen_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM seen_urls").fetchone()
        return row[0] if row else 0

    # --- Runs ---

    def start_run(self, run_id: str, *, trigger_source: str = "scheduled") -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO runs (run_id, started_at, status, trigger_source) VALUES (?, ?, 'running', ?)",
            (run_id, now, trigger_source),
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

    def latest_run_started_at(self, *, trigger_source: str | None = None) -> str | None:
        if trigger_source:
            row = self._conn.execute(
                "SELECT started_at FROM runs WHERE trigger_source = ? ORDER BY started_at DESC LIMIT 1",
                (trigger_source,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT started_at FROM runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return row["started_at"] if row else None

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
