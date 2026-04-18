"""Scraping API route implementations shared with dashboard backend."""

from __future__ import annotations

import os
import signal
import time

# Reuse shared backend state/helpers from dashboard backend app module.
import app as _app
globals().update({k: v for k, v in _app.__dict__.items() if not k.startswith("__")})

def _sync_app_state() -> None:
    globals().update({k: v for k, v in _app.__dict__.items() if not k.startswith("__")})

def overview():
    _sync_app_state()
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

def list_jobs(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    board: str | None = None,
    seniority: str | None = None,
    decision: str | None = None,
    source: str | None = None,
    search: str | None = None,
    url_search: str | None = None,
    run_id: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    date_from: str | None = None,
    date_to: str | None = None,
):
    _sync_app_state()
    allowed_sort = {"created_at", "title", "board", "seniority", "experience_years", "salary_k", "decision", "source"}
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
    if decision:
        conditions.append("decision = :decision")
        params["decision"] = decision
    if source == "manual_ingest":
        conditions.append("run_id = :manual_run_id")
        params["manual_run_id"] = "manual-ingest"
    elif source == "mobile_ingest":
        conditions.append("run_id = :mobile_run_id")
        params["mobile_run_id"] = "mobile-ingest"
    elif source == "scrape":
        conditions.append("run_id NOT IN ('manual-ingest', 'mobile-ingest')")
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

    conditions.append("NOT EXISTS (SELECT 1 FROM applied_applications aa WHERE aa.job_id = results.id)")
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * per_page
    params["limit"] = per_page
    params["offset"] = offset

    conn = get_db()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM results{where}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT id, url, title, board, seniority, experience_years, salary_k,
                       snippet, query, run_id, created_at, decision
                       , CASE
                           WHEN run_id = 'manual-ingest' THEN 'manual_ingest'
                           WHEN run_id = 'mobile-ingest' THEN 'mobile_ingest'
                           ELSE 'scrape'
                         END AS source
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
        inventory = {
            "results_total": conn.execute(
                "SELECT COUNT(*) FROM results WHERE NOT EXISTS (SELECT 1 FROM applied_applications aa WHERE aa.job_id = results.id)"
            ).fetchone()[0],
            "qa_pending": conn.execute(
                "SELECT COUNT(*) FROM results WHERE decision = 'qa_pending' "
                "AND NOT EXISTS (SELECT 1 FROM applied_applications aa WHERE aa.job_id = results.id)"
            ).fetchone()[0],
            "qa_approved": conn.execute(
                "SELECT COUNT(*) FROM results WHERE decision = 'qa_approved' "
                "AND NOT EXISTS (SELECT 1 FROM applied_applications aa WHERE aa.job_id = results.id)"
            ).fetchone()[0],
            "qa_rejected": conn.execute(
                "SELECT COUNT(*) FROM results WHERE decision = 'qa_rejected' "
                "AND NOT EXISTS (SELECT 1 FROM applied_applications aa WHERE aa.job_id = results.id)"
            ).fetchone()[0],
            "scraper_rejected": conn.execute("SELECT COUNT(*) FROM rejected").fetchone()[0],
            "source_counts": {
                "scrape": conn.execute(
                    "SELECT COUNT(*) FROM results WHERE run_id NOT IN ('manual-ingest', 'mobile-ingest') "
                    "AND NOT EXISTS (SELECT 1 FROM applied_applications aa WHERE aa.job_id = results.id)"
                ).fetchone()[0],
                "manual_ingest": conn.execute(
                    "SELECT COUNT(*) FROM results WHERE run_id = 'manual-ingest' "
                    "AND NOT EXISTS (SELECT 1 FROM applied_applications aa WHERE aa.job_id = results.id)"
                ).fetchone()[0],
                "mobile_ingest": conn.execute(
                    "SELECT COUNT(*) FROM results WHERE run_id = 'mobile-ingest' "
                    "AND NOT EXISTS (SELECT 1 FROM applied_applications aa WHERE aa.job_id = results.id)"
                ).fetchone()[0],
            },
        }
        return {
            "items": items,
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
            "latest_run_id": latest_run_id,
            "inventory": inventory,
        }
    finally:
        conn.close()



def get_job(job_id: int):
    _sync_app_state()
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

def list_runs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    _sync_app_state()
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
                      SUM(CASE WHEN status IN ('complete','completed') THEN 1 ELSE 0 END) as success_count,
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



