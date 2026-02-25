"""Runtime control flags shared by scraper and dashboard."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

CONTROL_PATH = Path(
    os.environ.get(
        "JOB_SCRAPER_RUNTIME_CONTROLS",
        str(Path.home() / ".local" / "share" / "job_scraper" / "runtime_controls.json"),
    )
)

DEFAULT_CONTROLS = {
    "scrape_enabled": True,
    "llm_enabled": True,
}


def load_runtime_controls() -> dict:
    controls = dict(DEFAULT_CONTROLS)
    try:
        raw = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
        controls["scrape_enabled"] = bool(raw.get("scrape_enabled", controls["scrape_enabled"]))
        controls["llm_enabled"] = bool(raw.get("llm_enabled", controls["llm_enabled"]))
        controls["updated_at"] = raw.get("updated_at")
    except FileNotFoundError:
        controls["updated_at"] = None
    except Exception:
        controls["updated_at"] = None
    return controls


def save_runtime_controls(*, scrape_enabled: bool | None = None, llm_enabled: bool | None = None) -> dict:
    controls = load_runtime_controls()
    if scrape_enabled is not None:
        controls["scrape_enabled"] = bool(scrape_enabled)
    if llm_enabled is not None:
        controls["llm_enabled"] = bool(llm_enabled)
    controls["updated_at"] = datetime.now(timezone.utc).isoformat()
    CONTROL_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTROL_PATH.write_text(
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
