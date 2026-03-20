"""Spider for aggregator sites (SimplyHired)."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
import scrapy
from job_scraper.items import JobItem

logger = logging.getLogger(__name__)

class AggregatorSpider(scrapy.Spider):
    name = "aggregator"
    def __init__(self, boards=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boards = boards or []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        boards = [{"url": b.url, "company": b.company} for b in cfg.boards if b.board_type == "simplyhired" and b.enabled]
        kwargs["boards"] = boards
        spider = super().from_crawler(crawler, *args, **kwargs)
        return spider

    def start_requests(self):
        for board in self._boards:
            yield scrapy.Request(url=board["url"], callback=self.parse_board, meta={"playwright": True, "playwright_include_page": False, "playwright_page_methods": [{"method": "wait_for_timeout", "args": [3000]}]}, dont_filter=True)

    def parse_board(self, response):
        for article in response.css("article.SerpJob, li.SerpJob"):
            link = article.css("a.SerpJob-link::attr(href), a.card-link::attr(href)").get()
            title = article.css("h2.jobposting-title::text, h2::text").get() or "Unknown"
            company = article.css(".jobposting-company::text, .company::text").get() or "Unknown"
            location = article.css(".jobposting-location::text, .location::text").get() or ""
            if link:
                yield scrapy.Request(url=response.urljoin(link), callback=self.parse_job, meta={"title": title.strip(), "company": company.strip(), "location": location.strip(), "playwright": True, "playwright_include_page": False})
        if not response.css("article.SerpJob, li.SerpJob"):
            for link in response.css('a[href*="/job/"]::attr(href)').getall():
                yield scrapy.Request(url=response.urljoin(link), callback=self.parse_job, meta={"playwright": True})

    def parse_job(self, response):
        title = response.meta.get("title") or response.css("h1::text").get() or "Unknown"
        company = response.meta.get("company") or "Unknown"
        location = response.meta.get("location") or ""
        jd_html = response.css(".viewjob-description, .job-description, #content").get() or response.text
        yield JobItem(url=response.url, title=title.strip(), company=company.strip(), board="simplyhired", location=location, jd_html=jd_html, source=self.name, created_at=datetime.now(timezone.utc).isoformat())
