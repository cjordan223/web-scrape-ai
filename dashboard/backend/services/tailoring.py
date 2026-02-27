"""Tailoring route implementations."""

from __future__ import annotations

# Reuse shared backend state/helpers from app module.
import app as _app
globals().update({k: v for k, v in _app.__dict__.items() if not k.startswith("__")})

def _sync_app_state() -> None:
    globals().update({k: v for k, v in _app.__dict__.items() if not k.startswith("__")})

def tailoring_runner_status(lines: int = Query(80, ge=0, le=500)):
    _sync_app_state()
    return _tailoring_runner_snapshot(log_lines=lines)



def tailoring_recent_jobs(
    limit: int = Query(25, ge=1, le=100),
    max_age_hours: int | None = Query(None, ge=1, le=24 * 30),
):
    _sync_app_state()
    items = _recent_jobs(limit=limit, max_age_hours=max_age_hours)
    return {"items": items, "count": len(items)}



def tailoring_run_job(payload: dict = Body(...)):
    _sync_app_state()
    job_id = payload.get("job_id")
    skip_analysis = bool(payload.get("skip_analysis", False))
    if not isinstance(job_id, int):
        return JSONResponse({"ok": False, "error": "job_id must be an integer"}, 400)

    job = _get_job_context(job_id)
    if not job:
        return JSONResponse({"ok": False, "error": f"Job {job_id} not found"}, 404)

    ok, data = _start_tailoring_run(
        {
            "id": int(job["id"]),
            "title": job.get("title"),
            "created_at": job.get("created_at"),
            "url": job.get("url"),
        },
        skip_analysis=skip_analysis,
    )
    if not ok:
        return JSONResponse(data, 409 if "in progress" in (data.get("error") or "") else 500)
    return data



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

    job = _latest_job(max_age_hours=max_age_hours)
    if not job:
        msg = "No jobs found"
        if max_age_hours is not None:
            msg = f"No jobs found in last {max_age_hours} hours"
        return JSONResponse({"ok": False, "error": msg}, 404)

    ok, data = _start_tailoring_run(job, skip_analysis=skip_analysis)
    if not ok:
        return JSONResponse(data, 409 if "in progress" in (data.get("error") or "") else 500)
    return data



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
    return FileResponse(artifact)


# ---------------------------------------------------------------------------
# Routes — API: Completed application packages (content review/edit)
# ---------------------------------------------------------------------------

def package_runs(status: str = Query("complete")):
    _sync_app_state()
    if not TAILORING_OUTPUT_DIR.exists():
        return {"items": []}

    rows = []
    for d in sorted(TAILORING_OUTPUT_DIR.iterdir()):
        if not d.is_dir():
            continue
        s = _tailoring_summary(d)
        if status != "all" and s.get("status") != status:
            continue
        rows.append(s)
    rows.sort(key=lambda r: _parse_ts(r.get("updated_at")) or 0, reverse=True)
    return {"items": rows}



def package_detail(slug: str):
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    if d is None:
        return JSONResponse({"error": "Package not found"}, 404)

    summary = _tailoring_summary(d)
    meta = summary.get("meta", {}) or {}
    job_context = _get_job_context(meta.get("job_id")) if meta.get("job_id") else None
    if job_context is None:
        job_context = {
            "id": meta.get("job_id"),
            "url": meta.get("url"),
            "title": meta.get("title"),
            "snippet": None,
            "jd_text": None,
        }

    resume_tex, resume_pdf = TAILORING_DOC_MAP["resume"]
    cover_tex, cover_pdf = TAILORING_DOC_MAP["cover"]

    return {
        "summary": summary,
        "job_context": job_context,
        "analysis": _load_json_file(d / "analysis.json"),
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



def package_compile(slug: str, doc_type: str):
    _sync_app_state()
    d = _safe_tailoring_slug(slug)
    if d is None:
        return JSONResponse({"error": "Package not found"}, 404)
    if doc_type not in TAILORING_DOC_MAP:
        return JSONResponse({"error": "Invalid document type"}, 400)

    tex_name, pdf_name = TAILORING_DOC_MAP[doc_type]
    ok, error = _compile_tex_in_place(d / tex_name)
    return {
        "ok": ok,
        "error": error,
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
    return FileResponse(out_pdf)


# ---------------------------------------------------------------------------
# Routes — API: Runtime controls
# ---------------------------------------------------------------------------

def llm_status():
    _sync_app_state()
    """Check whether the local LLM server is reachable."""
    controls = _load_runtime_controls()
    if not controls["llm_enabled"]:
        return {
            "enabled": False,
            "available": False,
            "models": [],
            "url": LLM_URL,
            "state": "disabled",
        }
    try:
        with urllib.request.urlopen(f"{LLM_URL}/v1/models", timeout=2) as resp:
            data = json.loads(resp.read())
        models = [m["id"] for m in data.get("data", [])]
        return {"enabled": True, "available": True, "models": models, "url": LLM_URL, "state": "online"}
    except Exception:
        return {"enabled": True, "available": False, "models": [], "url": LLM_URL, "state": "offline"}


# ---------------------------------------------------------------------------
# Catch-all route to serve the React index.html for client-side routing
# ---------------------------------------------------------------------------

