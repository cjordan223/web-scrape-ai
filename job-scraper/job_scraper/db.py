"""SQLite database layer for job_scraper v2."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from difflib import SequenceMatcher
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

CREATE TABLE IF NOT EXISTS job_fingerprints (
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
    fingerprint TEXT NOT NULL,
    content_hash TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    duplicate_status TEXT NOT NULL,
    duplicate_of_job_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_job_fingerprint ON job_fingerprints(fingerprint);
CREATE INDEX IF NOT EXISTS idx_job_canonical_url ON job_fingerprints(canonical_url);
CREATE INDEX IF NOT EXISTS idx_job_ats_id ON job_fingerprints(ats_provider, ats_job_id);
CREATE INDEX IF NOT EXISTS idx_job_content_hash ON job_fingerprints(content_hash);

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
    rotation_group INTEGER,
    rotation_members TEXT,
    llm_review TEXT,
    llm_review_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);

CREATE TABLE IF NOT EXISTS run_tier_stats (
    run_id TEXT NOT NULL,
    tier TEXT NOT NULL,
    source TEXT NOT NULL,
    raw_hits INTEGER DEFAULT 0,
    dedup_drops INTEGER DEFAULT 0,
    duplicate_url INTEGER DEFAULT 0,
    duplicate_ats_id INTEGER DEFAULT 0,
    duplicate_fingerprint INTEGER DEFAULT 0,
    duplicate_similar INTEGER DEFAULT 0,
    duplicate_content INTEGER DEFAULT 0,
    reposts INTEGER DEFAULT 0,
    changed_postings INTEGER DEFAULT 0,
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


def _token_similarity(left: str, right: str) -> float:
    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _title_tokens(value: str) -> set[str]:
    aliases = {
        "engineering": "engineer",
        "engineers": "engineer",
        "developer": "engineer",
        "development": "engineer",
    }
    return {aliases.get(token, token) for token in value.split("-") if token}


_GENERIC_COMPANY_NORMS = {"jobs", "job", "careers", "career", "en-us", "en"}
_TITLE_LEVEL_TOKENS = {
    "intern", "internship", "junior", "senior", "staff", "principal",
    "lead", "manager", "director", "head", "i", "ii", "iii", "iv",
}
_SIMILAR_LOCATION_BUCKETS = {"us-remote"}


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
                    ("rotation_members", "TEXT"),
                    ("llm_review", "TEXT"),
                    ("llm_review_at", "TEXT"),
                ]:
                    if col not in cols:
                        self._conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {defn}")
                self._conn.commit()
        except Exception:
            pass
        # Add job fingerprint table/columns and duplicate tier counters.
        try:
            self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS job_fingerprints (
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
                fingerprint TEXT NOT NULL,
                content_hash TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                duplicate_status TEXT NOT NULL,
                duplicate_of_job_id INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_job_fingerprint ON job_fingerprints(fingerprint);
            CREATE INDEX IF NOT EXISTS idx_job_canonical_url ON job_fingerprints(canonical_url);
            CREATE INDEX IF NOT EXISTS idx_job_ats_id ON job_fingerprints(ats_provider, ats_job_id);
            CREATE INDEX IF NOT EXISTS idx_job_content_hash ON job_fingerprints(content_hash);
            """)
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(run_tier_stats)")}
            for col in [
                "duplicate_url", "duplicate_ats_id", "duplicate_fingerprint",
                "duplicate_similar", "duplicate_content", "reposts", "changed_postings",
            ]:
                if cols and col not in cols:
                    self._conn.execute(
                        f"ALTER TABLE run_tier_stats ADD COLUMN {col} INTEGER DEFAULT 0"
                    )
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

    def classify_fingerprint(self, meta: dict, ttl_days: int = 14) -> dict:
        """Return duplicate classification for prepared fingerprint metadata."""
        now_dt = datetime.now(timezone.utc)

        def fresh(row) -> bool:
            first = datetime.fromisoformat(row["first_seen_at"])
            if first.tzinfo is None:
                first = first.replace(tzinfo=timezone.utc)
            return (now_dt - first).days < ttl_days

        def decision(status: str, row=None) -> dict:
            out = {"duplicate_status": status}
            if row is not None:
                out["duplicate_of_job_id"] = row["job_id"]
                out["fingerprint_id"] = row["id"]
            return out

        canonical_url = meta.get("canonical_url") or ""
        if canonical_url:
            row = self._conn.execute(
                """SELECT * FROM job_fingerprints
                   WHERE canonical_url = ?
                   ORDER BY last_seen_at DESC LIMIT 1""",
                (canonical_url,),
            ).fetchone()
            if row:
                return decision("duplicate_url" if fresh(row) else "repost", row)

        ats_provider = meta.get("ats_provider") or ""
        ats_job_id = meta.get("ats_job_id") or ""
        if ats_provider and ats_job_id:
            row = self._conn.execute(
                """SELECT * FROM job_fingerprints
                   WHERE ats_provider = ? AND ats_job_id = ?
                   ORDER BY last_seen_at DESC LIMIT 1""",
                (ats_provider, ats_job_id),
            ).fetchone()
            if row:
                if meta.get("content_hash") and row["content_hash"] and meta["content_hash"] != row["content_hash"]:
                    return decision("changed_posting", row)
                return decision("duplicate_ats_id" if fresh(row) else "repost", row)

        fingerprint = meta.get("fingerprint") or ""
        if fingerprint:
            row = self._conn.execute(
                """SELECT * FROM job_fingerprints
                   WHERE fingerprint = ?
                   ORDER BY last_seen_at DESC LIMIT 1""",
                (fingerprint,),
            ).fetchone()
            if row:
                if meta.get("content_hash") and row["content_hash"] and meta["content_hash"] != row["content_hash"]:
                    return decision("changed_posting", row)
                return decision("duplicate_fingerprint" if fresh(row) else "repost", row)

        content_hash = meta.get("content_hash") or ""
        if content_hash:
            row = self._conn.execute(
                """SELECT * FROM job_fingerprints
                   WHERE content_hash = ?
                   ORDER BY last_seen_at DESC LIMIT 1""",
                (content_hash,),
            ).fetchone()
            if row:
                return decision("mirror" if fresh(row) else "repost", row)

        similar = self._find_similar_fingerprint(meta)
        if similar:
            return decision("similar_posting" if fresh(similar) else "repost", similar)

        return decision("new")

    def _find_similar_fingerprint(
        self,
        meta: dict,
        *,
        exclude_fingerprint_id: int | None = None,
        before_fingerprint_id: int | None = None,
    ):
        """Find a conservative same-company/title-variant match."""
        company_norm = meta.get("company_norm") or ""
        title_norm = meta.get("title_norm") or ""
        location_bucket = meta.get("location_bucket") or ""
        remote_flag = meta.get("remote_flag") or ""
        salary_bucket = meta.get("salary_bucket") or ""
        if not company_norm or not title_norm or len(title_norm) < 10:
            return None
        if company_norm in _GENERIC_COMPANY_NORMS:
            return None
        if location_bucket not in _SIMILAR_LOCATION_BUCKETS:
            return None
        if remote_flag != "true":
            return None

        conditions = [
            "company_norm = ?",
            "location_bucket = ?",
            "remote_flag = ?",
            "title_norm IS NOT NULL",
        ]
        params: list[object] = [company_norm, location_bucket, remote_flag]
        if exclude_fingerprint_id is not None:
            conditions.append("id != ?")
            params.append(exclude_fingerprint_id)
        if before_fingerprint_id is not None:
            conditions.append("id < ?")
            params.append(before_fingerprint_id)
        rows = self._conn.execute(
            f"""SELECT *
                FROM job_fingerprints
                WHERE {' AND '.join(conditions)}
                ORDER BY last_seen_at DESC
                LIMIT 50""",
            params,
        ).fetchall()
        for row in rows:
            existing_title = row["title_norm"] or ""
            if not existing_title or existing_title == title_norm:
                continue
            title_tokens = _title_tokens(title_norm)
            existing_tokens = _title_tokens(existing_title)
            if (title_tokens & _TITLE_LEVEL_TOKENS) != (existing_tokens & _TITLE_LEVEL_TOKENS):
                continue
            if salary_bucket and row["salary_bucket"]:
                known_salary_mismatch = (
                    salary_bucket != "unknown"
                    and row["salary_bucket"] != "unknown"
                    and salary_bucket != row["salary_bucket"]
                )
                if known_salary_mismatch:
                    continue
            ratio = SequenceMatcher(None, title_norm, existing_title).ratio()
            token_ratio = _token_similarity(title_norm, existing_title)
            if token_ratio >= 0.82 or (ratio >= 0.94 and token_ratio >= 0.67):
                return row
        return None

    def save_job_fingerprint(self, job_id: int | None, meta: dict, duplicate_status: str = "new") -> None:
        now = _now()
        duplicate_of = meta.get("duplicate_of_job_id")
        self._conn.execute(
            """INSERT INTO job_fingerprints (
                   job_id, canonical_url, ats_provider, ats_job_id,
                   company_norm, title_norm, location_bucket, remote_flag,
                   salary_bucket, fingerprint, content_hash,
                   first_seen_at, last_seen_at, duplicate_status, duplicate_of_job_id
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                meta.get("canonical_url") or None,
                meta.get("ats_provider") or None,
                meta.get("ats_job_id") or None,
                meta.get("company_norm") or None,
                meta.get("title_norm") or None,
                meta.get("location_bucket") or None,
                meta.get("remote_flag") or None,
                meta.get("salary_bucket") or None,
                meta.get("fingerprint") or "",
                meta.get("content_hash") or None,
                now,
                now,
                duplicate_status,
                duplicate_of,
            ),
        )
        self._conn.commit()

    def touch_fingerprint(self, fingerprint_id: int | None, duplicate_status: str) -> None:
        if fingerprint_id is None:
            return
        self._conn.execute(
            "UPDATE job_fingerprints SET last_seen_at = ?, duplicate_status = ? WHERE id = ?",
            (_now(), duplicate_status, fingerprint_id),
        )
        self._conn.commit()

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
        rotation_members: list[str] | None = None,
        status: str = "completed",
    ) -> None:
        import json as _json
        now = _now()
        started = self._conn.execute(
            "SELECT started_at FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        elapsed = None
        if started:
            start_dt = datetime.fromisoformat(started["started_at"])
            elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()
        members_json = _json.dumps(rotation_members) if rotation_members is not None else None
        self._conn.execute(
            """UPDATE runs SET completed_at = ?, elapsed = ?, raw_count = ?,
               dedup_count = ?, filtered_count = ?, error_count = ?, errors = ?,
               net_new = COALESCE(?, net_new),
               gate_mode = COALESCE(?, gate_mode),
               rotation_group = COALESCE(?, rotation_group),
               rotation_members = COALESCE(?, rotation_members),
               status = ?
            WHERE run_id = ?""",
            (now, elapsed, raw_count, dedup_count, filtered_count, error_count,
             errors, net_new, gate_mode, rotation_group, members_json, status, run_id),
        )
        self._conn.commit()

    def seed_tier_stats(self, run_id: str, members: list[tuple[str, str]]) -> None:
        """Insert a zero row for every (spider, tier) in the rotation.

        Call at run start so spiders that yield 0 items are still visible in
        run_tier_stats (distinguishes 'scheduled-but-silent' from 'not-scheduled').
        """
        for source, tier in members:
            self._conn.execute(
                "INSERT OR IGNORE INTO run_tier_stats (run_id, tier, source) VALUES (?, ?, ?)",
                (run_id, tier, source),
            )
        self._conn.commit()

    def save_run_review(self, run_id: str, review_json: str) -> None:
        self._conn.execute(
            "UPDATE runs SET llm_review = ?, llm_review_at = ? WHERE run_id = ?",
            (review_json, _now(), run_id),
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def backfill_job_fingerprints(self, *, limit: int | None = None, dry_run: bool = False) -> dict:
        """Create fingerprint rows for existing jobs in chronological order."""
        from job_scraper.fingerprints import build_fingerprint_data

        sql = """
            SELECT j.*
            FROM jobs j
            LEFT JOIN job_fingerprints fp ON fp.job_id = j.id
            WHERE fp.id IS NULL
            ORDER BY j.created_at, j.id
        """
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        rows = self._conn.execute(sql, params).fetchall()
        counts: dict[str, int] = {}
        processed = 0
        for row in rows:
            job = dict(row)
            meta = build_fingerprint_data(job).as_dict()
            decision = self.classify_fingerprint(meta)
            duplicate_status = decision["duplicate_status"]
            if decision.get("duplicate_of_job_id") is not None:
                meta["duplicate_of_job_id"] = decision["duplicate_of_job_id"]
            counts[duplicate_status] = counts.get(duplicate_status, 0) + 1
            processed += 1
            if not dry_run:
                self.save_job_fingerprint(int(job["id"]), meta, duplicate_status=duplicate_status)
        return {"processed": processed, "dry_run": dry_run, "counts": counts}

    def reclassify_similar_fingerprints(
        self,
        *,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Reclassify historical 'new' fingerprints that match earlier title variants."""
        sql = """
            SELECT *
            FROM job_fingerprints
            WHERE duplicate_status = 'new'
            ORDER BY first_seen_at, id
        """
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        rows = self._conn.execute(sql, params).fetchall()
        counts = {"similar_posting": 0, "unchanged": 0}
        samples: list[dict] = []
        for row in rows:
            meta = dict(row)
            similar = self._find_similar_fingerprint(
                meta,
                exclude_fingerprint_id=row["id"],
                before_fingerprint_id=row["id"],
            )
            if not similar:
                counts["unchanged"] += 1
                continue
            counts["similar_posting"] += 1
            if len(samples) < 20:
                samples.append({
                    "fingerprint_id": row["id"],
                    "job_id": row["job_id"],
                    "title_norm": row["title_norm"],
                    "matched_fingerprint_id": similar["id"],
                    "duplicate_of_job_id": similar["job_id"],
                    "matched_title_norm": similar["title_norm"],
                })
            if not dry_run:
                self._conn.execute(
                    """UPDATE job_fingerprints
                       SET duplicate_status = 'similar_posting',
                           duplicate_of_job_id = ?
                       WHERE id = ?""",
                    (similar["job_id"], row["id"]),
                )
        if not dry_run:
            self._conn.commit()
        return {
            "processed": len(rows),
            "dry_run": dry_run,
            "counts": counts,
            "samples": samples,
        }
