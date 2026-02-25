"""Tracing helpers for per-run LLM transparency logs."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRACE_FILENAME = "llm_trace.jsonl"


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


class TraceRecorder:
    """Append newline-delimited JSON trace events for a tailoring run."""

    def __init__(self, output_dir: Path, run_context: dict[str, Any]):
        self.output_dir = output_dir
        self.run_context = dict(run_context)
        self.path = output_dir / TRACE_FILENAME
        self._lock = threading.Lock()

    def record(self, event: dict[str, Any]) -> None:
        """Append a single trace event safely.

        Serialization failures are converted to a safe fallback event so trace
        continuity is preserved.
        """
        payload: dict[str, Any] = {}
        payload.update(self.run_context)
        payload.update(event)
        payload.setdefault("timestamp", utc_now_iso())

        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            line = json.dumps(payload, ensure_ascii=False) + "\n"
        except Exception as e:  # pragma: no cover - defensive fallback
            fallback = {
                **self.run_context,
                "event_type": "trace_error",
                "timestamp": utc_now_iso(),
                "error": f"Failed to serialize trace event: {e}",
            }
            line = json.dumps(fallback, ensure_ascii=False) + "\n"

        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
