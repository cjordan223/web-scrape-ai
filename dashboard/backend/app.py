"""Job Scraper Dashboard — FastAPI backend."""

import json
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import urllib.error
import urllib.request

import uvicorn
from fastapi import Body, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get(
    "JOB_SCRAPER_DB",
    str(Path.home() / ".local/share/job_scraper/jobs.db"),
)
PORT = int(os.environ.get("DASHBOARD_PORT", "8899"))
LAUNCH_AGENTS_DIR = Path.home() / "Library/LaunchAgents"
SCRAPE_SCHEDULED_LABEL = "com.jobscraper.scrape"

HERE = Path(__file__).resolve().parent
# Load environment variables from .env file in project root
load_dotenv(HERE.parent.parent / ".env")
TAILORING_OUTPUT_DIR = Path(
    os.environ.get("TAILORING_OUTPUT_DIR", str(HERE.parent.parent / "tailoring" / "output"))
)
TAILORING_ROOT = Path(os.environ.get("TAILORING_ROOT", str(HERE.parent.parent / "tailoring")))
_DEFAULT_TAILORING_PYTHON = HERE.parent.parent / "venv" / "bin" / "python"
TAILORING_PYTHON = Path(
    os.environ.get(
        "TAILORING_PYTHON",
        str(_DEFAULT_TAILORING_PYTHON if _DEFAULT_TAILORING_PYTHON.exists() else Path(sys.executable)),
    )
)
SCRAPER_ROOT = HERE.parent.parent / "job-scraper"
_DEFAULT_SCRAPER_PYTHON = HERE.parent.parent / "venv" / "bin" / "python"
SCRAPER_PYTHON = Path(
    os.environ.get(
        "SCRAPER_PYTHON",
        str(_DEFAULT_SCRAPER_PYTHON if _DEFAULT_SCRAPER_PYTHON.exists() else Path(sys.executable)),
    )
)
TAILORING_TRACE_FILE = "llm_trace.jsonl"
TAILORING_ALLOWED_ARTIFACTS = {
    "Conner_Jordan_Resume.tex",
    "Conner_Jordan_Resume.pdf",
    "Conner_Jordan_Cover_Letter.tex",
    "Conner_Jordan_Cover_Letter.pdf",
    "analysis.json",
    "meta.json",
    "resume_strategy.json",
    "cover_strategy.json",
    TAILORING_TRACE_FILE,
}
TAILORING_DOC_MAP = {
    "resume": ("Conner_Jordan_Resume.tex", "Conner_Jordan_Resume.pdf"),
    "cover": ("Conner_Jordan_Cover_Letter.tex", "Conner_Jordan_Cover_Letter.pdf"),
}
TAILORING_BASELINE_DOC_MAP = {
    "resume": HERE.parent.parent / "tailoring" / "Baseline-Dox" / "Conner_Jordan_Software_Engineer" / "Conner_Jordan_Resume.tex",
    "cover": HERE.parent.parent / "tailoring" / "Baseline-Dox" / "Conner_Jordan_Cover_letter" / "Conner_Jordan_Cover_Letter.tex",
}
TAILORING_RUNNER_LOG_DIR = TAILORING_OUTPUT_DIR / "_runner_logs"
APPLIED_STATUS_VALUES = {
    "applied",
    "follow_up",
    "withdrawn",
    "rejected",
    "offer",
}
APPLIED_ARTIFACT_COLUMNS = {
    "meta.json": ("meta", "application/json", False),
    "job_context.json": ("job_context", "application/json", False),
    "analysis.json": ("analysis", "application/json", False),
    "resume_strategy.json": ("resume_strategy", "application/json", False),
    "cover_strategy.json": ("cover_strategy", "application/json", False),
    "Conner_Jordan_Resume.tex": ("resume_tex", "text/plain; charset=utf-8", False),
    "Conner_Jordan_Cover_Letter.tex": ("cover_tex", "text/plain; charset=utf-8", False),
    "Conner_Jordan_Resume.pdf": ("resume_pdf", "application/pdf", True),
    "Conner_Jordan_Cover_Letter.pdf": ("cover_pdf", "application/pdf", True),
    TAILORING_TRACE_FILE: ("llm_trace", "text/plain; charset=utf-8", False),
}
_APPLIED_DB_SCHEMA = """\
CREATE TABLE IF NOT EXISTS applied_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_slug TEXT NOT NULL UNIQUE,
    job_id INTEGER,
    job_title TEXT,
    company_name TEXT,
    job_url TEXT,
    application_url TEXT,
    applied_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'applied',
    follow_up_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status_updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_applied_applications_job_id ON applied_applications(job_id);
CREATE INDEX IF NOT EXISTS idx_applied_applications_status ON applied_applications(status);
CREATE INDEX IF NOT EXISTS idx_applied_applications_applied_at ON applied_applications(applied_at);
CREATE INDEX IF NOT EXISTS idx_applied_applications_updated_at ON applied_applications(updated_at);
CREATE TABLE IF NOT EXISTS applied_snapshots (
    application_id INTEGER PRIMARY KEY REFERENCES applied_applications(id) ON DELETE CASCADE,
    meta TEXT,
    job_context TEXT,
    analysis TEXT,
    resume_strategy TEXT,
    cover_strategy TEXT,
    resume_tex TEXT,
    cover_tex TEXT,
    resume_pdf BLOB,
    cover_pdf BLOB,
    llm_trace TEXT,
    created_at TEXT NOT NULL
);
"""

