"""Spider for Greenhouse job boards via public API (boards-api.greenhouse.io)."""
from __future__ import annotations
import json, logging
from datetime import datetime, timezone
import scrapy
from job_scraper.items import JobItem
from job_scraper.spiders import diversified_subset, title_matches
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

    def _org_slug(self, url: str) -> str:
        """Extract org slug: https://job-boards.greenhouse.io/adyen -> adyen"""
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
            api_url = f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs"
            yield scrapy.Request(
                url=api_url,
                callback=self.parse_board,
                meta={"company": board["company"], "org": org},
                dont_filter=True,
            )

    def parse_board(self, response):
        company = response.meta["company"]
        org = response.meta["org"]
        try:
            data = json.loads(response.text)
            jobs = data.get("jobs", [])
        except (json.JSONDecodeError, KeyError):
            logger.warning("Failed to parse Greenhouse API response for %s", org)
            return

        logger.info("Greenhouse %s: %d job postings (limit %d)", org, len(jobs), self._max_per_board)
        for job in jobs[:self._max_per_board]:
            job_id = job["id"]
            detail_url = f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs/{job_id}"
            yield scrapy.Request(
                url=detail_url,
                callback=self.parse_job,
                meta={"company": company, "org": org},
                dont_filter=True,
            )

    def parse_job(self, response):
        company = response.meta["company"]
        org = response.meta["org"]
        try:
            job = json.loads(response.text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse Greenhouse job detail for %s", org)
            return

        title = job.get("title", "Unknown")
        if not title_matches(title):
            logger.debug("Greenhouse %s: skipping non-matching title: %s", org, title)
            return
        location = job.get("location", {}).get("name", "")
        jd_html = job.get("content", "")
        url = job.get("absolute_url", response.url)

        yield JobItem(
            url=url,
            title=title.strip(),
            company=company,
            board="greenhouse",
            location=location,
            jd_html=jd_html,
            source=self.name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
