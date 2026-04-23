"""Job Scraper Dashboard — FastAPI backend."""

import json
import logging
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
    "grounding.json",
    "grounding_audit.json",
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
    "grounding.json": ("grounding", "application/json", False),
    "grounding_audit.json": ("grounding_audit", "application/json", False),
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
    grounding TEXT,
    grounding_audit TEXT,
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

_APPLIED_RESULTS_PROTECTION_SCHEMA = """\
CREATE TRIGGER IF NOT EXISTS protect_applied_results_before_update
BEFORE UPDATE ON results
FOR EACH ROW
WHEN EXISTS (
    SELECT 1
    FROM applied_applications aa
    WHERE aa.job_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'Applied job rows are protected from inventory writes');
END;

CREATE TRIGGER IF NOT EXISTS protect_applied_results_before_delete
BEFORE DELETE ON results
FOR EACH ROW
WHEN EXISTS (
    SELECT 1
    FROM applied_applications aa
    WHERE aa.job_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'Applied job rows are protected from inventory writes');
END;
"""

_APPLIED_QUEUE_PROTECTION_SCHEMA = """\
DROP TRIGGER IF EXISTS protect_applied_queue_before_insert;
CREATE TRIGGER IF NOT EXISTS protect_applied_queue_before_insert
BEFORE INSERT ON tailoring_queue_items
FOR EACH ROW
WHEN EXISTS (
    SELECT 1
    FROM applied_applications aa
    WHERE aa.job_id = NEW.job_id
)
BEGIN
    SELECT RAISE(ABORT, 'Applied jobs cannot be re-queued');
END;

DROP TRIGGER IF EXISTS protect_applied_queue_before_update;
CREATE TRIGGER IF NOT EXISTS protect_applied_queue_before_update
BEFORE UPDATE ON tailoring_queue_items
FOR EACH ROW
WHEN EXISTS (
    SELECT 1
    FROM applied_applications aa
    WHERE aa.job_id = COALESCE(NEW.job_id, OLD.job_id)
)
AND COALESCE(NEW.status, OLD.status) IN ('queued', 'running')
BEGIN
    SELECT RAISE(ABORT, 'Applied jobs cannot be re-queued');
END;
"""

_WORKFLOW_DB_SCHEMA = """\
CREATE TABLE IF NOT EXISTS seen_urls (
    url TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    permanently_rejected INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_seen_urls_first_seen ON seen_urls(first_seen);
CREATE TABLE IF NOT EXISTS job_state_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    job_url TEXT,
    old_state TEXT,
    new_state TEXT,
    action TEXT NOT NULL,
    source TEXT DEFAULT 'dashboard',
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_state_log_job_id ON job_state_log(job_id);
CREATE INDEX IF NOT EXISTS idx_state_log_created_at ON job_state_log(created_at);
CREATE TABLE IF NOT EXISTS tailoring_queue_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    skip_analysis INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    run_slug TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tailoring_queue_items_status_id ON tailoring_queue_items(status, id);
CREATE INDEX IF NOT EXISTS idx_tailoring_queue_items_job_id ON tailoring_queue_items(job_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tailoring_queue_items_open_job
ON tailoring_queue_items(job_id)
WHERE status IN ('queued', 'running');
CREATE TABLE IF NOT EXISTS qa_llm_review_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    ended_at TEXT,
    resolved_model TEXT,
    trigger_source TEXT NOT NULL DEFAULT 'manual',
    queued_count INTEGER NOT NULL DEFAULT 0,
    report_json TEXT,
    report_generated_at TEXT
);
CREATE TABLE IF NOT EXISTS qa_llm_review_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    queued_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    reason TEXT,
    confidence REAL,
    top_matches TEXT,
    gaps TEXT,
    polished INTEGER NOT NULL DEFAULT 0,
    polished_with_llm INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_qa_llm_review_items_batch_id
ON qa_llm_review_items(batch_id, id);
CREATE INDEX IF NOT EXISTS idx_qa_llm_review_items_status
ON qa_llm_review_items(status, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_llm_review_items_open_job
ON qa_llm_review_items(job_id)
WHERE status IN ('queued', 'reviewing');
CREATE TABLE IF NOT EXISTS tailoring_ready_bucket_state (
    job_id INTEGER PRIMARY KEY,
    bucket TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tailoring_ready_bucket_state_bucket
ON tailoring_ready_bucket_state(bucket, updated_at);
CREATE TABLE IF NOT EXISTS tailoring_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_slug TEXT NOT NULL UNIQUE,
    job_id INTEGER NOT NULL,
    model TEXT,
    timestamp TEXT NOT NULL,
    total_wall_time_s REAL,
    queue_wait_s REAL,
    analysis_time_s REAL,
    analysis_llm_time_s REAL,
    analysis_llm_calls INTEGER,
    resume_time_s REAL,
    resume_llm_time_s REAL,
    resume_llm_calls INTEGER,
    resume_attempts INTEGER,
    cover_time_s REAL,
    cover_llm_time_s REAL,
    cover_llm_calls INTEGER,
    cover_attempts INTEGER,
    compile_resume_s REAL,
    compile_cover_s REAL,
    total_llm_calls INTEGER,
    total_llm_time_s REAL
);
CREATE INDEX IF NOT EXISTS idx_tailoring_metrics_job_id ON tailoring_metrics(job_id);
"""
_LEGACY_DECISION_MAP = {
    "accept": "qa_pending",
    "manual": "qa_pending",
    "manual_approved": "qa_approved",
}
_QUEUE_OPEN_STATUSES = ("queued", "running")
_READY_BUCKET_VALUES = ("backlog", "next", "later")
_DEFAULT_READY_BUCKET = "backlog"
_WORKFLOW_DB_INIT_CACHE: set[str] = set()