_TAILORING_RUNNER: dict = {
    "proc": None,
    "log_handle": None,
    "job": None,
    "started_at": None,
    "ended_at": None,
    "exit_code": None,
    "log_path": None,
    "cmd": None,
}
_TAILORING_QUEUE: list[dict] = []
_QA_LLM_REVIEW_LOCK = threading.Lock()
_QA_LLM_REVIEW_RUNNER: dict = {
    "thread": None,
    "batch_id": 0,
    "started_at": None,
    "ended_at": None,
    "active_job_id": None,
    "active_started_at": None,
    "resolved_model": None,
    "items": [],
}
_SCRAPE_RUNNER: dict = {
    "proc": None,
    "log_handle": None,
    "started_at": None,
    "ended_at": None,
    "exit_code": None,
    "log_path": None,
    "cmd": None,
    "options": {},
}

RUNTIME_CONTROLS_PATH = Path(
    os.environ.get(
        "JOB_SCRAPER_RUNTIME_CONTROLS",
        str(Path.home() / ".local" / "share" / "job_scraper" / "runtime_controls.json"),
    )
)
_DEFAULT_RUNTIME_CONTROLS = {
    "scrape_enabled": True,
    "llm_enabled": True,
    "llm_provider": os.environ.get("LLM_PROVIDER", "lmstudio"),
    "llm_base_url": os.environ.get("LLM_URL", "http://localhost:1234"),
    "llm_model": os.environ.get(
        "TAILOR_LMSTUDIO_MODEL",
        os.environ.get("TAILOR_OLLAMA_MODEL", "default"),
    ),
    "schedule_interval_minutes": None,
    "schedule_started_at": None,
    "schedule_stop_at": None,
}

