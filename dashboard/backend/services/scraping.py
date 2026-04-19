"""Shim loader for scraping handlers owned by job-scraper/api."""

from __future__ import annotations

import importlib.util
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

