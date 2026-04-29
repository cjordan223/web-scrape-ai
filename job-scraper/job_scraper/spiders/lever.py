"""Spider for Lever job boards via postings-api JSON."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import scrapy

from job_scraper.items import JobItem
from job_scraper.spiders import diversified_subset
from job_scraper.tiers import rotation_filter

logger = logging.getLogger(__name__)

_MAX_BOARDS_PER_RUN = 6


class LeverSpider(scrapy.Spider):
    name = "lever"

    def __init__(self, boards=None, run_id="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boards = boards or []
        self._run_id = run_id

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        boards = [{"url": b.url, "company": b.company} for b in cfg.boards if b.board_type == "lever" and b.enabled]
        kwargs["boards"] = boards
        kwargs["run_id"] = crawler.settings.get("SCRAPE_RUN_ID", "")
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider._rotation_group = crawler.settings.get("SCRAPE_ROTATION_GROUP")
        spider._rotation_total = crawler.settings.getint("SCRAPE_ROTATION_TOTAL", 4)
        return spider

    @staticmethod
    def _slug_from_url(url: str) -> str:
        path = urlparse(url).path.strip("/")
        return path.split("/")[0] if path else ""

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
            "Lever: scraping %d/%d boards this run (group=%s, rotated=%d)",
            len(boards), len(self._boards), self._rotation_group, len(rotated),
        )
        for board in boards:
            slug = self._slug_from_url(board["url"])
            yield scrapy.Request(
                url=f"https://api.lever.co/v0/postings/{slug}?mode=json",
                callback=self.parse_board_json,
                meta={"company": board["company"]},
                dont_filter=True,
            )

    def parse_board_json(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Lever JSON endpoint returned non-JSON: %s", response.url)
            return
        company = response.meta.get("company", "unknown")
        for job in data:
            categories = job.get("categories") or {}
            salary_k = None
            sr = job.get("salaryRange") or {}
            top = sr.get("max") or sr.get("min")
            if top:
                salary_k = top / 1000.0
            jd_html = (
                job.get("descriptionHtml")
                or job.get("descriptionBody")
                or job.get("description")
                or ""
            )
            additional_html = job.get("additional") or ""
            if additional_html:
                jd_html = f"{jd_html}\n{additional_html}".strip()
            jd_text = (
                job.get("descriptionPlain")
                or job.get("descriptionBodyPlain")
                or ""
            )
            additional_plain = job.get("additionalPlain") or ""
            if additional_plain:
                jd_text = f"{jd_text}\n{additional_plain}".strip()
            yield JobItem(
                url=job.get("hostedUrl", ""),
                ats_provider="lever",
                ats_job_id=str(job.get("id") or ""),
                title=job.get("text", "Unknown"),
                company=company,
                board="lever",
                location=categories.get("location", ""),
                salary_k=salary_k,
                jd_html=jd_html,
                jd_text=jd_text,
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
