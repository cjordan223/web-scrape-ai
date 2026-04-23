"""Auto-queue QA LLM review after scrape runs and manual ingests.

Feature-flagged by TEXTAILOR_AUTO_QA_REVIEW=1. Two entry points:
- poll_and_enqueue(): scheduler tick, fires when a new scrape run completes.
- enqueue_auto_qa_review(source): direct call from ingest-commit handler.

Both funnel into the existing manual LLM review pathway
(tailoring_qa_llm_review), so prompts, grounding, model fallback, and batch
accounting are unchanged. Only the trigger differs — batch rows carry
trigger_source='auto_post_scrape' or 'auto_post_ingest' for audit.
"""
from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from datetime import datetime, timezone
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_BATCH_CAP = 50
_POLL_INTERVAL_SECONDS = 600
_last_processed_completed_at: str | None = None
_scheduler: Any = None
_pending_drain = False
_state_lock = Lock()
_state: dict[str, Any] = {
    "last_tick_at": None,
    "last_completed_run": None,
    "last_enqueue_result": None,
    "last_skip_reason": None,
    "last_error": None,
}


def enabled() -> bool:
    return os.getenv("TEXTAILOR_AUTO_QA_REVIEW", "0") == "1"


def _db_path():
    try:
        import app as dashboard_app
        return dashboard_app.DB_PATH
    except Exception:
        from job_scraper.config import DB_PATH
        return DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _remember(**updates: Any) -> None:
    with _state_lock:
        _state.update(updates)


def _qa_pending_count() -> int:
    with contextlib.closing(sqlite3.connect(str(_db_path()))) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status='qa_pending'"
        ).fetchone()
    return int(row[0]) if row else 0


def _qa_pending_ids(limit: int) -> list[int]:
    with contextlib.closing(sqlite3.connect(str(_db_path()))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id FROM jobs WHERE status='qa_pending' "
            "ORDER BY created_at ASC, id ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [int(r["id"]) for r in rows]


def _in_flight_count() -> int:
    with contextlib.closing(sqlite3.connect(str(_db_path()))) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM qa_llm_review_items "
            "WHERE status IN ('queued', 'reviewing')"
        ).fetchone()
    return int(row[0]) if row else 0


def status() -> dict[str, Any]:
    try:
        pending_count = _qa_pending_count()
    except sqlite3.DatabaseError as exc:
        pending_count = None
        _remember(last_error=str(exc))
    try:
        in_flight_count = _in_flight_count()
    except sqlite3.DatabaseError as exc:
        in_flight_count = None
        _remember(last_error=str(exc))
    with _state_lock:
        state = dict(_state)
    return {
        "enabled": enabled(),
        "scheduler_running": _scheduler is not None,
        "poll_interval_seconds": _POLL_INTERVAL_SECONDS,
        "batch_cap": _BATCH_CAP,
        "pending_drain": _pending_drain,
        "pending_qa_count": pending_count,
        "in_flight_count": in_flight_count,
        **state,
    }