def active_runs():
    _sync_app_state()
    controls = _load_runtime_controls()
    _reconcile_stale_scrape_runs()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT run_id, started_at FROM runs WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if row:
            return {
                "active": True,
                "run_id": row["run_id"],
                "started_at": row["started_at"],
                "enabled": controls["scrape_enabled"],
            }
        return {"active": False, "enabled": controls["scrape_enabled"]}
    finally:
        conn.close()



def scrape_runner_status(lines: int = Query(80, ge=0, le=500)):
    _sync_app_state()
    return _scrape_runner_snapshot(log_lines=lines)



def run_scrape(payload: dict = Body(default={})):
    _sync_app_state()
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid payload"}, 400)
    spider = payload.get("spider")  # optional: run only one spider
    tiers = payload.get("tiers")
    rotation_group = payload.get("rotation_group")
    run_index = payload.get("run_index")
    ok, result = _start_scrape_run(
        spider=spider,
        tiers=tiers,
        rotation_group=rotation_group,
        run_index=run_index,
    )
    if not ok:
        return JSONResponse(result, 409)
    return result



def get_run(run_id: str):
    _sync_app_state()
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



def get_run_logs(run_id: str, lines: int = Query(200, ge=1, le=2000)):
    _sync_app_state()
    _reconcile_stale_scrape_runs()
    conn = get_db()
    try:
        row = conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "Run not found"}, 404)
        if row["status"] != "running":
            return {"lines": ["Run is no longer active. Historical logs are not available in this view."], "total_lines": 1}
    finally:
        conn.close()

    # Check manual runner first
    snap = _scrape_runner_snapshot(log_lines=lines)
    if snap.get("running") and snap.get("log_tail"):
        return {"lines": snap["log_tail"].split("\n"), "log_path": snap["log_path"]}

    # Check scheduled launchd agent
    label = SCRAPE_SCHEDULED_LABEL
    plist_path = LAUNCH_AGENTS_DIR / f"{label}.plist"
    if plist_path.exists():
        info = _parse_plist(plist_path)
        log_path = info.get("log_path")
        if log_path and Path(log_path).exists():
            try:
                with open(log_path, "r", errors="replace") as f:
                    all_lines = f.readlines()
                return {"lines": [l.rstrip("\n") for l in all_lines[-lines:]], "log_path": log_path}
            except OSError as e:
                return {"lines": [f"Error reading log file: {e}"]}

    return {"lines": ["Waiting for logs to initialize..."]}


def _terminate_pid(pid: int, *, grace_seconds: float = 5.0) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    deadline = time.time() + max(grace_seconds, 0.5)
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        time.sleep(0.2)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    time.sleep(0.2)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def terminate_run(run_id: str):
    _sync_app_state()
    conn = get_db()
    try:
        row = conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row or row["status"] != "running":
            return JSONResponse({"error": "Run is not active"}, 400)
    finally:
        conn.close()

    terminated = False

    # 1. Terminate manual runner if active
    proc = _SCRAPE_RUNNER.get("proc")
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
            terminated = True
        except Exception:
            pass

    # 2. Stop scheduled job via launchctl
    schedule_status = _scrape_schedule_status()
    if schedule_status.get("loaded"):
        subprocess.run(["launchctl", "stop", SCRAPE_SCHEDULED_LABEL], capture_output=True, text=True)
    schedule_pid = schedule_status.get("pid")
    if isinstance(schedule_pid, int) and schedule_pid > 0:
        terminated = _terminate_pid(schedule_pid) or terminated
    elif schedule_status.get("loaded"):
        terminated = True

    reconciled = _mark_scrape_run_inactive(
        run_id,
        status="failed",
        error="Run terminated by user via dashboard.",
    )
    if reconciled:
        _reconcile_stale_scrape_runs()

    if terminated or reconciled:
        return {
            "ok": True,
            "message": "Termination processed successfully",
            "terminated_process": terminated,
            "reconciled_run": reconciled,
            "runner": _scrape_runner_snapshot(log_lines=0),
        }

    stale = _reconcile_stale_scrape_runs()
    if run_id in set(stale.get("stale_run_ids", [])):
        return {
            "ok": True,
            "message": "No live process was found. Cleared stale active run state.",
            "terminated_process": False,
            "reconciled_run": True,
            "runner": _scrape_runner_snapshot(log_lines=0),
        }

    return JSONResponse({"error": "Could not find an active process to terminate. The run may have already exited."}, 500)


