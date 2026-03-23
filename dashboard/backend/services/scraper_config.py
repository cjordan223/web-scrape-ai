"""Scraper config API — read/write config.default.yaml as JSON."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import yaml
from fastapi import Body
from fastapi.responses import JSONResponse

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "job-scraper" / "job_scraper" / "config.default.yaml"
_DB_PATH_DEFAULT = str(Path.home() / ".local" / "share" / "job_scraper" / "jobs.db")

import os
DB_PATH = os.environ.get("JOB_SCRAPER_DB", _DB_PATH_DEFAULT)


def _read_yaml() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def _write_yaml(data: dict) -> None:
    with open(_CONFIG_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _company_from_url(url: str, board_type: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if board_type in ("ashby", "greenhouse", "lever") and path_parts:
        return path_parts[0]
    return parsed.netloc.replace("www.", "").split(".")[0]


def _yaml_to_json(raw: dict) -> dict:
    """Convert raw YAML config to structured JSON for the frontend."""
    # Boards
    boards = []
    for target in raw.get("crawl", {}).get("targets", []):
        board_type = target.get("board", "unknown")
        url = target.get("url", "")
        boards.append({
            "url": url,
            "board_type": board_type,
            "company": target.get("company") or _company_from_url(url, board_type),
            "enabled": target.get("enabled", True),
        })

    # Queries
    queries = []
    for q in raw.get("queries", []):
        queries.append({
            "title_phrase": q.get("title_phrase", ""),
            "board_site": q.get("board_site", ""),
            "board": q.get("board", "unknown"),
            "suffix": q.get("suffix", ""),
        })

    # USAJobs watcher
    usajobs = {"enabled": False, "keywords": [], "series": [], "agencies": [], "days": 14, "remote": True}
    for w in raw.get("watchers", []):
        if w.get("name") == "usajobs":
            params = w.get("params", {})
            usajobs = {
                "enabled": w.get("enabled", True),
                "keywords": [k for k in (params.get("keywords", "") or "").split(";") if k],
                "series": [s for s in (params.get("series", "") or "").split(";") if s],
                "agencies": [a for a in (params.get("agencies", "") or "").split(";") if a],
                "days": int(params.get("days", "14")),
                "remote": params.get("remote", "true") == "true",
            }
            break

    search = raw.get("search", {})
    filt = raw.get("filter", {})

    return {
        "boards": boards,
        "queries": queries,
        "searxng": {
            "enabled": search.get("enabled", True),
            "url": search.get("searx_url", "http://localhost:8888/search"),
            "timeout": search.get("timeout", 15),
            "engines": search.get("engines", "google,startpage"),
            "time_range": search.get("time_range", "week"),
            "request_delay": search.get("request_delay", 1.0),
        },
        "usajobs": usajobs,
        "hard_filters": {
            "domain_blocklist": filt.get("url_domain_blocklist", []),
            "title_blocklist": filt.get("seniority_exclude", []),
            "content_blocklist": filt.get("content_blocklist", []),
            "min_salary_k": filt.get("min_salary_k", 70),
        },
        "filter": {
            "title_keywords": filt.get("title_keywords", []),
            "title_role_words": filt.get("title_role_words", []),
            "require_remote": filt.get("require_remote", True),
            "require_us_location": filt.get("require_us_location", True),
            "min_jd_chars": filt.get("min_jd_chars", 50),
            "max_experience_years": filt.get("max_experience_years", 5),
            "score_accept_threshold": filt.get("score_accept_threshold", 0),
            "score_reject_threshold": filt.get("score_reject_threshold", -3),
        },
        "seen_ttl_days": filt.get("seen_ttl_days", 14),
        "target_max_results": filt.get("target_max_results", 50),
        "pipeline_order": raw.get("pipeline_order", [
            "text_extraction", "dedup", "hard_filter", "storage",
        ]),
        "llm_review": raw.get("llm_review", {}),
        "crawl": {
            "enabled": raw.get("crawl", {}).get("enabled", True),
            "request_delay": raw.get("crawl", {}).get("request_delay", 2.0),
            "max_results_per_target": raw.get("crawl", {}).get("max_results_per_target", 50),
        },
    }


def _json_to_yaml(config_json: dict, existing: dict) -> dict:
    """Merge frontend JSON changes back into the YAML structure."""
    raw = dict(existing)

    if "boards" in config_json:
        targets = []
        for b in config_json["boards"]:
            t = {"url": b["url"], "board": b["board_type"]}
            if not b.get("enabled", True):
                t["enabled"] = False
            if b.get("company"):
                t["company"] = b["company"]
            targets.append(t)
        raw.setdefault("crawl", {})["targets"] = targets

    if "queries" in config_json:
        raw["queries"] = config_json["queries"]

    if "searxng" in config_json:
        s = config_json["searxng"]
        raw.setdefault("search", {}).update({
            "searx_url": s.get("url", raw.get("search", {}).get("searx_url")),
            "timeout": s.get("timeout", 15),
            "engines": s.get("engines", "google,startpage"),
            "time_range": s.get("time_range", "week"),
            "request_delay": s.get("request_delay", 1.0),
        })

    if "usajobs" in config_json:
        u = config_json["usajobs"]
        watchers = raw.get("watchers", [])
        found = False
        for w in watchers:
            if w.get("name") == "usajobs":
                w["enabled"] = u.get("enabled", True)
                w.setdefault("params", {}).update({
                    "keywords": ";".join(u.get("keywords", [])),
                    "series": ";".join(u.get("series", [])),
                    "agencies": ";".join(u.get("agencies", [])),
                    "days": str(u.get("days", 14)),
                    "remote": "true" if u.get("remote", True) else "false",
                })
                found = True
                break
        if not found and u.get("enabled"):
            watchers.append({
                "name": "usajobs",
                "type": "custom",
                "module": "job_scraper.usajobs",
                "board": "usajobs",
                "enabled": True,
                "skip_filters": ["url_domain", "source_quality", "remote", "location"],
                "params": {
                    "keywords": ";".join(u.get("keywords", [])),
                    "series": ";".join(u.get("series", [])),
                    "agencies": ";".join(u.get("agencies", [])),
                    "days": str(u.get("days", 14)),
                    "remote": "true" if u.get("remote", True) else "false",
                },
            })
        raw["watchers"] = watchers

    if "hard_filters" in config_json:
        hf = config_json["hard_filters"]
        filt = raw.setdefault("filter", {})
        if "domain_blocklist" in hf:
            filt["url_domain_blocklist"] = hf["domain_blocklist"]
        if "title_blocklist" in hf:
            filt["seniority_exclude"] = hf["title_blocklist"]
        if "content_blocklist" in hf:
            filt["content_blocklist"] = hf["content_blocklist"]
        if "min_salary_k" in hf:
            filt["min_salary_k"] = hf["min_salary_k"]

    if "filter" in config_json:
        f = config_json["filter"]
        filt = raw.setdefault("filter", {})
        for key in ("title_keywords", "title_role_words", "require_remote",
                     "require_us_location", "min_jd_chars", "max_experience_years",
                     "score_accept_threshold", "score_reject_threshold"):
            if key in f:
                filt[key] = f[key]

    if "seen_ttl_days" in config_json:
        raw.setdefault("filter", {})["seen_ttl_days"] = config_json["seen_ttl_days"]
    if "target_max_results" in config_json:
        raw.setdefault("filter", {})["target_max_results"] = config_json["target_max_results"]
    if "pipeline_order" in config_json:
        raw["pipeline_order"] = config_json["pipeline_order"]
    if "llm_review" in config_json:
        raw["llm_review"] = config_json["llm_review"]
    if "crawl" in config_json:
        c = config_json["crawl"]
        crawl = raw.setdefault("crawl", {})
        if "enabled" in c:
            crawl["enabled"] = c["enabled"]
        if "request_delay" in c:
            crawl["request_delay"] = c["request_delay"]
        if "max_results_per_target" in c:
            crawl["max_results_per_target"] = c["max_results_per_target"]

    return raw


# ---------------------------------------------------------------------------
# API handlers
# ---------------------------------------------------------------------------

def scraper_config_get():
    """Return the full scraper config as JSON."""
    try:
        raw = _read_yaml()
        return _yaml_to_json(raw)
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


def scraper_config_save(payload: dict = Body(default={})):
    """Save partial config changes to config.default.yaml."""
    try:
        existing = _read_yaml()
        merged = _json_to_yaml(payload, existing)
        _write_yaml(merged)
        return {"ok": True, "config": _yaml_to_json(merged)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


def scraper_pipeline_stats():
    """Return per-stage item counts from the latest completed run."""
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        # Latest completed run
        run = conn.execute(
            "SELECT run_id, started_at, raw_count, dedup_count, filtered_count, error_count "
            "FROM runs WHERE status = 'completed' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if not run:
            conn.close()
            return {"run_id": None, "started_at": None, "raw_count": 0, "dedup_dropped": 0,
                    "filter_rejected": 0, "stored": 0, "per_source": {}}

        run_id = run["run_id"]

        # Per-source counts
        source_rows = conn.execute(
            "SELECT board, COUNT(*) as cnt FROM jobs WHERE run_id = ? GROUP BY board",
            (run_id,),
        ).fetchall()
        per_source = {r["board"]: r["cnt"] for r in source_rows}

        # Rejection breakdown
        rejected_rows = conn.execute(
            "SELECT rejection_stage, COUNT(*) as cnt FROM jobs "
            "WHERE run_id = ? AND status = 'rejected' GROUP BY rejection_stage",
            (run_id,),
        ).fetchall()
        per_rejection = {r["rejection_stage"]: r["cnt"] for r in rejected_rows}

        stored = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE run_id = ? AND status != 'rejected'",
            (run_id,),
        ).fetchone()[0]

        # Aggregate inventory counts across all runs
        inventory_rows = conn.execute(
            "SELECT decision, COUNT(*) as cnt FROM results GROUP BY decision"
        ).fetchall()
        inventory = {r["decision"]: r["cnt"] for r in inventory_rows}
        total_stored = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]

        conn.close()
        return {
            "run_id": run_id,
            "started_at": run["started_at"],
            "raw_count": run["raw_count"],
            "dedup_dropped": run["raw_count"] - run["dedup_count"],
            "filter_rejected": run["filtered_count"],
            "stored": stored,
            "error_count": run["error_count"],
            "per_source": per_source,
            "per_rejection": per_rejection,
            "inventory": {
                "total": total_stored,
                "qa_pending": inventory.get("qa_pending", 0),
                "qa_approved": inventory.get("qa_approved", 0),
                "qa_rejected": inventory.get("qa_rejected", 0),
                "rejected": inventory.get("rejected", 0),
            },
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)
