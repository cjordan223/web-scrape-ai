"""Spider for Ashby job boards (jobs.ashbyhq.com)."""
from __future__ import annotations
import json, logging
from datetime import datetime, timezone
import scrapy
from job_scraper.items import JobItem

logger = logging.getLogger(__name__)

class AshbySpider(scrapy.Spider):
    name = "ashby"
    def __init__(self, boards=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boards = boards or []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        boards = [{"url": b.url, "company": b.company} for b in cfg.boards if b.board_type == "ashby" and b.enabled]
        return cls(boards=boards, *args, **kwargs)

    def start_requests(self):
        for board in self._boards:
            yield scrapy.Request(url=board["url"], callback=self.parse_board, meta={"company": board["company"]}, dont_filter=True)

    def parse_board(self, response):
        company = response.meta["company"]
        script = response.css('script#__NEXT_DATA__::text').get()
        if script:
            try:
                data = json.loads(script)
                jobs = data.get("props", {}).get("pageProps", {}).get("jobBoard", {}).get("jobs", [])
                for job in jobs:
                    job_url = f"{response.url}/{job.get('id', '')}"
                    yield scrapy.Request(url=job_url, callback=self.parse_job, meta={"company": company, "board": "ashby", "title": job.get("title", ""), "location": job.get("location", "")})
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to parse Ashby JSON for %s: %s", response.url, e)
        # Fallback: extract links
        for link in response.css('a[href*="/"]::attr(href)').getall():
            if company in link and link.count("/") >= 3:
                yield scrapy.Request(url=response.urljoin(link), callback=self.parse_job, meta={"company": company, "board": "ashby"})

    def parse_job(self, response):
        company = response.meta.get("company", "unknown")
        title = response.meta.get("title") or response.css("h1::text").get() or "Unknown"
        location = response.meta.get("location") or ""
        jd_html = response.css(".ashby-job-posting-description").get() or response.text
        yield JobItem(url=response.url, title=title.strip(), company=company, board="ashby", location=location, jd_html=jd_html, source=self.name, discovered_at=datetime.now(timezone.utc).isoformat())
