#!/usr/bin/env python3
"""Migrate job_scraper v1 schema (results TABLE) to v2 (jobs TABLE + views).

Safe to run multiple times -- skips if migration already done.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path.home() / ".local/share/job_scraper/jobs.db"


def _is_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row[0] > 0


def _is_view(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='view' AND name=?", (name,)
    ).fetchone()
    return row[0] > 0


def migrate(db_path: Path) -> None:
    if not db_path.exists():
        print(f"DB not found at {db_path}, nothing to migrate.")
        return

    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")

    # Already migrated?
    if _is_table(conn, "jobs") and not _is_table(conn, "results"):
        print("Already migrated (jobs table exists, no results table). Ensuring views...")
        _ensure_views(conn)
        conn.close()
        return

    if _is_table(conn, "jobs") and _is_table(conn, "results"):
        print("Both jobs and results tables exist. Assuming partial migration.")
        print("Please inspect manually.")
        conn.close()
        return

    if not _is_table(conn, "results"):
        print("No results table found. Nothing to migrate.")
        conn.close()
        return

    # results is a TABLE (v1 schema) -- migrate it
    print("Migrating v1 results TABLE -> jobs TABLE...")

    # Get results columns
    cols_info = conn.execute("PRAGMA table_info(results)").fetchall()
    col_names = [c[1] for c in cols_info]

    # Create jobs table
    conn.executescript("""
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
    """)

    # Build column mapping: v1 decision -> v2 status, created_at stays
    # Determine source columns that exist
    select_parts = []
    insert_cols = []

    # Map old columns to new
    mapping = {
        "id": "id", "url": "url", "title": "title", "company": "company",
        "board": "board", "location": "location", "seniority": "seniority",
        "salary_text": "salary_text", "jd_text": "jd_text",
        "approved_jd_text": "approved_jd_text", "snippet": "snippet",
        "query": "query", "source": "source", "rejection_stage": "rejection_stage",
        "rejection_reason": "rejection_reason", "experience_years": "experience_years",
        "salary_k": "salary_k", "score": "score", "filter_verdicts": "filter_verdicts",
        "run_id": "run_id", "created_at": "created_at", "updated_at": "updated_at",
    }

    for old_col, new_col in mapping.items():
        if old_col in col_names:
            select_parts.append(old_col)
            insert_cols.append(new_col)

    # decision -> status
    if "decision" in col_names:
        select_parts.append("decision")
        insert_cols.append("status")
    elif "status" in col_names:
        select_parts.append("status")
        insert_cols.append("status")

    select_sql = ", ".join(select_parts)
    insert_sql = ", ".join(insert_cols)
    placeholders = ", ".join(["?"] * len(insert_cols))

    rows = conn.execute(f"SELECT {select_sql} FROM results").fetchall()
    print(f"  Copying {len(rows)} rows...")

    for row in rows:
        try:
            conn.execute(
                f"INSERT OR IGNORE INTO jobs ({insert_sql}) VALUES ({placeholders})",
                tuple(row),
            )
        except Exception as e:
            print(f"  Warning: skipping row: {e}")

    conn.commit()
    print(f"  Copied {conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]} rows to jobs.")

    # Rename old results table
    conn.execute("ALTER TABLE results RENAME TO results_v1_backup")
    conn.commit()
    print("  Renamed results -> results_v1_backup")

    # Migrate runs columns if needed
    runs_cols = [c[1] for c in conn.execute("PRAGMA table_info(runs)").fetchall()]
    if "items_scraped" in runs_cols and "raw_count" not in runs_cols:
        print("  Migrating runs table columns...")
        conn.executescript("""
        ALTER TABLE runs RENAME TO runs_v1_backup;
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
            status TEXT NOT NULL DEFAULT 'running',
            trigger_source TEXT NOT NULL DEFAULT 'scheduled'
        );
        INSERT INTO runs (run_id, started_at, completed_at, elapsed,
            raw_count, dedup_count, filtered_count, error_count, errors, status, trigger_source)
        SELECT run_id, started_at, completed_at, elapsed,
            COALESCE(raw_count, items_scraped, 0),
            COALESCE(dedup_count, items_new, 0),
            COALESCE(filtered_count, items_filtered, 0),
            COALESCE(error_count, errors, 0),
            NULL, status,
            COALESCE(trigger_source, 'scheduled')
        FROM runs_v1_backup;
        CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);
        """)
        print(f"  Migrated {conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0]} runs.")

    _ensure_views(conn)
    conn.close()
    print("Migration complete.")


def _ensure_views(conn: sqlite3.Connection) -> None:
    if _is_view(conn, "results"):
        conn.execute("DROP VIEW results")
    if _is_view(conn, "rejected"):
        conn.execute("DROP VIEW rejected")

    conn.execute("CREATE VIEW results AS SELECT *, status AS decision FROM jobs")
    conn.execute("""CREATE VIEW rejected AS
        SELECT id, url, title, board, snippet, rejection_stage, rejection_reason,
               filter_verdicts, run_id, created_at
        FROM jobs WHERE status = 'rejected'""")
    conn.commit()
    print("  Created results and rejected views.")


if __name__ == "__main__":
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    migrate(db_path)
