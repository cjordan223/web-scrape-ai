"""Spider for Lever job boards."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
import scrapy
from job_scraper.items import JobItem
from job_scraper.spiders import diversified_subset, title_matches
from job_scraper.tiers import rotation_filter

logger = logging.getLogger(__name__)

_MAX_BOARDS_PER_RUN = 2

class LeverSpider(scrapy.Spider):
    name = "lever"
    custom_settings = {
        "PLAYWRIGHT_CONTEXTS": {
            "lever": {
                "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "viewport": {"width": 1920, "height": 1080},
                "java_script_enabled": True,
            }
        }
    }
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
            yield scrapy.Request(url=board["url"], callback=self.parse_board, meta={"company": board["company"], "playwright": True, "playwright_context": "lever", "playwright_include_page": False, "playwright_page_methods": [{"method": "wait_for_timeout", "args": [3000]}]}, dont_filter=True)

    def parse_board(self, response):
        company = response.meta.get("company", "unknown")
        for link in response.css('a.posting-title::attr(href)').getall():
            yield scrapy.Request(url=response.urljoin(link), callback=self.parse_job, meta={"company": company, "board": "lever", "playwright": True, "playwright_context": "lever", "playwright_include_page": False, "playwright_page_methods": [{"method": "wait_for_timeout", "args": [2000]}]})
        if not response.css('a.posting-title').getall():
            for link in response.css('a[href*="/"]::attr(href)').getall():
                full_url = response.urljoin(link)
                if company in full_url and full_url.count("/") >= 4:
                    yield scrapy.Request(url=full_url, callback=self.parse_job, meta={"company": company, "board": "lever", "playwright": True, "playwright_context": "lever"})

    def parse_job(self, response):
        company = response.meta.get("company", "unknown")
        title = response.css(".posting-headline h2::text").get() or response.css("h1::text").get() or "Unknown"
        if not title_matches(title):
            logger.debug("Lever %s: skipping non-matching title: %s", company, title)
            return
        jd_html = response.css(".posting-page-content").get() or response.css(".content").get() or response.text
        location = response.css(".sort-by-location::text").get() or ""
        yield JobItem(url=response.url, title=title.strip(), company=company, board="lever", location=location.strip(), jd_html=jd_html, source=self.name, created_at=datetime.now(timezone.utc).isoformat())
