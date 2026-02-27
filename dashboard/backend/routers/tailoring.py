"""Tailoring-domain route registration."""

from __future__ import annotations

from fastapi import FastAPI


ROUTES: list[tuple[str, str, str]] = [
    ("GET", "/api/tailoring/runner/status", "tailoring_runner_status"),
    ("GET", "/api/tailoring/jobs/recent", "tailoring_recent_jobs"),
    ("POST", "/api/tailoring/run", "tailoring_run_job"),
    ("POST", "/api/tailoring/run-latest", "tailoring_run_latest"),
    ("GET", "/api/tailoring/runs", "tailoring_runs"),
    ("GET", "/api/tailoring/runs/{slug}", "tailoring_run_detail"),
    ("GET", "/api/tailoring/runs/{slug}/trace", "tailoring_trace"),
    ("GET", "/api/tailoring/runs/{slug}/artifact/{name}", "tailoring_artifact"),
    ("GET", "/api/packages", "package_runs"),
    ("GET", "/api/packages/{slug}", "package_detail"),
    ("POST", "/api/packages/{slug}/latex/{doc_type}", "package_save_latex"),
    ("POST", "/api/packages/{slug}/compile/{doc_type}", "package_compile"),
    ("GET", "/api/packages/{slug}/diff-preview/{doc_type}", "package_diff_preview"),
    ("GET", "/api/llm/status", "llm_status"),
]


def register(app: FastAPI, handlers: dict[str, object]) -> None:
    for method, path, name in ROUTES:
        app.add_api_route(path, handlers[name], methods=[method])
