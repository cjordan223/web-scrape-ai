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
SCRAPER_ROOT = HERE.parent
_DEFAULT_SCRAPER_PYTHON = HERE.parent / "venv" / "bin" / "python"
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
    controls["updated_at"] = datetime.now(timezone.utc).isoformat()
    RUNTIME_CONTROLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONTROLS_PATH.write_text(
        json.dumps(
            {
                "scrape_enabled": controls["scrape_enabled"],
                "llm_enabled": controls["llm_enabled"],
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
    controls = _load_runtime_controls()
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


@app.get("/api/scrape/runner/status")
def scrape_runner_status(lines: int = Query(80, ge=0, le=500)):
    return _scrape_runner_snapshot(log_lines=lines)


@app.post("/api/scrape/run")
def run_scrape(payload: dict = Body(default={})):
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid payload"}, 400)
    dry_run = bool(payload.get("dry_run", False))
    no_fetch = bool(payload.get("no_fetch", False))
    no_crawl = bool(payload.get("no_crawl", False))
    llm_enabled_override = payload.get("llm_enabled")
    if llm_enabled_override is not None:
        llm_enabled_override = bool(llm_enabled_override)
    # Manual runs are intended for one-off testing and should bypass schedule toggle by default.
    ignore_runtime_controls = bool(payload.get("ignore_runtime_controls", True))
    ok, result = _start_scrape_run(
        dry_run=dry_run,
        no_fetch=no_fetch,
        no_crawl=no_crawl,
        ignore_runtime_controls=ignore_runtime_controls,
        llm_enabled_override=llm_enabled_override,
    )
    if not ok:
        return JSONResponse(result, 409)
    return result


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


@app.post("/api/rejected/{rejected_id}/approve")
def approve_rejected(rejected_id: int):
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
                """INSERT INTO results
                   (url, title, board, seniority, experience_years, salary_k, score, decision,
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
                    "manual_approved",
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
# Routes — API: Tailoring transparency
# ---------------------------------------------------------------------------
@app.get("/api/tailoring/runner/status")
def tailoring_runner_status(lines: int = Query(80, ge=0, le=500)):
    return _tailoring_runner_snapshot(log_lines=lines)


@app.get("/api/tailoring/jobs/recent")
def tailoring_recent_jobs(
    limit: int = Query(25, ge=1, le=100),
    max_age_hours: int | None = Query(None, ge=1, le=24 * 30),
):
    items = _recent_jobs(limit=limit, max_age_hours=max_age_hours)
    return {"items": items, "count": len(items)}


@app.post("/api/tailoring/run")
def tailoring_run_job(payload: dict = Body(...)):
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


@app.post("/api/tailoring/run-latest")
def tailoring_run_latest(payload: dict | None = Body(None)):
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


@app.get("/api/tailoring/runs")
def tailoring_runs():
    if not TAILORING_OUTPUT_DIR.exists():
        return {"runs": []}

    runs = []
    for d in sorted(TAILORING_OUTPUT_DIR.iterdir()):
        if not d.is_dir():
            continue
        runs.append(_tailoring_summary(d))

    runs.sort(key=lambda r: _parse_ts(r.get("updated_at")) or 0, reverse=True)
    return {"runs": runs}


@app.get("/api/tailoring/runs/{slug}")
def tailoring_run_detail(slug: str):
    d = _safe_tailoring_slug(slug)
    if d is None:
        return JSONResponse({"error": "Run not found"}, 404)
    return _tailoring_summary(d)


@app.get("/api/tailoring/runs/{slug}/trace")
def tailoring_trace(
    slug: str,
    doc_type: str | None = None,
    phase: str | None = None,
    attempt: int | None = None,
):
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


@app.get("/api/tailoring/runs/{slug}/artifact/{name}")
def tailoring_artifact(slug: str, name: str):
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
@app.get("/api/packages")
def package_runs(status: str = Query("complete")):
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


@app.get("/api/packages/{slug}")
def package_detail(slug: str):
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


@app.post("/api/packages/{slug}/latex/{doc_type}")
def package_save_latex(
    slug: str,
    doc_type: str,
    payload: dict = Body(...),
):
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


@app.post("/api/packages/{slug}/compile/{doc_type}")
def package_compile(slug: str, doc_type: str):
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


@app.get("/api/packages/{slug}/diff-preview/{doc_type}")
def package_diff_preview(slug: str, doc_type: str):
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
@app.get("/api/runtime-controls")
def get_runtime_controls():
    return _load_runtime_controls()


@app.post("/api/runtime-controls")
def update_runtime_controls(payload: dict = Body(default={})):
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid payload"}, 400)
    allowed = {"scrape_enabled", "llm_enabled"}
    updates = {k: payload[k] for k in allowed if k in payload}
    controls = _save_runtime_controls(updates)
    return {"ok": True, "controls": controls}


# ---------------------------------------------------------------------------
# Routes — API: LLM status
# ---------------------------------------------------------------------------
LLM_URL = os.environ.get("LLM_URL", "http://localhost:1234")


@app.get("/api/llm/status")
def llm_status():
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
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=True)
