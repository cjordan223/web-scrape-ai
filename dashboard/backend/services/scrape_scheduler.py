"""APScheduler-driven tier-aware scrape dispatcher.

Feature-flagged by TEXTAILOR_SCRAPE_SCHEDULER=1. Reads cron/group/alternation
from scrape_profile in the scraper config. Cadence changes are config + restart
(architectural, not runtime — no UI knobs).
"""
from __future__ import annotations

import logging
import os
import json
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_scheduler: Any = None


class OllamaHealthError(RuntimeError):
    """Raised when the scheduler cannot verify the required Ollama runtime."""


def _fetch_json(url: str, timeout: int = 3) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_ollama_ready(
    *,
    model: str,
    base_url: str = "http://localhost:11434",
    fetch_json=_fetch_json,
) -> None:
    """Fail loudly unless Ollama is reachable and the configured model is pulled."""
    tags_url = f"{base_url.rstrip('/')}/api/tags"
    try:
        data = fetch_json(tags_url, timeout=3)
    except Exception as exc:
        raise OllamaHealthError(f"Ollama unavailable at {tags_url}: {exc}") from exc

    available = {
        str(item.get("name") or item.get("model") or "").strip()
        for item in data.get("models", []) or []
    }
    available.discard("")
    if model not in available:
        raise OllamaHealthError(
            f"Required Ollama model '{model}' is not pulled. "
            f"Run `ollama pull {model}` before starting the scrape scheduler."
        )


def ollama_base_url_from_chat_endpoint(endpoint: str) -> str:
    value = str(endpoint or "http://localhost:11434").strip().rstrip("/")
    suffix = "/v1/chat/completions"
    if value.endswith(suffix):
        return value[: -len(suffix)]
    return value


def compute_tick_plan(
    *,
    run_index: int,
    rotation_groups: int,
    discovery_every_nth: int,
) -> dict[str, Any]:
    group = run_index % rotation_groups
    fire_discovery = (run_index % discovery_every_nth) == 0
    tiers = ["workhorse"]
    if fire_discovery:
        tiers.append("discovery")
    return {"run_index": run_index, "group": group, "tiers": tiers}


def _next_run_index(db_path) -> int:
    """Count of historical rotated runs — feeds run_index for new tick."""
    import contextlib
    import sqlite3

    try:
        with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
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
    if profile.llm_gate.enabled:
        check_ollama_ready(
            model=profile.llm_gate.model,
            base_url=ollama_base_url_from_chat_endpoint(profile.llm_gate.endpoint),
        )
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
