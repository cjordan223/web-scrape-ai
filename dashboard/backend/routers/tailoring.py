"""Tailoring-domain route registration."""

from __future__ import annotations

from fastapi import FastAPI


ROUTES: list[tuple[str, str, str]] = [
    ("GET", "/api/tailoring/runner/status", "tailoring_runner_status"),
    ("POST", "/api/tailoring/runner/stop", "tailoring_runner_stop"),
    ("GET", "/api/tailoring/ready", "tailoring_ready_jobs"),
    ("POST", "/api/tailoring/ready/bucket", "tailoring_ready_bucket_update"),
    ("POST", "/api/tailoring/ready/queue-bucket", "tailoring_queue_bucket"),
    ("GET", "/api/tailoring/rejected", "tailoring_rejected_jobs"),
    ("GET", "/api/tailoring/jobs/recent", "tailoring_recent_jobs"),
    ("GET", "/api/tailoring/jobs/{job_id}", "tailoring_job_detail"),
    ("GET", "/api/tailoring/jobs/{job_id}/briefing", "tailoring_job_briefing"),
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
    ("DELETE", "/api/packages/{slug}", "package_delete"),
    ("POST", "/api/packages/{slug}/reject", "package_reject"),
    ("POST", "/api/packages/{slug}/apply", "package_apply"),
    ("POST", "/api/packages/{slug}/regenerate/cover", "package_regenerate_cover"),
    ("POST", "/api/packages/{slug}/latex/{doc_type}", "package_save_latex"),
    ("POST", "/api/packages/{slug}/compile/{doc_type}", "package_compile"),
    ("GET", "/api/packages/{slug}/diff-preview/{doc_type}", "package_diff_preview"),
    ("GET", "/api/applied", "applied_list"),
    ("GET", "/api/applied/{application_id}", "applied_detail"),
    ("POST", "/api/applied/{application_id}/tracking", "applied_update_tracking"),
    ("GET", "/api/applied/{application_id}/artifact/{name}", "applied_artifact"),
    ("GET", "/api/llm/status", "llm_status"),
    ("GET", "/api/llm/models", "llm_models"),
    ("POST", "/api/llm/models/load", "llm_load_model"),
    ("POST", "/api/llm/models/unload", "llm_unload_model"),
    ("POST", "/api/tailoring/ingest/parse", "tailoring_ingest_parse"),
    ("POST", "/api/tailoring/ingest/commit", "tailoring_ingest_commit"),
    ("POST", "/api/tailoring/ingest/fetch-url", "tailoring_ingest_fetch_url"),
    ("POST", "/api/tailoring/ingest/scan-mobile", "tailoring_ingest_scan_mobile"),
    ("GET", "/api/tailoring/qa", "tailoring_qa_list"),
    ("POST", "/api/tailoring/qa/approve", "tailoring_qa_approve"),
    ("POST", "/api/tailoring/qa/reject", "tailoring_qa_reject"),
    ("GET", "/api/tailoring/qa/llm-review", "tailoring_qa_llm_review_status"),
    ("POST", "/api/tailoring/qa/llm-review", "tailoring_qa_llm_review"),
    ("DELETE", "/api/tailoring/qa/llm-review", "tailoring_qa_llm_review_cancel"),
    ("POST", "/api/tailoring/qa/reset-approved", "tailoring_qa_reset_approved"),
    ("POST", "/api/tailoring/qa/undo-approve", "tailoring_qa_undo_approve"),
    ("POST", "/api/tailoring/qa/undo-reject", "tailoring_qa_undo_reject"),
    ("POST", "/api/tailoring/qa/rollback", "tailoring_qa_rollback"),
    ("GET", "/api/leads", "leads_list"),
("GET", "/api/state-log", "state_log"),
    ("POST", "/api/packages/{slug}/chat", "package_chat_send"),
    ("GET", "/api/packages/{slug}/chat", "package_chat_history"),
    ("DELETE", "/api/packages/{slug}/chat", "package_chat_clear"),
]


def register(app: FastAPI, handlers: dict[str, object]) -> None:
    for method, path, name in ROUTES:
        app.add_api_route(path, handlers[name], methods=[method])
