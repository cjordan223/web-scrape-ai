"""Scrapy spiders for job_scraper — shared utilities."""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache


# URL path segments that act as aggregator/board prefixes rather than company
# slugs. Used by spider company-extraction and hard_filter company-sanity.
AGGREGATOR_PATH_SEGMENTS = frozenset({
    "jobs", "job", "careers", "career", "companies", "company",
    "hiring", "apply", "listings", "listing", "browse", "view",
    "positions", "position",
})


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


def run_seed(run_id: str, scope: str) -> int:
    digest = hashlib.sha256(f"{run_id}:{scope}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def diversified_subset(
    items: list,
    *,
    run_id: str,
    scope: str,
    limit: int | None,
    key: callable | None = None,
):
    """Pick a stable per-run subset so consecutive scrapes hit different slices.

    The ordering changes with run_id but remains deterministic inside a run.
    """
    if limit is None or limit <= 0 or len(items) <= limit:
        return list(items)
    item_key = key or (lambda item: str(item))
    scored = []
    for item in items:
        token = f"{run_id}:{scope}:{item_key(item)}"
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        scored.append((digest, item))
    scored.sort(key=lambda pair: pair[0])
    return [item for _, item in scored[:limit]]
