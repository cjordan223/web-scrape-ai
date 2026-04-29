"""Workable JSON API spider (workhorse tier)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import scrapy

from job_scraper.items import JobItem

logger = logging.getLogger(__name__)


class WorkableSpider(scrapy.Spider):
    name = "workable"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._targets: list[dict] = []
        self._rotation_group: int | None = None
        self._rotation_total: int = 4

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider._targets = [
            {"url": b.url, "company": b.company}
            for b in cfg.boards if b.board_type == "workable" and b.enabled
        ]
        spider._rotation_group = crawler.settings.get("SCRAPE_ROTATION_GROUP")
        spider._rotation_total = crawler.settings.getint("SCRAPE_ROTATION_TOTAL", 4)
        return spider

    def start_requests(self):
        from job_scraper.tiers import rotation_filter
        targets = rotation_filter(
            self._targets,
            rotation_group=self._rotation_group,
            total_groups=self._rotation_total,
            key=lambda t: t["url"],
        )
        logger.info(
            "Workable: crawling %d/%d targets (group=%s)",
            len(targets), len(self._targets), self._rotation_group,
        )
        for target in targets:
            slug = self._slug_from_url(target["url"])
            yield scrapy.Request(
                url=f"https://apply.workable.com/api/v3/accounts/{slug}/jobs",
                callback=self.parse_board,
                meta={"company": target["company"]},
                dont_filter=True,
            )

    def parse_board(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Workable returned non-JSON: %s", response.url)
            return
        company = response.meta.get("company", "unknown")
        for job in data.get("results", []):
            loc = job.get("location") or {}
            location_str = ", ".join(
                x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x
            )
            yield JobItem(
                url=job.get("url") or job.get("application_url", ""),
                ats_provider="workable",
                ats_job_id=str(job.get("id") or job.get("shortcode") or ""),
                title=job.get("title", "Unknown"),
                company=company,
                board="workable",
                location=location_str,
                jd_html=job.get("description") or "",
                jd_text="",
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )

    @staticmethod
    def _slug_from_url(url: str) -> str:
        path = urlparse(url).path.strip("/")
        return path.split("/")[0] if path else ""
