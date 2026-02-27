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
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import urllib.error
import urllib.request

import uvicorn
from fastapi import Body, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
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


def _load_runtime_controls() -> dict:
    controls = dict(_DEFAULT_RUNTIME_CONTROLS)
    try:
        raw = json.loads(RUNTIME_CONTROLS_PATH.read_text(encoding="utf-8"))
        controls["scrape_enabled"] = bool(raw.get("scrape_enabled", controls["scrape_enabled"]))
        controls["llm_enabled"] = bool(raw.get("llm_enabled", controls["llm_enabled"]))
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


def _get_job_context(job_id: int) -> dict | None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, url, title, snippet, jd_text, query, run_id, created_at "
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
    conn = get_db()
    try:
        where = ""
        params: list = []
        if max_age_hours is not None:
            where = "WHERE julianday(created_at) >= julianday('now', ?)"
            params.append(f"-{int(max_age_hours)} hours")
        params.append(max(1, min(int(limit), 100)))
        rows = conn.execute(
            f"SELECT id, title, created_at, url FROM results {where} ORDER BY id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return [dict(r) for r in rows]
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
        proc = subprocess.Popen(
            cmd,
            cwd=str(TAILORING_ROOT),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
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
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM runs WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


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

# Serve static assets from the vite build
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")
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
from services import ops as ops_handlers
from services import scraping as scraping_handlers
from services import tailoring as tailoring_handlers


def _register_routes() -> None:
    handlers = {
        **{name: getattr(scraping_handlers, name) for _, _, name in scraping_routes.ROUTES},
        **{name: getattr(tailoring_handlers, name) for _, _, name in tailoring_routes.ROUTES},
        **{name: getattr(ops_handlers, name) for _, _, name in ops_routes.ROUTES},
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
