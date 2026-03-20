"""Spider for Greenhouse job boards."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
import scrapy
from job_scraper.items import JobItem

logger = logging.getLogger(__name__)

class GreenhouseSpider(scrapy.Spider):
    name = "greenhouse"
    def __init__(self, boards=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boards = boards or []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        boards = [{"url": b.url, "company": b.company} for b in cfg.boards if b.board_type == "greenhouse" and b.enabled]
        kwargs["boards"] = boards
        spider = super().from_crawler(crawler, *args, **kwargs)
        return spider

    def start_requests(self):
        for board in self._boards:
            yield scrapy.Request(url=board["url"], callback=self.parse_board, meta={"company": board["company"], "playwright": True, "playwright_include_page": False, "playwright_page_methods": [{"method": "wait_for_timeout", "args": [3000]}]}, dont_filter=True)

    def parse_board(self, response):
        company = response.meta.get("company", "unknown")
        for link in response.css('a[href*="/jobs/"]::attr(href)').getall():
            full_url = response.urljoin(link)
            if "/jobs/" in full_url:
                yield scrapy.Request(url=full_url, callback=self.parse_job, meta={"company": company, "board": "greenhouse", "playwright": True, "playwright_include_page": False, "playwright_page_methods": [{"method": "wait_for_timeout", "args": [2000]}]})

    def parse_job(self, response):
        company = response.meta.get("company", "unknown")
        title = response.css("h1::text").get() or "Unknown"
        jd_html = response.css(".job-post-content").get() or response.css("#content").get() or response.text
        location = response.css(".location::text").get() or ""
        yield JobItem(url=response.url, title=title.strip(), company=company, board="greenhouse", location=location.strip(), jd_html=jd_html, source=self.name, discovered_at=datetime.now(timezone.utc).isoformat())
