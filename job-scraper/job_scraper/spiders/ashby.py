"""Spider for Ashby job boards via posting-api JSON."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import scrapy

from job_scraper.items import JobItem
from job_scraper.spiders import diversified_subset
from job_scraper.tiers import rotation_filter

logger = logging.getLogger(__name__)

_MAX_BOARDS_PER_RUN = 12


class AshbySpider(scrapy.Spider):
    name = "ashby"

    def __init__(self, boards=None, max_per_board=50, run_id="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boards = boards or []
        self._max_per_board = max_per_board
        self._run_id = run_id

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        boards = [{"url": b.url, "company": b.company} for b in cfg.boards if b.board_type == "ashby" and b.enabled]
        kwargs["boards"] = boards
        kwargs["max_per_board"] = cfg.target_max_results
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
            "Ashby: scraping %d/%d boards this run (group=%s, rotated=%d)",
            len(boards), len(self._boards), self._rotation_group, len(rotated),
        )
        for board in boards:
            org = self._slug_from_url(board["url"])
            yield scrapy.Request(
                url=f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true",
                callback=self.parse_board_json,
                meta={"company": board["company"], "org": org},
                dont_filter=True,
            )

    def parse_board_json(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Ashby JSON endpoint returned non-JSON: %s", response.url)
            return
        company = response.meta.get("company", "unknown")
        for job in data.get("jobs", []):
            salary_k = None
            comp_data = job.get("compensation") or {}
            comp = comp_data.get("summaryComponents") or []
            if comp:
                values = [c.get("minValue") for c in comp if c.get("minValue")]
                if values:
                    salary_k = min(values) / 1000.0
            salary_text = comp_data.get("compensationTierSummary") or comp_data.get("scrapeableCompensationSalarySummary") or ""

            # Compose richer location string from location + workplaceType +
            # address country, so downstream geo/remote checks have explicit
            # signal even when `location` is just a city name.
            location = job.get("location", "") or ""
            workplace = job.get("workplaceType") or ""
            is_remote = job.get("isRemote")
            country = ((job.get("address") or {}).get("postalAddress") or {}).get("addressCountry") or ""
            parts = [location]
            if country and country.lower() not in location.lower():
                parts.append(country)
            if workplace and workplace.lower() not in location.lower():
                parts.append(workplace)
            if is_remote is True and "remote" not in " ".join(parts).lower():
                parts.append("Remote")
            location_full = ", ".join(p for p in parts if p)

            yield JobItem(
                url=job.get("jobUrl", ""),
                title=job.get("title", "Unknown"),
                company=company,
                board="ashby",
                location=location_full,
                salary_text=salary_text,
                salary_k=salary_k,
                jd_html=job.get("descriptionHtml", ""),
                jd_text="",
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
