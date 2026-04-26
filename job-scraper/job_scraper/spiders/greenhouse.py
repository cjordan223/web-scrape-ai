"""Spider for Greenhouse job boards via boards-api.greenhouse.io JSON."""
from __future__ import annotations
import logging
from datetime import datetime, timezone

import scrapy

from job_scraper.items import JobItem
from job_scraper.spiders import diversified_subset
from job_scraper.tiers import rotation_filter

logger = logging.getLogger(__name__)

_MAX_BOARDS_PER_RUN = 6


class GreenhouseSpider(scrapy.Spider):
    name = "greenhouse"

    def __init__(self, boards=None, max_per_board=50, run_id="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boards = boards or []
        self._max_per_board = max_per_board
        self._run_id = run_id

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        boards = [{"url": b.url, "company": b.company} for b in cfg.boards if b.board_type == "greenhouse" and b.enabled]
        kwargs["boards"] = boards
        kwargs["max_per_board"] = cfg.target_max_results
        kwargs["run_id"] = crawler.settings.get("SCRAPE_RUN_ID", "")
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider._rotation_group = crawler.settings.get("SCRAPE_ROTATION_GROUP")
        spider._rotation_total = crawler.settings.getint("SCRAPE_ROTATION_TOTAL", 4)
        return spider

    @staticmethod
    def _org_slug(url: str) -> str:
        return url.rstrip("/").split("/")[-1]

    def start_requests(self):
        rotated = rotation_filter(
            self._boards,
            rotation_group=self._rotation_group,
            total_groups=self._rotation_total,
            key=lambda b: b.get("url", ""),
        )
        boards = diversified_subset(
            rotated,
            run_id=self._run_id,
            scope=self.name,
            limit=_MAX_BOARDS_PER_RUN,
            key=lambda board: board["url"],
        )
        logger.info(
            "Greenhouse: scraping %d/%d boards this run (group=%s, rotated=%d)",
            len(boards), len(self._boards), self._rotation_group, len(rotated),
        )
        for board in boards:
            org = self._org_slug(board["url"])
            yield scrapy.Request(
                url=f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs?content=true",
                callback=self.parse_board_json,
                meta={"company": board["company"], "org": org},
                dont_filter=True,
            )

    def parse_board_json(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Greenhouse JSON endpoint returned non-JSON: %s", response.url)
            return
        company = response.meta.get("company", "unknown")
        for job in data.get("jobs", []):
            loc = (job.get("location") or {}).get("name") or ""
            yield JobItem(
                url=job.get("absolute_url", ""),
                title=job.get("title", "Unknown"),
                company=company,
                board="greenhouse",
                location=loc,
                jd_html=job.get("content") or "",
                jd_text="",
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
