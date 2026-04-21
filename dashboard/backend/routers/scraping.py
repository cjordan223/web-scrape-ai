"""Scraping-domain route registration."""

from __future__ import annotations

from fastapi import FastAPI


ROUTES: list[tuple[str, str, str]] = [
    ("GET", "/api/overview", "overview"),
    ("GET", "/api/jobs", "list_jobs"),
    ("GET", "/api/jobs/{job_id}", "get_job"),
    ("GET", "/api/runs", "list_runs"),
    ("GET", "/api/runs/active", "active_runs"),
    ("GET", "/api/scrape/runner/status", "scrape_runner_status"),
    ("POST", "/api/scrape/run", "run_scrape"),
    ("GET", "/api/runs/{run_id}", "get_run"),
    ("GET", "/api/runs/{run_id}/logs", "get_run_logs"),
    ("POST", "/api/runs/{run_id}/terminate", "terminate_run"),
    ("GET", "/api/filters/stats", "filter_stats"),
    ("GET", "/api/dedup/stats", "dedup_stats"),
    ("GET", "/api/growth", "growth"),
    ("GET", "/api/rejected/stats", "rejected_stats"),
    ("GET", "/api/rejected", "list_rejected"),
    ("GET", "/api/rejected/{rejected_id}", "get_rejected"),
    ("POST", "/api/rejected/{rejected_id}/approve", "approve_rejected"),
    ("GET", "/api/scrape/sources", "source_diagnostics"),
    ("GET", "/api/scraper/metrics/tier-stats", "tier_stats_rollup"),
    ("GET", "/api/scraper/system/status", "system_status"),
    ("GET", "/api/scraper/reviews", "list_run_reviews"),
    ("POST", "/api/scraper/reviews/{run_id}/regenerate", "regenerate_run_review"),
]


def register(app: FastAPI, handlers: dict[str, object]) -> None:
    for method, path, name in ROUTES:
        app.add_api_route(path, handlers[name], methods=[method])
