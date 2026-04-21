"""Job state audit logging."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


def log_state_change(
    conn: sqlite3.Connection,
    *,
    job_id: int | None = None,
    job_url: str | None = None,
    old_state: str | None = None,
    new_state: str | None = None,
    action: str,
    source: str = "dashboard",
    detail: dict | str | None = None,
) -> None:
    """Insert an audit row into job_state_log."""
    ensure_state_log_table(conn)
    detail_str = json.dumps(detail) if isinstance(detail, dict) else detail
    conn.execute(
        "INSERT INTO job_state_log (job_id, job_url, old_state, new_state, action, source, detail, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            job_id,
            job_url,
            old_state,
            new_state,
            action,
            source,
            detail_str,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def ensure_state_log_table(conn: sqlite3.Connection) -> None:
    """Create job_state_log if it doesn't exist (for dashboard-only DB connections)."""
    conn.executescript(
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
