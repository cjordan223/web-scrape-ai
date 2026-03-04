"""Ops route implementations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Request

# Reuse shared backend state/helpers from app module.
import app as _app
globals().update({k: v for k, v in _app.__dict__.items() if not k.startswith("__")})

def _sync_app_state() -> None:
    globals().update({k: v for k, v in _app.__dict__.items() if not k.startswith("__")})


def db_schema():
    _sync_app_state()
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        tables: list[dict] = []
        for r in rows:
            name = r["name"]
            cols = [
                {
                    "name": c["name"],
                    "type": c["type"],
                    "notnull": bool(c["notnull"]),
                    "pk": bool(c["pk"]),
                }
                for c in conn.execute(f"PRAGMA table_info([{name}])").fetchall()
            ]
            tables.append({"name": name, "columns": cols})
        return {"tables": tables}
    finally:
        conn.close()


def db_tables():
    _sync_app_state()
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



def db_table_browse(
    name: str,
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort_by: str | None = None,
    sort_dir: str = "asc",
):
    _sync_app_state()
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

        # Column filters are provided as arbitrary query params where
        # the key matches a column name and value is a substring filter.
        reserved = {"page", "per_page", "sort_by", "sort_dir"}
        filters: dict[str, str] = {}
        for key, raw_val in request.query_params.items():
            if key in reserved:
                continue
            val = (raw_val or "").strip()
            if key in col_names and val:
                filters[key] = val

        where_parts: list[str] = []
        where_vals: list[object] = []
        for col, val in filters.items():
            where_parts.append(f"CAST([{col}] AS TEXT) LIKE ?")
            where_vals.append(f"%{val}%")

        where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        total = conn.execute(
            f"SELECT COUNT(*) FROM [{name}] {where_sql}",
            where_vals,
        ).fetchone()[0]
        offset = (page - 1) * per_page

        order = f"ORDER BY [{sort_by}] {sort_dir}" if sort_by else ""
        query_vals = [*where_vals, per_page, offset]
        rows = conn.execute(
            f"SELECT * FROM [{name}] {where_sql} {order} LIMIT ? OFFSET ?",
            query_vals,
        ).fetchall()

        items = [dict(r) for r in rows]
        return {
            "items": items,
            "columns": col_names,
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
            "applied_filters": filters,
        }
    finally:
        conn.close()



def db_query(sql: str = Query(..., min_length=1)):
    _sync_app_state()
    # Security: only SELECT, enforce LIMIT, timeout
    stripped = sql.strip().rstrip(";")
    if not re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
        return JSONResponse({"error": "Only SELECT queries are allowed"}, 400)

    # Block dangerous keywords as parsed tokens to avoid false positives on
    # column names like "created_at".
    upper = stripped.upper()
    tokens = set(re.findall(r"[A-Z_]+", upper))
    for kw in ("DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "ATTACH", "DETACH"):
        if kw in tokens:
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



def db_size():
    _sync_app_state()
    try:
        size = os.path.getsize(DB_PATH)
    except OSError:
        size = 0
    return {"size_bytes": size, "path": DB_PATH}


def _db_admin_enabled() -> bool:
    raw = os.environ.get("DASHBOARD_ENABLE_DB_ADMIN", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _db_user_tables(conn) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


def _db_table_counts(conn, tables: list[str]) -> list[dict]:
    out: list[dict] = []
    for table in tables:
        cnt = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
        out.append({"name": table, "row_count": cnt})
    return out


def db_admin_status():
    _sync_app_state()
    enabled = _db_admin_enabled()
    conn = get_db()
    try:
        tables = _db_user_tables(conn)
        table_counts = _db_table_counts(conn, tables)
        return {
            "enabled": enabled,
            "confirm_phrase": "DROP ALL DATA",
            "tables": table_counts,
            "actions": [
                {"key": "truncate_all", "label": "Delete all rows from all tables"},
                {"key": "truncate_tables", "label": "Delete all rows from selected tables"},
                {"key": "drop_tables", "label": "Drop selected tables (schema + data)"},
            ],
        }
    finally:
        conn.close()


def db_admin_action(payload: dict = Body(default={})):
    _sync_app_state()
    if not _db_admin_enabled():
        return JSONResponse(
            {"error": "DB admin actions are disabled. Set DASHBOARD_ENABLE_DB_ADMIN=1 to enable."},
            403,
        )

    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid payload"}, 400)

    action = str(payload.get("action", "")).strip()
    confirm = str(payload.get("confirm", "")).strip()
    if confirm != "DROP ALL DATA":
        return JSONResponse({"error": "Confirmation phrase mismatch."}, 400)

    conn = get_db_write()
    try:
        existing = set(_db_user_tables(conn))
        if action == "truncate_all":
            targets = sorted(existing)
            for t in targets:
                conn.execute(f"DELETE FROM [{t}]")
            conn.commit()
            return {"ok": True, "action": action, "affected_tables": targets}

        raw_tables = payload.get("tables", [])
        if not isinstance(raw_tables, list) or not raw_tables:
            return JSONResponse({"error": "tables must be a non-empty array"}, 400)

        targets = [str(t).strip() for t in raw_tables if str(t).strip()]
        unknown = [t for t in targets if t not in existing]
        if unknown:
            return JSONResponse({"error": f"Unknown tables: {', '.join(unknown)}"}, 400)

        if action == "truncate_tables":
            for t in targets:
                conn.execute(f"DELETE FROM [{t}]")
            conn.commit()
            return {"ok": True, "action": action, "affected_tables": targets}

        if action == "drop_tables":
            for t in targets:
                conn.execute(f"DROP TABLE [{t}]")
            conn.commit()
            return {"ok": True, "action": action, "affected_tables": targets}

        return JSONResponse({"error": "Unsupported action"}, 400)
    except sqlite3.Error as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, 500)
    finally:
        conn.close()


def ops_action(payload: dict = Body(default={})):
    """Unified ops action endpoint — handles all workflow admin actions."""
    _sync_app_state()
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid payload"}, 400)

    action = str(payload.get("action", "")).strip()

    # ── Scraping: DB table clears ──────────────────────────────────────────
    _SCRAPING_TABLE_ACTIONS = {
        "clear_scrape_runs":   ["runs"],
        "clear_jobs":          ["results"],
        "clear_rejected":      ["rejected"],
        "clear_seen_urls":     ["seen_urls"],
        "clear_scraping_all":  ["runs", "results", "rejected", "seen_urls"],
    }
    if action in _SCRAPING_TABLE_ACTIONS:
        tables = _SCRAPING_TABLE_ACTIONS[action]
        conn = get_db_write()
        try:
            existing = set(_db_user_tables(conn))
            affected = [t for t in tables if t in existing]
            for t in affected:
                conn.execute(f"DELETE FROM [{t}]")
            conn.commit()
            return {"ok": True, "action": action, "affected_tables": affected}
        except sqlite3.Error as e:
            conn.rollback()
            return JSONResponse({"error": str(e)}, 500)
        finally:
            conn.close()

    # ── Tailoring: filesystem purges ──────────────────────────────────────
    if action in (
        "clear_tailoring_runs",
        "clear_tailoring_failed",
        "clear_tailoring_partial",
        "clear_tailoring_succeeded",
        "clear_tailoring_logs",
    ):
        import shutil as _shutil
        output_dir = TAILORING_OUTPUT_DIR
        log_dir = TAILORING_RUNNER_LOG_DIR

        if action == "clear_tailoring_logs":
            removed = 0
            if log_dir.exists():
                for f in log_dir.iterdir():
                    if f.is_file():
                        f.unlink()
                        removed += 1
            return {"ok": True, "action": action, "removed": removed}

        if action == "clear_tailoring_failed":
            removed = []
            if output_dir.exists():
                for d in output_dir.iterdir():
                    if not d.is_dir() or d.name == "_runner_logs":
                        continue
                    status = _tailoring_run_status(d)
                    if status in ("failed", "error", "unknown", "no-trace"):
                        _shutil.rmtree(d)
                        removed.append(d.name)
            return {"ok": True, "action": action, "removed": removed}

        if action == "clear_tailoring_partial":
            removed = []
            if output_dir.exists():
                for d in output_dir.iterdir():
                    if not d.is_dir() or d.name == "_runner_logs":
                        continue
                    status = _tailoring_run_status(d)
                    if status == "partial":
                        _shutil.rmtree(d)
                        removed.append(d.name)
            return {"ok": True, "action": action, "removed": removed}

        if action == "clear_tailoring_succeeded":
            removed = []
            if output_dir.exists():
                for d in output_dir.iterdir():
                    if not d.is_dir() or d.name == "_runner_logs":
                        continue
                    status = _tailoring_run_status(d)
                    if status in ("complete", "passed", "success", "succeeded"):
                        _shutil.rmtree(d)
                        removed.append(d.name)
            return {"ok": True, "action": action, "removed": removed}

        if action == "clear_tailoring_runs":
            removed = []
            if output_dir.exists():
                for d in output_dir.iterdir():
                    if not d.is_dir() or d.name == "_runner_logs":
                        continue
                    _shutil.rmtree(d)
                    removed.append(d.name)
            return {"ok": True, "action": action, "removed": removed}

    # ── Nuclear ────────────────────────────────────────────────────────────
    if action == "nuke_all":
        import shutil as _shutil
        conn = get_db_write()
        try:
            existing = set(_db_user_tables(conn))
            for t in sorted(existing):
                conn.execute(f"DELETE FROM [{t}]")
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            return JSONResponse({"error": f"DB error: {e}"}, 500)
        finally:
            conn.close()
        removed_runs = []
        if TAILORING_OUTPUT_DIR.exists():
            for d in TAILORING_OUTPUT_DIR.iterdir():
                if d.is_dir() and d.name != "_runner_logs":
                    _shutil.rmtree(d)
                    removed_runs.append(d.name)
        return {"ok": True, "action": action, "tailoring_runs_removed": removed_runs}

    return JSONResponse({"error": f"Unknown action: {action!r}"}, 400)


def ops_status():
    """Return counts/sizes for all admin-relevant resources."""
    _sync_app_state()
    conn = get_db()
    try:
        tables = _db_user_tables(conn)
        table_counts = _db_table_counts(conn, tables)
    finally:
        conn.close()

    # Tailoring output stats
    output_dir = TAILORING_OUTPUT_DIR
    tailoring_runs = 0
    tailoring_failed = 0
    tailoring_partial = 0
    tailoring_succeeded = 0
    tailoring_unknown = 0
    tailoring_logs = 0
    if output_dir.exists():
        for d in output_dir.iterdir():
            if not d.is_dir() or d.name == "_runner_logs":
                continue
            tailoring_runs += 1
            s = _tailoring_run_status(d)
            if s in ("complete", "passed", "success", "succeeded"):
                tailoring_succeeded += 1
            elif s == "partial":
                tailoring_partial += 1
            elif s in ("failed", "error"):
                tailoring_failed += 1
            else:
                tailoring_unknown += 1
        log_dir = TAILORING_RUNNER_LOG_DIR
        if log_dir.exists():
            tailoring_logs = sum(1 for f in log_dir.iterdir() if f.is_file())

    return {
        "db_tables": table_counts,
        "tailoring": {
            "total_runs": tailoring_runs,
            "failed_runs": tailoring_failed,
            "partial_runs": tailoring_partial,
            "succeeded_runs": tailoring_succeeded,
            "unknown_runs": tailoring_unknown,
            "log_files": tailoring_logs,
        },
    }


def _tailoring_run_status(run_dir):
    """Infer tailoring run status from summary first, then status.json if present."""
    try:
        summary = _tailoring_summary(run_dir)
        s = str(summary.get("status") or "").strip().lower()
        if s:
            return s
    except Exception:
        pass

    status_file = run_dir / "status.json"
    if status_file.exists():
        try:
            import json as _json
            s = str(_json.loads(status_file.read_text()).get("status", "unknown")).strip().lower()
            return s or "unknown"
        except Exception:
            return "unknown"
    return "unknown"


# ---------------------------------------------------------------------------
# Routes — API: Schedules (launchd)
# ---------------------------------------------------------------------------

def list_schedules():
    _sync_app_state()
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



def get_schedule_log(label: str, lines: int = Query(100, ge=1, le=2000)):
    _sync_app_state()
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

def get_runtime_controls():
    _sync_app_state()
    return _load_runtime_controls()



def update_runtime_controls(payload: dict = Body(default={})):
    _sync_app_state()
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid payload"}, 400)
    updates: dict = {}

    if "scrape_enabled" in payload:
        updates["scrape_enabled"] = bool(payload["scrape_enabled"])
    if "llm_enabled" in payload:
        updates["llm_enabled"] = bool(payload["llm_enabled"])

    if "schedule_interval_minutes" in payload:
        raw_interval = payload["schedule_interval_minutes"]
        if raw_interval is None or raw_interval == "":
            updates["schedule_interval_minutes"] = None
        else:
            try:
                interval = int(raw_interval)
            except (TypeError, ValueError):
                return JSONResponse({"error": "schedule_interval_minutes must be an integer"}, 400)
            if interval < 1:
                return JSONResponse({"error": "schedule_interval_minutes must be >= 1"}, 400)
            updates["schedule_interval_minutes"] = interval

    # Shutoff window: if provided, compute absolute stop time from now.
    if "schedule_stop_after_hours" in payload:
        raw_stop_hours = payload["schedule_stop_after_hours"]
        started_at = datetime.now(timezone.utc)
        updates["schedule_started_at"] = started_at.isoformat()
        if raw_stop_hours is None or raw_stop_hours == "":
            updates["schedule_stop_at"] = None
        else:
            try:
                stop_hours = int(raw_stop_hours)
            except (TypeError, ValueError):
                return JSONResponse({"error": "schedule_stop_after_hours must be an integer"}, 400)
            if stop_hours < 1:
                return JSONResponse({"error": "schedule_stop_after_hours must be >= 1"}, 400)
            updates["schedule_stop_at"] = (started_at + timedelta(hours=stop_hours)).isoformat()

    controls = _save_runtime_controls(updates)
    return {"ok": True, "controls": controls}


# ---------------------------------------------------------------------------
# Routes — API: LLM status
# ---------------------------------------------------------------------------
LLM_URL = os.environ.get("LLM_URL", "http://localhost:1234")



def catch_all(full_path: str):
    _sync_app_state()
    if full_path.startswith("api/"):
        return JSONResponse({"error": "API Route Not Found"}, status_code=404)
    return FileResponse(DIST_DIR / "index.html")


from routers import ops as ops_routes
from routers import scraping as scraping_routes
from routers import tailoring as tailoring_routes
from services import ops as ops_handlers
from services import scraping as scraping_handlers
from services import tailoring as tailoring_handlers
