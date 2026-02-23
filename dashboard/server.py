"""Job Scraper Dashboard — FastAPI backend."""

import json
import os
import plistlib
import re
import sqlite3
import subprocess
import time
from collections import defaultdict
from pathlib import Path

import urllib.error
import urllib.request

import uvicorn
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get(
    "JOB_SCRAPER_DB",
    str(Path.home() / ".local/share/job_scraper/jobs.db"),
)
PORT = int(os.environ.get("DASHBOARD_PORT", "8899"))
LAUNCH_AGENTS_DIR = Path.home() / "Library/LaunchAgents"

HERE = Path(__file__).resolve().parent

app = FastAPI(title="Job Scraper Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Routes — static
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(HERE / "index.html")


# ---------------------------------------------------------------------------
# Routes — API: Overview
# ---------------------------------------------------------------------------
@app.get("/api/overview")
def overview():
    conn = get_db()
    try:
        total_results = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        total_seen = conn.execute("SELECT COUNT(*) FROM seen_urls").fetchone()[0]
        jobs_today = conn.execute(
            "SELECT COUNT(*) FROM results WHERE date(created_at) = date('now')"
        ).fetchone()[0]

        # Dedup ratio
        dedup_ratio = round(total_results / total_seen, 3) if total_seen > 0 else 0

        # Error rate from recent runs
        recent_runs = conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed FROM runs"
        ).fetchone()
        error_rate = round(recent_runs["failed"] / recent_runs["total"], 3) if recent_runs["total"] > 0 else 0

        # DB file size
        try:
            db_size = os.path.getsize(DB_PATH)
        except OSError:
            db_size = 0

        last_run_row = conn.execute(
            "SELECT run_id, started_at, status FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        last_run = (
            {"run_id": last_run_row["run_id"], "timestamp": last_run_row["started_at"], "status": last_run_row["status"]}
            if last_run_row
            else None
        )

        trend = [
            {"date": r["day"], "count": r["cnt"]}
            for r in conn.execute(
                """SELECT date(created_at) AS day, COUNT(*) AS cnt
                   FROM results
                   WHERE created_at >= date('now', '-30 days')
                   GROUP BY date(created_at)
                   ORDER BY day"""
            ).fetchall()
        ]

        boards = {
            r["board"]: r["cnt"]
            for r in conn.execute(
                "SELECT board, COUNT(*) AS cnt FROM results GROUP BY board"
            ).fetchall()
        }

        seniority = {
            r["seniority"]: r["cnt"]
            for r in conn.execute(
                "SELECT seniority, COUNT(*) AS cnt FROM results GROUP BY seniority"
            ).fetchall()
        }

        # Run health: last 20 runs
        health_rows = conn.execute(
            "SELECT run_id, status, started_at FROM runs ORDER BY started_at DESC LIMIT 20"
        ).fetchall()
        run_health = [{"run_id": r["run_id"], "status": r["status"], "started_at": r["started_at"]} for r in health_rows]

        return {
            "total_results": total_results,
            "total_seen": total_seen,
            "jobs_today": jobs_today,
            "dedup_ratio": dedup_ratio,
            "error_rate": error_rate,
            "db_size": db_size,
            "last_run": last_run,
            "trend": trend,
            "boards": boards,
            "seniority": seniority,
            "run_health": run_health,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes — API: Jobs
# ---------------------------------------------------------------------------
@app.get("/api/jobs")
def list_jobs(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    board: str | None = None,
    seniority: str | None = None,
    search: str | None = None,
    url_search: str | None = None,
    run_id: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    date_from: str | None = None,
    date_to: str | None = None,
):
    allowed_sort = {"created_at", "title", "board", "seniority", "experience_years", "salary_k"}
    if sort_by not in allowed_sort:
        sort_by = "created_at"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    conditions: list[str] = []
    params: dict = {}

    if board:
        conditions.append("board = :board")
        params["board"] = board
    if seniority:
        conditions.append("seniority = :seniority")
        params["seniority"] = seniority
    if search:
        conditions.append("title LIKE :search")
        params["search"] = f"%{search}%"
    if url_search:
        conditions.append("url LIKE :url_search")
        params["url_search"] = f"%{url_search}%"
    if run_id:
        conditions.append("run_id = :run_id")
        params["run_id"] = run_id
    if date_from:
        conditions.append("created_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("created_at <= :date_to")
        params["date_to"] = date_to

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * per_page
    params["limit"] = per_page
    params["offset"] = offset

    conn = get_db()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM results{where}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT id, url, title, board, seniority, experience_years, salary_k,
                       snippet, query, run_id, created_at
                FROM results{where}
                ORDER BY {sort_by} {sort_dir}
                LIMIT :limit OFFSET :offset""",
            params,
        ).fetchall()

        # Get latest run_id for "new this run" badge
        latest_run = conn.execute(
            "SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        latest_run_id = latest_run["run_id"] if latest_run else None

        items = [dict(r) for r in rows]
        return {
            "items": items,
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
            "latest_run_id": latest_run_id,
        }
    finally:
        conn.close()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM results WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "Not found"}, 404)
        data = dict(row)
        data["filter_verdicts"] = json.loads(data.get("filter_verdicts") or "[]")
        return data
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes — API: Runs
# ---------------------------------------------------------------------------
@app.get("/api/runs")
def list_runs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        offset = (page - 1) * per_page
        rows = conn.execute(
            """SELECT run_id, started_at, completed_at, elapsed,
                      raw_count, dedup_count, filtered_count,
                      error_count, errors, status
               FROM runs
               ORDER BY started_at DESC
               LIMIT ? OFFSET ?""",
            (per_page, offset),
        ).fetchall()
        runs = []
        for r in rows:
            run = dict(r)
            run["errors"] = json.loads(run["errors"]) if run["errors"] else []
            # Count actual jobs stored for this run
            job_count = conn.execute(
                "SELECT COUNT(*) FROM results WHERE run_id = ?", (run["run_id"],)
            ).fetchone()[0]
            run["job_count"] = job_count
            runs.append(run)

        # Stats
        stats_row = conn.execute(
            """SELECT AVG(elapsed) as avg_duration,
                      COUNT(*) as total_runs,
                      SUM(CASE WHEN status='complete' THEN 1 ELSE 0 END) as success_count,
                      AVG(filtered_count) as avg_jobs
               FROM runs WHERE status != 'running'"""
        ).fetchone()
        stats = {
            "avg_duration": round(stats_row["avg_duration"], 1) if stats_row["avg_duration"] else 0,
            "success_rate": round(stats_row["success_count"] / stats_row["total_runs"] * 100, 1) if stats_row["total_runs"] > 0 else 0,
            "avg_jobs_per_run": round(stats_row["avg_jobs"], 1) if stats_row["avg_jobs"] else 0,
            "total_runs": stats_row["total_runs"] or 0,
        }

        return {
            "runs": runs,
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
            "stats": stats,
        }
    finally:
        conn.close()


@app.get("/api/runs/active")
def active_runs():
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT run_id, started_at FROM runs WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if row:
            return {"active": True, "run_id": row["run_id"], "started_at": row["started_at"]}
        return {"active": False}
    finally:
        conn.close()


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT run_id, started_at, completed_at, elapsed,
                      raw_count, dedup_count, filtered_count,
                      error_count, errors, status
               FROM runs WHERE run_id = ?""",
            (run_id,),
        ).fetchone()
        if not row:
            return JSONResponse({"error": "Run not found"}, 404)
        run = dict(row)
        run["errors"] = json.loads(run["errors"]) if run["errors"] else []

        # Get all jobs from this run
        jobs = [
            dict(r)
            for r in conn.execute(
                """SELECT id, url, title, board, seniority, experience_years,
                          snippet, query, created_at
                   FROM results WHERE run_id = ?
                   ORDER BY created_at DESC""",
                (run_id,),
            ).fetchall()
        ]
        run["jobs"] = jobs
        return run
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes — API: Filters
# ---------------------------------------------------------------------------
@app.get("/api/filters/stats")
def filter_stats():
    conn = get_db()
    try:
        rows = conn.execute("SELECT filter_verdicts FROM results").fetchall()
        stage_reasons: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in rows:
            verdicts = json.loads(row["filter_verdicts"] or "[]")
            for v in verdicts:
                stage_reasons[v["stage"]][v["reason"]] += 1

        stages = []
        for stage, reasons in stage_reasons.items():
            sorted_reasons = sorted(reasons.items(), key=lambda x: -x[1])
            stages.append({
                "stage": stage,
                "total": sum(reasons.values()),
                "reasons": [{"reason": r, "count": c} for r, c in sorted_reasons],
            })

        return {"stages": stages}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes — API: Dedup & Growth
# ---------------------------------------------------------------------------
@app.get("/api/dedup/stats")
def dedup_stats():
    conn = get_db()
    try:
        total_seen = conn.execute("SELECT COUNT(*) FROM seen_urls").fetchone()[0]
        total_results = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]

        # Daily new URL rate (from seen_urls first_seen if available, else from results created_at)
        daily_new = [
            {"date": r["day"], "count": r["cnt"]}
            for r in conn.execute(
                """SELECT date(created_at) AS day, COUNT(*) AS cnt
                   FROM results
                   GROUP BY date(created_at)
                   ORDER BY day"""
            ).fetchall()
        ]

        # Per-run uniqueness: for each run, how many of its results were new
        # (run's filtered_count vs how many were actually stored as new)
        run_uniqueness = []
        runs = conn.execute(
            """SELECT run_id, started_at, raw_count, dedup_count, filtered_count
               FROM runs WHERE status='complete'
               ORDER BY started_at DESC LIMIT 50"""
        ).fetchall()
        for r in runs:
            job_count = conn.execute(
                "SELECT COUNT(*) FROM results WHERE run_id = ?", (r["run_id"],)
            ).fetchone()[0]
            run_uniqueness.append({
                "run_id": r["run_id"],
                "date": r["started_at"],
                "raw": r["raw_count"] or 0,
                "dedup": r["dedup_count"] or 0,
                "filtered": r["filtered_count"] or 0,
                "stored": job_count,
            })

        # Repeat URL frequency: count how many times each URL appears across runs
        # Using seen_urls table — group by count ranges
        # Since seen_urls just tracks unique URLs, we use results table to find repeats
        repeat_freq = {"1x": 0, "2-5x": 0, "5-10x": 0, "10x+": 0}
        url_counts = conn.execute(
            """SELECT url, COUNT(*) as cnt FROM (
                 SELECT url FROM results
                 UNION ALL
                 SELECT url FROM seen_urls WHERE url NOT IN (SELECT url FROM results)
               ) GROUP BY url"""
        ).fetchall()
        for r in url_counts:
            c = r["cnt"]
            if c == 1:
                repeat_freq["1x"] += 1
            elif c <= 5:
                repeat_freq["2-5x"] += 1
            elif c <= 10:
                repeat_freq["5-10x"] += 1
            else:
                repeat_freq["10x+"] += 1

        return {
            "total_seen": total_seen,
            "total_results": total_results,
            "daily_new": daily_new,
            "run_uniqueness": run_uniqueness,
            "repeat_freq": repeat_freq,
        }
    finally:
        conn.close()


