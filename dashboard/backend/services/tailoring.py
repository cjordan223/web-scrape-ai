"""Tailoring route implementations."""

from __future__ import annotations

import os

# Reuse shared backend state/helpers from app module.
import app as _app
globals().update({k: v for k, v in _app.__dict__.items() if not k.startswith("__")})

LLM_URL = os.environ.get("LLM_URL", "http://localhost:1234")

def _sync_app_state() -> None:
    globals().update({k: v for k, v in _app.__dict__.items() if not k.startswith("__")})

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
        cleared = len(_app._TAILORING_QUEUE)
        _app._TAILORING_QUEUE.clear()

    if not had_running:
        return {
            "ok": True,
            "stopped": False,
            "message": "No active tailoring run",
            "cleared_queue": cleared,
            "runner": _tailoring_runner_snapshot(),
        }

    try:
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


def tailoring_recent_jobs(
    limit: int = Query(25, ge=1, le=100),
    max_age_hours: int | None = Query(None, ge=1, le=24 * 30),
):
    _sync_app_state()
    items = _recent_jobs(limit=limit, max_age_hours=max_age_hours)
    return {"items": items, "count": len(items)}



def tailoring_job_detail(job_id: int):
    _sync_app_state()
    job = _get_job_context(job_id)
    if not job:
        return JSONResponse({"error": f"Job {job_id} not found"}, 404)
    return job


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



def tailoring_queue_add(payload: dict = Body(...)):
    _sync_app_state()
    jobs = payload.get("jobs", [])
    if not jobs or not isinstance(jobs, list):
        return JSONResponse({"ok": False, "error": "jobs must be a non-empty array"}, 400)

    added = []
    for item in jobs:
        job_id = item.get("job_id")
        if not isinstance(job_id, int):
            return JSONResponse({"ok": False, "error": f"Invalid job_id: {job_id}"}, 400)
        job = _get_job_context(job_id)
        if not job:
            return JSONResponse({"ok": False, "error": f"Job {job_id} not found"}, 404)
        added.append({
            "job": {"id": int(job["id"]), "title": job.get("title"), "created_at": job.get("created_at"), "url": job.get("url")},
            "skip_analysis": bool(item.get("skip_analysis", False)),
        })

    _app._TAILORING_QUEUE.extend(added)

    # If runner is idle, start the first one
    if _app._TAILORING_RUNNER.get("proc") is None:
        _app._process_tailoring_queue()

    return {"ok": True, "queued": len(added), "runner": _tailoring_runner_snapshot()}


def tailoring_queue_get():
    _sync_app_state()
    return {"queue": [{"job": item["job"], "skip_analysis": item.get("skip_analysis", False)} for item in _app._TAILORING_QUEUE]}


def tailoring_queue_clear():
    _sync_app_state()
    count = len(_app._TAILORING_QUEUE)
    _app._TAILORING_QUEUE.clear()
    return {"ok": True, "cleared": count}


def tailoring_queue_remove(index: int):
    _sync_app_state()
    if index < 0 or index >= len(_app._TAILORING_QUEUE):
        return JSONResponse({"ok": False, "error": "Index out of range"}, 400)
    removed = _app._TAILORING_QUEUE.pop(index)
    return {"ok": True, "removed": removed["job"]}


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
# Routes — API: Manual JD ingestion
# ---------------------------------------------------------------------------

_INGEST_EXTRACT_SYSTEM = (
    "Extract structured fields from a job description. Return ONLY valid JSON:\n"
    '{ "title": "", "company": "", "url": "", "seniority": "", "snippet": "", "salary_k": null, "experience_years": null }\n'
    '- seniority: junior|mid|senior|lead|staff|principal or ""\n'
    "- snippet: 1-3 sentence summary, max 400 chars\n"
    "- salary_k: integer (thousands) or null\n"
    "- experience_years: integer or null\n"
    '- url: application URL if present, else ""'
)


