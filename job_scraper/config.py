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
    engines: str = "google,bing,duckduckgo"
    time_range: str = "month"
    request_delay: float = 1.0


class FilterConfig(BaseModel):
    title_keywords: list[str] = Field(default_factory=lambda: [
        "security", "cyber", "appsec", "devsecops", "detection",
        "vulnerability", "soc", "infosec", "secops",
    ])
    seniority_exclude: list[str] = Field(default_factory=lambda: [
        "senior", "staff", "principal", "lead", "manager", "director",
    ])
    max_experience_years: int = 4
    content_blocklist: list[str] = Field(default_factory=lambda: [
        "clearance", "ts/sci", "ts-sci", "polygraph", "top secret",
        "secret clearance",
    ])
    title_role_words: list[str] = Field(default_factory=lambda: [
        "engineer", "analyst", "architect", "developer", "specialist",
        "consultant", "administrator", "operator", "intern", "associate",
        "responder", "researcher", "pentester", "tester",
    ])
    url_domain_blocklist: list[str] = Field(default_factory=lambda: [
        "dictionary.com", "collinsdictionary.com", "techtarget.com",
        "wikipedia.org", "merriam-webster.com", "investopedia.com",
        "reddit.com", "quora.com", "youtube.com", "medium.com",
    ])
    require_remote: bool = False
    fetch_jd: bool = True
    jd_max_chars: int = 15000


class QueryTemplate(BaseModel):
    board: str = "unknown"
    board_site: str = ""
    title_phrase: str = ""
    suffix: str = ""


class ScraperConfig(BaseModel):
    search: SearchConfig = Field(default_factory=SearchConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)
    queries: list[QueryTemplate] = Field(default_factory=list)


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
