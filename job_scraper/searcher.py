"""SearXNG query execution."""

from __future__ import annotations

import logging
import time

import requests

from .config import QueryTemplate, ScraperConfig
from .models import JobBoard, SearchResult

logger = logging.getLogger(__name__)

_BOARD_MAP = {
    "greenhouse": JobBoard.greenhouse,
    "lever": JobBoard.lever,
    "ashby": JobBoard.ashby,
    "workday": JobBoard.workday,
    "bamboohr": JobBoard.bamboohr,
    "icims": JobBoard.icims,
    "smartrecruiters": JobBoard.smartrecruiters,
    "jobvite": JobBoard.jobvite,
}


def build_query_string(template: QueryTemplate) -> str:
    """Assemble a search query from a template."""
    parts = []
    if template.board_site:
        parts.append(f"site:{template.board_site}")
    if template.title_phrase:
        parts.append(f'"{template.title_phrase}"')
    if template.suffix:
        parts.append(template.suffix)
    return " ".join(parts)


def execute_queries(config: ScraperConfig) -> list[SearchResult]:
    """Run all configured queries against SearXNG and return deduplicated results."""
    seen_urls: set[str] = set()
    results: list[SearchResult] = []
    search = config.search

    for i, template in enumerate(config.queries):
        query_str = build_query_string(template)
        board = _BOARD_MAP.get(template.board, JobBoard.unknown)

        logger.debug("Query %d/%d: %s", i + 1, len(config.queries), query_str)

        try:
            resp = requests.get(
                search.searx_url,
                params={
                    "q": query_str,
                    "format": "json",
                    "engines": search.engines,
                    "time_range": search.time_range,
                },
                timeout=search.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Query failed [%s]: %s", query_str, e)
            continue

        query_results = data.get("results", [])
        query_new = 0

        for item in query_results[: search.max_results_per_query]:
            url = item.get("url", "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            query_new += 1
            results.append(
                SearchResult(
                    title=item.get("title", "").strip(),
                    url=url,
                    snippet=item.get("content", "").strip(),
                    query=query_str,
                    board=board,
                )
            )

        logger.info(
            "Query %d/%d: %d results, %d new — %s",
            i + 1, len(config.queries), len(query_results), query_new, query_str,
        )

        # Rate limit between queries
        if i < len(config.queries) - 1:
            time.sleep(search.request_delay)

    return results
