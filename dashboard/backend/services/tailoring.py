"""Tailoring route implementations."""

from __future__ import annotations

import io
import sys
import zipfile

from fastapi.responses import StreamingResponse

# Reuse shared backend state/helpers from app module.
import app as _app
globals().update({k: v for k, v in _app.__dict__.items() if not k.startswith("__")})

_scraper_root = str(SCRAPER_ROOT)
if _scraper_root not in sys.path:
    sys.path.insert(0, _scraper_root)
from job_scraper.config import load_config as _load_scraper_config
from job_scraper.salary_policy import evaluate_salary_policy as _evaluate_salary_policy

_tailoring_root = str(TAILORING_ROOT)
if _tailoring_root not in sys.path:
    sys.path.insert(0, _tailoring_root)

_chat_expect_json = None  # lazy-loaded to avoid circular import

def _sync_app_state() -> None:
    globals().update({k: v for k, v in _app.__dict__.items() if not k.startswith("__")})


def _salary_policy_for_job(*, salary_text: str = "", salary_k: object = None):
    cfg = _load_scraper_config()
    return _evaluate_salary_policy(
        min_salary_k=cfg.hard_filters.min_salary_k,
        target_salary_k=cfg.hard_filters.target_salary_k,
        salary_text=salary_text,
        salary_k=salary_k,
    )


def _shared_chat_expect_json(
    system_prompt: str,
    user_prompt: str,
    *,
    llm_runtime: dict,
    model_id: str,
    max_tokens: int = 2048,
    temperature: float = 0.2,
    trace: dict | None = None,
) -> dict:
    """Use tailoring's shared LLM helper while keeping dashboard runtime controls authoritative."""
    global _chat_expect_json
    if _chat_expect_json is None:
        from tailor.ollama import chat_expect_json
        _chat_expect_json = chat_expect_json
    return _chat_expect_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        model=model_id,
        runtime={
            "provider": llm_runtime.get("provider"),
            "chat_url": llm_runtime.get("chat_url"),
            "api_key": llm_runtime.get("api_key", ""),
            "timeout": max(90, int(max_tokens / 32)),
        },
        trace=trace,
    )


def _ready_job_for_tailoring(job_id: int) -> tuple[dict | None, JSONResponse | None]:
    job = _get_job_context(job_id)
    if not job:
        return None, JSONResponse({"ok": False, "error": f"Job {job_id} not found"}, 404)
    if not _job_is_qa_ready(job.get("decision")):
        return None, JSONResponse(
            {
                "ok": False,
                "error": f"Job {job_id} is not ready for tailoring",
                "decision": job.get("decision"),
            },
            409,
        )
    jd = (job.get("jd_text") or job.get("approved_jd_text") or job.get("snippet") or "").strip()
    if len(jd) < 10:
        return None, JSONResponse(
            {"ok": False, "error": f"Job {job_id} has no JD text — cannot tailor without a job description"},
            422,
        )
    return {
        "id": int(job["id"]),
        "title": job.get("title"),
        "created_at": job.get("created_at"),
        "url": job.get("url"),
    }, None


def tailoring_runner_status(lines: int = Query(80, ge=0, le=500)):
    _sync_app_state()
    return _tailoring_runner_snapshot(log_lines=lines)


def tailoring_runner_stop(payload: dict | None = Body(None)):
    _sync_app_state()
    payload = payload or {}
    clear_queue = bool(payload.get("clear_queue", False))
    wait_seconds = payload.get("wait_seconds", 5)
    try:
        wait_seconds = int(wait_seconds)
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "wait_seconds must be an integer"}, 400)
    if wait_seconds < 0 or wait_seconds > 30:
        return JSONResponse({"ok": False, "error": "wait_seconds must be between 0 and 30"}, 400)

    proc = _app._TAILORING_RUNNER.get("proc")
    had_running = proc is not None and proc.poll() is None
    cleared = 0
    if clear_queue:
        cleared = _cancel_tailoring_queue_items(statuses=("queued",), reason="Cleared from dashboard.")

    if not had_running:
        return {
            "ok": True,
            "stopped": False,
            "message": "No active tailoring run",
            "cleared_queue": cleared,
            "runner": _tailoring_runner_snapshot(),
        }

    try:
        _app._TAILORING_RUNNER["stop_reason"] = "Tailoring run stopped from dashboard."
        proc.terminate()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Failed to signal terminate: {e}"}, 500)

    exited = False
    if wait_seconds > 0:
        try:
            proc.wait(timeout=wait_seconds)
            exited = True
        except Exception:
            exited = False

    return {
        "ok": True,
        "stopped": True,
        "graceful_exit_observed": exited,
        "cleared_queue": cleared,
        "runner": _tailoring_runner_snapshot(),
    }


def tailoring_ready_jobs(
    limit: int = Query(200, ge=1, le=2000),
    max_age_hours: int | None = Query(None, ge=1, le=24 * 30),
    board: str | None = Query(None),
    source: str | None = Query(None),
    seniority: str | None = Query(None),
    location: str | None = Query(None),
    search: str | None = Query(None),
    bucket: str | None = Query(None),
):
    _sync_app_state()
    normalized_bucket = None
    if bucket:
        raw_bucket = bucket.strip().lower()
        normalized_bucket = None if raw_bucket == "all" else _normalize_ready_bucket(raw_bucket)
    items = _recent_jobs(
        limit=limit,
        max_age_hours=max_age_hours,
        board=board,
        source=source,
        seniority=seniority,
        location=location,
        search=search,
        bucket=bucket,
    )
    conn = get_db()
    try:
        clauses, params, _available = _ready_job_query_parts(
            conn,
            max_age_hours=max_age_hours,
            board=board,
            source=source,
            seniority=seniority,
            location=location,
            search=search,
        )
        if normalized_bucket == _DEFAULT_READY_BUCKET:
            clauses.append("NOT EXISTS (SELECT 1 FROM tailoring_ready_bucket_state b WHERE b.job_id = results.id)")
        elif normalized_bucket in _READY_BUCKET_VALUES and normalized_bucket != _DEFAULT_READY_BUCKET:
            clauses.append("EXISTS (SELECT 1 FROM tailoring_ready_bucket_state b WHERE b.job_id = results.id AND b.bucket = ?)")
            params.append(normalized_bucket)
        where = "WHERE " + " AND ".join(clauses)
        total = conn.execute(f"SELECT COUNT(*) FROM results {where}", tuple(params)).fetchone()[0]
        count_rows = conn.execute(
            f"""
            SELECT COALESCE(b.bucket, '{_DEFAULT_READY_BUCKET}') AS bucket, COUNT(*) AS count
            FROM results
            LEFT JOIN tailoring_ready_bucket_state b ON b.job_id = results.id
            {where}
            GROUP BY COALESCE(b.bucket, '{_DEFAULT_READY_BUCKET}')
            """,
            tuple(params),
        ).fetchall()
        bucket_counts = {bucket_name: 0 for bucket_name in _READY_BUCKET_VALUES}
        for row in count_rows:
            bucket_counts[_normalize_ready_bucket(row["bucket"])] = int(row["count"])
    finally:
        conn.close()
    return {"items": items, "count": len(items), "total": total, "bucket_counts": bucket_counts}


def tailoring_recent_jobs(
    limit: int = Query(200, ge=1, le=2000),
    max_age_hours: int | None = Query(None, ge=1, le=24 * 30),
):
    _sync_app_state()
    return tailoring_ready_jobs(limit=limit, max_age_hours=max_age_hours)


def tailoring_rejected_jobs(
    limit: int = Query(200, ge=1, le=500),
    max_age_hours: int | None = Query(None, ge=1, le=24 * 30),
):
    _sync_app_state()
    conn = get_db()
    try:
        clauses = [
            "decision = 'qa_rejected'",
            "NOT EXISTS (SELECT 1 FROM applied_applications aa WHERE aa.job_id = results.id)",
        ]
        params: list = []
        if max_age_hours is not None:
            clauses.append("julianday(created_at) >= julianday('now', ?)")
            params.append(f"-{int(max_age_hours)} hours")
        where = "WHERE " + " AND ".join(clauses)
        total = conn.execute(f"SELECT COUNT(*) FROM results {where}", tuple(params)).fetchone()[0]
        query_params = [*params, max(1, min(int(limit), 500))]
        rows = conn.execute(
            f"""SELECT id, title, created_at, url, snippet, board, seniority
                FROM results {where}
                ORDER BY id DESC
                LIMIT ?""",
            tuple(query_params),
        ).fetchall()
        items = [dict(r) for r in rows]
        return {"items": items, "count": len(items), "total": total}
    finally:
        conn.close()



def tailoring_job_detail(job_id: int):
    _sync_app_state()
    job = _get_job_context(job_id)
    if not job:
        return JSONResponse({"error": f"Job {job_id} not found"}, 404)
    return job


def tailoring_job_briefing(job_id: int):
    """Return job detail + analysis/strategy from the latest run (if any)."""
    _sync_app_state()
    job = _get_job_context(job_id)
    if not job:
        return JSONResponse({"error": f"Job {job_id} not found"}, 404)

    briefing: dict = {"job": job, "analysis": None, "resume_strategy": None, "cover_strategy": None, "run_slug": None}

    if not TAILORING_OUTPUT_DIR.exists():
        return briefing

    # Find latest run dir for this job
    best_dir = None
    best_ts = 0.0
    for d in TAILORING_OUTPUT_DIR.iterdir():
        if not d.is_dir():
            continue
        meta_path = d / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if int(meta.get("job_id", -1)) != job_id:
                continue
            ts = d.stat().st_mtime
            if ts > best_ts:
                best_ts = ts
                best_dir = d
        except Exception:
            continue

    if not best_dir:
        return briefing

    briefing["run_slug"] = best_dir.name
    for name, key in [("analysis.json", "analysis"), ("resume_strategy.json", "resume_strategy"), ("cover_strategy.json", "cover_strategy")]:
        path = best_dir / name
        if path.exists():
            try:
                briefing[key] = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass

    return briefing


def tailoring_run_job(payload: dict = Body(...)):
    _sync_app_state()
    job_id = payload.get("job_id")
    skip_analysis = bool(payload.get("skip_analysis", False))
    if not isinstance(job_id, int):
        return JSONResponse({"ok": False, "error": "job_id must be an integer"}, 400)

    if _app._TAILORING_RUNNER.get("proc") is not None and _app._TAILORING_RUNNER["proc"].poll() is None:
        return JSONResponse({"ok": False, "error": "A tailoring run is already in progress", "runner": _tailoring_runner_snapshot()}, 409)

    job, error = _ready_job_for_tailoring(job_id)
    if error:
        return error

    added, duplicates = _enqueue_tailoring_queue_items([{"job": job, "skip_analysis": skip_analysis}])
    if duplicates:
        return JSONResponse(
            {
                "ok": False,
                "error": f"Job {job_id} is already queued or running",
                "existing": duplicates[0],
                "runner": _tailoring_runner_snapshot(),
            },
            409,
        )
    if added and _app._TAILORING_RUNNER.get("proc") is None:
        _app._process_tailoring_queue()
    return {"ok": True, "queued": len(added), "item": added[0] if added else None, "runner": _tailoring_runner_snapshot()}



def tailoring_run_latest(payload: dict | None = Body(None)):
    _sync_app_state()
    payload = payload or {}
    max_age_hours = payload.get("max_age_hours")
    skip_analysis = bool(payload.get("skip_analysis", False))

    if max_age_hours in ("", None):
        max_age_hours = None
    else:
        try:
            max_age_hours = int(max_age_hours)
            if max_age_hours <= 0:
                return JSONResponse({"ok": False, "error": "max_age_hours must be > 0"}, 400)
        except (TypeError, ValueError):
            return JSONResponse({"ok": False, "error": "max_age_hours must be an integer"}, 400)

    if _app._TAILORING_RUNNER.get("proc") is not None and _app._TAILORING_RUNNER["proc"].poll() is None:
        return JSONResponse({"ok": False, "error": "A tailoring run is already in progress", "runner": _tailoring_runner_snapshot()}, 409)

    job = _latest_job(max_age_hours=max_age_hours)
    if not job:
        msg = "No ready jobs found"
        if max_age_hours is not None:
            msg = f"No ready jobs found in last {max_age_hours} hours"
        return JSONResponse({"ok": False, "error": msg}, 404)

    added, duplicates = _enqueue_tailoring_queue_items([{"job": job, "skip_analysis": skip_analysis}])
    if duplicates:
        return JSONResponse(
            {
                "ok": False,
                "error": f"Job {job['id']} is already queued or running",
                "existing": duplicates[0],
                "runner": _tailoring_runner_snapshot(),
            },
            409,
        )
    if added and _app._TAILORING_RUNNER.get("proc") is None:
        _app._process_tailoring_queue()
    return {"ok": True, "queued": len(added), "item": added[0] if added else None, "runner": _tailoring_runner_snapshot()}



def tailoring_queue_add(payload: dict = Body(...)):
    _sync_app_state()
    jobs = payload.get("jobs", [])
    if not jobs or not isinstance(jobs, list):
        return JSONResponse({"ok": False, "error": "jobs must be a non-empty array"}, 400)

    queue_items = []
    for item in jobs:
        job_id = item.get("job_id")
        if not isinstance(job_id, int):
            return JSONResponse({"ok": False, "error": f"Invalid job_id: {job_id}"}, 400)
        job, error = _ready_job_for_tailoring(job_id)
        if error:
            return error
        queue_items.append({"job": job, "skip_analysis": bool(item.get("skip_analysis", False))})

    added, duplicates = _enqueue_tailoring_queue_items(queue_items)
    if added:
        _set_ready_bucket_for_job_ids([int(item["job_id"]) for item in added], _DEFAULT_READY_BUCKET)
    if added and _app._TAILORING_RUNNER.get("proc") is None:
        _app._process_tailoring_queue()

    return {
        "ok": True,
        "queued": len(added),
        "duplicates": duplicates,
        "items": added,
        "runner": _tailoring_runner_snapshot(),
    }


def tailoring_ready_bucket_update(payload: dict = Body(...)):
    _sync_app_state()
    job_ids = payload.get("job_ids", [])
    bucket = _normalize_ready_bucket(payload.get("bucket"))
    if not isinstance(job_ids, list) or not job_ids:
        return JSONResponse({"ok": False, "error": "job_ids must be a non-empty array"}, 400)

    valid_job_ids: list[int] = []
    for raw_job_id in job_ids:
        if not isinstance(raw_job_id, int):
            return JSONResponse({"ok": False, "error": f"Invalid job_id: {raw_job_id}"}, 400)
        job = _get_job_context(raw_job_id)
        if not job or not _job_is_qa_ready(job.get("decision")):
            return JSONResponse(
                {"ok": False, "error": f"Job {raw_job_id} is not ready for tailoring"},
                409,
            )
        valid_job_ids.append(raw_job_id)

    updated = _set_ready_bucket_for_job_ids(valid_job_ids, bucket)
    return {"ok": True, "updated": updated, "bucket": bucket, "job_ids": valid_job_ids}


