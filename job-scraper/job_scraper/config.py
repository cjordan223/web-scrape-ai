"""YAML config loader + Pydantic models."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

_DEFAULT_CONFIG = Path(__file__).parent / "config.default.yaml"


class SearchConfig(BaseModel):
    searx_url: str = "http://localhost:8888/search"
    timeout: int = 15
    max_results_per_query: int = 20
    engines: str = "google,startpage"
    fallback_engines: list[str] = Field(default_factory=lambda: ["google", "startpage"])
    time_range: str = "month"
    fallback_time_ranges: list[str] = Field(default_factory=lambda: ["year"])
    fallback_to_all_engines: bool = True
    request_delay: float = 1.0


class FilterConfig(BaseModel):
    title_keywords: list[str] = Field(default_factory=lambda: [
        "security", "cyber", "appsec", "devsecops", "detection",
        "vulnerability", "soc", "infosec", "secops",
    ])
    seniority_exclude: list[str] = Field(default_factory=lambda: [
        "senior", "staff", "principal", "lead", "manager", "director",
    ])
    max_experience_years: int = 6
    min_salary_k: int = 95
    content_blocklist: list[str] = Field(default_factory=lambda: [
        "clearance", "ts/sci", "ts-sci", "polygraph", "top secret",
        "secret clearance",
    ])
    title_role_words: list[str] = Field(default_factory=lambda: [
        "engineer", "analyst", "architect", "developer", "specialist",
        "consultant", "administrator", "operator", "associate",
        "responder", "researcher", "pentester", "tester",
    ])
    url_domain_blocklist: list[str] = Field(default_factory=lambda: [
        "dictionary.com", "collinsdictionary.com", "techtarget.com",
        "wikipedia.org", "merriam-webster.com", "investopedia.com",
        "reddit.com", "quora.com", "youtube.com", "medium.com",
    ])
    require_remote: bool = True
    require_explicit_remote: bool = False
    require_us_location: bool = True
    require_known_board: bool = True
    fetch_jd: bool = True
    min_jd_chars: int = 120
    jd_max_chars: int = 15000
    score_accept_threshold: int = 0
    score_reject_threshold: int = -3
    target_min_results: int = 5
    target_max_results: int = 10
    promotion_min_score: int = 0


class QueryTemplate(BaseModel):
    board: str = "unknown"
    board_site: str = ""
    title_phrase: str = ""
    suffix: str = ""


class CrawlTarget(BaseModel):
    url: str
    board: str = "unknown"
    link_pattern: str | None = None


class CrawlConfig(BaseModel):
    enabled: bool = False
    targets: list[CrawlTarget] = Field(default_factory=list)
    request_delay: float = 2.0
    max_results_per_target: int = 50


class LLMReviewConfig(BaseModel):
    enabled: bool = False
    url: str = "http://localhost:1234/v1/chat/completions"
    model: str = "default"
    fail_open: bool = False
    timeout: int = 30
    jd_max_chars: int = 2000


class ScraperConfig(BaseModel):
    search: SearchConfig = Field(default_factory=SearchConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)
    queries: list[QueryTemplate] = Field(default_factory=list)
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)
    llm_review: LLMReviewConfig = Field(default_factory=LLMReviewConfig)


def load_config(config_path: Optional[Path] = None) -> ScraperConfig:
    """Load config from YAML, falling back to defaults."""
    # Start with defaults
    with open(_DEFAULT_CONFIG) as f:
        data = yaml.safe_load(f)

    # Merge user overrides if provided
    if config_path and config_path.exists():
        with open(config_path) as f:
            overrides = yaml.safe_load(f) or {}
        _deep_merge(data, overrides)

    return ScraperConfig.model_validate(data)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base dict."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base