@app.get("/api/growth")
def growth():
    conn = get_db()
    try:
        # Cumulative results over time
        results_growth = [
            {"date": r["day"], "cumulative": r["cum"]}
            for r in conn.execute(
                """SELECT day, SUM(cnt) OVER (ORDER BY day) as cum
                   FROM (SELECT date(created_at) AS day, COUNT(*) AS cnt
                         FROM results GROUP BY date(created_at))
                   ORDER BY day"""
            ).fetchall()
        ]

        # Cumulative seen_urls — use first_seen (schema column name)
        seen_growth = []
        try:
            seen_growth = [
                {"date": r["day"], "cumulative": r["cum"]}
                for r in conn.execute(
                    """SELECT day, SUM(cnt) OVER (ORDER BY day) as cum
                       FROM (SELECT date(first_seen) AS day, COUNT(*) AS cnt
                             FROM seen_urls WHERE first_seen IS NOT NULL
                             GROUP BY date(first_seen))
                       ORDER BY day"""
                ).fetchall()
            ]
        except sqlite3.OperationalError:
            seen_growth = []

        return {
            "results": results_growth,
            "seen_urls": seen_growth,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes — API: DB Explorer
# ---------------------------------------------------------------------------
ALLOWED_TABLES = {"seen_urls", "results", "runs", "sqlite_sequence"}


@app.get("/api/db/tables")
def db_tables():
    conn = get_db()
    try:
        tables = []
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        for r in rows:
            name = r["name"]
            count = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
            cols = [
                {"name": c["name"], "type": c["type"], "notnull": bool(c["notnull"]), "pk": bool(c["pk"])}
                for c in conn.execute(f"PRAGMA table_info([{name}])").fetchall()
            ]
            tables.append({"name": name, "row_count": count, "columns": cols})
        return {"tables": tables}
    finally:
        conn.close()


@app.get("/api/db/table/{name}")
def db_table_browse(
    name: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort_by: str | None = None,
    sort_dir: str = "asc",
):
    # Validate table name against actual tables
    conn = get_db()
    try:
        existing = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if name not in existing:
            return JSONResponse({"error": f"Table '{name}' not found"}, 404)

        if sort_dir not in ("asc", "desc"):
            sort_dir = "asc"

        # Validate sort column
        col_names = [c["name"] for c in conn.execute(f"PRAGMA table_info([{name}])").fetchall()]
        if sort_by and sort_by not in col_names:
            sort_by = None

        total = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
        offset = (page - 1) * per_page

        order = f"ORDER BY [{sort_by}] {sort_dir}" if sort_by else ""
        rows = conn.execute(
            f"SELECT * FROM [{name}] {order} LIMIT ? OFFSET ?",
            (per_page, offset),
        ).fetchall()

        items = [dict(r) for r in rows]
        return {
            "items": items,
            "columns": col_names,
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
        }
    finally:
        conn.close()


@app.get("/api/db/query")
def db_query(sql: str = Query(..., min_length=1)):
    # Security: only SELECT, enforce LIMIT, timeout
    stripped = sql.strip().rstrip(";")
    if not re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
        return JSONResponse({"error": "Only SELECT queries are allowed"}, 400)

    # Block dangerous keywords
    upper = stripped.upper()
    for kw in ("DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "ATTACH", "DETACH"):
        if kw in upper:
            return JSONResponse({"error": f"'{kw}' is not allowed in queries"}, 400)

    # Enforce LIMIT
    if "LIMIT" not in upper:
        stripped += " LIMIT 1000"

    conn = get_db()
    try:
        conn.execute("PRAGMA query_only = ON")
        start = time.monotonic()
        try:
            cursor = conn.execute(stripped)
        except sqlite3.OperationalError as e:
            return JSONResponse({"error": str(e)}, 400)
        elapsed = time.monotonic() - start

        if elapsed > 5:
            return JSONResponse({"error": "Query timed out (>5s)"}, 408)

        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "elapsed_ms": round(elapsed * 1000, 1),
        }
    finally:
        conn.close()


@app.get("/api/db/size")
def db_size():
    try:
        size = os.path.getsize(DB_PATH)
    except OSError:
        size = 0
    return {"size_bytes": size, "path": DB_PATH}


# ---------------------------------------------------------------------------
# Routes — API: Schedules (launchd)
# ---------------------------------------------------------------------------
def _parse_plist(path: Path) -> dict:
    """Parse a launchd plist file and return structured info."""
    with open(path, "rb") as f:
        plist = plistlib.load(f)

    label = plist.get("Label", path.stem)
    program_args = plist.get("ProgramArguments", [])
    command = " ".join(program_args) if program_args else plist.get("Program", "")
    working_dir = plist.get("WorkingDirectory", "")
    run_at_load = plist.get("RunAtLoad", False)

    # Schedule info
    interval = plist.get("StartInterval")
    cal = plist.get("StartCalendarInterval")
    schedule_str = ""
    if interval:
        mins = interval // 60
        schedule_str = f"Every {mins}m" if mins > 0 else f"Every {interval}s"
    elif cal:
        if isinstance(cal, list):
            schedule_str = f"{len(cal)} calendar entries"
        else:
            parts = []
            if "Weekday" in cal:
                days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
                parts.append(days[cal["Weekday"]] if cal["Weekday"] < 7 else str(cal["Weekday"]))
            if "Hour" in cal:
                parts.append(f"{cal['Hour']:02d}:{cal.get('Minute', 0):02d}")
            schedule_str = " ".join(parts) if parts else "Calendar"
    elif run_at_load:
        schedule_str = "On load only"

    stdout = plist.get("StandardOutPath", "")
    stderr = plist.get("StandardErrorPath", "")
    log_path = stdout or stderr or ""

    return {
        "label": label,
        "plist_path": str(path),
        "command": command,
        "working_dir": working_dir,
        "schedule": schedule_str,
        "interval_seconds": interval,
        "run_at_load": run_at_load,
        "log_path": log_path,
    }


def _get_launchctl_status(label: str) -> dict:
    """Get runtime status from launchctl."""
    try:
        result = subprocess.run(
            ["launchctl", "list", label],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return {"loaded": False, "pid": None, "last_exit": None}

        info = {}
        for line in result.stdout.splitlines():
            line = line.strip().strip(";")
            if "=" in line:
                key, _, val = line.partition("=")
                key = key.strip().strip('"')
                val = val.strip().strip('"').strip(";")
                info[key] = val

        pid_raw = info.get("PID")
        pid = int(pid_raw) if pid_raw and pid_raw.isdigit() else None
        last_exit_raw = info.get("LastExitStatus")
        last_exit = int(last_exit_raw) if last_exit_raw and last_exit_raw.isdigit() else None

        return {"loaded": True, "pid": pid, "last_exit": last_exit, "running": pid is not None}
    except Exception:
        return {"loaded": False, "pid": None, "last_exit": None}


@app.get("/api/schedules")
def list_schedules():
    """List all launchd agents with their config and runtime status."""
    if not LAUNCH_AGENTS_DIR.exists():
        return {"jobs": []}

    jobs = []
    for plist_path in sorted(LAUNCH_AGENTS_DIR.glob("*.plist")):
        try:
            info = _parse_plist(plist_path)
        except Exception:
            continue

        status = _get_launchctl_status(info["label"])
        info.update(status)

        # Log file stats
        if info["log_path"]:
            try:
                lp = Path(info["log_path"])
                info["log_size"] = lp.stat().st_size if lp.exists() else 0
                info["log_modified"] = lp.stat().st_mtime if lp.exists() else None
            except OSError:
                info["log_size"] = 0
                info["log_modified"] = None
        else:
            info["log_size"] = 0
            info["log_modified"] = None

        jobs.append(info)

    return {"jobs": jobs}


@app.get("/api/schedules/{label}/log")
def get_schedule_log(label: str, lines: int = Query(100, ge=1, le=2000)):
    """Get the last N lines of a scheduled job's log file."""
    # Find the plist for this label
    plist_path = LAUNCH_AGENTS_DIR / f"{label}.plist"
    if not plist_path.exists():
        return JSONResponse({"error": "Job not found"}, 404)

    try:
        info = _parse_plist(plist_path)
    except Exception as e:
        return JSONResponse({"error": f"Failed to parse plist: {e}"}, 500)

    log_path = info.get("log_path")
    if not log_path or not Path(log_path).exists():
        return {"lines": [], "total_lines": 0, "log_path": log_path or ""}

    try:
        # Read last N lines efficiently
        with open(log_path, "r", errors="replace") as f:
            all_lines = f.readlines()
        total = len(all_lines)
        tail = all_lines[-lines:]
        return {
            "lines": [l.rstrip("\n") for l in tail],
            "total_lines": total,
            "log_path": log_path,
        }
    except OSError as e:
        return JSONResponse({"error": str(e)}, 500)


# ---------------------------------------------------------------------------
# Routes — API: Rejected jobs
# ---------------------------------------------------------------------------
@app.get("/api/rejected/stats")
def rejected_stats():
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM rejected").fetchone()[0]
        by_stage = {
            r["rejection_stage"]: r["cnt"]
            for r in conn.execute(
                "SELECT rejection_stage, COUNT(*) as cnt FROM rejected GROUP BY rejection_stage ORDER BY cnt DESC"
            ).fetchall()
        }
        return {"total": total, "by_stage": by_stage}
    finally:
        conn.close()


@app.get("/api/rejected")
def list_rejected(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    stage: str | None = None,
    run_id: str | None = None,
    search: str | None = None,
):
    conditions: list[str] = []
    params: dict = {}

    if stage:
        conditions.append("rejection_stage = :stage")
        params["stage"] = stage
    if run_id:
        conditions.append("run_id = :run_id")
        params["run_id"] = run_id
    if search:
        conditions.append("title LIKE :search")
        params["search"] = f"%{search}%"

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * per_page
    params["limit"] = per_page
    params["offset"] = offset

    conn = get_db()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM rejected{where}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT id, url, title, board, snippet, rejection_stage, rejection_reason, run_id, created_at
                FROM rejected{where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset""",
            params,
        ).fetchall()
        stages = [
            r["rejection_stage"]
            for r in conn.execute(
                "SELECT DISTINCT rejection_stage FROM rejected ORDER BY rejection_stage"
            ).fetchall()
        ]
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
            "stages": stages,
        }
    finally:
        conn.close()


@app.get("/api/rejected/{rejected_id}")
def get_rejected(rejected_id: int):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM rejected WHERE id = ?", (rejected_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "Not found"}, 404)
        data = dict(row)
        data["filter_verdicts"] = json.loads(data.get("filter_verdicts") or "[]")
        return data
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes — API: LLM status
# ---------------------------------------------------------------------------
LLM_URL = os.environ.get("LLM_URL", "http://localhost:8800")


@app.get("/api/llm/status")
def llm_status():
    """Check whether the local LLM server is reachable."""
    try:
        with urllib.request.urlopen(f"{LLM_URL}/v1/models", timeout=2) as resp:
            data = json.loads(resp.read())
        models = [m["id"] for m in data.get("data", [])]
        return {"available": True, "models": models, "url": LLM_URL}
    except Exception:
        return {"available": False, "models": [], "url": LLM_URL}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=True)