def tailoring_queue_bucket(payload: dict = Body(...)):
    _sync_app_state()
    bucket = _normalize_ready_bucket(payload.get("bucket"))
    if bucket == _DEFAULT_READY_BUCKET:
        return JSONResponse({"ok": False, "error": "bucket must be one of: next, later"}, 400)
    limit = payload.get("limit", 200)
    try:
        limit = max(1, min(int(limit), 2000))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "limit must be an integer"}, 400)
    skip_analysis = bool(payload.get("skip_analysis", False))

    ready_items = _recent_jobs(limit=limit, bucket=bucket)
    queue_items = []
    for item in ready_items:
        queue_state = ((item.get("queue_item") or {}).get("status") or "").strip().lower()
        if queue_state in {"queued", "running"}:
            continue
        queue_items.append(
            {
                "job": {
                    "id": int(item["id"]),
                    "title": item.get("title"),
                    "created_at": item.get("created_at"),
                    "url": item.get("url"),
                },
                "skip_analysis": skip_analysis,
            }
        )

    if not queue_items:
        return {"ok": True, "queued": 0, "duplicates": [], "items": [], "bucket": bucket, "runner": _tailoring_runner_snapshot()}

    added, duplicates = _enqueue_tailoring_queue_items(queue_items)
    if added:
        _set_ready_bucket_for_job_ids([int(item["job_id"]) for item in added], _DEFAULT_READY_BUCKET)
    if added and _app._TAILORING_RUNNER.get("proc") is None:
        _app._process_tailoring_queue()
    return {
        "ok": True,
        "queued": len(added),
        "duplicates": duplicates,
        "items": added,
        "bucket": bucket,
        "runner": _tailoring_runner_snapshot(),
    }


def tailoring_queue_get():
    _sync_app_state()
    conn = get_db_write()
    try:
        if _reconcile_stale_tailoring_queue(conn):
            conn.commit()
        items = _fetch_tailoring_queue_items(conn, statuses=_QUEUE_OPEN_STATUSES)
    finally:
        conn.close()
    active_item = next((item for item in items if item.get("status") == "running"), None)
    queue = [item for item in items if item.get("status") == "queued"]
    return {"items": items, "active_item": active_item, "queue": queue, "count": len(items)}


def tailoring_queue_clear():
    _sync_app_state()
    count = _cancel_tailoring_queue_items(statuses=("queued",), reason="Cleared from dashboard.")
    return {"ok": True, "cleared": count}


def tailoring_queue_remove(index: int):
    _sync_app_state()
    conn = get_db_write()
    try:
        if _reconcile_stale_tailoring_queue(conn):
            conn.commit()
        queued = _fetch_tailoring_queue_items(conn, statuses=("queued",))
    finally:
        conn.close()
    if index < 0 or index >= len(queued):
        return JSONResponse({"ok": False, "error": "Index out of range"}, 400)
    removed = queued[index]
    _cancel_tailoring_queue_items(item_ids=[int(removed["id"])], statuses=("queued",), reason="Removed from queue.")
    return {"ok": True, "removed": removed}


def tailoring_runs():
    _sync_app_state()
    if not TAILORING_OUTPUT_DIR.exists():
        return {"runs": []}

    runs = []
    for d in sorted(TAILORING_OUTPUT_DIR.iterdir()):
        if not d.is_dir():
            continue
        runs.append(_tailoring_summary(d))

    runs.sort(key=lambda r: _parse_ts(r.get("updated_at")) or 0, reverse=True)
    return {"runs": runs}



def tailoring_run_detail(slug: str):
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    if d is None:
        return JSONResponse({"error": "Run not found"}, 404)
    return _tailoring_summary(d)



def tailoring_trace(
    slug: str,
    doc_type: str | None = None,
    phase: str | None = None,
    attempt: int | None = None,
):
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    if d is None:
        return JSONResponse({"error": "Run not found"}, 404)

    trace_path = d / TAILORING_TRACE_FILE
    events = _read_trace_events(trace_path)
    if doc_type:
        events = [e for e in events if e.get("doc_type") == doc_type]
    if phase:
        events = [e for e in events if e.get("phase") == phase]
    if attempt is not None:
        events = [e for e in events if int(e.get("attempt", -1)) == attempt]
    events.sort(key=lambda e: _parse_ts(e.get("timestamp") or e.get("started_at")))
    return {"slug": slug, "events": events, "count": len(events)}



def tailoring_artifact(slug: str, name: str):
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    if d is None:
        return JSONResponse({"error": "Run not found"}, 404)
    if name not in TAILORING_ALLOWED_ARTIFACTS:
        return JSONResponse({"error": "Artifact not allowed"}, 400)
    artifact = d / name
    if not artifact.exists():
        return JSONResponse({"error": "Artifact not found"}, 404)
    return FileResponse(
        artifact,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ---------------------------------------------------------------------------
# Routes — API: Completed application packages (content review/edit)
# ---------------------------------------------------------------------------

def _package_job_context(summary: dict) -> dict:
    meta = summary.get("meta", {}) or {}
    job_context = None
    if meta.get("job_id"):
        try:
            job_context = _get_job_context(meta.get("job_id"))
        except sqlite3.Error:
            job_context = None
    if job_context is None:
        job_context = {
            "id": meta.get("job_id"),
            "url": meta.get("url"),
            "title": meta.get("title") or meta.get("job_title"),
            "snippet": None,
            "jd_text": None,
        }
    return job_context


def _package_detail_payload(d: Path, summary: dict | None = None) -> dict:
    summary = summary or _tailoring_summary(d)
    applied = _fetch_applied_by_package_slugs([summary.get("slug") or d.name]).get(summary.get("slug") or d.name)
    summary["applied"] = applied

    resume_tex, resume_pdf = TAILORING_DOC_MAP["resume"]
    cover_tex, cover_pdf = TAILORING_DOC_MAP["cover"]

    return {
        "summary": summary,
        "job_context": _package_job_context(summary),
        "analysis": _load_json_file(d / "analysis.json"),
        "grounding": _load_json_file(d / "grounding.json"),
        "grounding_audit": _load_json_file(d / "grounding_audit.json"),
        "resume_strategy": _load_json_file(d / "resume_strategy.json"),
        "cover_strategy": _load_json_file(d / "cover_strategy.json"),
        "latex": {
            "resume": (d / resume_tex).read_text(encoding="utf-8") if (d / resume_tex).exists() else "",
            "cover": (d / cover_tex).read_text(encoding="utf-8") if (d / cover_tex).exists() else "",
        },
        "pdf_available": {
            "resume": (d / resume_pdf).exists(),
            "cover": (d / cover_pdf).exists(),
        },
        "artifacts": summary.get("artifacts", {}),
    }


def _enrich_summary_company_from_analysis(d: Path, summary: dict) -> dict:
    meta = summary.get("meta")
    if not isinstance(meta, dict):
        return summary
    current = str(meta.get("company_name") or meta.get("company") or "").strip().lower()
    if current not in {"", "ingest", "manual", "mobile", "unknown", "--"}:
        return summary
    analysis = _load_json_file(d / "analysis.json")
    company_name = str((analysis or {}).get("company_name") or "").strip()
    if not company_name:
        return summary
    meta["company_name"] = company_name
    if current in {"", "ingest", "manual", "mobile", "unknown", "--"}:
        meta["company"] = company_name
    return summary


def package_runs(status: str = Query("complete")):
    _sync_app_state()
    if not TAILORING_OUTPUT_DIR.exists():
        return {"items": []}

    rows = []
    for d in sorted(TAILORING_OUTPUT_DIR.iterdir()):
        if not d.is_dir():
            continue
        s = _tailoring_summary(d)
        s = _enrich_summary_company_from_analysis(d, s)
        if status != "all" and s.get("status") != status:
            continue
        rows.append(s)
    applied_by_slug = _fetch_applied_by_package_slugs([str(row.get("slug") or "") for row in rows])
    # Enrich with DB decision state
    job_ids = [r.get("meta", {}).get("job_id") for r in rows if r.get("meta", {}).get("job_id")]
    decision_map: dict[int, str] = {}
    if job_ids:
        try:
            conn = get_db()
        except sqlite3.Error:
            conn = None
        if conn is not None:
            try:
                placeholders = ",".join("?" for _ in job_ids)
                for r in conn.execute(f"SELECT id, decision FROM results WHERE id IN ({placeholders})", job_ids):
                    decision_map[r["id"]] = r["decision"]
            finally:
                conn.close()
    filtered = []
    for row in rows:
        row["applied"] = applied_by_slug.get(str(row.get("slug") or ""))
        jid = (row.get("meta") or {}).get("job_id")
        if jid:
            row["decision"] = decision_map.get(jid)
        # Hide packages whose job was rolled back (no longer qa_approved) unless already applied
        if row.get("decision") and row["decision"] != "qa_approved" and not row.get("applied"):
            continue
        filtered.append(row)
    filtered.sort(key=lambda r: _parse_ts(r.get("updated_at")) or 0, reverse=True)
    return {"items": filtered}



def package_detail(slug: str):
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    if d is None:
        return JSONResponse({"error": "Package not found"}, 404)
    return _package_detail_payload(d)


def package_download_zip(slug: str):
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    if d is None:
        return JSONResponse({"error": "Package not found"}, 404)

    pdf_names = [
        "Conner_Jordan_Resume.pdf",
        "Conner_Jordan_Cover_Letter.pdf",
    ]
    available = [name for name in pdf_names if (d / name).exists()]
    if not available:
        return JSONResponse({"error": "No package PDFs found"}, 404)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in available:
            zf.write(d / name, arcname=name)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
    )


def package_delete(slug: str):
    """Delete a tailoring package directory. Rolls back the job to qa_approved."""
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    job_id = None

    if d is not None:
        summary = _tailoring_summary(d)
        job_id = (summary.get("meta") or {}).get("job_id")
        import shutil
        shutil.rmtree(d)

    # Roll back the job status to qa_approved so it can be re-tailored
    if job_id:
        conn = get_db_write()
        try:
            conn.execute(
                "UPDATE jobs SET status = 'qa_approved' WHERE id = ?",
                (job_id,),
            )
            conn.commit()
        finally:
            conn.close()

    return {"ok": True, "slug": slug}


def package_reject(slug: str):
    """Delete a tailoring package and reject the job so it never resurfaces."""
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    job_id = None

    if d is not None:
        summary = _tailoring_summary(d)
        job_id = (summary.get("meta") or {}).get("job_id")
        import shutil
        shutil.rmtree(d)

    if job_id:
        conn = get_db_write()
        try:
            from services.audit import log_state_change
            row = conn.execute("SELECT status, url FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row:
                old = row["status"]
                conn.execute(
                    "UPDATE jobs SET status = 'qa_rejected' WHERE id = ?",
                    (job_id,),
                )
                log_state_change(conn, job_id=job_id, job_url=row["url"],
                                 old_state=old, new_state="qa_rejected",
                                 action="package_reject")
            conn.commit()
        finally:
            conn.close()

    return {"ok": True, "slug": slug, "job_id": job_id}


def package_permanently_reject(slug: str):
    """Delete a tailoring package and permanently reject the job so it never resurfaces."""
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    job_id = None

    if d is not None:
        summary = _tailoring_summary(d)
        job_id = (summary.get("meta") or {}).get("job_id")
        import shutil
        shutil.rmtree(d)

    if job_id:
        conn = get_db_write()
        try:
            from datetime import datetime, timezone
            from services.audit import log_state_change

            row = conn.execute("SELECT status, url FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row:
                old = row["status"]
                if _normalize_decision(old) != "permanently_rejected":
                    _cancel_tailoring_queue_items(conn=conn, job_ids=[int(job_id)], statuses=("queued",), reason="Job permanently rejected from package view.")
                    _stop_active_tailoring_job([int(job_id)], "Job permanently rejected from package view.")
                    _set_ready_bucket_for_job_ids_in_conn(conn, [int(job_id)], _DEFAULT_READY_BUCKET)
                    conn.execute(
                        "UPDATE jobs SET status = 'permanently_rejected' WHERE id = ?",
                        (job_id,),
                    )
                    now = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        "INSERT INTO seen_urls (url, first_seen, last_seen, permanently_rejected) "
                        "VALUES (?, ?, ?, 1) "
                        "ON CONFLICT(url) DO UPDATE SET permanently_rejected = 1, last_seen = ?",
                        (row["url"], now, now, now),
                    )
                    log_state_change(
                        conn,
                        job_id=job_id,
                        job_url=row["url"],
                        old_state=old,
                        new_state="permanently_rejected",
                        action="package_permanently_reject",
                    )
            conn.commit()
        finally:
            conn.close()

    return {"ok": True, "slug": slug, "job_id": job_id}


def _package_regen_env() -> dict[str, str]:
    llm_runtime = _resolve_llm_runtime()
    env = os.environ.copy()
    env["TAILOR_LLM_URL"] = llm_runtime["chat_url"]
    env["TAILOR_LLM_MODELS_URL"] = llm_runtime["models_url"]
    env["TAILOR_LLM_MODEL"] = llm_runtime["selected_model"]
    env["TAILOR_OLLAMA_URL"] = llm_runtime["chat_url"]
    env["TAILOR_OLLAMA_MODELS_URL"] = llm_runtime["models_url"]
    env["TAILOR_OLLAMA_MODEL"] = llm_runtime["selected_model"]
    env["TAILOR_LLM_API_KEY"] = llm_runtime.get("api_key", "")
    env["TAILOR_LLM_PROVIDER"] = llm_runtime["provider"]
    return env


def package_regenerate_cover(slug: str):
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    if d is None:
        return JSONResponse({"ok": False, "error": "Package not found"}, 404)
    if _app._TAILORING_RUNNER.get("proc") is not None and _app._TAILORING_RUNNER["proc"].poll() is None:
        return JSONResponse({"ok": False, "error": "A tailoring run is already in progress"}, 409)

    summary = _tailoring_summary(d)
    job_context = _package_job_context(summary)
    analysis = _load_json_file(d / "analysis.json")
    if not isinstance(analysis, dict) or not analysis:
        return JSONResponse({"ok": False, "error": "Package analysis is missing; cannot regenerate cover letter"}, 409)

    meta = summary.get("meta", {}) or {}
    job_id = meta.get("job_id") or job_context.get("id")
    try:
        job_id = int(job_id)
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "Package metadata is missing a valid job_id"}, 409)

    job_payload = {
        "id": job_id,
        "url": str(job_context.get("url") or meta.get("url") or ""),
        "title": str(job_context.get("title") or meta.get("title") or meta.get("job_title") or "Untitled"),
        "board": meta.get("board"),
        "seniority": job_context.get("seniority"),
        "jd_text": job_context.get("jd_text"),
        "snippet": job_context.get("snippet"),
        "company": str(
            analysis.get("company_name")
            or meta.get("company_name")
            or meta.get("company")
            or "unknown"
        ),
    }
    if not job_payload["url"]:
        return JSONResponse({"ok": False, "error": "Package metadata is missing a job URL"}, 409)

    script = r"""
import json
import sys
from pathlib import Path

from tailor import config as cfg
from tailor.selector import SelectedJob
from tailor.tracing import TraceRecorder, utc_now_iso
from tailor.validator import validate_cover_letter
from tailor.writer import write_cover_letter

payload = json.loads(sys.stdin.read())
output_dir = Path(payload["output_dir"])
job = SelectedJob(**payload["job"])
analysis = payload["analysis"]
trace = TraceRecorder(
    output_dir,
    run_context={
        "run_slug": output_dir.name,
        "job_slug": payload.get("job_slug") or output_dir.name,
        "job_id": job.id,
        "job_title": job.title,
    },
)

def _build_validator_retry_feedback(result):
    return {
        "source": "validator",
        "summary": str(result),
        "failures": list(result.failures),
        "failure_details": list(result.failure_details),
    }


previous_feedback = None
passed = False
last_result = None
last_tex_path = None
for attempt in range(1, cfg.MAX_RETRIES + 1):
    tex_path = write_cover_letter(
        job,
        analysis,
        output_dir,
        previous_feedback=previous_feedback,
        attempt=attempt,
        trace_recorder=trace.record,
    )
    result = validate_cover_letter(tex_path)
    trace.record(
        {
            "event_type": "validation_result",
            "doc_type": "cover",
            "phase": "qa",
            "attempt": attempt,
            "passed": result.passed,
            "failures": result.failures,
            "failure_details": result.failure_details,
            "metrics": result.metrics,
            "timestamp": utc_now_iso(),
        }
    )
    trace.record(
        {
            "event_type": "doc_attempt_result",
            "doc_type": "cover",
            "phase": "qa",
            "attempt": attempt,
            "status": "passed" if result.passed else "failed",
            "error": None if result.passed else str(result),
            "timestamp": utc_now_iso(),
        }
    )
    last_result = result
    last_tex_path = str(tex_path)
    if result.passed:
        passed = True
        break
    previous_feedback = _build_validator_retry_feedback(result)

print(json.dumps({
    "ok": passed,
    "tex_path": last_tex_path,
    "validation": {
        "passed": bool(last_result.passed) if last_result is not None else False,
        "failures": list(last_result.failures) if last_result is not None else [],
        "metrics": dict(last_result.metrics) if last_result is not None else {},
    },
}))
"""

    try:
        env = _package_regen_env()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 503)

    proc = subprocess.run(
        [str(TAILORING_PYTHON), "-c", script],
        cwd=str(TAILORING_ROOT),
        input=json.dumps(
            {
                "output_dir": str(d),
                "job_slug": meta.get("job_slug") or meta.get("run_slug") or d.name,
                "job": job_payload,
                "analysis": analysis,
            }
        ),
        text=True,
        capture_output=True,
        env=env,
        timeout=300,
    )
    if proc.returncode != 0:
        error = (proc.stderr or proc.stdout or "Cover regeneration failed").strip()
        return JSONResponse({"ok": False, "error": error[-6000:]}, 500)

    try:
        payload = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return JSONResponse({"ok": False, "error": "Cover regeneration returned invalid output"}, 500)

    if not payload.get("ok"):
        validation = payload.get("validation") or {}
        failures = validation.get("failures") or []
        error = "; ".join(str(item) for item in failures) or "Cover regeneration failed validation"
        return JSONResponse(
            {"ok": False, "error": error, "validation": validation},
            422,
        )

    tex_path = d / "Conner_Jordan_Cover_Letter.tex"
    ok, error = _compile_tex_in_place(tex_path)
    if not ok:
        return JSONResponse(
            {
                "ok": False,
                "error": error or "Compile failed",
                "validation": payload.get("validation"),
            },
            _package_compile_status_code(error),
        )

    return {
        "ok": True,
        "slug": slug,
        "validation": payload.get("validation"),
        "pdf_name": "Conner_Jordan_Cover_Letter.pdf",
        "detail": _package_detail_payload(d),
    }



