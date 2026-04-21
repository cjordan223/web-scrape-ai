"""Select a job from the scraper database for tailoring."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import config as cfg


@dataclass
class SelectedJob:
    id: int
    url: str
    title: str
    board: str | None
    seniority: str | None
    jd_text: str | None
    snippet: str | None
    company: str  # best-effort parse from URL/title

    @property
    def slug(self) -> str:
        """Filesystem-safe slug for output directory."""
        import re
        from datetime import date
        # Include DB job id to avoid collisions between similar titles on the same day.
        raw = f"{self.id}-{self.company}-{self.title}-{date.today()}"
        return re.sub(r"[^a-zA-Z0-9_-]+", "-", raw).strip("-").lower()[:80]


def _parse_company(url: str, title: str) -> str:
    """Best-effort company name from URL domain or title."""
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    # Strip common ATS domains
    for ats in ("greenhouse.io", "lever.co", "ashbyhq.com", "workday.com",
                "simplyhired.com", "linkedin.com", "indeed.com", "ziprecruiter.com"):
        if ats in host:
            # Try to get subdomain (e.g., boards.greenhouse.io/companyname)
            from urllib.parse import urlparse
            path_parts = urlparse(url).path.strip("/").split("/")
            if path_parts and path_parts[0] not in ("jobs", "job", "embed"):
                return path_parts[0]
            return ats.split(".")[0]
    # Use second-level domain
    parts = host.replace("www.", "").split(".")
    return parts[0] if parts else "unknown"


def list_recent_jobs(limit: int = 20) -> list[dict]:
    """Return recent QA-approved jobs from the DB."""
    conn = sqlite3.connect(cfg.DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, url, title, board, seniority, snippet "
        "FROM jobs WHERE status = 'qa_approved' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _jobs_has_column(conn: sqlite3.Connection, column: str) -> bool:
    rows = conn.execute("PRAGMA table_info(jobs)").fetchall()
    return any((row["name"] if isinstance(row, sqlite3.Row) else row[1]) == column for row in rows)


def select_job(job_id: int) -> SelectedJob:
    """Fetch a specific job by ID."""
    conn = sqlite3.connect(cfg.DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    jd_expr = "jd_text"
    if _jobs_has_column(conn, "approved_jd_text"):
        jd_expr = "COALESCE(approved_jd_text, jd_text)"
    company_expr = "company" if _jobs_has_column(conn, "company") else "NULL AS company"
    row = conn.execute(
        f"SELECT id, url, title, {company_expr}, board, seniority, {jd_expr} AS jd_text, snippet, status "
        "FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    conn.close()
    if not row:
        raise ValueError(f"Job ID {job_id} not found in jobs table")
    if row["status"] != "qa_approved":
        raise ValueError(
            f"Job ID {job_id} is not QA-approved (current state: {row['status'] or 'unknown'})"
        )
    return SelectedJob(
        id=row["id"],
        url=row["url"],
        title=row["title"],
        board=row["board"],
        seniority=row["seniority"],
        jd_text=row["jd_text"],
        snippet=row["snippet"],
        company=(row["company"] or _parse_company(row["url"], row["title"])).strip(),
    )