_TAILORING_RUNNER: dict = {
    "proc": None,
    "log_handle": None,
    "job": None,
    "queue_item_id": None,
    "started_at": None,
    "ended_at": None,
    "exit_code": None,
    "log_path": None,
    "cmd": None,
    "stop_reason": None,
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
    "llm_provider": os.environ.get("LLM_PROVIDER", "ollama"),
    "llm_base_url": os.environ.get("LLM_URL", "http://localhost:11434"),
    "llm_model": os.environ.get(
        "TAILOR_LLM_MODEL",
        os.environ.get("TAILOR_OLLAMA_MODEL", ""),
    ),
    "schedule_interval_minutes": None,
    "schedule_started_at": None,
    "schedule_stop_at": None,
}

app = FastAPI(title="Job Scraper Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Recover MLX server state if one is already running on the default port.
from services.mlx_manager import recover_on_startup
recover_on_startup()

from services import scrape_scheduler as _scrape_scheduler
from services import run_reviewer as _run_reviewer
from services import auto_qa_review as _auto_qa_review


@app.on_event("startup")
async def _scrape_scheduler_startup():
    if _scrape_scheduler.enabled():
        await _scrape_scheduler.start()
    await _run_reviewer.start()
    await _auto_qa_review.start()


@app.on_event("shutdown")
async def _scrape_scheduler_shutdown():
    if _scrape_scheduler.enabled():
        await _scrape_scheduler.stop()
    await _run_reviewer.stop()
    await _auto_qa_review.stop()


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    _ensure_workflow_schema()
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_db_write() -> sqlite3.Connection:
    _ensure_workflow_schema()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_applied_tables() -> None:
    db_file = Path(DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(_WORKFLOW_DB_SCHEMA)
        conn.executescript(_APPLIED_DB_SCHEMA)
        _ensure_applied_protection(conn)
        conn.commit()
    finally:
        conn.close()


def _ensure_applied_protection(conn: sqlite3.Connection) -> None:
    existing_tables = {
        row["name"] if isinstance(row, sqlite3.Row) else row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "results" in existing_tables:
        conn.executescript(_APPLIED_RESULTS_PROTECTION_SCHEMA)
    if "tailoring_queue_items" in existing_tables:
        conn.executescript(_APPLIED_QUEUE_PROTECTION_SCHEMA)


def _normalize_decision(decision: str | None) -> str | None:
    return _LEGACY_DECISION_MAP.get(decision or "", decision)


def _fetch_protected_job_ids(conn: sqlite3.Connection) -> list[int]:
    _ensure_applied_tables()
    rows = conn.execute(
        "SELECT DISTINCT job_id FROM applied_applications WHERE job_id IS NOT NULL ORDER BY job_id"
    ).fetchall()
    return [int(row["job_id"] if isinstance(row, sqlite3.Row) else row[0]) for row in rows]


def _ensure_workflow_schema(force: bool = False) -> None:
    db_key = str(Path(DB_PATH).expanduser())
    if not force and db_key in _WORKFLOW_DB_INIT_CACHE:
        return

    db_file = Path(DB_PATH).expanduser()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_WORKFLOW_DB_SCHEMA)
        conn.executescript(_APPLIED_DB_SCHEMA)
        existing_tables = {
            row["name"] if isinstance(row, sqlite3.Row) else row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        _ensure_applied_protection(conn)
        if "jobs" in existing_tables:
            cols = {
                row["name"] if isinstance(row, sqlite3.Row) else row[1]
                for row in conn.execute("PRAGMA table_info(jobs)")
            }
            if "approved_jd_text" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN approved_jd_text TEXT")
        if "seen_urls" in existing_tables:
            seen_cols = {
                row["name"] if isinstance(row, sqlite3.Row) else row[1]
                for row in conn.execute("PRAGMA table_info(seen_urls)")
            }
            if "permanently_rejected" not in seen_cols:
                conn.execute(
                    "ALTER TABLE seen_urls ADD COLUMN permanently_rejected INTEGER NOT NULL DEFAULT 0"
                )
        if "qa_llm_review_batches" in existing_tables:
            batch_cols = {
                row["name"] if isinstance(row, sqlite3.Row) else row[1]
                for row in conn.execute("PRAGMA table_info(qa_llm_review_batches)")
            }
            if "trigger_source" not in batch_cols:
                conn.execute(
                    "ALTER TABLE qa_llm_review_batches ADD COLUMN trigger_source TEXT NOT NULL DEFAULT 'manual'"
                )
            if "queued_count" not in batch_cols:
                conn.execute(
                    "ALTER TABLE qa_llm_review_batches ADD COLUMN queued_count INTEGER NOT NULL DEFAULT 0"
                )
            if "report_json" not in batch_cols:
                conn.execute("ALTER TABLE qa_llm_review_batches ADD COLUMN report_json TEXT")
            if "report_generated_at" not in batch_cols:
                conn.execute("ALTER TABLE qa_llm_review_batches ADD COLUMN report_generated_at TEXT")
        if "applied_snapshots" in existing_tables:
            snap_cols = {
                row["name"] if isinstance(row, sqlite3.Row) else row[1]
                for row in conn.execute("PRAGMA table_info(applied_snapshots)")
            }
            if "grounding" not in snap_cols:
                conn.execute("ALTER TABLE applied_snapshots ADD COLUMN grounding TEXT")
            if "grounding_audit" not in snap_cols:
                conn.execute("ALTER TABLE applied_snapshots ADD COLUMN grounding_audit TEXT")
        if "jobs" in existing_tables:
            conn.execute(
                """
                UPDATE jobs
                SET status = CASE
                    WHEN status IN ('accept', 'manual') THEN 'qa_pending'
                    WHEN status = 'manual_approved' THEN 'qa_approved'
                    ELSE status
                END
                WHERE status IN ('accept', 'manual', 'manual_approved')
                """
            )
        conn.commit()
    finally:
        conn.close()
    _WORKFLOW_DB_INIT_CACHE.add(db_key)


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
        # Auto-migrate legacy lmstudio → ollama.
        if controls["llm_provider"] in ("lmstudio", "openai"):
            controls["llm_provider"] = "ollama"
            controls["llm_base_url"] = "http://localhost:11434"
            raw["llm_provider"] = "ollama"
            raw["llm_base_url"] = "http://localhost:11434"
            try:
                RUNTIME_CONTROLS_PATH.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            except Exception:
                pass
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
        controls["llm_model"] = str(updates["llm_model"] or "").strip()
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
    for suffix in ("/v1/chat/completions", "/v1/models", "/api/tags", "/api/pull", "/api/show"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return value.rstrip("/") or _DEFAULT_RUNTIME_CONTROLS["llm_base_url"]


def _resolve_llm_runtime(controls: dict | None = None) -> dict:
    from providers import PROVIDERS
    from services.llm_keys import get_key

    controls = controls or _load_runtime_controls()
    provider = str(controls.get("llm_provider") or "ollama").strip().lower()

    # Look up provider in registry; map legacy values.
    provider_def = PROVIDERS.get(provider)
    if provider_def is None:
        # Legacy "lmstudio"/"openai" → ollama.
        provider = "ollama"
        provider_def = PROVIDERS["ollama"]

    # Base URL: use controls override for local/custom providers, else registry default.
    if provider in ("ollama", "mlx", "custom"):
        base_url = _normalize_llm_base_url(
            str(controls.get("llm_base_url") or provider_def["base_url"] or _DEFAULT_RUNTIME_CONTROLS["llm_base_url"])
        )
    else:
        base_url = provider_def["base_url"].rstrip("/")

    selected_model = str(controls.get("llm_model") or "").strip()

    # Gemini's OpenAI-compat base already includes /openai — don't double-add /v1.
    if provider == "gemini":
        chat_url = f"{base_url}/chat/completions"
        models_url = f"{base_url}/models"
    else:
        chat_url = f"{base_url}/v1/chat/completions"
        models_url = f"{base_url}/v1/models"

    api_key = get_key(provider) or ""

    return {
        "provider": provider,
        "base_url": base_url,
        "chat_url": chat_url,
        "models_url": models_url,
        "manage_models": provider == "ollama",
        "selected_model": selected_model,
        "api_key": api_key,
    }


def _fetch_runtime_models(runtime: dict, *, timeout: int = 3) -> tuple[list[dict], list[dict]]:
    api_key = runtime.get("api_key", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(runtime["models_url"], headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    v1_models = data.get("data", []) or []

    manage_models: list[dict] = []
    if runtime.get("manage_models"):
        req = urllib.request.Request(f"{runtime['base_url']}/api/tags", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            manage_data = json.loads(resp.read().decode("utf-8"))
        for item in manage_data.get("models", []) or []:
            model_name = str(item.get("name") or item.get("model") or "").strip()
            if not model_name:
                continue
            manage_models.append(
                {
                    "id": model_name,
                    "state": "loaded",
                    "type": "embeddings" if "embed" in model_name.lower() else "llm",
                    "size": item.get("size", 0),
                }
            )
    return v1_models, manage_models


def _resolve_runtime_model_id(
    runtime: dict,
    *,
    v1_models: list[dict] | None = None,
    manage_models: list[dict] | None = None,
) -> str | None:
    model_id = str(runtime.get("selected_model") or "default").strip() or "default"
    manage_models = manage_models or []

    if runtime.get("manage_models"):
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
            raise RuntimeError(f"Selected model '{model_id}' is not loaded.")
        return loaded[0] if loaded else None

    if model_id != "default":
        return model_id
    for item in v1_models or []:
        candidate = str(item.get("id") or "").strip()
        if candidate:
            return candidate
    return None


def _resolve_tailoring_subprocess_runtime() -> dict:
    """Resolve a reachable LLM runtime for background tailoring runs.

    Prefer the active runtime-controls selection. If that provider is unreachable
    and it is not already Ollama, fall back to local Ollama when it has a usable
    non-embedding model. This keeps dashboard-triggered runs working when MLX is
    selected but offline.
    """
    from providers import PROVIDERS

    controls = _load_runtime_controls()
    active_provider = str(controls.get("llm_provider") or "ollama").strip().lower()
    candidate_controls = [dict(controls)]
    if active_provider != "ollama":
        fallback_controls = dict(controls)
        fallback_controls["llm_provider"] = "ollama"
        fallback_controls["llm_base_url"] = PROVIDERS["ollama"]["base_url"]
        # An MLX/custom-selected model often doesn't exist in Ollama. Let the
        # fallback auto-pick the first usable local model instead.
        fallback_controls["llm_model"] = "default"
        candidate_controls.append(fallback_controls)

    errors: list[str] = []
    for candidate in candidate_controls:
        runtime = _resolve_llm_runtime(candidate)
        try:
            v1_models, manage_models = _fetch_runtime_models(runtime, timeout=3)
            model_id = _resolve_runtime_model_id(runtime, v1_models=v1_models, manage_models=manage_models)
            if not model_id:
                raise RuntimeError("No LLM model available")
            runtime = dict(runtime)
            runtime["selected_model"] = model_id
            if runtime["provider"] != active_provider:
                logger.warning(
                    "Active LLM provider '%s' unavailable for tailoring run; falling back to '%s' with model '%s'",
                    active_provider,
                    runtime["provider"],
                    model_id,
                )
            return runtime
        except Exception as exc:
            errors.append(f"{runtime['provider']}: {exc}")

    raise RuntimeError("No reachable LLM runtime for tailoring run (" + "; ".join(errors) + ")")


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
    try:
        conn = get_db()
    except sqlite3.Error:
        return {}
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
    try:
        conn = get_db()
    except sqlite3.Error:
        return {}
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
    try:
        conn = get_db()
    except sqlite3.Error:
        return None
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
    try:
        conn = get_db()
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            """
            SELECT aa.id, aa.package_slug, aa.job_id, aa.job_title, aa.company_name, aa.job_url,
                   aa.application_url, aa.applied_at, aa.status, aa.follow_up_at, aa.notes,
                   aa.created_at, aa.updated_at, aa.status_updated_at,
                   s.meta, s.job_context, s.analysis, s.grounding, s.grounding_audit,
                   s.resume_strategy, s.cover_strategy,
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
        cols = conn.execute("PRAGMA table_info(jobs)").fetchall()
    except Exception:
        return False
    for col in cols:
        name = col["name"] if isinstance(col, sqlite3.Row) else col[1]
        if name == column:
            return True
    return False


def _job_is_qa_ready(decision: str | None) -> bool:
    return _normalize_decision(decision) == "qa_approved"


def _job_is_qa_pending(decision: str | None) -> bool:
    return _normalize_decision(decision) == "qa_pending"


def _queue_row_to_payload(row: sqlite3.Row | dict) -> dict:
    record = dict(row)
    return {
        "id": int(record["id"]),
        "job_id": int(record["job_id"]),
        "skip_analysis": bool(record.get("skip_analysis")),
        "status": record.get("status"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "run_slug": record.get("run_slug"),
        "error": record.get("error"),
        "job": {
            "id": int(record["job_id"]),
            "title": record.get("title"),
            "created_at": record.get("job_created_at"),
            "url": record.get("url"),
        },
    }


def _normalize_ready_bucket(bucket: str | None) -> str:
    value = (bucket or "").strip().lower()
    return value if value in _READY_BUCKET_VALUES else _DEFAULT_READY_BUCKET


def _fetch_ready_bucket_rows(
    conn: sqlite3.Connection,
    *,
    job_ids: list[int] | None = None,
) -> list[sqlite3.Row]:
    params: list[object] = []
    where = ""
    if job_ids:
        placeholders = ",".join("?" for _ in job_ids)
        where = f"WHERE job_id IN ({placeholders})"
        params.extend(int(job_id) for job_id in job_ids)
    return conn.execute(
        f"""
        SELECT job_id, bucket, updated_at
        FROM tailoring_ready_bucket_state
        {where}
        """,
        tuple(params),
    ).fetchall()


def _fetch_ready_bucket_map(
    conn: sqlite3.Connection,
    *,
    job_ids: list[int] | None = None,
) -> dict[int, dict]:
    bucket_map: dict[int, dict] = {}
    for row in _fetch_ready_bucket_rows(conn, job_ids=job_ids):
        record = dict(row)
        job_id = int(record["job_id"])
        bucket_map[job_id] = {
            "bucket": _normalize_ready_bucket(record.get("bucket")),
            "updated_at": record.get("updated_at"),
        }
    return bucket_map


def _set_ready_bucket_for_job_ids_in_conn(conn: sqlite3.Connection, job_ids: list[int], bucket: str) -> int:
    normalized = _normalize_ready_bucket(bucket)
    unique_job_ids = sorted({int(job_id) for job_id in job_ids if job_id is not None})
    if not unique_job_ids:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    if normalized == _DEFAULT_READY_BUCKET:
        placeholders = ",".join("?" for _ in unique_job_ids)
        cur = conn.execute(
            f"DELETE FROM tailoring_ready_bucket_state WHERE job_id IN ({placeholders})",
            tuple(unique_job_ids),
        )
    else:
        cur = conn.executemany(
            """
            INSERT INTO tailoring_ready_bucket_state (job_id, bucket, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                bucket = excluded.bucket,
                updated_at = excluded.updated_at
            """,
            [(job_id, normalized, now) for job_id in unique_job_ids],
        )
    return max(int(cur.rowcount or 0), 0)


def _set_ready_bucket_for_job_ids(job_ids: list[int], bucket: str) -> int:
    conn = get_db_write()
    try:
        updated = _set_ready_bucket_for_job_ids_in_conn(conn, job_ids, bucket)
        conn.commit()
        return updated
    finally:
        conn.close()


def _fetch_tailoring_queue_rows(
    conn: sqlite3.Connection,
    *,
    statuses: tuple[str, ...] | None = None,
    job_ids: list[int] | None = None,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[object] = []
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        clauses.append(f"q.status IN ({placeholders})")
        params.extend(statuses)
    if job_ids:
        placeholders = ",".join("?" for _ in job_ids)
        clauses.append(f"q.job_id IN ({placeholders})")
        params.extend(int(job_id) for job_id in job_ids)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.execute(
        f"""
        SELECT q.id, q.job_id, q.skip_analysis, q.status, q.run_slug, q.error,
               q.created_at, q.updated_at, q.started_at, q.finished_at,
               r.title, r.url, r.created_at AS job_created_at
        FROM tailoring_queue_items q
        LEFT JOIN results r ON r.id = q.job_id
        {where}
        ORDER BY CASE q.status
            WHEN 'running' THEN 0
            WHEN 'queued' THEN 1
            ELSE 2
        END,
        q.id ASC
        """,
        tuple(params),
    ).fetchall()


def _fetch_tailoring_queue_items(
    conn: sqlite3.Connection,
    *,
    statuses: tuple[str, ...] | None = None,
    job_ids: list[int] | None = None,
) -> list[dict]:
    return [_queue_row_to_payload(row) for row in _fetch_tailoring_queue_rows(conn, statuses=statuses, job_ids=job_ids)]


def _reconcile_stale_tailoring_queue(conn: sqlite3.Connection) -> int:
    proc = _TAILORING_RUNNER.get("proc")
    if proc is not None and proc.poll() is None:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """
        UPDATE tailoring_queue_items
        SET status = 'failed',
            error = COALESCE(error, ?),
            updated_at = ?,
            finished_at = COALESCE(finished_at, ?)
        WHERE status = 'running'
        """,
        ("Tailoring runner state was lost before completion.", now, now),
    )
    return max(int(cur.rowcount or 0), 0)


def _enqueue_tailoring_queue_items(items: list[dict]) -> tuple[list[dict], list[dict]]:
    if not items:
        return [], []
    conn = get_db_write()
    try:
        if _reconcile_stale_tailoring_queue(conn):
            conn.commit()
        added: list[dict] = []
        duplicates: list[dict] = []
        now = datetime.now(timezone.utc).isoformat()
        for item in items:
            job = item["job"]
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO tailoring_queue_items (
                    job_id, skip_analysis, status, created_at, updated_at
                ) VALUES (?, ?, 'queued', ?, ?)
                """,
                (int(job["id"]), 1 if item.get("skip_analysis") else 0, now, now),
            )
            if cur.rowcount > 0:
                row = conn.execute(
                    """
                    SELECT q.id, q.job_id, q.skip_analysis, q.status, q.run_slug, q.error,
                           q.created_at, q.updated_at, q.started_at, q.finished_at,
                           r.title, r.url, r.created_at AS job_created_at
                    FROM tailoring_queue_items q
                    LEFT JOIN results r ON r.id = q.job_id
                    WHERE q.id = ?
                    """,
                    (cur.lastrowid,),
                ).fetchone()
                if row:
                    added.append(_queue_row_to_payload(row))
                continue
            existing = conn.execute(
                """
                SELECT q.id, q.job_id, q.skip_analysis, q.status, q.run_slug, q.error,
                       q.created_at, q.updated_at, q.started_at, q.finished_at,
                       r.title, r.url, r.created_at AS job_created_at
                FROM tailoring_queue_items q
                LEFT JOIN results r ON r.id = q.job_id
                WHERE q.job_id = ? AND q.status IN ('queued', 'running')
                ORDER BY CASE q.status WHEN 'running' THEN 0 ELSE 1 END, q.id ASC
                LIMIT 1
                """,
                (int(job["id"]),),
            ).fetchone()
            if existing:
                duplicates.append(_queue_row_to_payload(existing))
        conn.commit()
        return added, duplicates
    finally:
        conn.close()


def _cancel_tailoring_queue_items(
    *,
    conn: sqlite3.Connection | None = None,
    statuses: tuple[str, ...] = ("queued",),
    job_ids: list[int] | None = None,
    item_ids: list[int] | None = None,
    reason: str | None = None,
) -> int:
    owns_conn = conn is None
    if conn is None:
        conn = get_db_write()
    try:
        if _reconcile_stale_tailoring_queue(conn):
            if owns_conn:
                conn.commit()
        clauses: list[str] = []
        params: list[object] = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(statuses)
        if job_ids:
            placeholders = ",".join("?" for _ in job_ids)
            clauses.append(f"job_id IN ({placeholders})")
            params.extend(int(job_id) for job_id in job_ids)
        if item_ids:
            placeholders = ",".join("?" for _ in item_ids)
            clauses.append(f"id IN ({placeholders})")
            params.extend(int(item_id) for item_id in item_ids)
        if not clauses:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        assignments = [
            "status = 'cancelled'",
            "updated_at = ?",
            "finished_at = COALESCE(finished_at, ?)",
        ]
        update_params: list[object] = [now, now]
        if reason:
            assignments.append("error = COALESCE(error, ?)")
            update_params.append(reason)

        cur = conn.execute(
            f"""
            UPDATE tailoring_queue_items
            SET {", ".join(assignments)}
            WHERE {' AND '.join(clauses)}
            """,
            tuple(update_params + params),
        )
        if owns_conn:
            conn.commit()
        return max(int(cur.rowcount or 0), 0)
    finally:
        if owns_conn:
            conn.close()


def _stop_active_tailoring_job(job_ids: list[int], reason: str) -> bool:
    proc = _TAILORING_RUNNER.get("proc")
    active_job = _TAILORING_RUNNER.get("job") or {}
    try:
        active_job_id = int(active_job.get("id"))
    except (TypeError, ValueError, AttributeError):
        active_job_id = None
    if proc is None or proc.poll() is not None or active_job_id is None or active_job_id not in {int(job_id) for job_id in job_ids}:
        return False
    _TAILORING_RUNNER["stop_reason"] = reason
    try:
        proc.terminate()
    except Exception:
        return False
    return True


def _latest_run_slug_for_job_since(job_id: int, started_at: str | None = None) -> str | None:
    if not TAILORING_OUTPUT_DIR.exists():
        return None
    started_ts = _parse_ts(started_at)
    best_slug = None
    best_ts = 0.0
    for d in TAILORING_OUTPUT_DIR.iterdir():
        if not d.is_dir():
            continue
        meta_path = d / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if int(meta.get("job_id", -1)) != int(job_id):
                continue
        except Exception:
            continue
        updated_ts = d.stat().st_mtime
        if started_ts and updated_ts + 1 < started_ts:
            continue
        if updated_ts >= best_ts:
            best_ts = updated_ts
            best_slug = d.name
    return best_slug


def _get_job_context(job_id: int) -> dict | None:
    conn = get_db()
    try:
        jd_expr = "jd_text"
        if _results_has_column(conn, "approved_jd_text"):
            jd_expr = "COALESCE(approved_jd_text, jd_text)"
        select_cols = [
            "id",
            "url",
            "title",
            "snippet",
            f"{jd_expr} AS jd_text",
            "query",
            "run_id",
            "created_at",
            "decision",
            "board",
            "seniority",
            "company" if _results_has_column(conn, "company") else "NULL AS company",
            "source" if _results_has_column(conn, "source") else "NULL AS source",
            "location" if _results_has_column(conn, "location") else "NULL AS location",
            "salary_k" if _results_has_column(conn, "salary_k") else "NULL AS salary_k",
        ]
        row = conn.execute(
            f"SELECT {', '.join(select_cols)} "
            "FROM results WHERE id = ?",
            (job_id,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["decision"] = _normalize_decision(data.get("decision"))
        return data
    finally:
        conn.close()


def _latest_job(max_age_hours: int | None = None) -> dict | None:
    conn = get_db()
    try:
        clauses = [
            "decision = 'qa_approved'",
            "NOT EXISTS (SELECT 1 FROM applied_applications aa WHERE aa.job_id = results.id)",
        ]
        params: list[object] = []
        if max_age_hours is not None:
            clauses.append("julianday(created_at) >= julianday('now', ?)")
            params.append(f"-{int(max_age_hours)} hours")
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM tailoring_queue_items q WHERE q.job_id = results.id AND q.status IN ('queued', 'running'))"
        )
        where = "WHERE " + " AND ".join(clauses)
        row = conn.execute(
            f"SELECT id, title, created_at, url FROM results {where} ORDER BY id DESC LIMIT 1",
            tuple(params),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _ready_job_query_parts(
    conn: sqlite3.Connection,
    *,
    max_age_hours: int | None = None,
    board: str | None = None,
    source: str | None = None,
    seniority: str | None = None,
    location: str | None = None,
    search: str | None = None,
) -> tuple[list[str], list[object], dict[str, bool]]:
    available = {
        "company": _results_has_column(conn, "company"),
        "source": _results_has_column(conn, "source"),
        "location": _results_has_column(conn, "location"),
        "salary_k": _results_has_column(conn, "salary_k"),
    }
    clauses = [
        "decision = 'qa_approved'",
        "NOT EXISTS (SELECT 1 FROM applied_applications aa WHERE aa.job_id = results.id)",
    ]
    params: list[object] = []
    if max_age_hours is not None:
        clauses.append("julianday(created_at) >= julianday('now', ?)")
        params.append(f"-{int(max_age_hours)} hours")
    if board:
        board_values = [value.strip().lower() for value in board.split(",") if value.strip()]
        if board_values:
            placeholders = ",".join("?" for _ in board_values)
            clauses.append(f"LOWER(COALESCE(board, '')) IN ({placeholders})")
            params.extend(board_values)
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
    if seniority:
        clauses.append("LOWER(COALESCE(seniority, '')) = ?")
        params.append(seniority.strip().lower())
    if location and available["location"]:
        clauses.append("LOWER(COALESCE(location, '')) LIKE ?")
        params.append(f"%{location.strip().lower()}%")
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
    return clauses, params, available


def _recent_jobs(
    limit: int = 25,
    max_age_hours: int | None = None,
    *,
    board: str | None = None,
    source: str | None = None,
    seniority: str | None = None,
    location: str | None = None,
    search: str | None = None,
    bucket: str | None = None,
) -> list[dict]:
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
        clauses, params, available = _ready_job_query_parts(
            conn,
            max_age_hours=max_age_hours,
            board=board,
            source=source,
            seniority=seniority,
            location=location,
            search=search,
        )
        bucket_value = None
        if bucket and bucket.strip().lower() != "all":
            bucket_value = _normalize_ready_bucket(bucket)
            if bucket_value == _DEFAULT_READY_BUCKET:
                clauses.append("NOT EXISTS (SELECT 1 FROM tailoring_ready_bucket_state b WHERE b.job_id = results.id)")
            else:
                clauses.append("EXISTS (SELECT 1 FROM tailoring_ready_bucket_state b WHERE b.job_id = results.id AND b.bucket = ?)")
                params.append(bucket_value)
        where = "WHERE " + " AND ".join(clauses)
        params.append(max(1, min(int(limit), 2000)))
        select_cols = [
            "id",
            "title",
            "created_at",
            "url",
            "snippet",
            "board",
            "seniority",
            "company" if available["company"] else "NULL AS company",
            "source" if available["source"] else "NULL AS source",
            "location" if available["location"] else "NULL AS location",
            "salary_k" if available["salary_k"] else "NULL AS salary_k",
        ]
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM results {where} ORDER BY id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        items = [dict(r) for r in rows]
        bucket_by_job_id = _fetch_ready_bucket_map(conn, job_ids=[int(item["id"]) for item in items if item.get("id") is not None])
        applied_by_job_id = _fetch_applied_by_job_ids([int(item["id"]) for item in items if item.get("id") is not None])
        open_queue_by_job_id = {}
        if items:
            queue_conn = get_db_write()
            try:
                if _reconcile_stale_tailoring_queue(queue_conn):
                    queue_conn.commit()
                open_queue_items = _fetch_tailoring_queue_items(
                    queue_conn,
                    statuses=_QUEUE_OPEN_STATUSES,
                    job_ids=[int(item["id"]) for item in items if item.get("id") is not None],
                )
            finally:
                queue_conn.close()
            for queue_item in open_queue_items:
                open_queue_by_job_id.setdefault(int(queue_item["job_id"]), queue_item)
        for item in items:
            count = run_counts_by_job.get(int(item["id"]), 0)
            item["tailoring_run_count"] = count
            item["has_tailoring_runs"] = count > 0
            item["tailoring_latest_status"] = (latest_status_by_job.get(int(item["id"])) or {}).get("status")
            item["applied"] = applied_by_job_id.get(int(item["id"]))
            item["queue_item"] = open_queue_by_job_id.get(int(item["id"]))
            bucket_meta = bucket_by_job_id.get(int(item["id"])) or {}
            item["ready_bucket"] = bucket_meta.get("bucket", _DEFAULT_READY_BUCKET)
            item["ready_bucket_updated_at"] = bucket_meta.get("updated_at")
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
    while True:
        conn = get_db_write()
        try:
            if _reconcile_stale_tailoring_queue(conn):
                conn.commit()
            row = conn.execute(
                """
                SELECT q.id, q.job_id, q.skip_analysis,
                       r.title, r.url, r.created_at, r.decision
                FROM tailoring_queue_items q
                LEFT JOIN results r ON r.id = q.job_id
                WHERE q.status = 'queued'
                ORDER BY q.id ASC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return
            if row["job_id"] is None or row["title"] is None:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    UPDATE tailoring_queue_items
                    SET status = 'failed',
                        error = ?,
                        updated_at = ?,
                        finished_at = COALESCE(finished_at, ?)
                    WHERE id = ?
                    """,
                    ("Queued job no longer exists.", now, now, row["id"]),
                )
                conn.commit()
                continue
            if not _job_is_qa_ready(row["decision"]):
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    UPDATE tailoring_queue_items
                    SET status = 'cancelled',
                        error = ?,
                        updated_at = ?,
                        finished_at = COALESCE(finished_at, ?)
                    WHERE id = ?
                    """,
                    (f"Job is no longer ready for tailoring ({_normalize_decision(row['decision']) or 'unknown'}).", now, now, row["id"]),
                )
                conn.commit()
                continue
            item = {
                "queue_item_id": int(row["id"]),
                "job": {
                    "id": int(row["job_id"]),
                    "title": row["title"],
                    "created_at": row["created_at"],
                    "url": row["url"],
                },
                "skip_analysis": bool(row["skip_analysis"]),
            }
        finally:
            conn.close()
        _start_tailoring_run(item["job"], skip_analysis=item["skip_analysis"], queue_item_id=item["queue_item_id"])
        return


def _ingest_tailoring_metrics(conn: sqlite3.Connection, run_slug: str, queue_item_id: int | None) -> None:
    """Read metrics.json from a completed run and insert into tailoring_metrics table."""
    try:
        # Find the output dir for this run_slug
        candidates = sorted(TAILORING_OUTPUT_DIR.glob(f"*{run_slug}*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            # Try exact match
            candidate = TAILORING_OUTPUT_DIR / run_slug
            if candidate.exists():
                candidates = [candidate]
        if not candidates:
            return
        metrics_path = candidates[0] / "metrics.json"
        if not metrics_path.exists():
            return
        metrics = json.loads(metrics_path.read_text())

        # Compute queue_wait_s from queue item timestamps
        queue_wait = None
        if queue_item_id is not None:
            row = conn.execute(
                "SELECT created_at, started_at FROM tailoring_queue_items WHERE id = ?",
                (int(queue_item_id),),
            ).fetchone()
            if row and row["created_at"] and row["started_at"]:
                try:
                    created = datetime.fromisoformat(row["created_at"])
                    started = datetime.fromisoformat(row["started_at"])
                    queue_wait = (started - created).total_seconds()
                except (ValueError, TypeError):
                    pass

        conn.execute(
            """
            INSERT OR REPLACE INTO tailoring_metrics (
                run_slug, job_id, model, timestamp,
                total_wall_time_s, queue_wait_s,
                analysis_time_s, analysis_llm_time_s, analysis_llm_calls,
                resume_time_s, resume_llm_time_s, resume_llm_calls, resume_attempts,
                cover_time_s, cover_llm_time_s, cover_llm_calls, cover_attempts,
                compile_resume_s, compile_cover_s,
                total_llm_calls, total_llm_time_s
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metrics.get("run_slug"), metrics.get("job_id"), metrics.get("model"),
                metrics.get("timestamp"),
                metrics.get("total_wall_time_s"), queue_wait,
                metrics.get("analysis_time_s"), metrics.get("analysis_llm_time_s"),
                metrics.get("analysis_llm_calls"),
                metrics.get("resume_time_s"), metrics.get("resume_llm_time_s"),
                metrics.get("resume_llm_calls"), metrics.get("resume_attempts"),
                metrics.get("cover_time_s"), metrics.get("cover_llm_time_s"),
                metrics.get("cover_llm_calls"), metrics.get("cover_attempts"),
                metrics.get("compile_resume_s"), metrics.get("compile_cover_s"),
                metrics.get("total_llm_calls"), metrics.get("total_llm_time_s"),
            ),
        )
    except Exception as e:
        logging.getLogger(__name__).warning("Failed to ingest tailoring metrics: %s", e)


TAILORING_MAX_WALL_TIME_S = 2700  # 45 minutes — kill job if exceeded


def _tailoring_runner_snapshot(log_lines: int = 80) -> dict:
    proc = _TAILORING_RUNNER.get("proc")
    if proc is not None:
        # Watchdog: kill jobs that exceed max wall time
        started_at = _TAILORING_RUNNER.get("started_at")
        if started_at and proc.poll() is None:
            try:
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds()
                if elapsed > TAILORING_MAX_WALL_TIME_S:
                    logger.warning("Tailoring job exceeded %ds wall time (%.0fs elapsed), killing PID %d",
                                   TAILORING_MAX_WALL_TIME_S, elapsed, proc.pid)
                    proc.kill()
                    proc.wait(timeout=5)
                    _TAILORING_RUNNER["stop_reason"] = f"Killed: exceeded {TAILORING_MAX_WALL_TIME_S}s wall time"
            except Exception:
                pass
        rc = proc.poll()
        if rc is not None:
            now = datetime.now(timezone.utc).isoformat()
            _TAILORING_RUNNER["exit_code"] = rc
            _TAILORING_RUNNER["ended_at"] = _TAILORING_RUNNER.get("ended_at") or now
            queue_item_id = _TAILORING_RUNNER.get("queue_item_id")
            if queue_item_id is not None:
                job = _TAILORING_RUNNER.get("job") or {}
                run_slug = None
                if job.get("id") is not None:
                    try:
                        run_slug = _latest_run_slug_for_job_since(int(job["id"]), _TAILORING_RUNNER.get("started_at"))
                    except (TypeError, ValueError):
                        run_slug = None
                stop_reason = _TAILORING_RUNNER.get("stop_reason")
                status = "cancelled" if stop_reason else ("succeeded" if rc == 0 else "failed")
                error = stop_reason or (None if rc == 0 else f"Tailoring exited with code {rc}")
                conn = get_db_write()
                try:
                    conn.execute(
                        """
                        UPDATE tailoring_queue_items
                        SET status = ?,
                            run_slug = COALESCE(?, run_slug),
                            error = ?,
                            updated_at = ?,
                            finished_at = COALESCE(finished_at, ?)
                        WHERE id = ?
                        """,
                        (status, run_slug, error, now, now, int(queue_item_id)),
                    )
                    # Ingest metrics if run succeeded
                    if status == "succeeded" and run_slug:
                        _ingest_tailoring_metrics(conn, run_slug, queue_item_id)
                    conn.commit()
                finally:
                    conn.close()
            handle = _TAILORING_RUNNER.get("log_handle")
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
            _TAILORING_RUNNER["log_handle"] = None
            _TAILORING_RUNNER["proc"] = None
            _TAILORING_RUNNER["queue_item_id"] = None
            _TAILORING_RUNNER["stop_reason"] = None
            _process_tailoring_queue()

    conn = get_db_write()
    try:
        if _reconcile_stale_tailoring_queue(conn):
            conn.commit()
        active_items = _fetch_tailoring_queue_items(conn, statuses=("running",))
        queued_items = _fetch_tailoring_queue_items(conn, statuses=("queued",))
    finally:
        conn.close()

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
        "queue": queued_items,
        "active_item": active_items[0] if active_items else None,
    }


# ---------------------------------------------------------------------------
# Background queue poller — reaps finished tailoring processes and advances
# the queue even when no one is hitting the status API.
# ---------------------------------------------------------------------------
def _tailoring_queue_poller():
    """Poll every 15s to reap finished runners, advance queue, and auto-recover MLX."""
    while True:
        time.sleep(15)
        try:
            _tailoring_runner_snapshot(log_lines=0)
        except Exception:
            pass
        # Auto-recover MLX server if provider is mlx and server is down
        try:
            controls = _load_runtime_controls()
            if controls.get("llm_provider") == "mlx":
                from services.mlx_manager import status as mlx_st, start as mlx_start
                st = mlx_st()
                if not st.get("running"):
                    model = controls.get("llm_model")
                    if model:
                        logger.warning("MLX server down — auto-restarting with model %s", model)
                        mlx_start(model)
        except Exception:
            pass

_poller_thread = threading.Thread(target=_tailoring_queue_poller, daemon=True)
_poller_thread.start()


def _start_tailoring_run(job: dict, skip_analysis: bool = False, queue_item_id: int | None = None) -> tuple[bool, dict]:
    if _TAILORING_RUNNER.get("proc") is not None and _TAILORING_RUNNER["proc"].poll() is None:
        return False, {"ok": False, "error": "A tailoring run is already in progress", "runner": _tailoring_runner_snapshot()}

    if queue_item_id is not None:
        conn = get_db_write()
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE tailoring_queue_items
                SET status = 'running',
                    updated_at = ?,
                    started_at = COALESCE(started_at, ?),
                    finished_at = NULL,
                    error = NULL
                WHERE id = ?
                """,
                (now, now, int(queue_item_id)),
            )
            conn.commit()
        finally:
            conn.close()

    TAILORING_RUNNER_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = TAILORING_RUNNER_LOG_DIR / f"tailor_job_{job['id']}_{stamp}.log"

    cmd = [str(TAILORING_PYTHON), "-m", "tailor", "run", "--job-id", str(job["id"])]
    if skip_analysis:
        cmd.append("--skip-analysis")

    try:
        log_handle = log_path.open("w", encoding="utf-8")
        llm_runtime = _resolve_tailoring_subprocess_runtime()
        env = os.environ.copy()
        env["TAILOR_LLM_URL"] = llm_runtime["chat_url"]
        env["TAILOR_LLM_MODELS_URL"] = llm_runtime["models_url"]
        env["TAILOR_LLM_MODEL"] = llm_runtime["selected_model"]
        env["TAILOR_OLLAMA_URL"] = llm_runtime["chat_url"]
        env["TAILOR_OLLAMA_MODELS_URL"] = llm_runtime["models_url"]
        env["TAILOR_OLLAMA_MODEL"] = llm_runtime["selected_model"]
        env["TAILOR_LLM_API_KEY"] = llm_runtime.get("api_key", "")
        env["TAILOR_LLM_PROVIDER"] = llm_runtime["provider"]
        proc = subprocess.Popen(
            cmd,
            cwd=str(TAILORING_ROOT),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
    except Exception as e:
        if queue_item_id is not None:
            conn = get_db_write()
            try:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    UPDATE tailoring_queue_items
                    SET status = 'failed',
                        error = ?,
                        updated_at = ?,
                        finished_at = COALESCE(finished_at, ?)
                    WHERE id = ?
                    """,
                    (f"Failed to start tailoring run: {e}", now, now, int(queue_item_id)),
                )
                conn.commit()
            finally:
                conn.close()
        return False, {"ok": False, "error": f"Failed to start tailoring run: {e}"}

    _TAILORING_RUNNER.update(
        {
            "proc": proc,
            "log_handle": log_handle,
            "job": job,
            "queue_item_id": queue_item_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": None,
            "exit_code": None,
            "log_path": str(log_path),
            "cmd": " ".join(cmd),
            "stop_reason": None,
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
    """Check if the in-process scrape schedule is active."""
    controls = _load_runtime_controls()
    interval = controls.get("schedule_interval_minutes")
    return {"loaded": False, "interval_minutes": interval}


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
    stale_run_ids: list[str] = []

    if manual_running:
        return {
            "manual_running": manual_running,
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
    spider: str | None = None,
    tiers: list[str] | None = None,
    rotation_group: int | None = None,
    run_index: int | None = None,
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
    if spider:
        cmd.extend(["--spider", spider])
    if tiers:
        cmd.extend(["--tiers", ",".join(tiers)])
    if rotation_group is not None:
        cmd.extend(["--rotation-group", str(rotation_group)])
    if run_index is not None:
        cmd.extend(["--run-index", str(run_index)])

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
                "spider": spider,
                "tiers": tiers,
                "rotation_group": rotation_group,
                "run_index": run_index,
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
# Startup — no automatic scrape scheduling. Runs are UI-initiated only.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=True)
