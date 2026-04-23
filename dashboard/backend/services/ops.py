"""Ops route implementations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Request

# Reuse shared backend state/helpers from app module.
import app as _app
globals().update({k: v for k, v in _app.__dict__.items() if not k.startswith("__")})

# Scraper config handlers (standalone module, no circular deps)
from services.scraper_config import scraper_config_get, scraper_config_save, scraper_pipeline_stats

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

    def _clear_inventory_preserving_applied(
        conn,
        *,
        clear_runs: bool,
        clear_rejected: bool,
        clear_seen_urls: bool,
    ) -> dict:
        existing = set(_db_user_tables(conn))
        protected_job_ids = _fetch_protected_job_ids(conn) if "results" in existing else []
        placeholders = ",".join("?" for _ in protected_job_ids)

        removed_results = 0
        removed_queue_items = 0
        removed_state_logs = 0
        cleared_tables: list[str] = []

        if "tailoring_queue_items" in existing:
            if protected_job_ids:
                cur = conn.execute(
                    f"DELETE FROM tailoring_queue_items WHERE job_id NOT IN ({placeholders})",
                    tuple(protected_job_ids),
                )
            else:
                cur = conn.execute("DELETE FROM tailoring_queue_items")
            removed_queue_items = max(int(cur.rowcount or 0), 0)
            cleared_tables.append("tailoring_queue_items")

        if "job_state_log" in existing:
            if protected_job_ids:
                cur = conn.execute(
                    f"DELETE FROM job_state_log WHERE job_id IS NULL OR job_id NOT IN ({placeholders})",
                    tuple(protected_job_ids),
                )
            else:
                cur = conn.execute("DELETE FROM job_state_log")
            removed_state_logs = max(int(cur.rowcount or 0), 0)
            cleared_tables.append("job_state_log")

        if "jobs" in existing:
            if protected_job_ids:
                cur = conn.execute(
                    f"DELETE FROM jobs WHERE id NOT IN ({placeholders})",
                    tuple(protected_job_ids),
                )
            else:
                cur = conn.execute("DELETE FROM jobs")
            removed_results = max(int(cur.rowcount or 0), 0)
            cleared_tables.append("jobs")

        if clear_rejected and "rejected" in existing:
            conn.execute("DELETE FROM rejected")
            cleared_tables.append("rejected")
        if clear_runs and "runs" in existing:
            conn.execute("DELETE FROM runs")
            cleared_tables.append("runs")
        removed_seen_urls = 0
        preserved_seen_urls = 0
        if clear_seen_urls and "seen_urls" in existing:
            preserved_seen_urls = int(
                conn.execute("SELECT COUNT(*) FROM seen_urls WHERE permanently_rejected = 1").fetchone()[0]
            )
            cur = conn.execute("DELETE FROM seen_urls WHERE permanently_rejected = 0")
            removed_seen_urls = max(int(cur.rowcount or 0), 0)
            cleared_tables.append("seen_urls")

        return {
            "protected_job_ids": protected_job_ids,
            "removed_results": removed_results,
            "removed_queue_items": removed_queue_items,
            "removed_state_logs": removed_state_logs,
            "removed_seen_urls": removed_seen_urls,
            "preserved_seen_urls": preserved_seen_urls,
            "affected_tables": cleared_tables,
        }

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
            if action in {"clear_jobs", "clear_scraping_all"}:
                summary = _clear_inventory_preserving_applied(
                    conn,
                    clear_runs=(action == "clear_scraping_all"),
                    clear_rejected=(action == "clear_scraping_all"),
                    clear_seen_urls=True,
                )
                conn.commit()
                return {"ok": True, "action": action, **summary}

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
        "clear_tailoring_docs",
        "clear_tailoring_failed",
        "clear_tailoring_partial",
        "clear_tailoring_succeeded",
        "clear_tailoring_logs",
    ):
        import shutil as _shutil
        output_dir = TAILORING_OUTPUT_DIR
        log_dir = TAILORING_RUNNER_LOG_DIR

        def _purge_tailoring_ingest_jobs() -> int:
            conn = get_db_write()
            try:
                existing = set(_db_user_tables(conn))
                if "jobs" not in existing:
                    return 0
                rows = conn.execute(
                    """
                    SELECT id FROM jobs
                    WHERE COALESCE(query, '') IN ('manual-ingest', 'mobile-ingest')
                       OR COALESCE(run_id, '') IN ('manual-ingest', 'mobile-ingest')
                       OR url LIKE 'manual://ingest/%'
                       OR url LIKE 'mobile://ingest/%'
                    """
                ).fetchall()
                job_ids = [int(row["id"]) for row in rows if row["id"] is not None]
                if not job_ids:
                    return 0
                placeholders = ",".join("?" for _ in job_ids)
                if "tailoring_queue_items" in existing:
                    conn.execute(
                        f"DELETE FROM tailoring_queue_items WHERE job_id IN ({placeholders})",
                        tuple(job_ids),
                    )
                if "job_state_log" in existing:
                    conn.execute(
                        f"DELETE FROM job_state_log WHERE job_id IN ({placeholders})",
                        tuple(job_ids),
                    )
                cur = conn.execute(
                    """
                    DELETE FROM jobs
                    WHERE COALESCE(query, '') IN ('manual-ingest', 'mobile-ingest')
                       OR COALESCE(run_id, '') IN ('manual-ingest', 'mobile-ingest')
                       OR url LIKE 'manual://ingest/%'
                       OR url LIKE 'mobile://ingest/%'
                    """
                )
                conn.commit()
                return max(int(cur.rowcount or 0), 0)
            except sqlite3.Error:
                conn.rollback()
                raise
            finally:
                conn.close()

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

        if action == "clear_tailoring_docs":
            # Delete generated documents (pdf, tex, strategies) but keep
            # meta.json, analysis.json, and llm_trace.jsonl so run history
            # and traces are preserved.
            _KEEP = {"meta.json", "analysis.json", "llm_trace.jsonl"}
            cleaned = []
            if output_dir.exists():
                for d in output_dir.iterdir():
                    if not d.is_dir() or d.name == "_runner_logs":
                        continue
                    removed_files = []
                    for f in list(d.iterdir()):
                        if f.name in _KEEP:
                            continue
                        if f.is_file():
                            f.unlink()
                            removed_files.append(f.name)
                        elif f.is_dir():
                            _shutil.rmtree(f)
                            removed_files.append(f.name + "/")
                    if removed_files:
                        cleaned.append({"slug": d.name, "files": len(removed_files)})
            return {"ok": True, "action": action, "cleaned": cleaned}

        if action == "clear_tailoring_runs":
            try:
                removed_jobs = _purge_tailoring_ingest_jobs()
            except sqlite3.Error as e:
                return JSONResponse({"error": str(e)}, 500)
            removed = []
            if output_dir.exists():
                for d in output_dir.iterdir():
                    if not d.is_dir() or d.name == "_runner_logs":
                        continue
                    _shutil.rmtree(d)
                    removed.append(d.name)
            return {"ok": True, "action": action, "removed": removed, "removed_jobs": removed_jobs}

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
    if "llm_provider" in payload:
        from providers import PROVIDERS
        provider = str(payload["llm_provider"] or "").strip().lower()
        if provider not in PROVIDERS:
            return JSONResponse({"error": f"Unknown llm_provider: {provider}"}, 400)
        updates["llm_provider"] = provider
    if "llm_base_url" in payload:
        base_url = str(payload["llm_base_url"] or "").strip()
        if not base_url:
            return JSONResponse({"error": "llm_base_url is required"}, 400)
        updates["llm_base_url"] = _normalize_llm_base_url(base_url)
    if "llm_model" in payload:
        updates["llm_model"] = str(payload["llm_model"] or "default").strip() or "default"

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

    # Automatic scheduling removed — runs are UI-initiated only.

    return {"ok": True, "controls": controls}


# ---------------------------------------------------------------------------
# Routes — API: LLM status
# ---------------------------------------------------------------------------
LLM_URL = os.environ.get("LLM_URL", "http://localhost:11434")



def catch_all(full_path: str):
    _sync_app_state()
    if full_path.startswith("api/"):
        return JSONResponse({"error": "API Route Not Found"}, status_code=404)
    # Serve static assets directly (route takes priority over StaticFiles mount)
    if full_path.startswith("assets/"):
        asset_path = DIST_DIR / full_path
        if asset_path.exists() and asset_path.is_file():
            return FileResponse(asset_path)
        if full_path.endswith(".js"):
            from starlette.responses import Response
            reload_stub = (
                "if (!window.sessionStorage.getItem('dashboard.asset-reload-once')) {"
                "window.sessionStorage.setItem('dashboard.asset-reload-once','1');"
                "window.location.reload();"
                "} "
                "export default {};"
            )
            return Response(
                content=reload_stub,
                media_type="application/javascript",
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
        return JSONResponse({"error": "Asset not found"}, status_code=404)
    from starlette.responses import Response
    content = (DIST_DIR / "index.html").read_bytes()
    return Response(content=content, media_type="text/html",
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


def tailoring_metrics_get():
    """Return all tailoring metrics rows with computed baselines."""
    _sync_app_state()
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT m.*, j.title as job_title, j.company as job_company
            FROM tailoring_metrics m
            LEFT JOIN jobs j ON m.job_id = j.id
            ORDER BY m.timestamp DESC
            """
        ).fetchall()
        metrics = [dict(r) for r in rows]

        # Compute baselines (averages)
        baselines = {}
        numeric_fields = [
            "total_wall_time_s", "queue_wait_s",
            "analysis_time_s", "analysis_llm_time_s",
            "resume_time_s", "resume_llm_time_s",
            "cover_time_s", "cover_llm_time_s",
            "total_llm_time_s",
        ]
        int_fields = [
            "analysis_llm_calls", "resume_llm_calls", "resume_attempts",
            "cover_llm_calls", "cover_attempts", "total_llm_calls",
        ]
        for field in numeric_fields + int_fields:
            values = [r[field] for r in metrics if r.get(field) is not None]
            if values:
                avg = sum(values) / len(values)
                baselines[field] = round(avg, 2) if field in numeric_fields else round(avg, 1)
        baselines["run_count"] = len(metrics)

        # Compute Queue Stats (Failure rate)
        try:
            queue_rows = conn.execute("SELECT status, count(*) as count FROM tailoring_queue_items GROUP BY status").fetchall()
            queue_stats = {r["status"]: r["count"] for r in queue_rows}
        except Exception:
            queue_stats = {}

        # Compute Model Usage Stats
        model_stats = {}
        for m in metrics:
            mod = m.get("model") or "unknown"
            model_stats[mod] = model_stats.get(mod, 0) + 1

        return {
            "metrics": metrics,
            "baselines": baselines,
            "queue_stats": queue_stats,
            "model_stats": model_stats,
        }
    finally:
        conn.close()


