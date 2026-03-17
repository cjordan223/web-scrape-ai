"""Watcher plugin system — source-agnostic job discovery."""

from __future__ import annotations

import importlib
import logging
import re
from typing import TYPE_CHECKING

import httpx

from .models import JobBoard, SearchResult

if TYPE_CHECKING:
    from .config import ScraperConfig, WatcherConfig

logger = logging.getLogger(__name__)


def run_watchers(config: ScraperConfig) -> list[SearchResult]:
    """Run all enabled watchers. Returns SearchResults with source/skip_filters set."""
    results: list[SearchResult] = []
    for w in config.watchers:
        if not w.enabled:
            continue
        try:
            runner = _RUNNERS.get(w.type)
            if runner is None:
                logger.warning("Unknown watcher type %r for %r, skipping", w.type, w.name)
                continue
            items = runner(w)
            logger.info("Watcher %r (%s) returned %d results", w.name, w.type, len(items))
            results.extend(items)
        except Exception:
            logger.exception("Watcher %r failed", w.name)
    return results


def _make_result(w: WatcherConfig, title: str, url: str, snippet: str = "") -> SearchResult:
    board = JobBoard.unknown
    try:
        board = JobBoard(w.board)
    except ValueError:
        pass
    return SearchResult(
        title=title,
        url=url,
        snippet=snippet,
        source=f"watcher:{w.name}",
        skip_filters=list(w.skip_filters),
        board=board,
    )


def _crawl_watcher(w: WatcherConfig) -> list[SearchResult]:
    """Reuse Crawl4AI for a single target URL."""
    import asyncio

    from crawl4ai import AsyncWebCrawler

    pattern = re.compile(w.link_pattern) if w.link_pattern else None

    async def _run() -> list[str]:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=w.url)
            links: list[str] = []
            if result.links:
                for cat in ("internal", "external"):
                    for link_obj in getattr(result.links, cat, []) if isinstance(result.links, dict) else result.links.get(cat, []):
                        href = link_obj.get("href", "") if isinstance(link_obj, dict) else getattr(link_obj, "href", "")
                        if href and (pattern is None or pattern.search(href)):
                            links.append(href)
            return links

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            links = pool.submit(lambda: asyncio.run(_run())).result()
    else:
        links = asyncio.run(_run())

    return [_make_result(w, "", link) for link in links]


def _rss_watcher(w: WatcherConfig) -> list[SearchResult]:
    """Parse RSS/Atom feed via feedparser."""
    import feedparser

    feed = feedparser.parse(w.url)
    results: list[SearchResult] = []
    for entry in feed.entries:
        title = getattr(entry, "title", "") or ""
        link = getattr(entry, "link", "") or ""
        summary = getattr(entry, "summary", "") or ""
        if link:
            results.append(_make_result(w, title, link, summary[:500]))
    return results


def _resolve_path(obj: object, path: str) -> object:
    """Navigate a nested dict/list by dot-path, e.g. 'data.jobs' or 'items.0.title'."""
    for key in path.split("."):
        if isinstance(obj, list):
            try:
                obj = obj[int(key)]
            except (ValueError, IndexError):
                return None
        elif isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
        if obj is None:
            return None
    return obj


def _api_watcher(w: WatcherConfig) -> list[SearchResult]:
    """Poll a JSON REST endpoint, extract jobs via field mapping."""
    with httpx.Client(timeout=30) as client:
        if w.method.upper() == "POST":
            resp = client.post(w.url, headers=w.headers, json=w.params)
        else:
            resp = client.get(w.url, headers=w.headers, params=w.params)
        resp.raise_for_status()
        data = resp.json()

    items = _resolve_path(data, w.results_path) if w.results_path else data
    if not isinstance(items, list):
        logger.warning("API watcher %r: results_path did not resolve to a list", w.name)
        return []

    results: list[SearchResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = _resolve_path(item, w.title_field) or ""
        url = _resolve_path(item, w.url_field) or ""
        snippet = (_resolve_path(item, w.snippet_field) or "") if w.snippet_field else ""
        if url:
            results.append(_make_result(w, str(title), str(url), str(snippet)[:500]))
    return results


def _custom_watcher(w: WatcherConfig) -> list[SearchResult]:
    """Import module, call module.fetch(w)."""
    if not w.module:
        logger.warning("Custom watcher %r has no module specified", w.name)
        return []
    mod = importlib.import_module(w.module)
    fetch_fn = getattr(mod, "fetch", None)
    if not callable(fetch_fn):
        logger.warning("Module %r for watcher %r has no fetch() function", w.module, w.name)
        return []
    raw = fetch_fn(w)
    # Stamp source/skip_filters onto results
    results: list[SearchResult] = []
    for r in raw:
        if isinstance(r, SearchResult):
            r.source = r.source or f"watcher:{w.name}"
            r.skip_filters = r.skip_filters or list(w.skip_filters)
            results.append(r)
    return results


_RUNNERS = {
    "crawl": _crawl_watcher,
    "rss": _rss_watcher,
    "api": _api_watcher,
    "custom": _custom_watcher,
}
