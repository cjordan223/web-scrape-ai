"""Scrapy spiders for job_scraper — shared utilities."""
from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=1)
def _get_title_patterns() -> tuple[re.Pattern, ...]:
    from job_scraper.config import load_config
    cfg = load_config()
    return tuple(
        re.compile(rf"\b{re.escape(kw)}\b", re.I)
        for kw in cfg.hard_filters.title_keywords
    )


def title_matches(title: str) -> bool:
    """Return True if the job title contains at least one inclusion keyword."""
    return any(p.search(title) for p in _get_title_patterns())