def enqueue_auto_qa_review(source: str = "auto") -> dict[str, Any]:
    """Fire LLM review against oldest qa_pending rows (capped at _BATCH_CAP).

    Idempotent: if a batch is already in-flight, mark a deferred drain so the
    poller queues the next batch after the current worker finishes.
    """
    global _pending_drain
    if not enabled():
        result = {"ok": False, "skipped": "disabled"}
        _remember(last_enqueue_result=result, last_skip_reason="disabled")
        return result

    try:
        if _in_flight_count() > 0:
            _pending_drain = True
            result = {"ok": True, "skipped": "batch_in_flight", "deferred": True}
            _remember(last_enqueue_result=result, last_skip_reason="batch_in_flight")
            return result
        pending_total = _qa_pending_count()
        job_ids = _qa_pending_ids(_BATCH_CAP)
    except sqlite3.DatabaseError as e:
        logger.exception("auto_qa: DB read failed")
        result = {"ok": False, "error": str(e)}
        _remember(last_enqueue_result=result, last_error=str(e), last_skip_reason="db_error")
        return result

    if not job_ids:
        _pending_drain = False
        result = {"ok": True, "queued": 0}
        _remember(last_enqueue_result=result, last_skip_reason="no_pending_jobs")
        return result

    from services.tailoring import tailoring_qa_llm_review
    try:
        result = tailoring_qa_llm_review(
            {"job_ids": job_ids, "trigger_source": source}
        )
    except Exception as e:  # the downstream handler logs its own detail
        logger.exception("auto_qa: enqueue call failed")
        result = {"ok": False, "error": str(e)}
        _remember(last_enqueue_result=result, last_error=str(e), last_skip_reason="enqueue_error")
        return result

    queued = result.get("queued") if isinstance(result, dict) else 0
    _pending_drain = bool(queued and pending_total > len(job_ids))
    _remember(last_enqueue_result=result, last_skip_reason=None, last_error=None)
    logger.info("auto_qa: enqueued %s items (source=%s)", queued, source)
    return result


async def poll_and_enqueue() -> None:
    """Scheduler tick: detect newly-completed scrape runs, fire auto-review."""
    global _last_processed_completed_at, _pending_drain
    _remember(last_tick_at=_now())
    if not enabled():
        _remember(last_skip_reason="disabled")
        return
    try:
        with contextlib.closing(sqlite3.connect(str(_db_path()))) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT run_id, completed_at FROM runs "
                "WHERE status='completed' AND completed_at IS NOT NULL "
                "ORDER BY completed_at DESC LIMIT 1"
            ).fetchone()
    except sqlite3.DatabaseError as exc:
        logger.exception("auto_qa: poll DB read failed")
        _remember(last_error=str(exc), last_skip_reason="db_error")
        return

    if row and row["completed_at"]:
        latest = str(row["completed_at"])
        latest_run = {"run_id": row["run_id"], "completed_at": latest}
        _remember(last_completed_run=latest_run)
    else:
        latest = None
        latest_run = None

    try:
        pending_count = _qa_pending_count()
        in_flight = _in_flight_count()
    except sqlite3.DatabaseError as exc:
        _remember(last_error=str(exc), last_skip_reason="db_error")
        return

    if in_flight > 0:
        if pending_count > 0:
            _pending_drain = True
        _remember(last_skip_reason="batch_in_flight")
        return

    should_enqueue = False
    source = "auto_backlog"
    if latest and _last_processed_completed_at != latest:
        should_enqueue = pending_count > 0
        source = "auto_post_scrape"
        _last_processed_completed_at = latest
    elif _pending_drain and pending_count > 0:
        should_enqueue = True
        source = "auto_backlog"
    elif _last_processed_completed_at is None and latest:
        _last_processed_completed_at = latest

    if not should_enqueue:
        if pending_count <= 0:
            _pending_drain = False
            _remember(last_skip_reason="no_pending_jobs")
        else:
            _remember(last_skip_reason="waiting_for_trigger")
        return

    logger.info(
        "auto_qa: enqueuing review source=%s run=%s pending=%s",
        source, latest_run, pending_count,
    )
    result = enqueue_auto_qa_review(source=source)
    if not result.get("ok") or result.get("error"):
        _pending_drain = False


async def start() -> None:
    """Register the post-scrape poll tick on its own AsyncIOScheduler."""
    global _scheduler
    if not enabled():
        logger.info("auto_qa_review disabled (set TEXTAILOR_AUTO_QA_REVIEW=1 to enable)")
        return
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        poll_and_enqueue,
        IntervalTrigger(seconds=_POLL_INTERVAL_SECONDS),
        id="auto_qa_review_tick",
    )
    _scheduler.start()
    await poll_and_enqueue()
    logger.info("auto_qa_review started: poll=%ss", _POLL_INTERVAL_SECONDS)


async def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("auto_qa_review stopped")
