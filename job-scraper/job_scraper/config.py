"""YAML config loader for scraper v2."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

_DEFAULT_CONFIG = Path(__file__).parent / "config.default.yaml"

DB_PATH = Path(
    os.environ.get("JOB_SCRAPER_DB", Path.home() / ".local" / "share" / "job_scraper" / "jobs.db")
)


class BoardTarget(BaseModel):
    url: str
    board_type: str
    company: str
    enabled: bool = True


class SearXNGConfig(BaseModel):
    enabled: bool = True
    url: str = "http://localhost:8888/search"
    timeout: int = 15
    engines: str = "google,startpage"
    time_range: str = "week"
    request_delay: float = 1.0


class USAJobsConfig(BaseModel):
    enabled: bool = True
    series: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    agencies: list[str] = Field(default_factory=list)
    days: int = 14
    remote: bool = True


class HardFilterConfig(BaseModel):
    domain_blocklist: list[str] = Field(default_factory=lambda: [
        "dictionary.com", "collinsdictionary.com", "techtarget.com",
        "wikipedia.org", "merriam-webster.com", "investopedia.com",
        "reddit.com", "quora.com", "youtube.com", "medium.com",
    ])
    title_blocklist: list[str] = Field(default_factory=lambda: [
        "staff", "principal", "manager", "director",
    ])
    content_blocklist: list[str] = Field(default_factory=lambda: [
        "clearance", "ts/sci", "ts-sci", "polygraph", "top secret",
        "secret clearance",
    ])
    title_keywords: list[str] = Field(default_factory=list)
    min_salary_k: int = 100
    target_salary_k: int = 150


class RemoteOKConfig(BaseModel):
    enabled: bool = True
    tag_filter: list[str] = Field(default_factory=list)


class HNHiringConfig(BaseModel):
    enabled: bool = True
    max_comments: int = 500


class SearXNGQuery(BaseModel):
    title_phrase: str
    board_site: str = ""
    suffix: str = ""


class ScraperConfig(BaseModel):
    boards: list[BoardTarget] = Field(default_factory=list)
    searxng: SearXNGConfig = Field(default_factory=SearXNGConfig)
    usajobs: USAJobsConfig = Field(default_factory=USAJobsConfig)
    remoteok: RemoteOKConfig = Field(default_factory=RemoteOKConfig)
    hn_hiring: HNHiringConfig = Field(default_factory=HNHiringConfig)
    hard_filters: HardFilterConfig = Field(default_factory=HardFilterConfig)
    queries: list[SearXNGQuery] = Field(default_factory=list)
    seen_ttl_days: int = 14
    target_max_results: int = 50
    pipeline_order: list[str] = Field(default_factory=lambda: [
        "text_extraction", "dedup", "hard_filter", "storage",
    ])


def _company_from_board_url(url: str, board_type: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if board_type == "ashby" and "ashbyhq.com" in parsed.netloc:
        return path_parts[0] if path_parts else "unknown"
    if board_type == "greenhouse" and "greenhouse.io" in parsed.netloc:
        return path_parts[0] if path_parts else "unknown"
    if board_type == "lever" and "lever.co" in parsed.netloc:
        return path_parts[0] if path_parts else "unknown"
    host = parsed.netloc.replace("www.", "")
    parts = host.split(".")
    return parts[0] if parts else "unknown"


# ---------------------------------------------------------------------------
# Backward-compat stubs — old modules import these; they will be deleted once
# all old modules are replaced in later tasks.
# ---------------------------------------------------------------------------

class FilterConfig(BaseModel):
    """Stub — kept for backward compat with old filters.py."""
    pass


class QueryTemplate(BaseModel):
    """Stub — kept for backward compat with old searcher.py."""
    title_phrase: str = ""
    board_site: str = ""
    suffix: str = ""


class WatcherConfig(BaseModel):
    """Stub — kept for backward compat with old watchers.py / usajobs.py."""
    name: str = ""
    params: dict = Field(default_factory=dict)


class LLMReviewConfig(BaseModel):
    """Legacy placeholder for deprecated llm_review config blocks."""
    pass


class CrawlTarget(BaseModel):
    """Stub — kept for backward compat with old crawler.py."""
    url: str
    board: str = ""
    link_pattern: str = ""


# ---------------------------------------------------------------------------


def load_config(path: str | Path | None = None) -> ScraperConfig:
    config_path = Path(path) if path else _DEFAULT_CONFIG
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    boards: list[BoardTarget] = []
    for target in raw.get("crawl", {}).get("targets", []):
        board_type = target.get("board", "unknown")
        company = target.get("company") or _company_from_board_url(target["url"], board_type)
        boards.append(BoardTarget(url=target["url"], board_type=board_type, company=company))

    queries = []
    for q in raw.get("queries", []):
        queries.append(SearXNGQuery(
            title_phrase=q.get("title_phrase", ""),
            board_site=q.get("board_site", ""),
            suffix=q.get("suffix", ""),
        ))

    searxng_raw = raw.get("search", {})
    searxng = SearXNGConfig(
        url=searxng_raw.get("searx_url", "http://localhost:8888/search"),
        timeout=searxng_raw.get("timeout", 15),
        engines=searxng_raw.get("engines", "google,startpage"),
        time_range=searxng_raw.get("time_range", "week"),
        request_delay=searxng_raw.get("request_delay", 1.0),
    )

    usajobs_raw = {}
    for w in raw.get("watchers", []):
        if w.get("name") == "usajobs":
            usajobs_raw = w.get("params", {})
            break
    usajobs = USAJobsConfig(
        series=usajobs_raw.get("series", "").split(";") if usajobs_raw.get("series") else [],
        keywords=usajobs_raw.get("keywords", "").split(";") if usajobs_raw.get("keywords") else [],
        agencies=usajobs_raw.get("agencies", "").split(";") if usajobs_raw.get("agencies") else [],
        days=int(usajobs_raw.get("days", "14")),
        remote=usajobs_raw.get("remote", "true") == "true",
    )

    filter_raw = raw.get("filter", {})
    hard_filters = HardFilterConfig(
        domain_blocklist=filter_raw.get("url_domain_blocklist", HardFilterConfig().domain_blocklist),
        title_blocklist=filter_raw.get("seniority_exclude", HardFilterConfig().title_blocklist),
        content_blocklist=filter_raw.get("content_blocklist", HardFilterConfig().content_blocklist),
        title_keywords=filter_raw.get("title_keywords", []),
        min_salary_k=filter_raw.get("min_salary_k", 100),
        target_salary_k=filter_raw.get("target_salary_k", 150),
    )

    remoteok_raw = raw.get("remoteok", {})
    remoteok = RemoteOKConfig(
        enabled=remoteok_raw.get("enabled", True),
        tag_filter=remoteok_raw.get("tag_filter", []),
    )

    hn_hiring_raw = raw.get("hn_hiring", {})
    hn_hiring = HNHiringConfig(
        enabled=hn_hiring_raw.get("enabled", True),
        max_comments=hn_hiring_raw.get("max_comments", 500),
    )

    pipeline_order = raw.get("pipeline_order", [
        "text_extraction", "dedup", "hard_filter", "storage",
    ])

    return ScraperConfig(
        boards=boards,
        searxng=searxng,
        usajobs=usajobs,
        remoteok=remoteok,
        hn_hiring=hn_hiring,
        hard_filters=hard_filters,
        queries=queries,
        seen_ttl_days=filter_raw.get("seen_ttl_days", 14),
        target_max_results=filter_raw.get("target_max_results", 50),
        pipeline_order=pipeline_order,
    )