def package_save_latex(
    slug: str,
    doc_type: str,
    payload: dict = Body(...),
):
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    if d is None:
        return JSONResponse({"error": "Package not found"}, 404)
    if doc_type not in TAILORING_DOC_MAP:
        return JSONResponse({"error": "Invalid document type"}, 400)

    content = payload.get("content")
    if not isinstance(content, str):
        return JSONResponse({"error": "content must be a string"}, 400)

    tex_name, _ = TAILORING_DOC_MAP[doc_type]
    tex_path = d / tex_name
    tex_path.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(tex_path), "chars": len(content)}


def _package_compile_status_code(error: str | None) -> int:
    if not error:
        return 500
    lowered = error.lower()
    if "tex file not found" in lowered:
        return 404
    if "pdflatex not found" in lowered:
        return 503
    if "pdflatex pass" in lowered or "pdf not produced" in lowered:
        return 422
    return 500



def package_compile(slug: str, doc_type: str):
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    if d is None:
        return JSONResponse({"error": "Package not found"}, 404)
    if doc_type not in TAILORING_DOC_MAP:
        return JSONResponse({"error": "Invalid document type"}, 400)

    tex_name, pdf_name = TAILORING_DOC_MAP[doc_type]
    ok, error = _compile_tex_in_place(d / tex_name)
    if not ok:
        return JSONResponse(
            {
                "ok": False,
                "error": error or "Compile failed",
                "pdf_name": pdf_name,
            },
            _package_compile_status_code(error),
        )
    return {
        "ok": True,
        "error": None,
        "pdf_name": pdf_name,
    }