# ---------------------------------------------------------------------------
# Routes — API: Filters
# ---------------------------------------------------------------------------

def filter_stats():
    _sync_app_state()
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

def dedup_stats():
    _sync_app_state()
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



def growth():
    _sync_app_state()
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



def rejected_stats():
    _sync_app_state()
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



def list_rejected(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    stage: str | None = None,
    run_id: str | None = None,
    search: str | None = None,
):
    _sync_app_state()
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



def get_rejected(rejected_id: int):
    _sync_app_state()
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



def approve_rejected(rejected_id: int):
    _sync_app_state()
    conn = get_db_write()
    try:
        conn.execute("BEGIN")
        rejected = conn.execute(
            "SELECT * FROM rejected WHERE id = ?",
            (rejected_id,),
        ).fetchone()
        if not rejected:
            conn.rollback()
            return JSONResponse({"ok": False, "error": "Rejected job not found"}, 404)

        existing = conn.execute(
            "SELECT id FROM results WHERE url = ? AND run_id = ?",
            (rejected["url"], rejected["run_id"]),
        ).fetchone()

        result_id: int | None = None
        already_present = existing is not None
        if existing:
            result_id = existing["id"]
        else:
            now = datetime.now(timezone.utc).isoformat()
            cur = conn.execute(
                """INSERT INTO jobs
                   (url, title, board, seniority, experience_years, salary_k, score, status,
                    snippet, query, jd_text, filter_verdicts, run_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rejected["url"],
                    rejected["title"],
                    rejected["board"],
                    "unknown",
                    None,
                    None,
                    None,
                    "qa_pending",
                    rejected["snippet"],
                    None,
                    None,
                    rejected["filter_verdicts"],
                    rejected["run_id"],
                    now,
                ),
            )
            result_id = cur.lastrowid

        conn.execute("DELETE FROM rejected WHERE id = ?", (rejected_id,))
        try:
            from services.audit import log_state_change
            log_state_change(
                conn,
                job_id=result_id,
                job_url=rejected["url"],
                old_state="rejected",
                new_state="qa_pending",
                action="rescue_to_qa",
                detail={
                    "rejection_stage": rejected["rejection_stage"],
                    "rejection_reason": rejected["rejection_reason"],
                    "already_present": already_present,
                },
            )
        except Exception:
            pass  # fail-open: don't block rescue if audit table missing
        conn.commit()
        return {"ok": True, "result_id": result_id, "already_present": already_present}
    except sqlite3.IntegrityError as e:
        conn.rollback()
        return JSONResponse({"ok": False, "error": f"Failed to approve rejected job: {e}"}, 409)
    except sqlite3.Error as e:
        conn.rollback()
        return JSONResponse({"ok": False, "error": f"Database error: {e}"}, 500)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes — API: Source Diagnostics
# ---------------------------------------------------------------------------

def tier_stats_rollup(since: str = "7d"):
    """Tier-aware rollups: per-run, source-health, daily net-new over a window."""
    import re
    from datetime import datetime, timedelta, timezone

    _sync_app_state()
    m = re.fullmatch(r"(\d+)d", since or "")
    days = int(m.group(1)) if m else 7
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_db()
    try:
        per_run = [
            dict(r)
            for r in conn.execute(
                """SELECT run_id, started_at, net_new, gate_mode, rotation_group
                   FROM runs WHERE started_at >= ? ORDER BY started_at DESC LIMIT 60""",
                (cutoff,),
            ).fetchall()
        ]
        by_source = [
            dict(r)
            for r in conn.execute(
                """SELECT source, tier,
                          SUM(raw_hits) AS raw_hits,
                          SUM(dedup_drops) AS dedup_drops,
                          SUM(filter_drops) AS filter_drops,
                          SUM(llm_rejects + llm_uncertain_low) AS llm_rejects,
                          SUM(stored_pending) AS stored_pending,
                          SUM(stored_lead) AS stored_lead,
                          COUNT(DISTINCT run_id) AS runs
                   FROM run_tier_stats
                   WHERE run_id IN (SELECT run_id FROM runs WHERE started_at >= ?)
                   GROUP BY source, tier""",
                (cutoff,),
            ).fetchall()
        ]
        daily_net_new = [
            dict(r)
            for r in conn.execute(
                """SELECT substr(started_at, 1, 10) AS day, SUM(net_new) AS net_new
                   FROM runs WHERE started_at >= ?
                   GROUP BY substr(started_at, 1, 10) ORDER BY day""",
                (cutoff,),
            ).fetchall()
        ]
        return {"per_run": per_run, "by_source": by_source, "daily_net_new": daily_net_new}
    finally:
        conn.close()


def source_diagnostics():
    """Per-source and per-board breakdown of pipeline performance."""
    _sync_app_state()
    conn = get_db()
    try:
        # --- Source breakdown (accepted jobs) ---
        source_rows = conn.execute(
            """SELECT
                 CASE
                   WHEN source LIKE 'watcher:%' THEN source
                   WHEN source = 'crawl4ai' OR source LIKE 'crawl%' THEN 'crawl4ai'
                   WHEN source = '' OR source IS NULL THEN 'searxng'
                   ELSE source
                 END AS src,
                 COUNT(*) AS cnt,
                 COUNT(DISTINCT run_id) AS runs
               FROM results
               GROUP BY src
               ORDER BY cnt DESC"""
        ).fetchall()
        by_source = [{"source": r["src"], "accepted": r["cnt"], "runs": r["runs"]} for r in source_rows]

        # --- Board breakdown (accepted jobs) ---
        board_rows = conn.execute(
            "SELECT board, COUNT(*) AS cnt FROM results GROUP BY board ORDER BY cnt DESC"
        ).fetchall()
        by_board = [{"board": r["board"], "accepted": r["cnt"]} for r in board_rows]

        # --- Rejection breakdown by source (from rejected table) ---
        # rejected table doesn't have source column, but has board which correlates
        rej_board_rows = conn.execute(
            """SELECT board, rejection_stage, COUNT(*) AS cnt
               FROM rejected
               GROUP BY board, rejection_stage
               ORDER BY cnt DESC"""
        ).fetchall()
        rejection_by_board: dict[str, dict[str, int]] = {}
        for r in rej_board_rows:
            board = r["board"] or "unknown"
            if board not in rejection_by_board:
                rejection_by_board[board] = {}
            rejection_by_board[board][r["rejection_stage"]] = r["cnt"]

        # --- Recent runs with source breakdown ---
        recent_runs = conn.execute(
            """SELECT run_id, started_at, raw_count, dedup_count, filtered_count, status
               FROM runs ORDER BY started_at DESC LIMIT 10"""
        ).fetchall()
        run_sources = []
        for run in recent_runs:
            rid = run["run_id"]
            src_counts = conn.execute(
                """SELECT
                     CASE
                       WHEN source LIKE 'watcher:%' THEN source
                       WHEN source = 'crawl4ai' OR source LIKE 'crawl%' THEN 'crawl4ai'
                       WHEN source = '' OR source IS NULL THEN 'searxng'
                       ELSE source
                     END AS src,
                     COUNT(*) AS cnt
                   FROM results WHERE run_id = ?
                   GROUP BY src""",
                (rid,),
            ).fetchall()
            board_counts = conn.execute(
                "SELECT board, COUNT(*) AS cnt FROM results WHERE run_id = ? GROUP BY board",
                (rid,),
            ).fetchall()
            run_sources.append({
                "run_id": rid,
                "started_at": run["started_at"],
                "status": run["status"],
                "raw_count": run["raw_count"],
                "dedup_count": run["dedup_count"],
                "filtered_count": run["filtered_count"],
                "sources": {r["src"]: r["cnt"] for r in src_counts},
                "boards": {r["board"]: r["cnt"] for r in board_counts},
            })

        # --- Top rejection stages overall ---
        rej_stage_rows = conn.execute(
            """SELECT rejection_stage, COUNT(*) AS cnt
               FROM rejected GROUP BY rejection_stage ORDER BY cnt DESC LIMIT 15"""
        ).fetchall()
        top_rejections = [{"stage": r["rejection_stage"], "count": r["cnt"]} for r in rej_stage_rows]

        return {
            "by_source": by_source,
            "by_board": by_board,
            "rejection_by_board": rejection_by_board,
            "recent_runs": run_sources,
            "top_rejections": top_rejections,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes — API: Tailoring transparency
# ---------------------------------------------------------------------------
