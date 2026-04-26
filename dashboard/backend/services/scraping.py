"""Shim loader for scraping handlers owned by job-scraper/api.

Also hosts `system_status` — a read-only snapshot of scheduler + scrape_profile
state for /ops/system. Kept here because the scheduler module lives in this
process and cannot be surfaced from the job-scraper side.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sqlite3
from pathlib import Path

from fastapi import Query
from fastapi.responses import JSONResponse

# Reuse shared backend state/helpers from app module.
import app as _app
globals().update({k: v for k, v in _app.__dict__.items() if not k.startswith("__")})

_HANDLERS_PATH = Path(__file__).resolve().parents[3] / "job-scraper" / "api" / "scraping_handlers.py"
_SPEC = importlib.util.spec_from_file_location("job_scraper_api_scraping_handlers", _HANDLERS_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load scraping handlers from {_HANDLERS_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

overview = _MOD.overview
list_jobs = _MOD.list_jobs
get_job = _MOD.get_job
list_runs = _MOD.list_runs
active_runs = _MOD.active_runs
scrape_runner_status = _MOD.scrape_runner_status
run_scrape = _MOD.run_scrape
get_run = _MOD.get_run
get_run_logs = _MOD.get_run_logs
terminate_run = _MOD.terminate_run
filter_stats = _MOD.filter_stats
dedup_stats = _MOD.dedup_stats
growth = _MOD.growth
rejected_stats = _MOD.rejected_stats
list_rejected = _MOD.list_rejected
get_rejected = _MOD.get_rejected
approve_rejected = _MOD.approve_rejected
source_diagnostics = _MOD.source_diagnostics
tier_stats_rollup = _MOD.tier_stats_rollup


def _sync_app_state() -> None:
    globals().update({k: v for k, v in _app.__dict__.items() if not k.startswith("__")})


def _current_db_path() -> str | None:
    _sync_app_state()
    return getattr(_app, "DB_PATH", None) or getattr(_MOD, "DB_PATH", None)


_FLAG_KEYS = (
    "TEXTAILOR_SCRAPE_SCHEDULER",
    "DASHBOARD_RELOAD",
)


def _last_run_summary(db_path: str) -> dict | None:
    try:
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT run_id, started_at, completed_at, status, net_new, "
                "gate_mode, rotation_group FROM runs "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None
    except sqlite3.DatabaseError:
        return None


def system_status():
    from job_scraper.config import load_config
    from job_scraper.tiers import SPIDER_TIERS
    from services import scrape_scheduler

    try:
        cfg = load_config()
        profile = cfg.scrape_profile
        profile_err = None
    except Exception as exc:
        profile = None
        profile_err = str(exc)

    tiers_by_name: dict[str, list[str]] = {}
    for spider, tier in SPIDER_TIERS.items():
        tiers_by_name.setdefault(tier.value, []).append(spider)
    tiers = [
        {"tier": name, "spiders": sorted(spiders)}
        for name, spiders in sorted(tiers_by_name.items())
    ]

    scheduler_block = {
        "enabled": scrape_scheduler.enabled(),
        "cadence": profile.cadence if profile else None,
        "cadence_hours": (profile._cadence_hours() if profile else None),
        "next_run_at": scrape_scheduler.next_run_time(),
        "running": bool(_MOD.scrape_runner_status(lines=0).get("running")),
    }

    profile_block = (
        {
            "rotation_groups": profile.rotation_groups,
            "rotation_cycle_hours": profile.rotation_cycle_hours,
            "seen_ttl_days": profile.seen_ttl_days,
            "discovery_every_nth_run": profile.discovery_every_nth_run,
            "target_net_new_per_run": profile.target_net_new_per_run,
        }
        if profile
        else {"error": profile_err}
    )

    llm_gate_block = (
        {
            "enabled": profile.llm_gate.enabled,
            "endpoint": profile.llm_gate.endpoint,
            "model": profile.llm_gate.model,
            "accept_threshold": profile.llm_gate.accept_threshold,
            "max_calls_per_run": profile.llm_gate.max_calls_per_run,
            "timeout_seconds": profile.llm_gate.timeout_seconds,
            "fail_open": profile.llm_gate.fail_open,
        }
        if profile
        else {}
    )

    flags = {k: os.environ.get(k, "") for k in _FLAG_KEYS}

    db_path = _current_db_path()
    last_run = _last_run_summary(db_path) if db_path else None

    return {
        "scheduler": scheduler_block,
        "profile": profile_block,
        "llm_gate": llm_gate_block,
        "tiers": tiers,
        "feature_flags": flags,
        "last_run": last_run,
    }


def _row_to_review(row) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    raw = data.pop("llm_review", None)
    data["review"] = _loads_json(raw, None)
    members_raw = data.pop("rotation_members", None)
    data["rotation_members"] = _loads_json(members_raw, None)
    return data


def _loads_json(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _intish(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _run_job_counts(conn: sqlite3.Connection, run_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM jobs WHERE run_id = ? GROUP BY status",
        (run_id,),
    ).fetchall()
    return {str(row["status"] or "unknown"): int(row["count"] or 0) for row in rows}


def _run_source_count(conn: sqlite3.Connection, run_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM run_tier_stats WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row["count"] or 0) if row else 0


def _scraper_report_from_row(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    include_detail: bool = False,
) -> dict:
    report = _row_to_review(row) or {}
    run_id = str(report.get("run_id") or "")
    counts = _run_job_counts(conn, run_id)
    accepted = sum(count for status, count in counts.items() if status != "rejected")
    summary = {
        "raw": _intish(report.get("raw_count")),
        "dedup": _intish(report.get("dedup_count")),
        "filtered": _intish(report.get("filtered_count")),
        "net_new": _intish(report.get("net_new")),
        "errors": _intish(report.get("error_count")),
        "accepted": accepted,
        "rejected": counts.get("rejected", 0),
        "jobs": sum(counts.values()),
    }
    report["summary"] = summary
    report["job_status_counts"] = counts
    report["source_count"] = _run_source_count(conn, run_id)
    review = report.get("review") or {}
    report["review_health"] = review.get("health") if isinstance(review, dict) else None

    if include_detail:
        report["errors"] = _loads_json(report.get("errors"), [])
        report["tier_stats"] = [
            dict(r)
            for r in conn.execute(
                """SELECT tier, source, raw_hits, dedup_drops, filter_drops,
                          llm_rejects, llm_uncertain_low, llm_overflow,
                          stored_pending, stored_lead, duration_ms
                   FROM run_tier_stats
                   WHERE run_id = ?
                   ORDER BY tier, source""",
                (run_id,),
            ).fetchall()
        ]
        report["jobs"] = [
            dict(r)
            for r in conn.execute(
                """SELECT id, title, company, url, board, source, status,
                          rejection_stage, rejection_reason, seniority,
                          experience_years, salary_k, score, created_at
                   FROM jobs
                   WHERE run_id = ?
                   ORDER BY created_at DESC
                   LIMIT 500""",
                (run_id,),
            ).fetchall()
        ]
    else:
        report.pop("errors", None)

    return report


def list_run_reviews(limit: int = 20):
    """Recent completed runs with their LLM review attached (if any)."""
    db_path = _current_db_path()
    if not db_path:
        return {"runs": []}
    try:
        with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT run_id, started_at, completed_at, status, elapsed,
                          raw_count, dedup_count, filtered_count, net_new,
                          gate_mode, rotation_group, rotation_members,
                          llm_review, llm_review_at
                   FROM runs
                   WHERE status = 'completed'
                   ORDER BY completed_at DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
    except sqlite3.DatabaseError:
        return {"runs": []}
    return {"runs": [_row_to_review(r) for r in rows]}


def list_scraper_reports(limit: int = Query(50, ge=1, le=200)):
    """Recent scrape reports, one report per scrape run."""
    db_path = _current_db_path()
    if not db_path:
        return {"items": []}
    try:
        with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT run_id, started_at, completed_at, status, elapsed,
                          raw_count, dedup_count, filtered_count, error_count,
                          errors, trigger_source, net_new, gate_mode,
                          rotation_group, rotation_members, llm_review,
                          llm_review_at
                   FROM runs
                   WHERE status != 'running'
                   ORDER BY COALESCE(completed_at, started_at) DESC
                   LIMIT ?""",
                (int(limit),),
            ).fetchall()
            return {
                "items": [
                    _scraper_report_from_row(conn, row, include_detail=False)
                    for row in rows
                ]
            }
    except sqlite3.DatabaseError:
        return {"items": []}


