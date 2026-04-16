"""Post-process trace data into a per-run metrics summary."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from datetime import datetime

logger = logging.getLogger(__name__)


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _seconds_between(start: str, end: str) -> float:
    return (_parse_iso(end) - _parse_iso(start)).total_seconds()


def compute_metrics(output_dir: Path) -> dict[str, Any]:
    """Read trace + meta from output_dir, return metrics dict."""
    meta_path = output_dir / "meta.json"
    trace_path = output_dir / "llm_trace.jsonl"

    meta: dict[str, Any] = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())

    events: list[dict] = []
    if trace_path.exists():
        for line in trace_path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    # Wall time from meta
    run_started = meta.get("run_started_at")
    run_finished = meta.get("run_finished_at")
    total_wall_time = _seconds_between(run_started, run_finished) if run_started and run_finished else None

    # Phase timings from phase_start/phase_end events
    phase_starts: dict[str, str] = {}
    phase_ends: dict[str, str] = {}
    for ev in events:
        if ev.get("event_type") == "phase_start":
            phase_starts[ev["phase"]] = ev["timestamp"]
        elif ev.get("event_type") == "phase_end":
            phase_ends[ev["phase"]] = ev["timestamp"]

    def phase_time(name: str) -> float | None:
        if name in phase_starts and name in phase_ends:
            return _seconds_between(phase_starts[name], phase_ends[name])
        return None

    # LLM call aggregation by doc_type
    llm_calls: list[dict] = [
        ev for ev in events if ev.get("event_type") == "llm_call_success"
    ]

    def llm_stats(doc_type: str) -> tuple[int, float]:
        matching = [c for c in llm_calls if c.get("doc_type") == doc_type]
        count = len(matching)
        total_ms = sum(c.get("duration_ms", 0) for c in matching)
        return count, total_ms / 1000.0

    # Attempt counts from doc_attempt_result
    def max_attempt(doc_type: str) -> int:
        attempts = [
            ev.get("attempt", 1)
            for ev in events
            if ev.get("event_type") == "doc_attempt_result" and ev.get("doc_type") == doc_type
        ]
        return max(attempts) if attempts else 1

    analysis_llm_calls, analysis_llm_time = llm_stats("analysis")
    resume_llm_calls, resume_llm_time = llm_stats("resume")
    cover_llm_calls, cover_llm_time = llm_stats("cover")

    # Also count failed LLM calls
    all_llm = [ev for ev in events if ev.get("event_type") in ("llm_call_success", "llm_call_error")]
    total_llm_calls = len(all_llm)
    total_llm_time = sum(c.get("duration_ms", 0) for c in all_llm) / 1000.0

    # Model from first LLM call
    model = None
    if llm_calls:
        model = llm_calls[0].get("model")

    metrics = {
        "run_slug": meta.get("run_slug"),
        "job_id": meta.get("job_id"),
        "model": model,
        "timestamp": run_finished or run_started,
        "total_wall_time_s": round(total_wall_time, 2) if total_wall_time is not None else None,
        "queue_wait_s": None,  # filled by backend
        "analysis_time_s": round(phase_time("analysis"), 2) if phase_time("analysis") is not None else None,
        "analysis_llm_time_s": round(analysis_llm_time, 2),
        "analysis_llm_calls": analysis_llm_calls,
        "resume_time_s": round(phase_time("resume"), 2) if phase_time("resume") is not None else None,
        "resume_llm_time_s": round(resume_llm_time, 2),
        "resume_llm_calls": resume_llm_calls,
        "resume_attempts": max_attempt("resume"),
        "cover_time_s": round(phase_time("cover"), 2) if phase_time("cover") is not None else None,
        "cover_llm_time_s": round(cover_llm_time, 2),
        "cover_llm_calls": cover_llm_calls,
        "cover_attempts": max_attempt("cover"),
        "compile_resume_s": round(phase_time("compile_resume"), 2) if phase_time("compile_resume") is not None else None,
        "compile_cover_s": round(phase_time("compile_cover"), 2) if phase_time("compile_cover") is not None else None,
        "total_llm_calls": total_llm_calls,
        "total_llm_time_s": round(total_llm_time, 2),
    }

    # Write to output dir
    metrics_path = output_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))
    logger.info("Metrics written to %s", metrics_path)

    return metrics
