"""YAML config loader for scraper v2."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from job_scraper.scrape_profile import ScrapeProfile

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
    require_us_location: bool = True
    require_remote: bool = True
    require_explicit_remote: bool = False
    allow_canada: bool = False
    max_experience_years: int = 5


class SearXNGQuery(BaseModel):
    title_phrase: str
    board_site: str = ""
    suffix: str = ""


class ScraperConfig(BaseModel):
    boards: list[BoardTarget] = Field(default_factory=list)
    searxng: SearXNGConfig = Field(default_factory=SearXNGConfig)
    hard_filters: HardFilterConfig = Field(default_factory=HardFilterConfig)
    queries: list[SearXNGQuery] = Field(default_factory=list)
    target_max_results: int = 50
    pipeline_order: list[str] = Field(default_factory=lambda: [
        "text_extraction", "dedup", "hard_filter", "storage",
    ])
    scrape_profile: ScrapeProfile = Field(default_factory=ScrapeProfile)


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

    filter_raw = raw.get("filter", {})
    hard_filters = HardFilterConfig(
        domain_blocklist=filter_raw.get("url_domain_blocklist", HardFilterConfig().domain_blocklist),
        title_blocklist=filter_raw.get("seniority_exclude", HardFilterConfig().title_blocklist),
        content_blocklist=filter_raw.get("content_blocklist", HardFilterConfig().content_blocklist),
        title_keywords=filter_raw.get("title_keywords", []),
        min_salary_k=filter_raw.get("min_salary_k", 100),
        target_salary_k=filter_raw.get("target_salary_k", 150),
        require_us_location=bool(filter_raw.get("require_us_location", True)),
        require_remote=bool(filter_raw.get("require_remote", True)),
        require_explicit_remote=bool(filter_raw.get("require_explicit_remote", False)),
        allow_canada=bool(filter_raw.get("allow_canada", False)),
        max_experience_years=int(filter_raw.get("max_experience_years", 5)),
    )

    pipeline_order = raw.get("pipeline_order", [
        "text_extraction", "dedup", "hard_filter", "storage",
    ])

    profile_raw = raw.get("scrape_profile") or {}
    scrape_profile = ScrapeProfile(**profile_raw) if profile_raw else ScrapeProfile()

    return ScraperConfig(
        boards=boards,
        searxng=searxng,
        hard_filters=hard_filters,
        queries=queries,
        target_max_results=filter_raw.get("target_max_results", 50),
        pipeline_order=pipeline_order,
        scrape_profile=scrape_profile,
    )