def package_diff_preview(slug: str, doc_type: str):
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    if d is None:
        return JSONResponse({"error": "Package not found"}, 404)
    if doc_type not in TAILORING_DOC_MAP:
        return JSONResponse({"error": "Invalid document type"}, 400)

    tex_name, _ = TAILORING_DOC_MAP[doc_type]
    baseline_tex = TAILORING_BASELINE_DOC_MAP[doc_type]
    generated_tex = d / tex_name
    out_name = "Conner_Jordan_Resume.diff.pdf" if doc_type == "resume" else "Conner_Jordan_Cover_Letter.diff.pdf"
    out_pdf = d / out_name

    ok, error = _build_diff_pdf(baseline_tex, generated_tex, out_pdf)
    if not ok:
        return JSONResponse({"error": error or "Failed to build diff preview"}, 500)
    return FileResponse(
        out_pdf,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def _read_optional_text(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_optional_bytes(path: Path) -> bytes | None:
    if not path.exists():
        return None
    try:
        return path.read_bytes()
    except Exception:
        return None


def _clean_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_tracking_datetime(value: object, field_name: str) -> tuple[str | None, str | None]:
    text = _clean_optional_str(value)
    if text is None:
        return None, None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat(), None
    except ValueError:
        return None, f"{field_name} must be an ISO-8601 datetime"


def package_apply(slug: str, payload: dict | None = Body(None)):
    _sync_app_state()
    payload = payload or {}
    d = _safe_tailoring_slug(slug)
    if d is None:
        return JSONResponse({"error": "Package not found"}, 404)

    existing = _fetch_applied_by_package_slugs([slug]).get(slug)
    if existing:
        return {"ok": True, "created": False, "application": existing}

    summary = _tailoring_summary(d)
    job_context = _package_job_context(summary)
    now = datetime.now(timezone.utc).isoformat()

    applied_at, applied_error = _normalize_tracking_datetime(payload.get("applied_at") or now, "applied_at")
    if applied_error:
        return JSONResponse({"ok": False, "error": applied_error}, 400)

    follow_up_at, follow_up_error = _normalize_tracking_datetime(payload.get("follow_up_at"), "follow_up_at")
    if follow_up_error:
        return JSONResponse({"ok": False, "error": follow_up_error}, 400)

    status = str(payload.get("status") or "applied").strip().lower()
    if status not in APPLIED_STATUS_VALUES:
        return JSONResponse({"ok": False, "error": f"status must be one of {', '.join(sorted(APPLIED_STATUS_VALUES))}"}, 400)

    meta = summary.get("meta", {}) or {}
    job_id = meta.get("job_id") or job_context.get("id")
    try:
        job_id = int(job_id) if job_id is not None else None
    except (TypeError, ValueError):
        job_id = None
    company_name = meta.get("company_name") or meta.get("company")
    job_title = meta.get("job_title") or meta.get("title") or job_context.get("title")
    job_url = job_context.get("url") or meta.get("url")
    application_url = _clean_optional_str(payload.get("application_url") or job_url)
    notes = _clean_optional_str(payload.get("notes"))

    _ensure_applied_tables()
    conn = get_db_write()
    try:
        cur = conn.execute(
            """
            INSERT INTO applied_applications (
                package_slug, job_id, job_title, company_name, job_url, application_url,
                applied_at, status, follow_up_at, notes, created_at, updated_at, status_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                job_id,
                job_title,
                company_name,
                job_url,
                application_url,
                applied_at,
                status,
                follow_up_at,
                notes,
                now,
                now,
                now,
            ),
        )
        application_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO applied_snapshots (
                application_id, meta, job_context, analysis, grounding, grounding_audit,
                resume_strategy, cover_strategy,
                resume_tex, cover_tex, resume_pdf, cover_pdf, llm_trace, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                json.dumps(meta),
                json.dumps(job_context),
                _read_optional_text(d / "analysis.json"),
                _read_optional_text(d / "grounding.json"),
                _read_optional_text(d / "grounding_audit.json"),
                _read_optional_text(d / "resume_strategy.json"),
                _read_optional_text(d / "cover_strategy.json"),
                _read_optional_text(d / "Conner_Jordan_Resume.tex"),
                _read_optional_text(d / "Conner_Jordan_Cover_Letter.tex"),
                _read_optional_bytes(d / "Conner_Jordan_Resume.pdf"),
                _read_optional_bytes(d / "Conner_Jordan_Cover_Letter.pdf"),
                _read_optional_text(d / TAILORING_TRACE_FILE),
                now,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        existing = _fetch_applied_by_package_slugs([slug]).get(slug)
        return {"ok": True, "created": False, "application": existing}
    except Exception as e:
        conn.rollback()
        return JSONResponse({"ok": False, "error": str(e)}, 500)
    finally:
        conn.close()

    return {
        "ok": True,
        "created": True,
        "application": _get_applied_application(application_id),
    }


def applied_list(
    status: str | None = Query(None),
    q: str | None = Query(None),
):
    _sync_app_state()
    _ensure_applied_tables()
    conn = get_db_write()
    try:
        clauses: list[str] = []
        params: list[object] = []
        if status:
            normalized_status = status.strip().lower()
            if normalized_status not in APPLIED_STATUS_VALUES:
                return JSONResponse({"ok": False, "error": f"status must be one of {', '.join(sorted(APPLIED_STATUS_VALUES))}"}, 400)
            clauses.append("status = ?")
            params.append(normalized_status)
        if q and q.strip():
            clauses.append("(job_title LIKE ? OR company_name LIKE ? OR notes LIKE ?)")
            pattern = f"%{q.strip()}%"
            params.extend([pattern, pattern, pattern])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"""
            SELECT aa.id, aa.package_slug, aa.job_id, aa.job_title, aa.company_name, aa.job_url,
                   aa.application_url, aa.applied_at, aa.status, aa.follow_up_at, aa.notes,
                   aa.created_at, aa.updated_at, aa.status_updated_at,
                   s.resume_pdf, s.cover_pdf
            FROM applied_applications aa
            JOIN applied_snapshots s ON s.application_id = aa.id
            {where}
            ORDER BY aa.updated_at DESC, aa.id DESC
            """,
            tuple(params),
        ).fetchall()
        items = []
        for row in rows:
            item = _applied_summary_from_row(row) or {}
            item["artifacts"] = {
                "Conner_Jordan_Resume.pdf": bool(row["resume_pdf"]),
                "Conner_Jordan_Cover_Letter.pdf": bool(row["cover_pdf"]),
            }
            items.append(item)
        return {"items": items, "count": len(items)}
    finally:
        conn.close()


def applied_detail(application_id: int):
    _sync_app_state()
    detail = _get_applied_snapshot_detail(application_id)
    if not detail:
        return JSONResponse({"error": "Applied record not found"}, 404)
    return detail


def applied_update_tracking(application_id: int, payload: dict = Body(...)):
    _sync_app_state()
    current = _get_applied_application(application_id)
    if not current:
        return JSONResponse({"error": "Applied record not found"}, 404)

    fields: dict[str, object] = {}
    errors: list[str] = []

    if "application_url" in payload:
        fields["application_url"] = _clean_optional_str(payload.get("application_url"))
    if "applied_at" in payload:
        if _clean_optional_str(payload.get("applied_at")) is None:
            errors.append("applied_at is required")
        else:
            applied_at, err = _normalize_tracking_datetime(payload.get("applied_at"), "applied_at")
            if err:
                errors.append(err)
            else:
                fields["applied_at"] = applied_at
    if "follow_up_at" in payload:
        follow_up_at, err = _normalize_tracking_datetime(payload.get("follow_up_at"), "follow_up_at")
        if err:
            errors.append(err)
        else:
            fields["follow_up_at"] = follow_up_at
    if "notes" in payload:
        fields["notes"] = _clean_optional_str(payload.get("notes"))
    if "status" in payload:
        status = str(payload.get("status") or "").strip().lower()
        if status not in APPLIED_STATUS_VALUES:
            errors.append(f"status must be one of {', '.join(sorted(APPLIED_STATUS_VALUES))}")
        else:
            fields["status"] = status

    if errors:
        return JSONResponse({"ok": False, "error": "; ".join(errors)}, 400)
    if not fields:
        return {"ok": True, "application": current}

    now = datetime.now(timezone.utc).isoformat()
    fields["updated_at"] = now
    if fields.get("status") and fields.get("status") != current.get("status"):
        fields["status_updated_at"] = now

    assignments = ", ".join(f"{name} = ?" for name in fields)
    params = list(fields.values()) + [application_id]

    _ensure_applied_tables()
    conn = get_db_write()
    try:
        conn.execute(
            f"UPDATE applied_applications SET {assignments} WHERE id = ?",
            tuple(params),
        )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return JSONResponse({"ok": False, "error": str(e)}, 500)
    finally:
        conn.close()

    return {"ok": True, "application": _get_applied_application(application_id)}


def applied_artifact(application_id: int, name: str):
    _sync_app_state()
    if name not in APPLIED_ARTIFACT_COLUMNS:
        return JSONResponse({"error": "Artifact not allowed"}, 400)
    column, media_type, is_bytes = APPLIED_ARTIFACT_COLUMNS[name]

    _ensure_applied_tables()
    conn = get_db_write()
    try:
        row = conn.execute(
            f"SELECT {column} FROM applied_snapshots WHERE application_id = ?",
            (application_id,),
        ).fetchone()
        if not row:
            return JSONResponse({"error": "Applied record not found"}, 404)
        value = row[column]
        if value is None:
            return JSONResponse({"error": "Artifact not found"}, 404)
        content = value if is_bytes else str(value)
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{name}"'},
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes — API: Manual JD ingestion
# ---------------------------------------------------------------------------

_INGEST_EXTRACT_SYSTEM = (
    "Extract structured fields from a job description. Return ONLY valid JSON:\n"
    '{ "title": "", "company": "", "url": "", "seniority": "", "snippet": "", "salary_k": null, "experience_years": null }\n'
    '- seniority: junior|mid|senior|lead|staff|principal or ""\n'
    "- snippet: 1-3 sentence summary, max 400 chars\n"
    "- salary_k: integer in thousands USD (top of range if a range is given, e.g. for '$90k-$130k' return 130). null if not stated.\n"
    "- experience_years: integer or null\n"
    '- url: application URL if present, else ""'
)


def _parse_manual_ingest_jd(jd_text: str) -> dict:
    llm_runtime, model_id = _resolve_active_llm_runtime()
    return _shared_chat_expect_json(
        _INGEST_EXTRACT_SYSTEM,
        jd_text[:12000],
        llm_runtime=llm_runtime,
        model_id=model_id,
        max_tokens=1200,
        temperature=0.1,
        trace={"phase": "dashboard_ingest_parse", "response_parse_kind": "json"},
    )


def _validate_package_url(url: str) -> tuple[str, str | None]:
    url = (url or "").strip()
    if not url:
        raise ValueError("LLM parse did not find a URL. Paste a JD with a working application URL.")

    from services.jd_fetch import fetch_jd
    text, method = fetch_jd(url)
    if not text or len(text.split()) < 20:
        raise ValueError("Could not extract job content from this URL")
    return text[:15000], method


def tailoring_ingest_parse(payload: dict = Body(...)):
    _sync_app_state()
    jd_text = (payload.get("jd_text") or "").strip()
    if not jd_text:
        return JSONResponse({"ok": False, "error": "jd_text is required"}, 400)

    try:
        fields = _parse_manual_ingest_jd(jd_text)
        return {"ok": True, "fields": fields}
    except Exception as e:
        message = str(e)
        if "No active" in message or "model" in message.lower():
            return JSONResponse({"ok": False, "error": message}, 503)
        return JSONResponse({"ok": False, "error": f"LLM call failed: {_http_error_details(e)}"}, 500)



def tailoring_ingest_fetch_url(payload: dict = Body(...)):
    """Fetch a job URL and return extracted text. Uses domain-specific extractors."""
    url = (payload.get("url") or "").strip()
    if not url:
        return JSONResponse({"ok": False, "error": "url is required"}, 400)

    from services.jd_fetch import fetch_jd
    text, _method = fetch_jd(url)

    if not text or len(text.split()) < 20:
        return JSONResponse({"ok": False, "error": "Could not extract job content from this URL"}, 422)

    return {"ok": True, "text": text[:15000], "url": url}


def _coerce_ingest_numeric(value: object) -> int | None:
    try:
        return int(value) if value not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _prepare_manual_ingest_fields(payload: dict) -> tuple[str, str, str, str, str | None, str | None, str | None, int | None, int | None, str]:
    title = (payload.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")

    url = (payload.get("url") or "").strip()
    if not url:
        import time as _time, random as _random
        url = f"manual://ingest/{int(_time.time() * 1000)}-{_random.randint(1000, 9999)}"

    company = (payload.get("company") or "").strip()
    board = (payload.get("board") or payload.get("company") or "manual").strip()
    seniority = (payload.get("seniority") or "").strip() or None
    snippet = (payload.get("snippet") or "").strip() or None
    jd_text = (payload.get("jd_text") or "").strip() or None
    salary_k = _coerce_ingest_numeric(payload.get("salary_k"))
    experience_years = _coerce_ingest_numeric(payload.get("experience_years"))

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return title, url, company, board, seniority, snippet, jd_text, salary_k, experience_years, now


def _insert_manual_ingest_job(
    conn: sqlite3.Connection,
    *,
    title: str,
    url: str,
    company: str,
    board: str,
    seniority: str | None,
    snippet: str | None,
    jd_text: str | None,
    salary_k: int | None,
    experience_years: int | None,
    now: str,
) -> int | None:
    cur = conn.execute(
        """INSERT INTO jobs
           (url, title, company, board, seniority, experience_years, salary_k, score, status,
            snippet, query, source, jd_text, filter_verdicts, run_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'qa_pending', ?, 'manual-ingest', 'manual', ?, NULL, 'manual-ingest', ?, ?)
           ON CONFLICT(url) DO NOTHING""",
        (url, title, company, board, seniority, experience_years, salary_k, snippet, jd_text, now, now),
    )
    return cur.lastrowid if cur.rowcount > 0 else None


def _approve_job_row(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    llm_available: bool,
    llm_runtime: dict | None,
    model_id: str | None,
) -> dict:
    jid = int(row["id"])
    old_decision = _normalize_decision(row["decision"])
    source_text = row["jd_text"] or row["snippet"] or ""
    if len(source_text.strip()) < 50:
        return {"job_id": jid, "skipped": True, "reason": "No JD text (too short to tailor)"}

    salary_verdict = _salary_policy_for_job(
        salary_text=row["salary_text"] or "",
        salary_k=row["salary_k"],
    )
    if salary_verdict.hard_reject:
        conn.execute("UPDATE jobs SET status='qa_rejected' WHERE id=?", (jid,))
        from services.audit import log_state_change
        log_state_change(
            conn,
            job_id=jid,
            job_url=row["url"],
            old_state=old_decision,
            new_state="qa_rejected",
            action="qa_reject",
        )
        return {
            "job_id": jid,
            "rejected": True,
            "reason": salary_verdict.reason,
        }

    req_summary, approved_jd_text, polished_with_llm = _polish_job_description(
        source_text,
        row["title"],
        row["url"],
        llm_runtime if llm_available else None,
        model_id if llm_available else None,
    )
    conn.execute(
        "UPDATE jobs SET status='qa_approved', snippet=?, approved_jd_text=? WHERE id=?",
        (
            (req_summary or row["snippet"] or "").strip() or None,
            (approved_jd_text or source_text or "").strip() or None,
            jid,
        ),
    )
    from services.audit import log_state_change
    log_state_change(
        conn,
        job_id=jid,
        job_url=row["url"],
        old_state=old_decision,
        new_state="qa_approved",
        action="qa_approve",
    )
    return {
        "job_id": jid,
        "summarized": bool(req_summary),
        "polished": bool(approved_jd_text),
        "polished_with_llm": polished_with_llm,
    }


def tailoring_ingest_commit(payload: dict = Body(...)):
    _sync_app_state()
    try:
        title, url, company, board, seniority, snippet, jd_text, salary_k, experience_years, now = _prepare_manual_ingest_fields(payload)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, 400)

    try:
        conn = get_db_write()
        job_id = _insert_manual_ingest_job(
            conn,
            title=title,
            url=url,
            company=company,
            board=board,
            seniority=seniority,
            snippet=snippet,
            jd_text=jd_text,
            salary_k=salary_k,
            experience_years=experience_years,
            now=now,
        )
        conn.commit()
        if job_id is None:
            conn.close()
            return JSONResponse({"ok": False, "error": "Duplicate — this URL already exists for manual-ingest"}, 409)
        from services.audit import log_state_change
        log_state_change(
            conn,
            job_id=job_id,
            job_url=url,
            old_state=None,
            new_state="qa_pending",
            action="ingest_manual",
            detail={"query": "manual-ingest"},
        )
        conn.commit()
        conn.close()
        try:
            from services.auto_qa_review import enqueue_auto_qa_review
            enqueue_auto_qa_review(source="auto_post_ingest")
        except Exception:
            logger.exception("auto_qa: post-ingest enqueue failed")
        return {"ok": True, "job_id": job_id, "url": url}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 500)


def tailoring_ingest_prepare(payload: dict = Body(...)):
    _sync_app_state()
    try:
        title, url, company, board, seniority, snippet, jd_text, salary_k, experience_years, now = _prepare_manual_ingest_fields(payload)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, 400)

    llm_available = False
    llm_runtime = None
    model_id = None
    try:
        llm_runtime, model_id = _resolve_active_llm_runtime()
        if model_id:
            llm_available = True
    except Exception:
        pass

    try:
        conn = get_db_write()
        _ensure_results_approved_jd_column(conn)
        job_id = _insert_manual_ingest_job(
            conn,
            title=title,
            url=url,
            company=company,
            board=board,
            seniority=seniority,
            snippet=snippet,
            jd_text=jd_text,
            salary_k=salary_k,
            experience_years=experience_years,
            now=now,
        )
        if job_id is None:
            conn.close()
            return JSONResponse({"ok": False, "error": "Duplicate — this URL already exists for manual-ingest"}, 409)

        from services.audit import log_state_change
        log_state_change(
            conn,
            job_id=job_id,
            job_url=url,
            old_state=None,
            new_state="qa_pending",
            action="ingest_manual",
            detail={"query": "manual-ingest", "prepare_for_tailoring": True},
        )
        row = conn.execute(
            "SELECT id, title, url, snippet, jd_text, salary_text, salary_k, decision FROM results WHERE id = ?",
            (job_id,),
        ).fetchone()
        approval = _approve_job_row(
            conn,
            row=row,
            llm_available=llm_available,
            llm_runtime=llm_runtime,
            model_id=model_id,
        )
        conn.commit()
        final_decision = conn.execute(
            "SELECT decision FROM results WHERE id = ?",
            (job_id,),
        ).fetchone()
        conn.close()
        return {
            "ok": True,
            "job_id": job_id,
            "url": url,
            "decision": final_decision["decision"] if final_decision else None,
            "approval": approval,
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 500)


def tailoring_ingest_package(payload: dict = Body(...)):
    _sync_app_state()
    jd_text = (payload.get("jd_text") or "").strip()
    if not jd_text:
        return JSONResponse({"ok": False, "error": "jd_text is required"}, 400)

    try:
        fields = _parse_manual_ingest_jd(jd_text)
    except Exception as e:
        message = str(e)
        if "No active" in message or "model" in message.lower():
            return JSONResponse({"ok": False, "error": message}, 503)
        return JSONResponse({"ok": False, "error": f"LLM call failed: {_http_error_details(e)}"}, 500)

    fields = fields or {}
    title = (fields.get("title") or "").strip()
    if not title:
        return JSONResponse({"ok": False, "error": "LLM parse did not find a title."}, 422)

    url = (fields.get("url") or "").strip()
    try:
        fetched_text, fetch_method = _validate_package_url(url)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, 422)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"URL check failed: {_http_error_details(e)}"}, 422)

    source_text = jd_text if len(jd_text.split()) >= 20 else fetched_text
    package_payload = {
        "title": title,
        "company": (fields.get("company") or "").strip(),
        "url": url,
        "seniority": (fields.get("seniority") or "").strip(),
        "snippet": (fields.get("snippet") or "").strip(),
        "salary_k": fields.get("salary_k"),
        "experience_years": fields.get("experience_years"),
        "jd_text": source_text,
    }

    try:
        title, url, company, board, seniority, snippet, jd_text, salary_k, experience_years, now = _prepare_manual_ingest_fields(package_payload)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, 400)

    llm_available = False
    llm_runtime = None
    model_id = None
    try:
        llm_runtime, model_id = _resolve_active_llm_runtime()
        if model_id:
            llm_available = True
    except Exception:
        pass

    conn = None
    try:
        conn = get_db_write()
        _ensure_results_approved_jd_column(conn)
        job_id = _insert_manual_ingest_job(
            conn,
            title=title,
            url=url,
            company=company,
            board=board,
            seniority=seniority,
            snippet=snippet,
            jd_text=jd_text,
            salary_k=salary_k,
            experience_years=experience_years,
            now=now,
        )
        if job_id is None:
            conn.close()
            conn = None
            return JSONResponse({"ok": False, "error": "Duplicate — this URL already exists for manual-ingest"}, 409)

        from services.audit import log_state_change
        log_state_change(
            conn,
            job_id=job_id,
            job_url=url,
            old_state=None,
            new_state="qa_pending",
            action="ingest_manual",
            detail={
                "query": "manual-ingest",
                "prepare_for_tailoring": True,
                "package_start": True,
                "url_fetch_method": fetch_method,
            },
        )

        row = conn.execute(
            "SELECT id, title, url, snippet, jd_text, salary_text, salary_k, decision FROM results WHERE id = ?",
            (job_id,),
        ).fetchone()
        approval = _approve_job_row(
            conn,
            row=row,
            llm_available=llm_available,
            llm_runtime=llm_runtime,
            model_id=model_id,
        )
        conn.commit()
        final_decision = conn.execute(
            "SELECT decision FROM results WHERE id = ?",
            (job_id,),
        ).fetchone()
        decision = final_decision["decision"] if final_decision else None
        if decision != "qa_approved":
            conn.close()
            conn = None
            reason = approval.get("reason") if isinstance(approval, dict) else None
            return JSONResponse(
                {
                    "ok": False,
                    "error": f"Job was not approved for tailoring: {decision or 'unknown'}",
                    "job_id": job_id,
                    "decision": decision,
                    "approval": approval,
                    "reason": reason,
                },
                409,
            )
        conn.close()
        conn = None

        job, error = _ready_job_for_tailoring(int(job_id))
        if error:
            return error
        added, duplicates = _enqueue_tailoring_queue_items([{"job": job, "skip_analysis": False}])
        item = added[0] if added else None
        if not item and duplicates:
            duplicate = next((d for d in duplicates if int(d.get("job_id", -1)) == int(job_id)), None)
            if duplicate:
                item = duplicate
            else:
                return JSONResponse(
                    {"ok": False, "error": "Another job is already queued or running", "duplicates": duplicates},
                    409,
                )
        if added and _app._TAILORING_RUNNER.get("proc") is None:
            _app._process_tailoring_queue()

        return {
            "ok": True,
            "job_id": job_id,
            "url": url,
            "decision": decision,
            "fields": package_payload,
            "approval": approval,
            "queued": len(added),
            "item": item,
            "duplicates": duplicates,
            "runner": _tailoring_runner_snapshot(),
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 500)
    finally:
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# Routes — API: Mobile JD Scan
# ---------------------------------------------------------------------------

def tailoring_ingest_scan_mobile():
    from services.mobile_jd import scan_and_process
    return scan_and_process()


# ---------------------------------------------------------------------------
# Routes — API: QA Triage
# ---------------------------------------------------------------------------

_QA_POLISH_SYSTEM = (
    "You are cleaning a scraped job description for internal QA approval and resume tailoring.\n"
    "Rewrite noisy job text into a polished, structured, high-signal plain text brief.\n\n"
    "Keep:\n"
    "- the actual role focus\n"
    "- core responsibilities\n"
    "- required qualifications\n"
    "- preferred qualifications when explicitly present\n"
    "- concrete tools, environments, and domain requirements\n"
    "- important logistics like remote/hybrid/onsite, location, employment type, or compensation when clearly stated\n\n"
    "Remove:\n"
    "- recruiting calls to action\n"
    "- social media links and follow-us text\n"
    "- legal/EEO/accommodation/privacy boilerplate\n"
    "- generic company hype and culture filler unless it directly explains the role\n"
    "- benefits and health-plan marketing unless unusually important to the role\n"
    "- duplicate or near-duplicate content\n\n"
    "approved_jd_text rules:\n"
    "- plain text only, no markdown fences\n"
    "- use these headings when you have content for them: ROLE SUMMARY, CORE RESPONSIBILITIES, REQUIRED QUALIFICATIONS, PREFERRED QUALIFICATIONS, LOGISTICS\n"
    "- bullets should start with '- '\n"
    "- keep it concise and readable\n"
    "- do not include raw URLs unless essential to the role itself\n\n"
    "Return JSON only:\n"
    '{ "requirements_summary": "2-4 sentence summary: role focus, key technical requirements, must-have qualifications, seniority signals", '
    '"approved_jd_text": "clean, structured JD body", "removed_noise": ["short examples of removed junk"] }'
)

_JD_NOISE_PATTERNS = [
    re.compile(r"(?i)\b(?:follow us|connect with us|share this job|job alerts?|talent network|apply now|submit your application)\b"),
    re.compile(r"(?i)\b(?:facebook|instagram|linkedin|twitter|x\.com|youtube|tiktok|social media)\b"),
    re.compile(r"(?i)\b(?:equal opportunity|eeo|affirmative action|protected veteran|disability|reasonable accommodation|e-verify|criminal histories|privacy policy|terms of use|pay transparency non-discrimination)\b"),
    re.compile(r"(?i)\b(?:medical|dental|vision|life insurance|401\(k\)|health savings|wellness program|employee assistance)\b"),
]
_JD_HEADING_MARKERS = [
    "Role Overview",
    "About the Role",
    "About Us",
    "Responsibilities",
    "Core Responsibilities",
    "What You'll Do",
    "What You Will Do",
    "Qualifications",
    "Required Qualifications",
    "Requirements",
    "What You Bring",
    "Preferred Qualifications",
    "Nice to Have",
    "Location",
    "Compensation",
    "Benefits",
]


def _ensure_results_approved_jd_column(conn: sqlite3.Connection) -> None:
    if not _app._results_has_column(conn, "approved_jd_text"):
        conn.execute("ALTER TABLE results ADD COLUMN approved_jd_text TEXT")


def _strip_llm_fences(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
    return raw.strip()


def _extract_llm_content(cdata: dict) -> str:
    """Extract content from either OpenAI or Ollama-native response shape."""
    # Ollama native /api/chat: {"message": {"content": "..."}}
    if "message" in cdata and isinstance(cdata["message"], dict):
        return cdata["message"].get("content") or ""
    # OpenAI-compatible: {"choices": [{"message": {"content": "..."}}]}
    choices = cdata.get("choices")
    if choices and isinstance(choices, list):
        return choices[0].get("message", {}).get("content") or ""
    return ""


def _normalize_jd_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    for marker in _JD_HEADING_MARKERS:
        text = re.sub(rf"(?<!\n)\b{re.escape(marker)}\b", f"\n\n{marker}", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_noise_paragraph(paragraph: str) -> bool:
    p = paragraph.strip()
    if not p:
        return True
    if len(p.split()) <= 4 and re.search(r"https?://|www\.", p):
        return True
    if p.startswith("#") or p.startswith("@"):
        return True
    return any(pattern.search(p) for pattern in _JD_NOISE_PATTERNS)


def _extract_candidate_paragraphs(text: str) -> list[str]:
    normalized = _normalize_jd_text(text)
    paragraphs = [
        re.sub(r"\s+", " ", p).strip(" \n\t-•")
        for p in re.split(r"\n{2,}", normalized)
    ]
    paragraphs = [p for p in paragraphs if p]
    if len(paragraphs) <= 1 and normalized:
        paragraphs = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", normalized)
            if s.strip()
        ]
    return paragraphs


def _looks_like_logistics(text: str) -> bool:
    return bool(re.search(r"(?i)\b(remote|hybrid|onsite|on-site|location|salary|compensation|employment type|full-time|contract)\b", text))


def _classify_sentence(sentence: str) -> str:
    s = sentence.strip()
    if _looks_like_logistics(s):
        return "logistics"
    if re.search(r"(?i)\b(preferred|nice to have|bonus)\b", s):
        return "preferred"
    if re.search(r"(?i)\b(required|required qualifications|requirements|must have|what you bring|experience with|proficiency|knowledge of|background in|foundation in)\b", s):
        return "required"
    if re.search(r"(?i)\b(you will|responsible for|build|design|develop|create|support|lead|collaborate|implement|monitor|optimi[sz]e|partner)\b", s):
        return "responsibilities"
    return "summary"


def _heuristic_requirements_summary(cleaned_text: str) -> str:
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", cleaned_text)
        if s.strip() and not s.strip().isupper()
    ]
    return " ".join(sentences[:3])[:400].strip()


def _heuristic_polish_jd(jd_text: str, title: str | None = None) -> tuple[str | None, str | None]:
    paragraphs = [p for p in _extract_candidate_paragraphs(jd_text) if not _is_noise_paragraph(p)]
    if not paragraphs:
        cleaned = re.sub(r"\s+", " ", (jd_text or "")).strip()
        summary = cleaned[:400] if cleaned else None
        return summary, cleaned or None

    sections: dict[str, list[str]] = {
        "ROLE SUMMARY": [],
        "CORE RESPONSIBILITIES": [],
        "REQUIRED QUALIFICATIONS": [],
        "PREFERRED QUALIFICATIONS": [],
        "LOGISTICS": [],
    }
    for paragraph in paragraphs:
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            sentence = sentence.strip(" -•")
            if not sentence:
                continue
            bucket = _classify_sentence(sentence)
            if bucket == "responsibilities":
                sections["CORE RESPONSIBILITIES"].append(sentence)
            elif bucket == "required":
                sections["REQUIRED QUALIFICATIONS"].append(sentence)
            elif bucket == "preferred":
                sections["PREFERRED QUALIFICATIONS"].append(sentence)
            elif bucket == "logistics":
                sections["LOGISTICS"].append(sentence)
            elif not sections["ROLE SUMMARY"]:
                sections["ROLE SUMMARY"].append(sentence)

    if not sections["ROLE SUMMARY"] and title:
        sections["ROLE SUMMARY"].append(f"{title.strip()} role with a focus on the responsibilities and qualifications listed below.")

    rendered: list[str] = []
    for heading, items in sections.items():
        unique_items: list[str] = []
        seen: set[str] = set()
        for item in items:
            norm = item.lower()
            if norm in seen:
                continue
            seen.add(norm)
            unique_items.append(item)
        if not unique_items:
            continue
        rendered.append(heading)
        if heading == "ROLE SUMMARY":
            rendered.append(" ".join(unique_items[:2]))
        else:
            rendered.extend(f"- {item}" for item in unique_items[:8])
        rendered.append("")
    approved = "\n".join(rendered).strip()
    return _heuristic_requirements_summary(approved), approved or None


def _polish_job_description(
    jd_text: str,
    title: str | None,
    url: str | None,
    llm_runtime: dict | None,
    model_id: str | None,
) -> tuple[str | None, str | None, bool]:
    heuristic_summary, heuristic_text = _heuristic_polish_jd(jd_text, title=title)
    if not (llm_runtime and model_id and jd_text and len(jd_text.strip()) > 80):
        return heuristic_summary, heuristic_text, False

    user_text = heuristic_text or _normalize_jd_text(jd_text)
    user_prompt = (
        f"Title: {title or 'Unknown'}\n"
        f"URL: {url or 'N/A'}\n\n"
        f"Scraped JD Text:\n{user_text[:12000]}"
    )
    try:
        fields = _shared_chat_expect_json(
            _QA_POLISH_SYSTEM,
            user_prompt,
            llm_runtime=llm_runtime,
            model_id=model_id,
            max_tokens=2400,
            temperature=0.1,
            trace={"phase": "dashboard_jd_polish", "response_parse_kind": "json"},
        )
        summary = (fields.get("requirements_summary") or "").strip() or heuristic_summary
        approved_jd_text = (fields.get("approved_jd_text") or "").strip() or heuristic_text
        return summary, approved_jd_text, True
    except Exception:
        return heuristic_summary, heuristic_text, False


def tailoring_qa_list(
    limit: int = Query(200, ge=1, le=2000),
    board: str | None = Query(None),
    source: str | None = Query(None),
    search: str | None = Query(None),
):
    _sync_app_state()
    board = board if isinstance(board, str) else None
    source = source if isinstance(source, str) else None
    search = search if isinstance(search, str) else None
    conn = get_db()
    try:
        available = {
            "company": _results_has_column(conn, "company"),
            "source": _results_has_column(conn, "source"),
            "location": _results_has_column(conn, "location"),
            "salary_k": _results_has_column(conn, "salary_k"),
        }
        clauses = [
            "decision = 'qa_pending'",
            "NOT EXISTS (SELECT 1 FROM applied_applications aa WHERE aa.job_id = results.id)",
        ]
        params: list[object] = []
        if board:
            clauses.append("LOWER(COALESCE(board, '')) = ?")
            params.append(board.strip().lower())
        if source and available["source"]:
            normalized_source = source.strip().lower()
            if normalized_source == "manual_ingest":
                clauses.append("LOWER(COALESCE(source, '')) IN ('manual', 'manual_ingest', 'manual-ingest')")
            elif normalized_source == "mobile_ingest":
                clauses.append("LOWER(COALESCE(source, '')) IN ('mobile', 'mobile_ingest', 'mobile-ingest')")
            elif normalized_source == "scrape":
                clauses.append("(TRIM(COALESCE(source, '')) = '' OR LOWER(COALESCE(source, '')) NOT IN ('manual', 'manual_ingest', 'manual-ingest', 'mobile', 'mobile_ingest', 'mobile-ingest'))")
            else:
                clauses.append("LOWER(COALESCE(source, '')) = ?")
                params.append(normalized_source)
        if search:
            query = f"%{search.strip()}%"
            search_fields = [
                "COALESCE(title, '')",
                "COALESCE(snippet, '')",
                "COALESCE(url, '')",
                "COALESCE(board, '')",
                "COALESCE(seniority, '')",
            ]
            if available["company"]:
                search_fields.append("COALESCE(company, '')")
            if available["location"]:
                search_fields.append("COALESCE(location, '')")
            clauses.append("(" + " OR ".join(f"{field} LIKE ?" for field in search_fields) + ")")
            params.extend([query] * len(search_fields))
        where = "WHERE " + " AND ".join(clauses)
        total = conn.execute(f"SELECT COUNT(*) FROM results {where}", tuple(params)).fetchone()[0]
        select_cols = [
            "id",
            "title",
            "url",
            "snippet",
            "board",
            "seniority",
            "created_at",
            "company" if available["company"] else "NULL AS company",
            "source" if available["source"] else "NULL AS source",
            "location" if available["location"] else "NULL AS location",
            "salary_k" if available["salary_k"] else "NULL AS salary_k",
        ]
        query_params = [*params, max(1, min(int(limit), 2000))]
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} "
            f"FROM results {where} "
            "ORDER BY id DESC LIMIT ?",
            tuple(query_params),
        ).fetchall()
        items = [dict(r) for r in rows]
        return {"items": items, "count": len(items), "total": total}
    finally:
        conn.close()


def tailoring_qa_approve(payload: dict = Body(...)):
    _sync_app_state()
    job_ids = payload.get("job_ids") or []
    if payload.get("job_id"):
        job_ids = [payload["job_id"]]
    if not job_ids:
        return JSONResponse({"ok": False, "error": "job_id or job_ids required"}, 400)

    # Try LLM reformat (fail-open)
    llm_available = False
    llm_runtime = None
    model_id = None
    try:
        llm_runtime, model_id = _resolve_active_llm_runtime()
        if model_id:
            llm_available = True
    except Exception:
        pass

    conn = get_db_write()
    try:
        _ensure_results_approved_jd_column(conn)
        results = []
        for jid in job_ids:
            row = conn.execute(
                "SELECT id, title, url, snippet, jd_text, salary_text, salary_k, decision FROM results WHERE id = ?",
                (jid,),
            ).fetchone()
            if not row:
                continue
            old_decision = _normalize_decision(row["decision"])
            if not _job_is_qa_pending(old_decision):
                continue
            results.append(
                _approve_job_row(
                    conn,
                    row=row,
                    llm_available=llm_available,
                    llm_runtime=llm_runtime,
                    model_id=model_id,
                )
            )

        conn.commit()
        return {"ok": True, "approved": results}
    finally:
        conn.close()


def tailoring_qa_reject(payload: dict = Body(...)):
    _sync_app_state()
    job_ids = payload.get("job_ids") or []
    if payload.get("job_id"):
        job_ids = [payload["job_id"]]
    if not job_ids:
        return JSONResponse({"ok": False, "error": "job_id or job_ids required"}, 400)

    conn = get_db_write()
    try:
        from services.audit import log_state_change
        for jid in job_ids:
            row = conn.execute("SELECT decision, url FROM results WHERE id=?", (jid,)).fetchone()
            old_decision = _normalize_decision(row["decision"]) if row else None
            if old_decision not in ("qa_pending", "qa_approved"):
                continue
            _cancel_tailoring_queue_items(conn=conn, job_ids=[int(jid)], statuses=("queued",), reason="Job rejected.")
            _stop_active_tailoring_job([int(jid)], "Job rejected.")
            _set_ready_bucket_for_job_ids_in_conn(conn, [int(jid)], _DEFAULT_READY_BUCKET)
            conn.execute("UPDATE jobs SET status='qa_rejected' WHERE id=?", (jid,))
            if row:
                log_state_change(conn, job_id=jid, job_url=row["url"],
                                 old_state=old_decision, new_state="qa_rejected",
                                 action="qa_reject")
        conn.commit()
        return {"ok": True, "rejected": len(job_ids)}
    finally:
        conn.close()


def tailoring_qa_permanently_reject(payload: dict = Body(...)):
    _sync_app_state()
    job_ids = payload.get("job_ids") or []
    if payload.get("job_id"):
        job_ids = [payload["job_id"]]
    if not job_ids:
        return JSONResponse({"ok": False, "error": "job_id or job_ids required"}, 400)

    conn = get_db_write()
    try:
        from services.audit import log_state_change
        from datetime import datetime, timezone
        updated = 0
        for jid in job_ids:
            row = conn.execute("SELECT decision, url FROM results WHERE id=?", (jid,)).fetchone()
            if not row:
                continue
            old_decision = _normalize_decision(row["decision"])
            if old_decision == "permanently_rejected":
                continue
            _cancel_tailoring_queue_items(conn=conn, job_ids=[int(jid)], statuses=("queued",), reason="Job permanently rejected.")
            _stop_active_tailoring_job([int(jid)], "Job permanently rejected.")
            _set_ready_bucket_for_job_ids_in_conn(conn, [int(jid)], _DEFAULT_READY_BUCKET)
            conn.execute("UPDATE jobs SET status='permanently_rejected' WHERE id=?", (jid,))
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO seen_urls (url, first_seen, last_seen, permanently_rejected) "
                "VALUES (?, ?, ?, 1) "
                "ON CONFLICT(url) DO UPDATE SET permanently_rejected = 1, last_seen = ?",
                (row["url"], now, now, now),
            )
            log_state_change(conn, job_id=jid, job_url=row["url"],
                             old_state=old_decision, new_state="permanently_rejected",
                             action="permanently_reject")
            updated += 1
        conn.commit()
        return {"ok": True, "updated": updated, "skipped": len(job_ids) - updated}
    finally:
        conn.close()


_QA_LLM_REVIEW_SYSTEM = (
    "You are a job-candidate fit reviewer. Given the candidate's profile and a job description, "
    "evaluate whether this is a strong enough match to warrant tailoring application materials.\n\n"
    "CRITICAL CONTEXT — read the candidate profile carefully. This candidate is a FULL-STACK "
    "software engineer with deep security expertise, NOT a security-only specialist. They have:\n"
    "- A CS degree in software engineering and professional web development experience\n"
    "- Daily, production-grade use of AI coding tools (Claude Code, Cursor, Copilot, Codex, Gemini CLI, etc.)\n"
    "- Extensive React, TypeScript, JavaScript, Python, and Java experience across personal and professional projects\n"
    "- Deep integration experience (SAML, REST APIs, multi-system dashboards, data connectors)\n"
    "- A flagship project (Coraline) built on React + Python + AWS + Postgres\n"
    "Security is a strength, not a boundary. Full-stack, backend, frontend, integration, platform, "
    "AI-native, and DevOps roles are ALL within scope.\n\n"
    "Evaluation criteria:\n"
    "- Requirement coverage: do candidate skills map to core JD requirements?\n"
    "- Experience relevance: does baseline evidence support the role?\n"
    "- Experience band (HARD GATE — most common reason to reject):\n"
    "    * Ideal: mid-level IC, 2-3 years total professional experience\n"
    "    * Acceptable: 3-5 years when the role is otherwise a strong fit\n"
    "    * REJECT: JD states a minimum of 6+ years required, regardless of title\n"
    "    * REJECT: staff / principal / lead-with-management-scope / manager / director titles\n"
    "    * Parse the JD for explicit experience floors — e.g. '5+ years', 'minimum 7 years of X', "
    "'senior-level: typically 8+ years of...'. These are hard signals and override the title. "
    "A 'Senior Engineer' that only requires 3-4 years can still pass; a 'Software Engineer' that "
    "requires 8+ years must fail. When the JD gives a range ('5-8 years'), use the floor.\n"
    "    * When no explicit floor is stated, infer from title: bare 'senior' is acceptable, "
    "bare 'staff' / 'principal' / 'lead' is reject.\n"
    "- Domain fit: software engineering, full-stack, backend, frontend, security, cloud, devops, "
    "platform, AI/ML, integration, data engineering — reject ONLY if the role is entirely outside "
    "software engineering (e.g., pure sales, marketing, hardware, mechanical engineering)\n"
    "- Red flags: onsite-only disguised as remote, clearance required, etc.\n\n"
    "Return ONLY valid JSON:\n"
    '{ "pass": true/false, "reason": "1-2 sentences", "confidence": 0.0-1.0, '
    '"min_years_required": <integer or null — experience floor parsed from JD, null if not stated>, '
    '"top_matches": ["skill1", "skill2"], "gaps": ["gap1"] }'
)

def _load_profile_context() -> str:
    """Load profile context fresh from disk each time (files are small, no cache needed)."""
    parts = []
    soul_path = TAILORING_ROOT / "soul.md"
    if soul_path.exists():
        parts.append("=== CANDIDATE PROFILE (soul.md) ===\n" + soul_path.read_text(encoding="utf-8")[:6000])

    skills_path = TAILORING_ROOT / "skills.json"
    if skills_path.exists():
        try:
            skills = json.loads(skills_path.read_text(encoding="utf-8"))
            profile = skills.get("candidate_profile", {})
            parts.append(
                "=== TARGET ROLES ===\n" + ", ".join(profile.get("target_roles", []))
                + "\n\n=== POSITIONING ===\n" + profile.get("positioning_summary", "")
            )
            inventory = skills.get("skills_inventory", {})
            skill_names = []
            for cat in inventory.get("core_skills", []) + inventory.get("supporting_skills", []):
                skill_names.append(f"- {cat['name']}: {', '.join(cat.get('skills', []))}")
            if skill_names:
                parts.append("=== SKILLS ===\n" + "\n".join(skill_names))
        except Exception:
            pass

    return "\n\n".join(parts)


def _http_error_details(exc: Exception) -> str:
    message = str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            body = ""
        if body:
            compact = re.sub(r"\s+", " ", body)
            return f"{message}: {compact[:700]}"
    return message


def _fetch_llm_catalog(llm_runtime: dict, *, timeout: int = 5) -> tuple[list[dict], list[dict]]:
    api_key = llm_runtime.get("api_key", "")
    with _llm_urlopen(llm_runtime["models_url"], api_key, timeout=timeout) as resp:
        data = json.loads(resp.read())
    v1_models = data.get("data", []) or []

    manage_models: list[dict] = []
    if llm_runtime.get("manage_models"):
        try:
            # Ollama: /api/tags lists all pulled models (all are available on-demand).
            with _llm_urlopen(f"{llm_runtime['base_url']}/api/tags", api_key, timeout=timeout) as resp:
                manage_data = json.loads(resp.read())
            # Normalize to the shape _resolve_llm_model_id expects.
            for m in manage_data.get("models", []):
                name = m.get("name", m.get("model", "unknown"))
                # Detect embedding models by name convention.
                is_embed = "embed" in name.lower()
                manage_models.append({
                    "id": name,
                    "state": "loaded",  # Ollama loads on-demand; treat all as available
                    "type": "embeddings" if is_embed else "llm",
                    "size": m.get("size", 0),
                })
        except Exception:
            manage_models = []
    return v1_models, manage_models


def _resolve_llm_model_id(
    llm_runtime: dict,
    *,
    v1_models: list[dict] | None = None,
    manage_models: list[dict] | None = None,
) -> str | None:
    model_id = str(llm_runtime.get("selected_model") or "default").strip() or "default"
    manage_models = manage_models or []
    if llm_runtime.get("manage_models"):
        loaded = [
            str(item.get("id") or "").strip()
            for item in manage_models
            if str(item.get("state") or "").strip() == "loaded"
            and str(item.get("type") or "llm").strip().lower() != "embeddings"
        ]
        loaded = [item for item in loaded if item]
        if model_id != "default":
            if model_id in loaded:
                return model_id
            raise RuntimeError(f"Selected model '{model_id}' is not loaded. Load it in the UI and retry.")
        if loaded:
            return loaded[0]
        raise RuntimeError("No LLM model is loaded. Load one in the UI and retry.")

    if model_id != "default":
        return model_id
    v1_models = v1_models or []
    for item in v1_models:
        candidate = str(item.get("id") or "").strip()
        if candidate:
            return candidate
    return None


def _resolve_active_llm_runtime() -> tuple[dict, str]:
    llm_runtime = _resolve_llm_runtime()
    try:
        v1_models, manage_models = _fetch_llm_catalog(llm_runtime, timeout=3)
        model_id = _resolve_llm_model_id(
            llm_runtime,
            v1_models=v1_models,
            manage_models=manage_models,
        )
        if not model_id:
            raise RuntimeError("No LLM model available")
        return llm_runtime, model_id
    except Exception as exc:
        raise RuntimeError(f"LLM unavailable: {_http_error_details(exc)}") from exc


def _coerce_confidence(value: object, default: float = 0.5) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _qa_llm_review_reconcile_stale_items(conn: sqlite3.Connection) -> int:
    """A restarted server should resume unfinished QA work instead of losing it."""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """
        UPDATE qa_llm_review_items
        SET status='queued',
            started_at = COALESCE(started_at, queued_at),
            reason = CASE
                WHEN COALESCE(reason, '') = '' THEN 'Resumed after server restart.'
                ELSE reason
            END
        WHERE status='reviewing'
        """
    )
    unfinished = conn.execute(
        "SELECT COUNT(*) FROM qa_llm_review_items WHERE status IN ('queued', 'reviewing')"
    ).fetchone()[0]
    if not unfinished:
        conn.execute(
            """
            UPDATE qa_llm_review_batches
            SET ended_at = COALESCE(ended_at, ?)
            WHERE ended_at IS NULL
            """,
            (now,),
        )
    return max(int(cur.rowcount or 0), 0)


def _qa_llm_review_get_batch(conn: sqlite3.Connection, batch_id: int | None = None) -> sqlite3.Row | None:
    if batch_id is not None:
        return conn.execute(
            """
            SELECT id, started_at, ended_at, resolved_model, trigger_source,
                   queued_count, report_json, report_generated_at
            FROM qa_llm_review_batches
            WHERE id = ?
            """,
            (int(batch_id),),
        ).fetchone()
    row = conn.execute(
        """
        SELECT id, started_at, ended_at, resolved_model, trigger_source,
               queued_count, report_json, report_generated_at
        FROM qa_llm_review_batches
        WHERE ended_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if row:
        return row
    return conn.execute(
        """
        SELECT id, started_at, ended_at, resolved_model, trigger_source,
               queued_count, report_json, report_generated_at
        FROM qa_llm_review_batches
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()


def _qa_llm_review_fetch_items(conn: sqlite3.Connection, batch_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, batch_id, job_id, title, status, queued_at, started_at, completed_at,
               reason, confidence, top_matches, gaps, polished, polished_with_llm
        FROM qa_llm_review_items
        WHERE batch_id = ?
        ORDER BY id ASC
        """,
        (int(batch_id),),
    ).fetchall()
    items: list[dict] = []
    for row in rows:
        items.append(
            {
                "id": int(row["id"]),
                "job_id": int(row["job_id"]),
                "title": row["title"],
                "status": row["status"],
                "queued_at": row["queued_at"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "reason": row["reason"] or "",
                "confidence": row["confidence"],
                "top_matches": list(json.loads(row["top_matches"] or "[]")),
                "gaps": list(json.loads(row["gaps"] or "[]")),
                "polished": bool(row["polished"]),
                "polished_with_llm": bool(row["polished_with_llm"]),
            }
        )
    return items


def _qa_llm_review_counts(items: list[dict]) -> dict:
    counts = {
        "total": len(items),
        "queued": 0,
        "reviewing": 0,
        "completed": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
        "cancelled": 0,
    }
    for item in items:
        status = item.get("status")
        if status == "queued":
            counts["queued"] += 1
        elif status == "reviewing":
            counts["reviewing"] += 1
        elif status == "pass":
            counts["completed"] += 1
            counts["passed"] += 1
        elif status == "fail":
            counts["completed"] += 1
            counts["failed"] += 1
        elif status == "skipped":
            counts["completed"] += 1
            counts["skipped"] += 1
        elif status == "error":
            counts["completed"] += 1
            counts["errors"] += 1
        elif status == "cancelled":
            counts["completed"] += 1
            counts["cancelled"] += 1
    return counts


def _parse_json_list(value: object) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _qa_llm_review_build_report(conn: sqlite3.Connection, batch_id: int) -> dict:
    batch = _qa_llm_review_get_batch(conn, batch_id=batch_id)
    if not batch:
        return {}
    rows = conn.execute(
        """
        SELECT i.id, i.job_id, i.title, i.status, i.queued_at, i.started_at, i.completed_at,
               i.reason, i.confidence, i.top_matches, i.gaps, i.polished, i.polished_with_llm,
               r.url, r.company, r.board, r.source, r.run_id, r.decision, r.created_at
        FROM qa_llm_review_items i
        LEFT JOIN results r ON r.id = i.job_id
        WHERE i.batch_id = ?
        ORDER BY i.id ASC
        """,
        (int(batch_id),),
    ).fetchall()
    items: list[dict] = []
    scrape_run_ids: set[str] = set()
    for row in rows:
        run_id = str(row["run_id"] or "").strip()
        if run_id:
            scrape_run_ids.add(run_id)
        items.append(
            {
                "review_item_id": int(row["id"]),
                "job_id": int(row["job_id"]),
                "title": row["title"] or "",
                "company": row["company"] or "",
                "url": row["url"] or "",
                "board": row["board"] or "",
                "source": row["source"] or "",
                "scrape_run_id": run_id,
                "job_created_at": row["created_at"],
                "queued_at": row["queued_at"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "status": row["status"],
                "review_status": row["status"],
                "final_decision": row["decision"],
                "reason": row["reason"] or "",
                "confidence": row["confidence"],
                "top_matches": _parse_json_list(row["top_matches"]),
                "gaps": _parse_json_list(row["gaps"]),
                "polished": bool(row["polished"]),
                "polished_with_llm": bool(row["polished_with_llm"]),
            }
        )
    summary = _qa_llm_review_counts(items)
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "batch_id": int(batch["id"]),
        "started_at": batch["started_at"],
        "ended_at": batch["ended_at"],
        "generated_at": generated_at,
        "resolved_model": batch["resolved_model"],
        "trigger_source": batch["trigger_source"],
        "queued_count": int(batch["queued_count"] or len(items)),
        "summary": summary,
        "scrape_run_ids": sorted(scrape_run_ids),
        "items": items,
    }


def _qa_llm_review_save_report(conn: sqlite3.Connection, batch_id: int) -> dict:
    report = _qa_llm_review_build_report(conn, batch_id)
    if not report:
        return {}
    conn.execute(
        """
        UPDATE qa_llm_review_batches
        SET report_json = ?,
            report_generated_at = ?
        WHERE id = ?
        """,
        (json.dumps(report, sort_keys=True), report["generated_at"], int(batch_id)),
    )
    return report


def _qa_llm_review_report_from_batch(batch: sqlite3.Row) -> dict | None:
    raw = batch["report_json"] if "report_json" in batch.keys() else None
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _qa_llm_review_snapshot() -> dict:
    _sync_app_state()
    with _app._QA_LLM_REVIEW_LOCK:
        thread = _app._QA_LLM_REVIEW_RUNNER.get("thread")
        if thread is not None and not thread.is_alive():
            _app._QA_LLM_REVIEW_RUNNER["thread"] = None
            thread = None
    conn = get_db_write()
    try:
        if thread is None:
            _qa_llm_review_reconcile_stale_items(conn)
        batch = _qa_llm_review_get_batch(conn)
        if not batch:
            return {
                "running": False,
                "batch_id": 0,
                "started_at": None,
                "ended_at": None,
                "resolved_model": None,
                "active_job": None,
                "items": [],
                "summary": _qa_llm_review_counts([]),
            }
        items = _qa_llm_review_fetch_items(conn, int(batch["id"]))
        counts = _qa_llm_review_counts(items)
        active_job = next((dict(item) for item in items if item.get("status") == "reviewing"), None)
        return {
            "running": bool(thread is not None or counts["queued"] > 0 or counts["reviewing"] > 0),
            "batch_id": int(batch["id"]),
            "started_at": batch["started_at"],
            "ended_at": batch["ended_at"],
            "resolved_model": batch["resolved_model"],
            "trigger_source": batch["trigger_source"],
            "report_generated_at": batch["report_generated_at"],
            "active_job": active_job,
            "items": items,
            "summary": counts,
        }
    finally:
        conn.commit()
        conn.close()


def _qa_llm_review_mark_pending_as_error(reason: str, *, batch_id: int | None = None) -> None:
    completed_at = datetime.now(timezone.utc).isoformat()
    conn = get_db_write()
    try:
        batch = _qa_llm_review_get_batch(conn, batch_id=batch_id)
        if not batch:
            return
        conn.execute(
            """
            UPDATE qa_llm_review_items
            SET status='error',
                reason=?,
                completed_at=?,
                started_at = COALESCE(started_at, queued_at)
            WHERE batch_id=? AND status IN ('queued', 'reviewing')
            """,
            (reason, completed_at, int(batch["id"])),
        )
        conn.execute(
            "UPDATE qa_llm_review_batches SET ended_at = COALESCE(ended_at, ?) WHERE id = ?",
            (completed_at, int(batch["id"])),
        )
        _qa_llm_review_save_report(conn, int(batch["id"]))
        conn.commit()
    finally:
        conn.close()


def _ensure_qa_llm_review_worker_running() -> None:
    with _app._QA_LLM_REVIEW_LOCK:
        thread = _app._QA_LLM_REVIEW_RUNNER.get("thread")
        if thread is not None and thread.is_alive():
            return
    conn = get_db_write()
    try:
        _qa_llm_review_reconcile_stale_items(conn)
        batch = conn.execute(
            """
            SELECT b.id
            FROM qa_llm_review_batches b
            WHERE EXISTS (
                SELECT 1
                FROM qa_llm_review_items i
                WHERE i.batch_id = b.id AND i.status IN ('queued', 'reviewing')
            )
            ORDER BY b.id DESC
            LIMIT 1
            """
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    if not batch:
        return
    worker = threading.Thread(
        target=_qa_llm_review_worker,
        kwargs={"batch_id": int(batch["id"])},
        daemon=True,
        name="qa-llm-review",
    )
    with _app._QA_LLM_REVIEW_LOCK:
        thread = _app._QA_LLM_REVIEW_RUNNER.get("thread")
        if thread is not None and thread.is_alive():
            return
        _app._QA_LLM_REVIEW_RUNNER["thread"] = worker
    worker.start()


def _run_single_qa_llm_review(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    llm_runtime: dict,
    model_id: str,
    profile_ctx: str,
) -> dict:
    row = conn.execute(
        "SELECT id, title, url, snippet, jd_text, salary_text, salary_k, decision FROM results WHERE id = ?",
        (job_id,),
    ).fetchone()
    if not row:
        return {"status": "skipped", "reason": "job not found"}
    if not _job_is_qa_pending(row["decision"]):
        return {
            "status": "skipped",
            "reason": f"job no longer pending QA ({_normalize_decision(row['decision']) or 'unknown'})",
        }

    jd_text = row["jd_text"] or row["snippet"] or ""
    if len(jd_text.strip()) < 30:
        return {"status": "skipped", "reason": "insufficient JD text"}

    user_msg = (
        f"Title: {row['title'] or 'Unknown'}\n"
        f"URL: {row['url'] or 'N/A'}\n\n"
        f"Job Description:\n{jd_text[:12000]}"
    )

    try:
        verdict = _shared_chat_expect_json(
            _QA_LLM_REVIEW_SYSTEM + "\n\n" + profile_ctx,
            user_msg,
            llm_runtime=llm_runtime,
            model_id=model_id,
            max_tokens=1800,
            temperature=0.2,
            trace={"phase": "dashboard_qa_llm_review", "response_parse_kind": "json"},
        )

        passed = bool(verdict.get("pass", False))
        salary_verdict = _salary_policy_for_job(
            salary_text=row["salary_text"] or "",
            salary_k=row["salary_k"],
        )
        if salary_verdict.hard_reject:
            passed = False
        new_decision = "qa_approved" if passed else "qa_rejected"
        req_summary = row["snippet"]
        approved_jd_text = row["jd_text"]
        polished_with_llm = False
        if passed:
            req_summary, approved_jd_text, polished_with_llm = _polish_job_description(
                jd_text,
                row["title"],
                row["url"],
                llm_runtime,
                model_id,
            )
            conn.execute(
                "UPDATE jobs SET status=?, snippet=?, approved_jd_text=? WHERE id=?",
                (
                    new_decision,
                    (req_summary or row["snippet"] or "").strip() or None,
                    (approved_jd_text or jd_text or "").strip() or None,
                    job_id,
                ),
            )
        else:
            conn.execute(
                "UPDATE jobs SET status=? WHERE id=?",
                (new_decision, job_id),
            )
        return {
            "status": "pass" if passed else "fail",
            "reason": salary_verdict.reason if salary_verdict.hard_reject else str(verdict.get("reason") or ""),
            "confidence": _coerce_confidence(verdict.get("confidence")),
            "top_matches": list(verdict.get("top_matches") or []),
            "gaps": list(verdict.get("gaps") or []),
            "polished": bool(passed and approved_jd_text),
            "polished_with_llm": bool(passed and polished_with_llm),
        }
    except Exception as exc:
        conn.rollback()
        return {"status": "error", "reason": _http_error_details(exc)}


def _qa_llm_review_worker(*, batch_id: int) -> None:
    try:
        llm_runtime, model_id = _resolve_active_llm_runtime()
    except Exception as exc:
        _qa_llm_review_mark_pending_as_error(str(exc), batch_id=batch_id)
        with _app._QA_LLM_REVIEW_LOCK:
            _app._QA_LLM_REVIEW_RUNNER["thread"] = None
        return

    conn = get_db_write()
    try:
        _qa_llm_review_reconcile_stale_items(conn)
        conn.execute(
            """
            UPDATE qa_llm_review_batches
            SET started_at = COALESCE(started_at, ?),
                resolved_model = ?
            WHERE id = ?
            """,
            (datetime.now(timezone.utc).isoformat(), model_id, int(batch_id)),
        )
        conn.commit()
        _ensure_results_approved_jd_column(conn)
        profile_ctx = _load_profile_context()
        while True:
            next_item = conn.execute(
                """
                SELECT id, job_id
                FROM qa_llm_review_items
                WHERE batch_id = ? AND status IN ('queued', 'reviewing')
                ORDER BY CASE status WHEN 'reviewing' THEN 0 ELSE 1 END, id ASC
                LIMIT 1
                """,
                (int(batch_id),),
            ).fetchone()
            if next_item is None:
                conn.execute(
                    "UPDATE qa_llm_review_batches SET ended_at = COALESCE(ended_at, ?) WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), int(batch_id)),
                )
                _qa_llm_review_save_report(conn, int(batch_id))
                conn.commit()
                break
            started_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE qa_llm_review_items
                SET status='reviewing',
                    started_at = COALESCE(started_at, ?)
                WHERE id = ?
                """,
                (started_at, int(next_item["id"])),
            )
            conn.commit()
            job_id = int(next_item["job_id"])

            result = _run_single_qa_llm_review(
                conn,
                job_id,
                llm_runtime=llm_runtime,
                model_id=model_id,
                profile_ctx=profile_ctx,
            )
            conn.commit()

            completed_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE qa_llm_review_items
                SET status=?,
                    reason=?,
                    confidence=?,
                    top_matches=?,
                    gaps=?,
                    polished=?,
                    polished_with_llm=?,
                    completed_at=?
                WHERE id = ?
                """,
                (
                    result.get("status"),
                    result.get("reason") or "",
                    result.get("confidence"),
                    json.dumps(list(result.get("top_matches") or [])),
                    json.dumps(list(result.get("gaps") or [])),
                    1 if result.get("polished") else 0,
                    1 if result.get("polished_with_llm") else 0,
                    completed_at,
                    int(next_item["id"]),
                ),
            )
            conn.commit()
    finally:
        conn.close()
        with _app._QA_LLM_REVIEW_LOCK:
            _app._QA_LLM_REVIEW_RUNNER["thread"] = None


def tailoring_qa_llm_review_cancel():
    _sync_app_state()
    conn = get_db_write()
    try:
        batch = _qa_llm_review_get_batch(conn)
        if not batch:
            return {"ok": True, "cancelled": 0}
        cur = conn.execute(
            """
            UPDATE qa_llm_review_items
            SET status='cancelled',
                completed_at = COALESCE(completed_at, ?)
            WHERE batch_id = ? AND status = 'queued'
            """,
            (datetime.now(timezone.utc).isoformat(), int(batch["id"])),
        )
        conn.commit()
        cancelled = max(int(cur.rowcount or 0), 0)
        open_count = conn.execute(
            "SELECT COUNT(*) FROM qa_llm_review_items WHERE batch_id = ? AND status IN ('queued', 'reviewing')",
            (int(batch["id"]),),
        ).fetchone()[0]
        if not open_count:
            conn.execute(
                "UPDATE qa_llm_review_batches SET ended_at = COALESCE(ended_at, ?) WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), int(batch["id"])),
            )
            _qa_llm_review_save_report(conn, int(batch["id"]))
            conn.commit()
    finally:
        conn.close()
    return {"ok": True, "cancelled": cancelled}


def tailoring_qa_llm_review_status():
    _sync_app_state()
    _ensure_qa_llm_review_worker_running()
    return _qa_llm_review_snapshot()


def tailoring_qa_auto_review_status():
    _sync_app_state()
    from services import auto_qa_review
    return auto_qa_review.status()


def tailoring_qa_llm_review_reports(limit: int = Query(20, ge=1, le=200)):
    _sync_app_state()
    conn = get_db_write()
    try:
        rows = conn.execute(
            """
            SELECT id, started_at, ended_at, resolved_model, trigger_source,
                   queued_count, report_json, report_generated_at
            FROM qa_llm_review_batches
            WHERE ended_at IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        items = []
        for row in rows:
            report = _qa_llm_review_report_from_batch(row)
            if report is None:
                report = _qa_llm_review_save_report(conn, int(row["id"]))
            summary = (report or {}).get("summary") or {}
            items.append(
                {
                    "batch_id": int(row["id"]),
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "resolved_model": row["resolved_model"],
                    "trigger_source": row["trigger_source"],
                    "queued_count": int(row["queued_count"] or summary.get("total") or 0),
                    "report_generated_at": (report or {}).get("generated_at") or row["report_generated_at"],
                    "summary": summary,
                    "scrape_run_ids": (report or {}).get("scrape_run_ids") or [],
                }
            )
        conn.commit()
        return {"items": items}
    finally:
        conn.close()


def tailoring_qa_llm_review_report(batch_id: int):
    _sync_app_state()
    conn = get_db_write()
    try:
        batch = _qa_llm_review_get_batch(conn, batch_id=batch_id)
        if not batch:
            return JSONResponse({"error": "Report not found"}, 404)
        report = _qa_llm_review_report_from_batch(batch)
        if report is None and batch["ended_at"] is not None:
            report = _qa_llm_review_save_report(conn, int(batch_id))
            conn.commit()
        if report is None:
            report = _qa_llm_review_build_report(conn, int(batch_id))
        return {"report": report}
    finally:
        conn.close()


def tailoring_qa_llm_review(payload: dict = Body(...)):
    _sync_app_state()
    job_ids = payload.get("job_ids") or []
    if not job_ids:
        return JSONResponse({"ok": False, "error": "job_ids required"}, 400)
    trigger_source = str(payload.get("trigger_source") or "manual").strip()[:80] or "manual"
    unique_ids: list[int] = []
    for raw_job_id in job_ids:
        if not isinstance(raw_job_id, int):
            return JSONResponse({"ok": False, "error": f"Invalid job_id: {raw_job_id}"}, 400)
        if raw_job_id not in unique_ids:
            unique_ids.append(raw_job_id)

    conn = get_db()
    try:
        placeholders = ",".join("?" for _ in unique_ids)
        rows = conn.execute(
            f"SELECT id, title FROM results WHERE id IN ({placeholders})",
            tuple(unique_ids),
        ).fetchall()
    finally:
        conn.close()
    titles_by_id = {int(row["id"]): row["title"] for row in rows}

    duplicates: list[int] = []
    missing: list[int] = []
    added = 0
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_write()
    try:
        _qa_llm_review_reconcile_stale_items(conn)
        batch = conn.execute(
            """
            SELECT b.id
            FROM qa_llm_review_batches b
            WHERE EXISTS (
                SELECT 1
                FROM qa_llm_review_items i
                WHERE i.batch_id = b.id AND i.status IN ('queued', 'reviewing')
            )
            ORDER BY b.id DESC
            LIMIT 1
            """
        ).fetchone()
        if batch is None:
            cur = conn.execute(
                """
                INSERT INTO qa_llm_review_batches (
                    started_at, ended_at, resolved_model, trigger_source, queued_count,
                    report_json, report_generated_at
                ) VALUES (?, NULL, NULL, ?, 0, NULL, NULL)
                """,
                (now, trigger_source),
            )
            batch_id = int(cur.lastrowid)
        else:
            batch_id = int(batch["id"])
        existing_ids = {
            int(row["job_id"])
            for row in conn.execute(
                "SELECT job_id FROM qa_llm_review_items WHERE status IN ('queued', 'reviewing')"
            ).fetchall()
        }
        for job_id in unique_ids:
            if job_id not in titles_by_id:
                missing.append(job_id)
                continue
            if job_id in existing_ids:
                duplicates.append(job_id)
                continue
            conn.execute(
                """
                INSERT INTO qa_llm_review_items (
                    batch_id, job_id, title, status, queued_at, started_at, completed_at,
                    reason, confidence, top_matches, gaps, polished, polished_with_llm
                ) VALUES (?, ?, ?, 'queued', ?, NULL, NULL, '', NULL, '[]', '[]', 0, 0)
                """,
                (batch_id, job_id, titles_by_id.get(job_id), now),
            )
            existing_ids.add(job_id)
            added += 1
        conn.execute(
            """
            UPDATE qa_llm_review_batches
            SET queued_count = (
                SELECT COUNT(*) FROM qa_llm_review_items WHERE batch_id = ?
            )
            WHERE id = ?
            """,
            (batch_id, batch_id),
        )
        conn.commit()
    finally:
        conn.close()

    if added > 0:
        _ensure_qa_llm_review_worker_running()

    return {
        "ok": True,
        "queued": added,
        "duplicates": duplicates,
        "missing": missing,
        "runner": _qa_llm_review_snapshot(),
    }


def tailoring_qa_reset_approved():
    _sync_app_state()
    conn = get_db_write()
    try:
        from services.audit import log_state_change
        rows = conn.execute("SELECT id, url FROM results WHERE decision='qa_approved'").fetchall()
        job_ids = [int(row["id"]) for row in rows]
        if job_ids:
            _cancel_tailoring_queue_items(conn=conn, job_ids=job_ids, statuses=("queued",), reason="Returned to QA.")
            _stop_active_tailoring_job(job_ids, "Job returned to QA.")
            _set_ready_bucket_for_job_ids_in_conn(conn, job_ids, _DEFAULT_READY_BUCKET)
        conn.execute("UPDATE jobs SET status='qa_pending' WHERE status='qa_approved'")
        for row in rows:
            log_state_change(conn, job_id=row["id"], job_url=row["url"],
                             old_state="qa_approved", new_state="qa_pending",
                             action="qa_reset_approved")
        conn.commit()
        return {"ok": True, "reset": len(rows)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes — API: QA Undo / Rollback
# ---------------------------------------------------------------------------

def tailoring_qa_undo_approve(payload: dict = Body(...)):
    """Undo QA approval — revert qa_approved back to qa_pending."""
    _sync_app_state()
    job_ids = payload.get("job_ids") or []
    if not job_ids:
        return JSONResponse({"ok": False, "error": "job_ids required"}, 400)

    conn = get_db_write()
    try:
        from services.audit import log_state_change
        _cancel_tailoring_queue_items(conn=conn, job_ids=[int(jid) for jid in job_ids], statuses=("queued",), reason="Returned to QA.")
        _stop_active_tailoring_job([int(jid) for jid in job_ids], "Job returned to QA.")
        _set_ready_bucket_for_job_ids_in_conn(conn, [int(jid) for jid in job_ids], _DEFAULT_READY_BUCKET)
        reverted = 0
        for jid in job_ids:
            row = conn.execute(
                "SELECT id, url, decision FROM results WHERE id=? AND decision='qa_approved'",
                (jid,),
            ).fetchone()
            if not row:
                continue
            conn.execute("UPDATE jobs SET status='qa_pending' WHERE id=?", (jid,))
            log_state_change(conn, job_id=jid, job_url=row["url"],
                             old_state="qa_approved", new_state="qa_pending",
                             action="qa_undo_approve")
            reverted += 1
        conn.commit()
        return {"ok": True, "reverted": reverted}
    finally:
        conn.close()


def tailoring_qa_undo_reject(payload: dict = Body(...)):
    """Undo QA rejection — revert qa_rejected back to qa_pending."""
    _sync_app_state()
    job_ids = payload.get("job_ids") or []
    if not job_ids:
        return JSONResponse({"ok": False, "error": "job_ids required"}, 400)

    conn = get_db_write()
    try:
        from services.audit import log_state_change
        reverted = 0
        for jid in job_ids:
            row = conn.execute(
                "SELECT id, url, decision FROM results WHERE id=? AND decision='qa_rejected'",
                (jid,),
            ).fetchone()
            if not row:
                continue
            conn.execute("UPDATE jobs SET status='qa_pending' WHERE id=?", (jid,))
            log_state_change(conn, job_id=jid, job_url=row["url"],
                             old_state="qa_rejected", new_state="qa_pending",
                             action="qa_undo_reject")
            reverted += 1
        conn.commit()
        return {"ok": True, "reverted": reverted}
    finally:
        conn.close()


def tailoring_qa_rollback(payload: dict = Body(...)):
    """Roll back tailored jobs to QA — resets decision to qa_pending without deleting output."""
    _sync_app_state()
    job_ids = payload.get("job_ids") or []
    if not job_ids:
        return JSONResponse({"ok": False, "error": "job_ids required"}, 400)

    conn = get_db_write()
    try:
        from services.audit import log_state_change
        _cancel_tailoring_queue_items(conn=conn, job_ids=[int(jid) for jid in job_ids], statuses=("queued",), reason="Returned to QA.")
        _stop_active_tailoring_job([int(jid) for jid in job_ids], "Job returned to QA.")
        _set_ready_bucket_for_job_ids_in_conn(conn, [int(jid) for jid in job_ids], _DEFAULT_READY_BUCKET)
        rolled_back = 0
        for jid in job_ids:
            row = conn.execute(
                "SELECT id, url, decision FROM results WHERE id=?",
                (jid,),
            ).fetchone()
            if not row:
                continue
            old = _normalize_decision(row["decision"])
            if old == "qa_pending":
                continue
            conn.execute("UPDATE jobs SET status='qa_pending' WHERE id=?", (jid,))
            log_state_change(conn, job_id=jid, job_url=row["url"],
                             old_state=old, new_state="qa_pending",
                             action="rollback_to_qa")
            rolled_back += 1
        conn.commit()
        return {"ok": True, "rolled_back": rolled_back}
    finally:
        conn.close()



def state_log(job_id: int | None = Query(None), limit: int = Query(50, ge=1, le=500)):
    """Return recent job state audit log entries."""
    conn = get_db()
    try:
        if job_id is not None:
            rows = conn.execute(
                "SELECT * FROM job_state_log WHERE job_id=? ORDER BY created_at DESC LIMIT ?",
                (job_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM job_state_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return {"entries": [dict(r) for r in rows]}
    except Exception:
        return {"entries": []}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes — API: Package Chat
# ---------------------------------------------------------------------------

def package_chat_send(slug: str, payload: dict = Body(...)):
    from services.package_chat import send_chat
    message = (payload.get("message") or "").strip()
    if not message:
        return JSONResponse({"ok": False, "error": "message is required"}, 400)
    doc_focus = payload.get("doc_focus") or None
    # Resolve current LLM runtime so package chat uses the active provider,
    # URL, and model — not whatever env vars were set at import time.
    llm_runtime, model_id = _resolve_active_llm_runtime()
    return send_chat(slug, message, doc_focus, model=model_id, llm_runtime=llm_runtime)


def package_chat_history(slug: str):
    from services.package_chat import load_history
    return {"messages": load_history(slug)}


def package_chat_clear(slug: str):
    from services.package_chat import clear_history
    cleared = clear_history(slug)
    return {"ok": True, "cleared": cleared}


# ---------------------------------------------------------------------------
# Routes — API: Runtime controls
# ---------------------------------------------------------------------------

def _llm_urlopen(url: str, api_key: str = "", timeout: int = 5, data: bytes | None = None, method: str | None = None):
    """Open a URL with optional Bearer auth."""
    req = urllib.request.Request(url, data=data, method=method)
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    if data:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=timeout)


def llm_status():
    _sync_app_state()
    """Check whether the local LLM server is reachable."""
    controls = _load_runtime_controls()
    llm_runtime = _resolve_llm_runtime(controls)
    if not controls["llm_enabled"]:
        return {
            "enabled": False,
            "available": False,
            "models": [],
            "url": llm_runtime["base_url"],
            "provider": llm_runtime["provider"],
            "selected_model": llm_runtime["selected_model"],
            "capabilities": {"manage_models": llm_runtime["manage_models"]},
            "state": "disabled",
        }
    try:
        with _llm_urlopen(llm_runtime["models_url"], llm_runtime.get("api_key", ""), timeout=2) as resp:
            data = json.loads(resp.read())
        models = [m["id"] for m in data.get("data", [])]
        return {
            "enabled": True,
            "available": True,
            "models": models,
            "url": llm_runtime["base_url"],
            "provider": llm_runtime["provider"],
            "selected_model": llm_runtime["selected_model"],
            "capabilities": {"manage_models": llm_runtime["manage_models"]},
            "state": "online",
        }
    except Exception:
        return {
            "enabled": True,
            "available": False,
            "models": [],
            "url": llm_runtime["base_url"],
            "provider": llm_runtime["provider"],
            "selected_model": llm_runtime["selected_model"],
            "capabilities": {"manage_models": llm_runtime["manage_models"]},
            "state": "offline",
        }


def llm_models(provider: str | None = None):
    _sync_app_state()
    """Return models from the configured provider or an explicit provider override."""
    controls = _load_runtime_controls()
    provider_override = (provider or "").strip().lower()
    if provider_override:
        from providers import PROVIDERS
        controls = dict(controls)
        if provider_override in PROVIDERS:
            controls["llm_provider"] = provider_override
            if provider_override != "custom":
                controls["llm_base_url"] = PROVIDERS[provider_override]["base_url"]
    llm_runtime = _resolve_llm_runtime(controls)
    api_key = llm_runtime.get("api_key", "")
    try:
        models: list[dict] = []
        if llm_runtime["manage_models"]:
            # Ollama: /api/tags returns all pulled models.
            with _llm_urlopen(f"{llm_runtime['base_url']}/api/tags", api_key, timeout=5) as resp:
                data = json.loads(resp.read())
            selected = llm_runtime["selected_model"]
            for idx, m in enumerate(data.get("models", [])):
                model_name = m.get("name", m.get("model", "unknown"))
                is_selected = model_name == selected
                models.append({
                    "id": model_name,
                    "state": "loaded" if is_selected else "available",
                    "size": m.get("size", 0),
                })
        else:
            with _llm_urlopen(llm_runtime["models_url"], api_key, timeout=5) as resp:
                data = json.loads(resp.read())
            selected = llm_runtime["selected_model"]
            raw_models = data.get("data", [])
            for idx, item in enumerate(raw_models):
                model_id = item["id"]
                is_selected = model_id == selected
                models.append({"id": model_id, "state": "loaded" if is_selected else "available"})
        return {
            "provider": llm_runtime["provider"],
            "selected_model": llm_runtime["selected_model"],
            "capabilities": {"manage_models": llm_runtime["manage_models"]},
            "models": models,
        }
    except Exception as e:
        return JSONResponse({"error": f"LLM unreachable: {e}"}, 503)


def llm_select_model(payload: dict = Body(...)):
    _sync_app_state()
    """Select a model for this app. Ollama loads on-demand — just persist the selection."""
    identifier = payload.get("identifier")
    if not identifier:
        return JSONResponse({"ok": False, "error": "identifier required"}, 400)
    _save_runtime_controls({"llm_model": identifier})
    return {"ok": True, "model": identifier}


def llm_deselect_model(payload: dict = Body(...)):
    _sync_app_state()
    """Clear model selection for this app. Does NOT unload from the server."""
    identifier = payload.get("identifier")
    if not identifier:
        return JSONResponse({"ok": False, "error": "identifier required"}, 400)
    controls = _load_runtime_controls()
    llm_runtime = _resolve_llm_runtime(controls)
    current_model = llm_runtime["selected_model"]
    if current_model == identifier:
        _save_runtime_controls({"llm_model": ""})
    return {"ok": True, "model": identifier}


# ---------------------------------------------------------------------------
# Routes — API: LLM Providers
# ---------------------------------------------------------------------------

def llm_providers():
    """List all supported providers with key status and active indicator."""
    from providers import PROVIDERS
    from services.llm_keys import get_masked_key

    controls = _load_runtime_controls()
    active_provider = str(controls.get("llm_provider") or "ollama").strip().lower()
    # Normalize legacy value.
    if active_provider not in PROVIDERS:
        active_provider = "ollama"

    result = []
    for pid, pdef in PROVIDERS.items():
        masked = get_masked_key(pid)
        result.append({
            "id": pid,
            "label": pdef["label"],
            "base_url": pdef["base_url"],
            "auth": pdef["auth"],
            "notes": pdef["notes"],
            "has_key": masked is not None,
            "masked_key": masked,
            "active": pid == active_provider,
        })
    return {"providers": result, "active_provider": active_provider}


def llm_set_provider_key(payload: dict = Body(...)):
    """Save or clear an API key for a provider."""
    from providers import PROVIDERS
    from services.llm_keys import save_key, get_masked_key

    provider = str(payload.get("provider", "")).strip().lower()
    key = str(payload.get("key", "")).strip()
    if provider not in PROVIDERS:
        return JSONResponse({"ok": False, "error": f"Unknown provider: {provider}"}, 400)
    save_key(provider, key)
    return {"ok": True, "has_key": bool(key), "masked_key": get_masked_key(provider)}


def llm_activate_provider(payload: dict = Body(...)):
    """Set the active LLM provider (persists to runtime_controls.json)."""
    from providers import PROVIDERS

    provider = str(payload.get("provider", "")).strip().lower()
    if provider not in PROVIDERS:
        return JSONResponse({"ok": False, "error": f"Unknown provider: {provider}"}, 400)

    updates = {"llm_provider": provider}
    # Set the base URL from registry for all known providers.
    if provider == "ollama":
        updates["llm_base_url"] = PROVIDERS["ollama"]["base_url"]
    elif provider == "custom":
        base_url = str(payload.get("base_url", "")).strip()
        if base_url:
            updates["llm_base_url"] = base_url
    # Preserve model selection — user can change it separately.
    # Only clear if explicitly requested via payload.
    if "model" in payload:
        updates["llm_model"] = str(payload["model"]).strip() or ""

    _save_runtime_controls(updates)
    return {"ok": True, "provider": provider}


def llm_test_provider(payload: dict = Body(...)):
    """Test connection to a provider by hitting its /v1/models (or equivalent)."""
    from providers import PROVIDERS
    from services.llm_keys import get_key

    provider = str(payload.get("provider", "")).strip().lower()
    if provider not in PROVIDERS:
        return JSONResponse({"ok": False, "error": f"Unknown provider: {provider}"}, 400)

    pdef = PROVIDERS[provider]
    base_url = pdef["base_url"]
    if provider == "custom":
        controls = _load_runtime_controls()
        base_url = str(controls.get("llm_base_url") or base_url or "http://localhost:11434").rstrip("/")

    if provider == "gemini":
        models_url = f"{base_url}/models"
    else:
        models_url = f"{base_url}/v1/models"

    api_key = get_key(provider) or ""
    try:
        with _llm_urlopen(models_url, api_key, timeout=10) as resp:
            data = json.loads(resp.read())
        models = [m.get("id", "unknown") for m in data.get("data", [])]
        return {"ok": True, "models": models[:20], "total": len(models)}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 502)


# ---------------------------------------------------------------------------
# LLM infrastructure status
# ---------------------------------------------------------------------------


def llm_infrastructure():
    """Return process/service info for all LLM backends."""
    import shutil
    import subprocess

    services: list[dict] = []

    # --- Ollama ---
    ollama: dict = {
        "name": "Ollama",
        "port": 11434,
        "managed_by": "Homebrew service",
        "pid": None,
        "status": "offline",
        "disk_usage": None,
    }
    try:
        result = subprocess.run(
            ["pgrep", "-f", "ollama serve"], capture_output=True, text=True, timeout=3
        )
        pids = result.stdout.strip().split()
        if pids:
            ollama["pid"] = int(pids[0])
            ollama["status"] = "running"
    except Exception:
        pass
    ollama_models = Path.home() / ".ollama" / "models"
    if ollama_models.exists():
        try:
            result = subprocess.run(
                ["du", "-sk", str(ollama_models)], capture_output=True, text=True, timeout=5
            )
            kb = int(result.stdout.split()[0])
            ollama["disk_usage"] = kb * 1024
        except Exception:
            pass
    services.append(ollama)

    # --- Dashboard ---
    dashboard: dict = {
        "name": "Dashboard",
        "port": 8899,
        "managed_by": "launchd (com.jobscraper.dashboard)",
        "pid": os.getpid(),
        "status": "running",
    }
    services.append(dashboard)

    return {"services": services}


# ---------------------------------------------------------------------------
# LLM chat proxy (simple model testing)
# ---------------------------------------------------------------------------


def llm_chat(payload: dict = Body(...)):
    """Proxy a chat message to the active LLM provider. Stateless — no history."""
    _sync_app_state()
    controls = _load_runtime_controls()
    llm_runtime = _resolve_llm_runtime(controls)

    messages = payload.get("messages")
    if not messages or not isinstance(messages, list):
        return JSONResponse({"ok": False, "error": "messages required"}, 400)

    model = payload.get("model") or llm_runtime["selected_model"]
    if not model:
        return JSONResponse({"ok": False, "error": "No model selected"}, 400)

    max_tokens = int(payload.get("max_tokens", 1024))
    temperature = float(payload.get("temperature", 0.7))

    import urllib.request

    headers = {"Content-Type": "application/json"}
    api_key = llm_runtime.get("api_key", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        if llm_runtime.get("manage_models"):
            req_body = json.dumps({
                "model": model,
                "messages": messages,
                "stream": False,
                "think": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                },
            }).encode()
            chat_url = f"{llm_runtime['base_url'].rstrip('/')}/api/chat"
            req = urllib.request.Request(
                chat_url, data=req_body, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            message = data.get("message") or {}
            reply = message.get("content", "")
            usage = {
                "prompt_tokens": data.get("prompt_eval_count"),
                "completion_tokens": data.get("eval_count"),
                "total_duration": data.get("total_duration"),
            }
            return {
                "ok": True,
                "reply": reply,
                "model": data.get("model", model),
                "usage": usage,
            }

        req_body = json.dumps({
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode()
        req = urllib.request.Request(
            llm_runtime["chat_url"], data=req_body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        choice = (data.get("choices") or [{}])[0]
        reply = (choice.get("message") or {}).get("content", "")
        usage = data.get("usage", {})
        return {
            "ok": True,
            "reply": reply,
            "model": data.get("model", model),
            "usage": usage,
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 502)


# ---------------------------------------------------------------------------
# Routes — API: Model Catalog
# ---------------------------------------------------------------------------


def llm_catalog():
    """Return enriched model catalog with machine profile and fit scores."""
    _sync_app_state()
    from services.model_catalog import get_catalog

    controls = _load_runtime_controls()
    llm_runtime = _resolve_llm_runtime(controls)
    # Catalog only works against Ollama's native API
    if llm_runtime.get("manage_models"):
        base_url = llm_runtime["base_url"]
    else:
        base_url = "http://localhost:11434"

    catalog = get_catalog(base_url)
    catalog["selected_model"] = llm_runtime["selected_model"]
    return catalog


def llm_benchmark(payload: dict = Body(...)):
    """Run a micro-benchmark against an installed Ollama model."""
    _sync_app_state()
    from services.model_catalog import run_benchmark

    model_id = payload.get("model_id")
    if not model_id:
        return JSONResponse({"error": "model_id required"}, 400)

    provider = payload.get("provider", "ollama")

    controls = _load_runtime_controls()
    llm_runtime = _resolve_llm_runtime(controls)
    base_url = llm_runtime["base_url"]
    if not llm_runtime.get("manage_models"):
        base_url = "http://localhost:11434"

    return run_benchmark(model_id, base_url, provider=provider)


# ---------------------------------------------------------------------------
# Catch-all route to serve the React index.html for client-side routing
# ---------------------------------------------------------------------------