def get_scraper_report(run_id: str):
    """Detailed scrape report for one run."""
    db_path = _current_db_path()
    if not db_path:
        return JSONResponse({"error": "DB path unavailable"}, 500)
    try:
        with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT run_id, started_at, completed_at, status, elapsed,
                          raw_count, dedup_count, filtered_count, error_count,
                          errors, trigger_source, net_new, gate_mode,
                          rotation_group, rotation_members, llm_review,
                          llm_review_at
                   FROM runs
                   WHERE run_id = ?""",
                (run_id,),
            ).fetchone()
            if not row:
                return JSONResponse({"error": "Scrape report not found"}, 404)
            return {"report": _scraper_report_from_row(conn, row, include_detail=True)}
    except sqlite3.DatabaseError as exc:
        return JSONResponse({"error": str(exc)}, 500)


def regenerate_run_review(run_id: str):
    """Force re-generate a review for the given run, bypassing the poll cadence."""
    from services import run_reviewer

    db_path = _current_db_path()
    if not db_path:
        return {"ok": False, "error": "DB path unavailable"}
    # Clear any existing review so the reviewer treats this as fresh.
    try:
        with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
            with conn:
                conn.execute(
                    "UPDATE runs SET llm_review = NULL, llm_review_at = NULL WHERE run_id = ?",
                    (run_id,),
                )
    except sqlite3.DatabaseError as exc:
        return {"ok": False, "error": str(exc)}
    review = run_reviewer.review_run(str(db_path), run_id)
    return {"ok": review is not None, "review": review}
