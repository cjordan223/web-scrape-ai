"""Compatibility launcher for the dashboard API server."""

from app import *  # noqa: F403
from app import PORT, app

import os
import uvicorn


if __name__ == "__main__":
    # Default to stable LAN serving. Enable reload explicitly for local dev only.
    reload_enabled = os.environ.get("DASHBOARD_RELOAD", "").lower() in {"1", "true", "yes"}
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=reload_enabled)
