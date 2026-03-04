"""Tailoring-domain route registration."""

from __future__ import annotations

from fastapi import FastAPI


ROUTES: list[tuple[str, str, str]] = [
    ("GET", "/api/tailoring/runner/status", "tailoring_runner_status"),
    ("POST", "/api/tailoring/runner/stop", "tailoring_runner_stop"),
    ("GET", "/api/tailoring/jobs/recent", "tailoring_recent_jobs"),
    ("GET", "/api/tailoring/jobs/{job_id}", "tailoring_job_detail"),
    ("POST", "/api/tailoring/run", "tailoring_run_job"),
    ("POST", "/api/tailoring/run-latest", "tailoring_run_latest"),
    ("POST", "/api/tailoring/queue", "tailoring_queue_add"),
    ("GET", "/api/tailoring/queue", "tailoring_queue_get"),
    ("DELETE", "/api/tailoring/queue", "tailoring_queue_clear"),
    ("DELETE", "/api/tailoring/queue/{index}", "tailoring_queue_remove"),
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
    ("GET", "/api/llm/models", "llm_models"),
    ("POST", "/api/llm/models/load", "llm_load_model"),
    ("POST", "/api/llm/models/unload", "llm_unload_model"),
    ("POST", "/api/tailoring/ingest/parse", "tailoring_ingest_parse"),
    ("POST", "/api/tailoring/ingest/commit", "tailoring_ingest_commit"),
    ("POST", "/api/tailoring/ingest/fetch-url", "tailoring_ingest_fetch_url"),
]


def register(app: FastAPI, handlers: dict[str, object]) -> None:
    for method, path, name in ROUTES:
        app.add_api_route(path, handlers[name], methods=[method])
