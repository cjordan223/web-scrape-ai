"""SQLite database layer for job_scraper v2."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_urls (
    url TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    permanently_rejected INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_seen_urls_first_seen ON seen_urls(first_seen);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    board TEXT,
    location TEXT,
    seniority TEXT,
    salary_text TEXT,
    jd_text TEXT,
    approved_jd_text TEXT,
    snippet TEXT,
    query TEXT,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    rejection_stage TEXT,
    rejection_reason TEXT,
    experience_years INTEGER,
    salary_k REAL,
    score REAL,
    filter_verdicts TEXT,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_run_id ON jobs(run_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_board ON jobs(board);

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
    trigger_source TEXT NOT NULL DEFAULT 'scheduled',
    net_new INTEGER,
    gate_mode TEXT,
    rotation_group INTEGER
);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);

CREATE TABLE IF NOT EXISTS run_tier_stats (
    run_id TEXT NOT NULL,
    tier TEXT NOT NULL,
    source TEXT NOT NULL,
    raw_hits INTEGER DEFAULT 0,
    dedup_drops INTEGER DEFAULT 0,
    filter_drops INTEGER DEFAULT 0,
    llm_rejects INTEGER DEFAULT 0,
    llm_uncertain_low INTEGER DEFAULT 0,
    llm_overflow INTEGER DEFAULT 0,
    stored_pending INTEGER DEFAULT 0,
    stored_lead INTEGER DEFAULT 0,
    duration_ms INTEGER,
    PRIMARY KEY (run_id, tier, source)
);
CREATE INDEX IF NOT EXISTS idx_run_tier_stats_run ON run_tier_stats(run_id);

CREATE VIEW IF NOT EXISTS results AS
    SELECT *, status AS decision FROM jobs;

CREATE VIEW IF NOT EXISTS rejected AS
    SELECT id, url, title, board, snippet, rejection_stage, rejection_reason,
           filter_verdicts, run_id, created_at
    FROM jobs WHERE status = 'rejected';
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobDB:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            from job_scraper.config import DB_PATH
            db_path = DB_PATH
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), timeout=60)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=60000")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate_schema()
        self._conn.executescript(_SCHEMA)

    def _migrate_schema(self) -> None:
        """Handle in-place schema migrations for existing databases."""
        # Rename discovered_at → created_at if needed
        try:
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(jobs)")}
            if "discovered_at" in cols and "created_at" not in cols:
                self._conn.execute("ALTER TABLE jobs RENAME COLUMN discovered_at TO created_at")
                self._conn.commit()
        except Exception:
            pass  # Table may not exist yet
        # Add missing columns to existing jobs table
        try:
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(jobs)")}
            if cols:  # table exists
                for col, defn in [
                    ("experience_years", "INTEGER"),
                    ("salary_k", "REAL"),
                    ("score", "REAL"),
                    ("filter_verdicts", "TEXT"),
                ]:
                    if col not in cols:
                        self._conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {defn}")
                self._conn.commit()
        except Exception:
            pass
        # Add permanently_rejected column to seen_urls if missing
        try:
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(seen_urls)")}
            if cols and "permanently_rejected" not in cols:
                self._conn.execute(
                    "ALTER TABLE seen_urls ADD COLUMN permanently_rejected INTEGER NOT NULL DEFAULT 0"
                )
                self._conn.commit()
        except Exception:
            pass
        # Rename runs columns if needed
        try:
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(runs)")}
            if cols:
                renames = [
                    ("items_scraped", "raw_count"),
                    ("items_new", "dedup_count"),
                    ("items_filtered", "filtered_count"),
                ]
                for old, new in renames:
                    if old in cols and new not in cols:
                        self._conn.execute(f"ALTER TABLE runs RENAME COLUMN {old} TO {new}")
                # Add missing runs columns
                for col, defn in [("error_count", "INTEGER DEFAULT 0"), ("errors", "TEXT")]:
                    if col not in cols:
                        self._conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {defn}")
                # Refresh the column set before adding freshness/rotation columns.
                cols = {r[1] for r in self._conn.execute("PRAGMA table_info(runs)")}
                for col, defn in [
                    ("net_new", "INTEGER"),
                    ("gate_mode", "TEXT"),
                    ("rotation_group", "INTEGER"),
                ]:
                    if col not in cols:
                        self._conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {defn}")
                self._conn.commit()
        except Exception:
            pass

    def close(self) -> None:
        self._conn.close()

    def tables(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]

    def is_seen(self, url: str, ttl_days: int = 14) -> bool:
        row = self._conn.execute(
            "SELECT first_seen, permanently_rejected FROM seen_urls WHERE url = ?", (url,)
        ).fetchone()
        if row is None:
            return False
        if row["permanently_rejected"]:
            return True
        first = datetime.fromisoformat(row["first_seen"])
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - first).days
        return age < ttl_days

    def mark_seen(self, url: str) -> None:
        now = _now()
        self._conn.execute(
            "INSERT INTO seen_urls (url, first_seen, last_seen) VALUES (?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET last_seen = ?",
            (url, now, now, now),
        )

    def mark_permanently_rejected(self, url: str) -> None:
        now = _now()
        self._conn.execute(
            "INSERT INTO seen_urls (url, first_seen, last_seen, permanently_rejected) "
            "VALUES (?, ?, ?, 1) "
            "ON CONFLICT(url) DO UPDATE SET permanently_rejected = 1, last_seen = ?",
            (url, now, now, now),
        )

    def commit(self) -> None:
        self._conn.commit()

    def insert_job(self, job: dict) -> int:
        now = _now()
        cur = self._conn.execute(
            """INSERT INTO jobs (url, title, company, board, location, seniority,
               salary_text, jd_text, snippet, query, source, status,
               rejection_stage, rejection_reason, experience_years, salary_k,
               score, filter_verdicts, run_id, created_at, updated_at)
            VALUES (:url, :title, :company, :board, :location, :seniority,
                    :salary_text, :jd_text, :snippet, :query, :source, :status,
                    :rejection_stage, :rejection_reason, :experience_years, :salary_k,
                    :score, :filter_verdicts, :run_id, :created_at, :updated_at)""",
            {
                "url": job["url"],
                "title": job["title"],
                "company": job["company"],
                "board": job.get("board"),
                "location": job.get("location"),
                "seniority": job.get("seniority"),
                "salary_text": job.get("salary_text"),
                "jd_text": job.get("jd_text"),
                "snippet": job.get("snippet"),
                "query": job.get("query"),
                "source": job["source"],
                "status": job.get("status", "qa_pending"),
                "rejection_stage": job.get("rejection_stage"),
                "rejection_reason": job.get("rejection_reason"),
                "experience_years": job.get("experience_years"),
                "salary_k": job.get("salary_k"),
                "score": job.get("score"),
                "filter_verdicts": job.get("filter_verdicts"),
                "run_id": job["run_id"],
                "created_at": job.get("created_at", job.get("discovered_at", now)),
                "updated_at": now,
            },
        )
        return cur.lastrowid

    def job_count(self, status: str | None = None) -> int:
        if status:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM jobs WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()
        return row["c"]

    def recent_jobs(self, limit: int = 50, status: str | None = None) -> list[dict]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def start_run(self, run_id: str, trigger: str = "scheduled") -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO runs (run_id, started_at, status, trigger_source) VALUES (?, ?, 'running', ?)",
            (run_id, _now(), trigger),
        )
        self._conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        raw_count: int = 0,
        dedup_count: int = 0,
        filtered_count: int = 0,
        error_count: int = 0,
        errors: str | None = None,
        net_new: int | None = None,
        gate_mode: str | None = None,
        rotation_group: int | None = None,
    ) -> None:
        now = _now()
        started = self._conn.execute(
            "SELECT started_at FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        elapsed = None
        if started:
            start_dt = datetime.fromisoformat(started["started_at"])
            elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()
        self._conn.execute(
            """UPDATE runs SET completed_at = ?, elapsed = ?, raw_count = ?,
               dedup_count = ?, filtered_count = ?, error_count = ?, errors = ?,
               net_new = COALESCE(?, net_new),
               gate_mode = COALESCE(?, gate_mode),
               rotation_group = COALESCE(?, rotation_group),
               status = 'completed'
            WHERE run_id = ?""",
            (now, elapsed, raw_count, dedup_count, filtered_count, error_count,
             errors, net_new, gate_mode, rotation_group, run_id),
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None
