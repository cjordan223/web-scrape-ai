"""Operations-domain route registration."""

from __future__ import annotations

from fastapi import FastAPI


ROUTES: list[tuple[str, str, str]] = [
    ("GET", "/api/db/schema", "db_schema"),
    ("GET", "/api/db/tables", "db_tables"),
    ("GET", "/api/db/table/{name}", "db_table_browse"),
    ("GET", "/api/db/query", "db_query"),
    ("GET", "/api/db/admin/status", "db_admin_status"),
    ("POST", "/api/db/admin/action", "db_admin_action"),
    ("GET", "/api/ops/status", "ops_status"),
    ("POST", "/api/ops/action", "ops_action"),
    ("GET", "/api/db/size", "db_size"),
    ("GET", "/api/schedules", "list_schedules"),
    ("GET", "/api/schedules/{label}/log", "get_schedule_log"),
    ("GET", "/api/runtime-controls", "get_runtime_controls"),
    ("POST", "/api/runtime-controls", "update_runtime_controls"),
    ("POST", "/api/tailoring/archive", "archive_create"),
    ("GET", "/api/tailoring/archives", "archive_list"),
    ("GET", "/api/tailoring/archives/{archive_id}", "archive_detail"),
    ("GET", "/api/ops/pipeline/packages", "pipeline_packages"),
    ("GET", "/api/ops/pipeline/trace/{archive_id}/{slug}", "pipeline_trace"),
    ("GET", "/{full_path:path}", "catch_all"),
]


def register(app: FastAPI, handlers: dict[str, object]) -> None:
    for method, path, name in ROUTES:
        app.add_api_route(path, handlers[name], methods=[method])
