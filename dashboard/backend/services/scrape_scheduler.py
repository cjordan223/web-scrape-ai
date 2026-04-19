"""APScheduler-driven tier-aware scrape dispatcher.

Feature-flagged by TEXTAILOR_SCRAPE_SCHEDULER=1. Reads cron/group/alternation
from scrape_profile in the scraper config. Cadence changes are config + restart
(architectural, not runtime — no UI knobs).
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_scheduler: Any = None


def compute_tick_plan(
    *,
    run_index: int,
    rotation_groups: int,
    discovery_every_nth: int,
) -> dict[str, Any]:
    group = run_index % rotation_groups
    fire_discovery = (run_index % discovery_every_nth) == 0
    tiers = ["workhorse", "lead"]
    if fire_discovery:
        tiers.append("discovery")
    return {"run_index": run_index, "group": group, "tiers": tiers}


def _next_run_index(db_path) -> int:
    """Count of historical rotated runs — feeds run_index for new tick."""
    import sqlite3

    try:
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM runs WHERE rotation_group IS NOT NULL"
            ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.DatabaseError:
        return 0


async def _tick():
    from job_scraper.config import DB_PATH, load_config

    cfg = load_config()
    profile = cfg.scrape_profile
    run_index = _next_run_index(DB_PATH)
    plan = compute_tick_plan(
        run_index=run_index,
        rotation_groups=profile.rotation_groups,
        discovery_every_nth=profile.discovery_every_nth_run,
    )
    logger.info(
        "scheduler: tick run_index=%s group=%s tiers=%s",
        plan["run_index"],
        plan["group"],
        plan["tiers"],
    )
    from services import scraping as scraping_handlers

    status = scraping_handlers.scrape_runner_status(lines=0)
    if status.get("running"):
        logger.warning("scheduler: skipping tick — run still active")
        return
    scraping_handlers.run_scrape(
        {
            "tiers": plan["tiers"],
            "rotation_group": plan["group"],
            "run_index": plan["run_index"],
        }
    )


async def start():
    global _scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    from job_scraper.config import load_config

    profile = load_config().scrape_profile
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_tick, CronTrigger.from_crontab(profile.cadence), id="scrape_tick")
    _scheduler.start()
    logger.info("scheduler started: cadence=%s", profile.cadence)


async def stop():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler stopped")


def enabled() -> bool:
    return os.getenv("TEXTAILOR_SCRAPE_SCHEDULER", "0") == "1"


def next_run_time() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job("scrape_tick")
    if not job or not job.next_run_time:
        return None
    return job.next_run_time.isoformat()
