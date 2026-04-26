"""Autonomous LLM review of completed scrape runs.

Polls for completed runs without a review, feeds run metadata + per-spider
stats + recent baseline to the LLM gate model, and persists a structured
{health, summary, flags, recommendations} blob to runs.llm_review.

Runs as a background task started from the FastAPI startup hook.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_POLL_SECONDS = 60
_MAX_PER_TICK = 5
_REQUEST_TIMEOUT = 30  # seconds per LLM call


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _unreviewed_run_ids(db_path: str, limit: int) -> list[str]:
    with contextlib.closing(_connect(db_path)) as conn:
        try:
            rows = conn.execute(
                """SELECT run_id FROM runs
                   WHERE status='completed' AND completed_at IS NOT NULL
                     AND llm_review IS NULL
                   ORDER BY completed_at ASC LIMIT ?""",
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError:
            # llm_review column not yet migrated — let the scraper DB init
            # apply the migration on its next run.
            return []
    return [r["run_id"] for r in rows]


def _load_context(db_path: str, run_id: str) -> dict[str, Any]:
    with contextlib.closing(_connect(db_path)) as conn:
        run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if run is None:
            return {}
        stats = conn.execute(
            "SELECT source, tier, raw_hits, dedup_drops, filter_drops, "
            "llm_rejects, llm_uncertain_low, llm_overflow, stored_pending, stored_lead "
            "FROM run_tier_stats WHERE run_id = ? ORDER BY tier, source",
            (run_id,),
        ).fetchall()
        baseline = conn.execute(
            """SELECT run_id, net_new, gate_mode, rotation_group,
                      raw_count, dedup_count, filtered_count, elapsed
               FROM runs
               WHERE status='completed' AND run_id != ?
               ORDER BY completed_at DESC LIMIT 7""",
            (run_id,),
        ).fetchall()
    run_dict = dict(run)
    run_dict["rotation_members_parsed"] = (
        json.loads(run_dict["rotation_members"]) if run_dict.get("rotation_members") else None
    )
    return {
        "run": run_dict,
        "stats": [dict(r) for r in stats],
        "baseline": [dict(r) for r in baseline],
    }


def _build_prompt(ctx: dict[str, Any], target_net_new: int) -> str:
    run = ctx["run"]
    stats = ctx["stats"]
    baseline = ctx["baseline"]

    baseline_net_new = [b["net_new"] for b in baseline if b["net_new"] is not None]
    baseline_median = (
        sorted(baseline_net_new)[len(baseline_net_new) // 2] if baseline_net_new else None
    )

    # Compact per-spider table
    stats_lines = []
    for s in stats:
        stats_lines.append(
            f"  {s['tier']:9s} {s['source']:12s} "
            f"raw={s['raw_hits']:<4} dedup_drop={s['dedup_drops']:<4} "
            f"filter_drop={s['filter_drops']:<4} stored_pending={s['stored_pending']:<3} "
            f"stored_lead={s['stored_lead']:<3} llm_rej={s['llm_rejects']} "
            f"llm_unc={s['llm_uncertain_low']} llm_of={s['llm_overflow']}"
        )

    baseline_lines = []
    for b in baseline[:5]:
        baseline_lines.append(
            f"  {b['run_id'][:8]} net_new={b['net_new']} gate={b['gate_mode']} "
            f"raw={b['raw_count']} elapsed={b['elapsed']:.0f}s"
            if b.get("elapsed") is not None
            else f"  {b['run_id'][:8]} net_new={b['net_new']} gate={b['gate_mode']} raw={b['raw_count']}"
        )

    return (
        "You are reviewing a job-scraper pipeline run. Return ONLY a single JSON "
        'object with keys: "health" (one of: green, yellow, red), "summary" '
        '(one sentence, under 120 chars), "flags" (list of short strings — '
        'anomalies, silent spiders, gate problems, yield collapse; empty list '
        'if none), "recommendations" (list of short actionable strings; empty '
        "list if everything looks fine). Be specific and terse.\n\n"
        f"RUN {run['run_id']}\n"
        f"  started={run['started_at']} completed={run['completed_at']}\n"
        f"  elapsed={run.get('elapsed')}s  status={run['status']}\n"
        f"  raw={run['raw_count']}  dedup_kept={run['dedup_count']}  "
        f"filtered={run['filtered_count']}  net_new={run['net_new']}\n"
        f"  gate_mode={run['gate_mode']}  rotation_group={run['rotation_group']}\n"
        f"  rotation_members={run.get('rotation_members_parsed')}\n"
        f"  target_net_new_per_run={target_net_new}\n"
        f"\nPER-SPIDER STATS:\n"
        + ("\n".join(stats_lines) if stats_lines else "  (none)")
        + "\n\nRECENT RUNS (newest first):\n"
        + ("\n".join(baseline_lines) if baseline_lines else "  (none)")
        + f"\n\n(baseline median net_new over last {len(baseline_net_new)} runs: "
        f"{baseline_median})\n\n"
        "Compare this run against the baseline and target. If net_new is far below "
        "target or baseline, flag it. If a spider in rotation_members yielded "
        "raw=0, flag it by name. If gate_mode is overflow/fail_open, flag it. "
        "If everything looks healthy, return empty flags + recommendations and "
        'health="green". Output ONLY the JSON.'
    )


def _call_llm(prompt: str, cfg) -> str:
    import requests
    body = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    r = requests.post(cfg.endpoint, json=body, timeout=_REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _parse_review(raw: str) -> dict[str, Any] | None:
    try:
        return json.loads(raw)
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except Exception:
                return None
    return None


def review_run(db_path: str, run_id: str) -> dict[str, Any] | None:
    """Generate and persist a review for a single run. Returns the review dict."""
    from job_scraper.config import load_config

    ctx = _load_context(db_path, run_id)
    if not ctx:
        return None

    cfg = load_config()
    prompt = _build_prompt(ctx, cfg.scrape_profile.target_net_new_per_run)

    try:
        raw = _call_llm(prompt, cfg.scrape_profile.llm_gate)
    except Exception as exc:
        # Leave llm_review NULL so the next poll tick retries once Ollama recovers.
        logger.warning("run_reviewer: LLM call failed for run=%s: %s", run_id, exc)
        return None

    review = _parse_review(raw)
    if review is None:
        logger.warning("run_reviewer: could not parse response for run=%s: %r", run_id, raw[:200])
        review = {
            "health": "unknown",
            "summary": "Reviewer returned unparseable output.",
            "flags": ["parse_failure"],
            "recommendations": [],
            "_raw": raw[:400],
        }

    with contextlib.closing(_connect(db_path)) as conn:
        with conn:
            conn.execute(
                "UPDATE runs SET llm_review = ?, llm_review_at = datetime('now') "
                "WHERE run_id = ?",
                (json.dumps(review), run_id),
            )
    return review


async def _loop():
    from job_scraper.config import DB_PATH

    db_path = str(DB_PATH)
    while True:
        try:
            ids = _unreviewed_run_ids(db_path, _MAX_PER_TICK)
            for rid in ids:
                logger.info("run_reviewer: reviewing run=%s", rid)
                # Run sync LLM call in a thread so the event loop stays free.
                await asyncio.to_thread(review_run, db_path, rid)
        except Exception as exc:
            logger.exception("run_reviewer: loop error: %s", exc)
        await asyncio.sleep(_POLL_SECONDS)


async def start() -> None:
    global _task
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_loop())
    logger.info("run_reviewer started: poll=%ds", _POLL_SECONDS)


async def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
    _task = None