def tailoring_ingest_parse(payload: dict = Body(...)):
    _sync_app_state()
    jd_text = (payload.get("jd_text") or "").strip()
    if not jd_text:
        return JSONResponse({"ok": False, "error": "jd_text is required"}, 400)

    # Auto-discover active model
    try:
        with urllib.request.urlopen(f"{LLM_URL}/v1/models", timeout=3) as resp:
            mdata = json.loads(resp.read())
        model_id = mdata["data"][0]["id"] if mdata.get("data") else None
        if not model_id:
            return JSONResponse({"ok": False, "error": "No LLM model loaded"}, 503)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"LLM unreachable: {e}"}, 503)

    req_body = json.dumps({
        "model": model_id,
        "messages": [
            {"role": "system", "content": _INGEST_EXTRACT_SYSTEM},
            {"role": "user", "content": jd_text[:12000]},
        ],
        "temperature": 0.1,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{LLM_URL}/v1/chat/completions",
            data=req_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            cdata = json.loads(resp.read())
        raw = cdata["choices"][0]["message"]["content"]
        # Strip markdown fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        fields = json.loads(raw)
        return {"ok": True, "fields": fields}
    except json.JSONDecodeError:
        return {"ok": True, "fields": {}, "warning": "LLM returned non-JSON; fill fields manually"}
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"LLM call failed: {e}"}, 500)


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


def tailoring_ingest_commit(payload: dict = Body(...)):
    _sync_app_state()
    title = (payload.get("title") or "").strip()
    if not title:
        return JSONResponse({"ok": False, "error": "title is required"}, 400)

    url = (payload.get("url") or "").strip()
    if not url:
        import time as _time, random as _random
        url = f"manual://ingest/{int(_time.time() * 1000)}-{_random.randint(1000, 9999)}"

    board = (payload.get("board") or payload.get("company") or "manual").strip()
    seniority = (payload.get("seniority") or "").strip() or None
    snippet = (payload.get("snippet") or "").strip() or None
    jd_text = (payload.get("jd_text") or "").strip() or None
    salary_k = payload.get("salary_k")
    experience_years = payload.get("experience_years")

    # Coerce to int or None
    try:
        salary_k = int(salary_k) if salary_k not in (None, "", "null") else None
    except (TypeError, ValueError):
        salary_k = None
    try:
        experience_years = int(experience_years) if experience_years not in (None, "", "null") else None
    except (TypeError, ValueError):
        experience_years = None

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        conn = get_db_write()
        cur = conn.execute(
            """INSERT INTO results
               (url, title, board, seniority, experience_years, salary_k, score, decision,
                snippet, query, jd_text, filter_verdicts, run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, NULL, 'manual', ?, 'manual-ingest', ?, NULL, 'manual-ingest', ?)
               ON CONFLICT(url, run_id) DO NOTHING""",
            (url, title, board, seniority, experience_years, salary_k, snippet, jd_text, now),
        )
        conn.commit()
        if cur.rowcount == 0:
            conn.close()
            return JSONResponse({"ok": False, "error": "Duplicate — this URL already exists for manual-ingest"}, 409)
        job_id = cur.lastrowid
        conn.close()
        return {"ok": True, "job_id": job_id, "url": url}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 500)


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


def llm_models():
    """Return all downloaded models from LM Studio with their load state."""
    try:
        with urllib.request.urlopen(f"{LLM_URL}/api/v0/models", timeout=5) as resp:
            data = json.loads(resp.read())
        models = data.get("data", [])
        return {
            "models": [
                {"id": m["id"], "state": m.get("state", "not-loaded")}
                for m in models
            ]
        }
    except Exception as e:
        return JSONResponse({"error": f"LM Studio unreachable: {e}"}, 503)


def llm_load_model(payload: dict = Body(...)):
    """Load a model in LM Studio."""
    identifier = payload.get("identifier")
    if not identifier:
        return JSONResponse({"ok": False, "error": "identifier required"}, 400)
    try:
        req = urllib.request.Request(
            f"{LLM_URL}/api/v0/models/load",
            data=json.dumps({"identifier": identifier}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            resp.read()
        return {"ok": True, "model": identifier}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 500)


def llm_unload_model(payload: dict = Body(...)):
    """Unload a model in LM Studio."""
    identifier = payload.get("identifier")
    if not identifier:
        return JSONResponse({"ok": False, "error": "identifier required"}, 400)
    try:
        req = urllib.request.Request(
            f"{LLM_URL}/api/v0/models/unload",
            data=json.dumps({"identifier": identifier}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        return {"ok": True, "model": identifier}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 500)


# ---------------------------------------------------------------------------
# Catch-all route to serve the React index.html for client-side routing
# ---------------------------------------------------------------------------

