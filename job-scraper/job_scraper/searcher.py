"""SearXNG query execution."""

from __future__ import annotations

import logging
import time

import requests

from .config import QueryTemplate, ScraperConfig
from .models import JobBoard, SearchResult
from .urlnorm import canonicalize_job_url

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


def _format_unresponsive_engines(raw: object) -> list[str]:
    items: list[str] = []
    if not isinstance(raw, list):
        return items
    for entry in raw:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            engine = str(entry[0]).strip()
            reason = str(entry[1]).strip()
            if engine or reason:
                items.append(f"{engine}: {reason}".strip(": "))
        elif entry:
            items.append(str(entry).strip())
    return items


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

        engine_candidates: list[str | None] = [search.engines]
        for fallback in search.fallback_engines:
            if fallback and fallback not in engine_candidates:
                engine_candidates.append(fallback)
        if search.fallback_to_all_engines and None not in engine_candidates:
            engine_candidates.append(None)

        time_range_candidates = [search.time_range]
        for fallback_range in search.fallback_time_ranges:
            if fallback_range and fallback_range not in time_range_candidates:
                time_range_candidates.append(fallback_range)

        query_results = []
        last_error = None
        used_engines = search.engines
        used_time_range = search.time_range
        engine_failures: list[str] = []
        for time_range in time_range_candidates:
            for engines in engine_candidates:
                try:
                    params = {
                        "q": query_str,
                        "format": "json",
                        "time_range": time_range,
                    }
                    if engines:
                        params["engines"] = engines
                    resp = requests.get(search.searx_url, params=params, timeout=search.timeout)
                    resp.raise_for_status()
                    data = resp.json()
                    query_results = data.get("results", [])
                    unresponsive = _format_unresponsive_engines(data.get("unresponsive_engines"))
                    if unresponsive:
                        engine_failures.extend(
                            reason for reason in unresponsive
                            if reason not in engine_failures
                        )
                    used_engines = engines or "all"
                    used_time_range = time_range
                    if query_results:
                        break
                except Exception as e:
                    last_error = e
                    continue
            if query_results:
                break

        if not query_results and last_error is not None:
            logger.error("Query failed [%s]: %s", query_str, last_error)
            continue

        if not query_results and engine_failures:
            logger.warning(
                "Query %d/%d returned 0 results because upstream search engines were unavailable [%s]: %s",
                i + 1,
                len(config.queries),
                query_str,
                "; ".join(engine_failures),
            )

        query_new = 0

        for item in query_results[: search.max_results_per_query]:
            url = canonicalize_job_url(item.get("url", "").strip())
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
            "Query %d/%d: %d results, %d new (engines=%s, time_range=%s) — %s",
            i + 1, len(config.queries), len(query_results), query_new, used_engines, used_time_range, query_str,
        )

        # Rate limit between queries
        if i < len(config.queries) - 1:
            time.sleep(search.request_delay)

    return results
