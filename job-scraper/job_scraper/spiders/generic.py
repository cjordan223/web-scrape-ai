"""Spider for RSS feeds and static HTML boards."""
from __future__ import annotations
import logging, xml.etree.ElementTree as ET
from datetime import datetime, timezone
import scrapy
from job_scraper.items import JobItem

logger = logging.getLogger(__name__)

class GenericSpider(scrapy.Spider):
    name = "generic"
    def __init__(self, boards=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boards = boards or []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        boards = [{"url": b.url, "company": b.company} for b in cfg.boards if b.board_type == "generic" and b.enabled]
        return cls(boards=boards, *args, **kwargs)

    def start_requests(self):
        for board in self._boards:
            url = board["url"]
            callback = self.parse_rss if url.endswith((".rss", ".xml", "/feed")) else self.parse_board
            yield scrapy.Request(url=url, callback=callback, meta={"company": board["company"], "board": "generic"}, dont_filter=True)

    def parse_board(self, response):
        company = response.meta.get("company", "unknown")
        for link in response.css('a[href*="job"], a[href*="career"], a[href*="position"]::attr(href)').getall():
            yield scrapy.Request(url=response.urljoin(link), callback=self.parse_job, meta={"company": company, "board": "generic"})

    def parse_rss(self, response):
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            logger.warning("Failed to parse RSS: %s", response.url)
            return
        for item in root.iter("item"):
            title = item.findtext("title", "Unknown")
            url = item.findtext("link", "")
            description = item.findtext("description", "")
            if url:
                yield JobItem(url=url, title=title, company=response.meta.get("company", "unknown"), board="generic", snippet=description, jd_html=description, source=self.name, discovered_at=datetime.now(timezone.utc).isoformat())

    def parse_job(self, response):
        company = response.meta.get("company", "unknown")
        title = response.css("h1::text").get() or "Unknown"
        jd_html = response.css(".job-description, .content, main").get() or response.text
        yield JobItem(url=response.url, title=title.strip(), company=company, board="generic", jd_html=jd_html, source=self.name, discovered_at=datetime.now(timezone.utc).isoformat())