# ── Persona inventory ────────────────────────────────────────────────

import json as _json
import re as _re
from pathlib import Path as _Path


_FRONTMATTER_RE = _re.compile(r"\A---\s*\n(.*?\n)---\s*\n(.*)\Z", _re.DOTALL)
_LEADING_COMMENT_RE = _re.compile(r"\A(\s*<!--.*?-->\s*)+", _re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    text = _LEADING_COMMENT_RE.sub("", text)
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text.strip()
    raw = m.group(1)
    body = m.group(2).strip()
    meta: dict = {}
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        bracket = _re.match(r"^\[(.*)\]$", v)
        if bracket:
            meta[k] = [x.strip().strip("'\"") for x in bracket.group(1).split(",") if x.strip()]
        else:
            meta[k] = v
    return meta, body


def persona_inventory_get():
    """Return persona content + vignette metadata + skills inventory for the Ops UI."""
    _sync_app_state()
    tailoring_root: _Path = TAILORING_ROOT  # from app globals
    persona_dir = tailoring_root / "persona"
    skills_path = tailoring_root / "skills.json"

    # ── Persona section files ──────────────────────────────────────
    sections: dict[str, dict] = {}
    for name in ("identity", "contributions", "voice", "evidence", "interests", "motivation"):
        p = persona_dir / f"{name}.md"
        if not p.exists():
            sections[name] = {"body": "", "chars": 0, "exists": False}
            continue
        meta, body = _parse_frontmatter(p.read_text())
        sections[name] = {
            "body": body,
            "chars": len(body),
            "tags": meta.get("tags", []),
            "exists": True,
            "path": str(p.relative_to(tailoring_root)),
        }

    # ── Vignettes ──────────────────────────────────────────────────
    vignettes: list[dict] = []
    vig_dir = persona_dir / "vignettes"
    if vig_dir.is_dir():
        for f in sorted(vig_dir.glob("*.md")):
            meta, body = _parse_frontmatter(f.read_text())
            vignettes.append({
                "name": f.stem,
                "path": str(f.relative_to(tailoring_root)),
                "body": body,
                "chars": len(body),
                "tags": meta.get("tags", []) or [],
                "company_types": meta.get("company_types", []) or [],
                "skill_categories": meta.get("skill_categories", []) or [],
                "keywords": meta.get("keywords", []) or [],
            })

    # ── Stats / coverage ───────────────────────────────────────────
    tag_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    company_counts: dict[str, int] = {}
    keyword_counts: dict[str, int] = {}
    total_chars = 0
    for v in vignettes:
        total_chars += v["chars"]
        for t in v["tags"]:
            tag_counts[t] = tag_counts.get(t, 0) + 1
        for c in v["skill_categories"]:
            category_counts[c] = category_counts.get(c, 0) + 1
        for ct in v["company_types"]:
            company_counts[ct] = company_counts.get(ct, 0) + 1
        for kw in v["keywords"]:
            keyword_counts[kw] = keyword_counts.get(kw, 0) + 1

    # ── Skills inventory ───────────────────────────────────────────
    skills_data: dict = {}
    if skills_path.exists():
        try:
            skills_data = _json.loads(skills_path.read_text())
        except Exception:
            skills_data = {}

    candidate_profile = skills_data.get("candidate_profile", {})
    inventory = skills_data.get("skills_inventory", {})
    core_skills = inventory.get("core_skills", []) or []

    # Category → vignette mapping (for cross-linking in UI)
    category_to_vignettes: dict[str, list[str]] = {}
    for v in vignettes:
        for c in v["skill_categories"]:
            category_to_vignettes.setdefault(c, []).append(v["name"])

    # Flat skill buckets
    buckets: dict[str, list[str]] = {}
    for key in (
        "programming_languages",
        "databases",
        "frameworks_and_infrastructure",
        "security_tooling",
        "devops_and_cloud",
        "ai_ml_research",
    ):
        val = inventory.get(key)
        if isinstance(val, list):
            buckets[key] = val

    stages = [
        {"stage": "strategy", "doc_type": "cover", "budget_chars": 1500, "diverse": True},
        {"stage": "strategy", "doc_type": "resume", "budget_chars": 1500, "diverse": False},
        {"stage": "draft", "doc_type": "cover", "budget_chars": 1500, "diverse": True},
        {"stage": "draft", "doc_type": "resume", "budget_chars": 1500, "diverse": False},
    ]

    return {
        "candidate_profile": candidate_profile,
        "sections": sections,
        "vignettes": vignettes,
        "core_skills": core_skills,
        "skill_buckets": buckets,
        "category_to_vignettes": category_to_vignettes,
        "stages": stages,
        "stats": {
            "vignette_count": len(vignettes),
            "total_chars": total_chars,
            "avg_chars": (total_chars // len(vignettes)) if vignettes else 0,
            "unique_tags": len(tag_counts),
            "unique_categories": len(category_counts),
            "unique_company_types": len(company_counts),
            "tag_counts": tag_counts,
            "category_counts": category_counts,
            "company_counts": company_counts,
            "keyword_counts": keyword_counts,
            "core_skill_count": sum(len(c.get("skills", []) or []) for c in core_skills),
            "core_category_count": len(core_skills),
        },
    }


from routers import ops as ops_routes
from routers import scraping as scraping_routes
from routers import tailoring as tailoring_routes
from services import ops as ops_handlers
from services import scraping as scraping_handlers
from services import tailoring as tailoring_handlers