app = FastAPI(title="Job Scraper Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_db_write() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_applied_tables() -> None:
    db_file = Path(DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(_APPLIED_DB_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _load_runtime_controls() -> dict:
    controls = dict(_DEFAULT_RUNTIME_CONTROLS)
    try:
        raw = json.loads(RUNTIME_CONTROLS_PATH.read_text(encoding="utf-8"))
        controls["scrape_enabled"] = bool(raw.get("scrape_enabled", controls["scrape_enabled"]))
        controls["llm_enabled"] = bool(raw.get("llm_enabled", controls["llm_enabled"]))
        controls["llm_provider"] = str(raw.get("llm_provider", controls["llm_provider"]) or controls["llm_provider"]).strip()
        controls["llm_base_url"] = str(raw.get("llm_base_url", controls["llm_base_url"]) or controls["llm_base_url"]).strip()
        controls["llm_model"] = str(raw.get("llm_model", controls["llm_model"]) or controls["llm_model"]).strip()
        interval = raw.get("schedule_interval_minutes")
        if isinstance(interval, int) and interval > 0:
            controls["schedule_interval_minutes"] = interval
        else:
            controls["schedule_interval_minutes"] = None
        controls["schedule_started_at"] = raw.get("schedule_started_at")
        controls["schedule_stop_at"] = raw.get("schedule_stop_at")
        controls["updated_at"] = raw.get("updated_at")
    except FileNotFoundError:
        controls["updated_at"] = None
    except Exception:
        controls["updated_at"] = None
    return controls


def _save_runtime_controls(updates: dict) -> dict:
    controls = _load_runtime_controls()
    if "scrape_enabled" in updates:
        controls["scrape_enabled"] = bool(updates["scrape_enabled"])
    if "llm_enabled" in updates:
        controls["llm_enabled"] = bool(updates["llm_enabled"])
    if "llm_provider" in updates:
        controls["llm_provider"] = str(updates["llm_provider"] or "openai").strip() or "openai"
    if "llm_base_url" in updates:
        controls["llm_base_url"] = str(updates["llm_base_url"] or "").strip() or controls["llm_base_url"]
    if "llm_model" in updates:
        controls["llm_model"] = str(updates["llm_model"] or "default").strip() or "default"
    if "schedule_interval_minutes" in updates:
        interval = updates["schedule_interval_minutes"]
        if interval is None:
            controls["schedule_interval_minutes"] = None
        else:
            interval = int(interval)
            controls["schedule_interval_minutes"] = interval if interval > 0 else None
    if "schedule_started_at" in updates:
        controls["schedule_started_at"] = updates["schedule_started_at"]
    if "schedule_stop_at" in updates:
        controls["schedule_stop_at"] = updates["schedule_stop_at"]
    controls["updated_at"] = datetime.now(timezone.utc).isoformat()
    RUNTIME_CONTROLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONTROLS_PATH.write_text(
        json.dumps(
            {
                "scrape_enabled": controls["scrape_enabled"],
                "llm_enabled": controls["llm_enabled"],
                "llm_provider": controls["llm_provider"],
                "llm_base_url": controls["llm_base_url"],
                "llm_model": controls["llm_model"],
                "schedule_interval_minutes": controls["schedule_interval_minutes"],
                "schedule_started_at": controls["schedule_started_at"],
                "schedule_stop_at": controls["schedule_stop_at"],
                "updated_at": controls["updated_at"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return controls


def _normalize_llm_base_url(url: str | None) -> str:
    value = (url or "").strip()
    if not value:
        return _DEFAULT_RUNTIME_CONTROLS["llm_base_url"]
    for suffix in ("/v1/chat/completions", "/v1/models", "/api/v0/models/load", "/api/v0/models/unload", "/api/v0/models"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return value.rstrip("/") or _DEFAULT_RUNTIME_CONTROLS["llm_base_url"]


def _resolve_llm_runtime(controls: dict | None = None) -> dict:
    controls = controls or _load_runtime_controls()
    provider = str(controls.get("llm_provider") or "openai").strip().lower()
    if provider not in {"lmstudio", "openai"}:
        provider = "openai"
    base_url = _normalize_llm_base_url(str(controls.get("llm_base_url") or _DEFAULT_RUNTIME_CONTROLS["llm_base_url"]))
    selected_model = str(controls.get("llm_model") or "default").strip() or "default"
    return {
        "provider": provider,
        "base_url": base_url,
        "chat_url": f"{base_url}/v1/chat/completions",
        "models_url": f"{base_url}/v1/models",
        "manage_models": provider == "lmstudio",
        "selected_model": selected_model,
    }


def _safe_tailoring_slug(slug: str) -> Path | None:
    if "/" in slug or "\\" in slug or ".." in slug:
        return None
    d = TAILORING_OUTPUT_DIR / slug
    if not d.exists() or not d.is_dir():
        return None
    return d


def _read_trace_events(trace_path: Path) -> list[dict]:
    events: list[dict] = []
    if not trace_path.exists():
        return events
    with trace_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _parse_ts(ts: str | None) -> float:
    if not ts:
        return 0
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def _tailoring_summary(slug_dir: Path) -> dict:
    meta_path = slug_dir / "meta.json"
    trace_path = slug_dir / TAILORING_TRACE_FILE
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    events = _read_trace_events(trace_path)
    events.sort(key=lambda e: _parse_ts(e.get("timestamp") or e.get("started_at")))

    doc_attempts: dict[str, list[dict]] = {"resume": [], "cover": []}
    validations: dict[str, list[dict]] = {"resume": [], "cover": []}
    for ev in events:
        if ev.get("event_type") == "doc_attempt_result" and ev.get("doc_type") in doc_attempts:
            doc_attempts[ev["doc_type"]].append(ev)
        if ev.get("event_type") == "validation_result" and ev.get("doc_type") in validations:
            validations[ev["doc_type"]].append(ev)

    def _doc_status(doc: str) -> str:
        attempts = doc_attempts[doc]
        if not attempts:
            return "pending"
        if any(a.get("status") == "passed" for a in attempts):
            return "passed"
        return "failed"

    resume_status = _doc_status("resume")
    cover_status = _doc_status("cover")

    if not trace_path.exists():
        status = "no-trace"
    elif resume_status == "passed" and cover_status == "passed":
        has_validation = (
            any(v.get("passed") is True for v in validations["resume"])
            and any(v.get("passed") is True for v in validations["cover"])
        )
        status = "complete" if has_validation else "partial"
    elif resume_status == "failed" and cover_status == "failed":
        status = "failed"
    else:
        status = "partial"

    attempts = {
        "resume": max((a.get("attempt", 0) for a in doc_attempts["resume"]), default=0),
        "cover": max((a.get("attempt", 0) for a in doc_attempts["cover"]), default=0),
    }
    artifacts = {
        name: (slug_dir / name).exists()
        for name in TAILORING_ALLOWED_ARTIFACTS
    }
    latest_ts = max((_parse_ts(ev.get("timestamp") or ev.get("ended_at") or ev.get("started_at")) for ev in events), default=0)
    updated_at = datetime.fromtimestamp(latest_ts, tz=timezone.utc).isoformat() if latest_ts else None

    return {
        "slug": slug_dir.name,
        "meta": meta,
        "status": status,
        "updated_at": updated_at,
        "event_count": len(events),
        "attempts": attempts,
        "doc_status": {"resume": resume_status, "cover": cover_status},
        "artifacts": artifacts,
    }


def _load_json_file(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_json_text(raw: str | None) -> dict | list | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _applied_summary_from_row(row: sqlite3.Row | dict | None) -> dict | None:
    if row is None:
        return None
    record = dict(row)
    return {
        "id": record["id"],
        "package_slug": record.get("package_slug"),
        "job_id": record.get("job_id"),
        "job_title": record.get("job_title"),
        "company_name": record.get("company_name"),
        "job_url": record.get("job_url"),
        "application_url": record.get("application_url"),
        "applied_at": record.get("applied_at"),
        "status": record.get("status"),
        "follow_up_at": record.get("follow_up_at"),
        "notes": record.get("notes"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "status_updated_at": record.get("status_updated_at"),
    }


def _fetch_applied_by_package_slugs(package_slugs: list[str]) -> dict[str, dict]:
    slugs = [slug for slug in package_slugs if slug]
    if not slugs:
        return {}
    _ensure_applied_tables()
    conn = get_db_write()
    try:
        placeholders = ",".join("?" for _ in slugs)
        rows = conn.execute(
            f"""
            SELECT id, package_slug, job_id, job_title, company_name, job_url,
                   application_url, applied_at, status, follow_up_at, notes,
                   created_at, updated_at, status_updated_at
            FROM applied_applications
            WHERE package_slug IN ({placeholders})
            """,
            tuple(slugs),
        ).fetchall()
        return {
            str(row["package_slug"]): _applied_summary_from_row(row)  # type: ignore[index]
            for row in rows
            if row["package_slug"]
        }
    finally:
        conn.close()


def _fetch_applied_by_job_ids(job_ids: list[int]) -> dict[int, dict]:
    ids = [int(job_id) for job_id in job_ids]
    if not ids:
        return {}
    _ensure_applied_tables()
    conn = get_db_write()
    try:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"""
            SELECT id, package_slug, job_id, job_title, company_name, job_url,
                   application_url, applied_at, status, follow_up_at, notes,
                   created_at, updated_at, status_updated_at
            FROM applied_applications
            WHERE job_id IN ({placeholders})
            ORDER BY updated_at DESC, id DESC
            """,
            tuple(ids),
        ).fetchall()
        items: dict[int, dict] = {}
        for row in rows:
            job_id = row["job_id"]
            if job_id is None or int(job_id) in items:
                continue
            items[int(job_id)] = _applied_summary_from_row(row)
        return items
    finally:
        conn.close()


def _get_applied_application(application_id: int) -> dict | None:
    _ensure_applied_tables()
    conn = get_db_write()
    try:
        row = conn.execute(
            """
            SELECT id, package_slug, job_id, job_title, company_name, job_url,
                   application_url, applied_at, status, follow_up_at, notes,
                   created_at, updated_at, status_updated_at
            FROM applied_applications
            WHERE id = ?
            """,
            (application_id,),
        ).fetchone()
        return _applied_summary_from_row(row)
    finally:
        conn.close()


def _get_applied_snapshot_detail(application_id: int) -> dict | None:
    _ensure_applied_tables()
    conn = get_db_write()
    try:
        row = conn.execute(
            """
            SELECT aa.id, aa.package_slug, aa.job_id, aa.job_title, aa.company_name, aa.job_url,
                   aa.application_url, aa.applied_at, aa.status, aa.follow_up_at, aa.notes,
                   aa.created_at, aa.updated_at, aa.status_updated_at,
                   s.meta, s.job_context, s.analysis, s.resume_strategy, s.cover_strategy,
                   s.resume_tex, s.cover_tex, s.resume_pdf, s.cover_pdf, s.llm_trace
            FROM applied_applications aa
            JOIN applied_snapshots s ON s.application_id = aa.id
            WHERE aa.id = ?
            """,
            (application_id,),
        ).fetchone()
        if not row:
            return None
        summary = _applied_summary_from_row(row) or {}
        meta = _parse_json_text(row["meta"])
        job_context = _parse_json_text(row["job_context"])
        analysis = _parse_json_text(row["analysis"])
        resume_strategy = _parse_json_text(row["resume_strategy"])
        cover_strategy = _parse_json_text(row["cover_strategy"])
        summary["meta"] = meta
        summary["artifacts"] = {
            name: bool(row[column])
            for name, (column, _media_type, _is_bytes) in APPLIED_ARTIFACT_COLUMNS.items()
        }
        return {
            "summary": summary,
            "job_context": job_context,
            "analysis": analysis,
            "resume_strategy": resume_strategy,
            "cover_strategy": cover_strategy,
            "latex": {
                "resume": row["resume_tex"] or "",
                "cover": row["cover_tex"] or "",
            },
            "pdf_available": {
                "resume": bool(row["resume_pdf"]),
                "cover": bool(row["cover_pdf"]),
            },
        }
    finally:
        conn.close()


def _results_has_column(conn: sqlite3.Connection, column: str) -> bool:
    try:
        cols = conn.execute("PRAGMA table_info(results)").fetchall()
    except Exception:
        return False
    for col in cols:
        name = col["name"] if isinstance(col, sqlite3.Row) else col[1]
        if name == column:
            return True
    return False


def _get_job_context(job_id: int) -> dict | None:
    conn = get_db()
    try:
        jd_expr = "jd_text"
        if _results_has_column(conn, "approved_jd_text"):
            jd_expr = "COALESCE(approved_jd_text, jd_text)"
        row = conn.execute(
            f"SELECT id, url, title, snippet, {jd_expr} AS jd_text, query, run_id, created_at "
            "FROM results WHERE id = ?",
            (job_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _latest_job(max_age_hours: int | None = None) -> dict | None:
    conn = get_db()
    try:
        where = ""
        params: tuple = ()
        if max_age_hours is not None:
            where = "WHERE julianday(created_at) >= julianday('now', ?)"
            params = (f"-{int(max_age_hours)} hours",)
        row = conn.execute(
            f"SELECT id, title, created_at, url FROM results {where} ORDER BY id DESC LIMIT 1",
            params,
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _recent_jobs(limit: int = 25, max_age_hours: int | None = None) -> list[dict]:
    run_counts_by_job: dict[int, int] = {}
    latest_status_by_job: dict[int, dict] = {}
    if TAILORING_OUTPUT_DIR.exists():
        for d in TAILORING_OUTPUT_DIR.iterdir():
            if not d.is_dir():
                continue
            summary = _tailoring_summary(d)
            meta = summary.get("meta") or {}
            raw_job_id = meta.get("job_id")
            if raw_job_id is None:
                continue
            try:
                job_id = int(raw_job_id)
            except (TypeError, ValueError):
                continue
            run_counts_by_job[job_id] = run_counts_by_job.get(job_id, 0) + 1
            status = summary.get("status")
            status_ts = _parse_ts(summary.get("updated_at"))
            prior = latest_status_by_job.get(job_id)
            if prior is None or status_ts >= prior["ts"]:
                latest_status_by_job[job_id] = {"status": status, "ts": status_ts}

    conn = get_db()
    try:
        clauses = ["decision IN ('qa_approved','manual','manual_approved')"]
        params: list = []
        if max_age_hours is not None:
            clauses.append("julianday(created_at) >= julianday('now', ?)")
            params.append(f"-{int(max_age_hours)} hours")
        where = "WHERE " + " AND ".join(clauses)
        params.append(max(1, min(int(limit), 100)))
        rows = conn.execute(
            f"SELECT id, title, created_at, url FROM results {where} ORDER BY id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        items = [dict(r) for r in rows]
        applied_by_job_id = _fetch_applied_by_job_ids([int(item["id"]) for item in items if item.get("id") is not None])
        for item in items:
            count = run_counts_by_job.get(int(item["id"]), 0)
            item["tailoring_run_count"] = count
            item["has_tailoring_runs"] = count > 0
            item["tailoring_latest_status"] = (latest_status_by_job.get(int(item["id"])) or {}).get("status")
            item["applied"] = applied_by_job_id.get(int(item["id"]))
        return items
    finally:
        conn.close()


def _read_tail(path: Path, lines: int = 80) -> str:
    if not path.exists() or lines <= 0:
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            data = f.readlines()
        return "".join(data[-lines:])
    except Exception:
        return ""


def _process_tailoring_queue() -> None:
    """Auto-start the next queued tailoring job if runner is idle."""
    if _TAILORING_RUNNER.get("proc") is not None:
        return
    if not _TAILORING_QUEUE:
        return
    item = _TAILORING_QUEUE.pop(0)
    _start_tailoring_run(item["job"], skip_analysis=item.get("skip_analysis", False))


def _tailoring_runner_snapshot(log_lines: int = 80) -> dict:
    proc = _TAILORING_RUNNER.get("proc")
    if proc is not None:
        rc = proc.poll()
        if rc is not None:
            _TAILORING_RUNNER["exit_code"] = rc
            _TAILORING_RUNNER["ended_at"] = _TAILORING_RUNNER.get("ended_at") or datetime.now(timezone.utc).isoformat()
            handle = _TAILORING_RUNNER.get("log_handle")
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
            _TAILORING_RUNNER["log_handle"] = None
            _TAILORING_RUNNER["proc"] = None
            _process_tailoring_queue()

    log_path = Path(_TAILORING_RUNNER["log_path"]) if _TAILORING_RUNNER.get("log_path") else None
    return {
        "running": _TAILORING_RUNNER.get("proc") is not None,
        "job": _TAILORING_RUNNER.get("job"),
        "started_at": _TAILORING_RUNNER.get("started_at"),
        "ended_at": _TAILORING_RUNNER.get("ended_at"),
        "exit_code": _TAILORING_RUNNER.get("exit_code"),
        "log_path": str(log_path) if log_path else None,
        "cmd": _TAILORING_RUNNER.get("cmd"),
        "log_tail": _read_tail(log_path, log_lines) if log_path else "",
        "queue": [{"job": item["job"], "skip_analysis": item.get("skip_analysis", False)} for item in _TAILORING_QUEUE],
    }


def _start_tailoring_run(job: dict, skip_analysis: bool = False) -> tuple[bool, dict]:
    if _TAILORING_RUNNER.get("proc") is not None and _TAILORING_RUNNER["proc"].poll() is None:
        return False, {"ok": False, "error": "A tailoring run is already in progress", "runner": _tailoring_runner_snapshot()}

    TAILORING_RUNNER_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = TAILORING_RUNNER_LOG_DIR / f"tailor_job_{job['id']}_{stamp}.log"

    cmd = [str(TAILORING_PYTHON), "-m", "tailor", "run", "--job-id", str(job["id"])]
    if skip_analysis:
        cmd.append("--skip-analysis")

    try:
        log_handle = log_path.open("w", encoding="utf-8")
        llm_runtime = _resolve_llm_runtime()
        env = os.environ.copy()
        env["TAILOR_LMSTUDIO_URL"] = llm_runtime["chat_url"]
        env["TAILOR_LMSTUDIO_MODELS_URL"] = llm_runtime["models_url"]
        env["TAILOR_LMSTUDIO_MODEL"] = llm_runtime["selected_model"]
        env["TAILOR_OLLAMA_URL"] = llm_runtime["chat_url"]
        env["TAILOR_OLLAMA_MODELS_URL"] = llm_runtime["models_url"]
        env["TAILOR_OLLAMA_MODEL"] = llm_runtime["selected_model"]
        proc = subprocess.Popen(
            cmd,
            cwd=str(TAILORING_ROOT),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
    except Exception as e:
        return False, {"ok": False, "error": f"Failed to start tailoring run: {e}"}

    _TAILORING_RUNNER.update(
        {
            "proc": proc,
            "log_handle": log_handle,
            "job": job,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": None,
            "exit_code": None,
            "log_path": str(log_path),
            "cmd": " ".join(cmd),
        }
    )
    return True, {"ok": True, "job": job, "runner": _tailoring_runner_snapshot()}


def _db_has_active_scrape() -> bool:
    _reconcile_stale_scrape_runs()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM runs WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _scrape_schedule_status() -> dict:
    return _get_launchctl_status(SCRAPE_SCHEDULED_LABEL)


def _mark_scrape_run_inactive(run_id: str, *, status: str = "failed", error: str | None = None) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_write()
    try:
        row = conn.execute(
            "SELECT errors FROM runs WHERE run_id = ? AND status = 'running'",
            (run_id,),
        ).fetchone()
        if not row:
            return False

        errors: list[str] = []
        raw_errors = row["errors"]
        if raw_errors:
            try:
                parsed = json.loads(raw_errors)
                if isinstance(parsed, list):
                    errors = [str(item) for item in parsed if str(item).strip()]
            except Exception:
                errors = [str(raw_errors)]
        if error and error not in errors:
            errors.append(error)

        conn.execute(
            """
            UPDATE runs
            SET completed_at = COALESCE(completed_at, ?),
                status = ?,
                errors = ?,
                error_count = ?
            WHERE run_id = ? AND status = 'running'
            """,
            (
                now,
                status,
                json.dumps(errors) if errors else None,
                len(errors),
                run_id,
            ),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def _reconcile_stale_scrape_runs() -> dict:
    manual_running = bool(_scrape_runner_snapshot(log_lines=0).get("running"))
    schedule_status = _scrape_schedule_status()
    scheduled_running = bool(schedule_status.get("running"))
    stale_run_ids: list[str] = []

    if manual_running or scheduled_running:
        return {
            "manual_running": manual_running,
            "scheduled_running": scheduled_running,
            "scheduled_pid": schedule_status.get("pid"),
            "stale_run_ids": stale_run_ids,
        }

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT run_id FROM runs WHERE status = 'running' ORDER BY started_at DESC"
        ).fetchall()
    finally:
        conn.close()

    for row in rows:
        run_id = row["run_id"]
        if _mark_scrape_run_inactive(
            run_id,
            status="failed",
            error="Run was marked active, but no live scrape process was found. Marked failed automatically.",
        ):
            stale_run_ids.append(run_id)

    return {
        "manual_running": manual_running,
        "scheduled_running": scheduled_running,
        "scheduled_pid": schedule_status.get("pid"),
        "stale_run_ids": stale_run_ids,
    }


def _scrape_runner_snapshot(log_lines: int = 80) -> dict:
    proc = _SCRAPE_RUNNER.get("proc")
    if proc is not None:
        rc = proc.poll()
        if rc is not None:
            _SCRAPE_RUNNER["exit_code"] = rc
            _SCRAPE_RUNNER["ended_at"] = _SCRAPE_RUNNER.get("ended_at") or datetime.now(timezone.utc).isoformat()
            handle = _SCRAPE_RUNNER.get("log_handle")
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
            _SCRAPE_RUNNER["log_handle"] = None
            _SCRAPE_RUNNER["proc"] = None

    log_path = Path(_SCRAPE_RUNNER["log_path"]) if _SCRAPE_RUNNER.get("log_path") else None
    return {
        "running": _SCRAPE_RUNNER.get("proc") is not None,
        "started_at": _SCRAPE_RUNNER.get("started_at"),
        "ended_at": _SCRAPE_RUNNER.get("ended_at"),
        "exit_code": _SCRAPE_RUNNER.get("exit_code"),
        "log_path": str(log_path) if log_path else None,
        "cmd": _SCRAPE_RUNNER.get("cmd"),
        "options": _SCRAPE_RUNNER.get("options", {}),
        "log_tail": _read_tail(log_path, log_lines) if log_path else "",
    }


def _start_scrape_run(
    *,
    dry_run: bool = False,
    no_fetch: bool = False,
    no_crawl: bool = False,
    ignore_runtime_controls: bool = True,
    llm_enabled_override: bool | None = None,
) -> tuple[bool, dict]:
    snap = _scrape_runner_snapshot(log_lines=0)
    if snap.get("running"):
        return False, {"ok": False, "error": "A manual scrape run is already in progress", "runner": snap}
    if _db_has_active_scrape():
        return False, {
            "ok": False,
            "error": "A scrape run is already active (likely scheduled). Wait for it to finish.",
            "runner": snap,
        }

    log_dir = Path.home() / ".local" / "share" / "job_scraper"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = log_dir / f"manual_scrape_{stamp}.log"

    cmd = [str(SCRAPER_PYTHON), "-m", "job_scraper", "scrape", "-v"]
    if dry_run:
        cmd.append("--dry-run")
    if no_fetch:
        cmd.append("--no-fetch")
    if no_crawl:
        cmd.append("--no-crawl")
    if ignore_runtime_controls:
        cmd.append("--ignore-runtime-controls")
    if llm_enabled_override is True:
        cmd.append("--llm-enabled")
    elif llm_enabled_override is False:
        cmd.append("--no-llm-enabled")

    try:
        log_handle = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            cwd=str(SCRAPER_ROOT),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception as e:
        return False, {"ok": False, "error": f"Failed to start manual scrape: {e}"}

    _SCRAPE_RUNNER.update(
        {
            "proc": proc,
            "log_handle": log_handle,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": None,
            "exit_code": None,
            "log_path": str(log_path),
            "cmd": " ".join(cmd),
            "options": {
                "dry_run": dry_run,
                "no_fetch": no_fetch,
                "no_crawl": no_crawl,
                "ignore_runtime_controls": ignore_runtime_controls,
                "llm_enabled_override": llm_enabled_override,
            },
        }
    )
    return True, {"ok": True, "runner": _scrape_runner_snapshot()}


def _compile_tex_in_place(tex_path: Path) -> tuple[bool, str | None]:
    """Compile a tex file in a temp dir and copy resulting pdf next to source."""
    if not tex_path.exists():
        return False, "TeX file not found"

    pdflatex_bin = os.environ.get("PDFLATEX_BIN")
    if pdflatex_bin:
        pdflatex = pdflatex_bin
    else:
        pdflatex = (
            shutil.which("pdflatex")
            or ("/Library/TeX/texbin/pdflatex" if Path("/Library/TeX/texbin/pdflatex").exists() else None)
            or ("/usr/texbin/pdflatex" if Path("/usr/texbin/pdflatex").exists() else None)
            or ("/opt/homebrew/bin/pdflatex" if Path("/opt/homebrew/bin/pdflatex").exists() else None)
        )
    if not pdflatex:
        return False, "pdflatex not found. Set PDFLATEX_BIN or install TeX (expected /Library/TeX/texbin/pdflatex)"

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            tmp_tex = tmp / tex_path.name
            shutil.copy2(tex_path, tmp_tex)

            for i in (1, 2):
                result = subprocess.run(
                    [pdflatex, "-interaction=nonstopmode", "-halt-on-error", tmp_tex.name],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode != 0:
                    tail = (result.stdout or "")[-4000:]
                    return False, f"pdflatex pass {i} failed:\n{tail}"

            tmp_pdf = tmp / (tex_path.stem + ".pdf")
            if not tmp_pdf.exists():
                return False, "PDF not produced"

            shutil.copy2(tmp_pdf, tex_path.parent / tmp_pdf.name)
        return True, None
    except Exception as e:
        return False, str(e)


def _build_diff_pdf(
    baseline_tex: Path,
    generated_tex: Path,
    output_pdf: Path,
) -> tuple[bool, str | None]:
    """Build a highlighted diff PDF (baseline vs generated) with latexdiff + pdflatex."""
    if not baseline_tex.exists():
        return False, f"Baseline TeX not found: {baseline_tex}"
    if not generated_tex.exists():
        return False, f"Generated TeX not found: {generated_tex}"

    latexdiff = (
        shutil.which("latexdiff")
        or ("/Library/TeX/texbin/latexdiff" if Path("/Library/TeX/texbin/latexdiff").exists() else None)
    )
    if not latexdiff:
        return False, "latexdiff not found. Install TeX tools with latexdiff."

    pdflatex = (
        os.environ.get("PDFLATEX_BIN")
        or shutil.which("pdflatex")
        or ("/Library/TeX/texbin/pdflatex" if Path("/Library/TeX/texbin/pdflatex").exists() else None)
        or ("/usr/texbin/pdflatex" if Path("/usr/texbin/pdflatex").exists() else None)
        or ("/opt/homebrew/bin/pdflatex" if Path("/opt/homebrew/bin/pdflatex").exists() else None)
    )
    if not pdflatex:
        return False, "pdflatex not found. Set PDFLATEX_BIN or install TeX."

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            old_tex = tmp / "old.tex"
            new_tex = tmp / "new.tex"
            diff_tex = tmp / "diff.tex"
            old_tex.write_text(baseline_tex.read_text(encoding="utf-8"), encoding="utf-8")
            new_tex.write_text(generated_tex.read_text(encoding="utf-8"), encoding="utf-8")

            diff_result = subprocess.run(
                [latexdiff, "--type=CFONT", '--exclude-textcmd=textbf', old_tex.name, new_tex.name],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=90,
            )
            if diff_result.returncode != 0:
                tail = (diff_result.stderr or diff_result.stdout or "")[-4000:]
                return False, f"latexdiff failed:\n{tail}"
            diff_tex.write_text(diff_result.stdout, encoding="utf-8")

            for i in (1, 2):
                result = subprocess.run(
                    [pdflatex, "-interaction=nonstopmode", "-halt-on-error", diff_tex.name],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                if result.returncode != 0:
                    tail = (result.stdout or "")[-4000:]
                    return False, f"pdflatex diff pass {i} failed:\n{tail}"

            tmp_pdf = tmp / "diff.pdf"
            if not tmp_pdf.exists():
                return False, "Diff PDF not produced"
            output_pdf.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tmp_pdf, output_pdf)
        return True, None
    except Exception as e:
        return False, str(e)


DIST_DIR = HERE.parent / "web" / "dist"


class StaleSafeStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and path.endswith(".js"):
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
            raise

# Serve static assets from the vite build
if DIST_DIR.exists():
    app.mount("/assets", StaleSafeStaticFiles(directory=str(DIST_DIR / "assets")), name="assets")

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


from routers import ops as ops_routes
from routers import scraping as scraping_routes
from routers import tailoring as tailoring_routes
from services import archive as archive_handlers
from services import ops as ops_handlers
from services import scraping as scraping_handlers
from services import tailoring as tailoring_handlers


def _register_routes() -> None:
    _archive_names = {"archive_create", "archive_list", "archive_detail", "pipeline_packages", "pipeline_trace"}
    handlers = {
        **{name: getattr(scraping_handlers, name) for _, _, name in scraping_routes.ROUTES},
        **{name: getattr(tailoring_handlers, name) for _, _, name in tailoring_routes.ROUTES},
        **{name: getattr(ops_handlers, name) for _, _, name in ops_routes.ROUTES if name not in _archive_names},
        **{name: getattr(archive_handlers, name) for name in _archive_names},
    }
    scraping_routes.register(app, handlers)
    tailoring_routes.register(app, handlers)
    ops_routes.register(app, handlers)


_register_routes()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=True)
