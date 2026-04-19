"""Shim loader for scraping handlers owned by job-scraper/api.

Also hosts `system_status` — a read-only snapshot of scheduler + scrape_profile
state for /ops/system. Kept here because the scheduler module lives in this
process and cannot be surfaced from the job-scraper side.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
from pathlib import Path

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


_FLAG_KEYS = (
    "TEXTAILOR_SCRAPE_SCHEDULER",
    "TEXTAILOR_MANAGE_MLX",
    "DASHBOARD_RELOAD",
    "ASHBY_LEGACY_HTML",
    "GREENHOUSE_LEGACY_HTML",
    "LEVER_LEGACY_HTML",
)


def _last_run_summary(db_path: str) -> dict | None:
    try:
        with sqlite3.connect(db_path) as conn:
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
            "fallback_endpoint": profile.llm_gate.fallback_endpoint,
            "fallback_model": profile.llm_gate.fallback_model,
            "accept_threshold": profile.llm_gate.accept_threshold,
            "max_calls_per_run": profile.llm_gate.max_calls_per_run,
            "timeout_seconds": profile.llm_gate.timeout_seconds,
            "fail_open": profile.llm_gate.fail_open,
        }
        if profile
        else {}
    )

    flags = {k: os.environ.get(k, "") for k in _FLAG_KEYS}

    db_path = getattr(_MOD, "DB_PATH", None)
    last_run = _last_run_summary(db_path) if db_path else None

    return {
        "scheduler": scheduler_block,
        "profile": profile_block,
        "llm_gate": llm_gate_block,
        "tiers": tiers,
        "feature_flags": flags,
        "last_run": last_run,
    }

