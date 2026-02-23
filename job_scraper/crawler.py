"""Job board crawling via Crawl4AI."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from urllib.parse import urljoin

from .config import CrawlTarget, ScraperConfig
from .models import JobBoard, SearchResult

logger = logging.getLogger(__name__)

# Built-in link patterns per board
_BOARD_PATTERNS: dict[str, str] = {
    "greenhouse": r"/jobs/\d+",
    "lever": r"/[^/]+/[0-9a-f-]{36}",
    "ashby": r"/[^/]+/[0-9a-f-]{36}",
}

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


async def _crawl_targets(config: ScraperConfig) -> list[SearchResult]:
    """Async implementation of board crawling."""
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

    crawl_cfg = config.crawl
    results: list[SearchResult] = []
    seen_urls: set[str] = set()

    run_config = CrawlerRunConfig(
        wait_until="networkidle",
        page_timeout=15000,
    )

    async with AsyncWebCrawler() as crawler:
        for i, target in enumerate(crawl_cfg.targets):
            board = _BOARD_MAP.get(target.board, JobBoard.unknown)
            pattern = target.link_pattern or _BOARD_PATTERNS.get(target.board)

            logger.debug("Crawling target %d/%d: %s", i + 1, len(crawl_cfg.targets), target.url)

            try:
                result = await crawler.arun(url=target.url, config=run_config)

                if not result.success:
                    logger.error("Crawl failed for %s: %s", target.url, result.error_message)
                    continue

                target_count = 0
                for link in result.links.get("internal", []) + result.links.get("external", []):
                    href = link.get("href", "").strip()
                    text = link.get("text", "").strip()

                    if not href:
                        continue

                    url = urljoin(target.url, href)

                    if pattern and not re.search(pattern, url):
                        continue

                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    target_count += 1
                    results.append(
                        SearchResult(
                            title=text or url.split("/")[-1],
                            url=url,
                            query=f"crawl:{target.url}",
                            board=board,
                        )
                    )

                    if target_count >= crawl_cfg.max_results_per_target:
                        break

                logger.info(
                    "Crawl target %d/%d: %d links found — %s",
                    i + 1, len(crawl_cfg.targets), target_count, target.url,
                )

            except Exception as e:
                logger.error("Crawl error for %s: %s", target.url, e)

            # Rate limit between targets
            if i < len(crawl_cfg.targets) - 1:
                time.sleep(crawl_cfg.request_delay)

    return results


def crawl_job_boards(config: ScraperConfig) -> list[SearchResult]:
    """Crawl configured job board pages and extract job listing URLs."""
    if not config.crawl.targets:
        return []

    logger.info("Crawling %d job board targets...", len(config.crawl.targets))
    return asyncio.run(_crawl_targets(config))
