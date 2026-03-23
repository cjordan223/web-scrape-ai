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
            yield scrapy.Request(
                url=board["url"],
                callback=self.parse_board,
                meta={
                    "playwright": True,
                    "playwright_include_page": False,
                    "playwright_page_methods": [
                        {"method": "wait_for_timeout", "args": [3000]},
                    ],
                },
                dont_filter=True,
            )

    def parse_board(self, response):
        # SimplyHired uses data-jobkey divs with Chakra UI classes
        cards = response.css('[data-jobkey]')
        if not cards:
            # Fallback: try old selectors
            cards = response.css("article.SerpJob, li.SerpJob")

        for card in cards:
            # Primary: data-testid selectors (current SimplyHired)
            link = card.css('[data-testid="searchSerpJobTitle"] a::attr(href)').get()
            title = card.css('[data-testid="searchSerpJobTitle"] a::text').get()
            company = card.css('a[href*="/browse-jobs/companies/"]::text').get()
            location = card.css('[data-testid="searchSerpJobLocation"]::text').get()
            salary = card.css('[data-testid="searchSerpJobSalary"]::text').get()

            # Fallback selectors
            if not link:
                link = card.css('a.SerpJob-link::attr(href), a.card-link::attr(href)').get()
            if not title:
                title = card.css('h2.jobposting-title::text, h2::text').get()
            if not company:
                company = card.css('.jobposting-company::text, .company::text').get()
            if not location:
                location = card.css('.jobposting-location::text, .location::text').get()

            # Clean company name (remove trailing " —")
            if company:
                company = company.replace('\u2014', '').replace('—', '').strip()

            if link:
                yield scrapy.Request(
                    url=response.urljoin(link),
                    callback=self.parse_job,
                    meta={
                        "title": (title or "Unknown").strip(),
                        "company": (company or "Unknown").strip(),
                        "location": (location or "").strip(),
                        "salary_text": (salary or "").strip(),
                        "playwright": True,
                        "playwright_include_page": False,
                    },
                )

        # If no cards found at all, try generic link extraction
        if not cards:
            for link in response.css('a[href*="/job/"]::attr(href)').getall():
                yield scrapy.Request(
                    url=response.urljoin(link),
                    callback=self.parse_job,
                    meta={"playwright": True},
                )

    def parse_job(self, response):
        title = response.meta.get("title") or response.css("h1::text, h2::text").get() or "Unknown"
        company = response.meta.get("company") or response.css('a[href*="/browse-jobs/companies/"]::text').get() or "Unknown"
        if company:
            company = company.replace('\u2014', '').replace('—', '').strip()
        location = response.meta.get("location") or ""
        salary_text = response.meta.get("salary_text") or ""
        jd_html = response.css('[data-testid="viewJobBodyJobFullDescriptionContent"], .viewjob-description, .job-description, #content').get() or response.text
        yield JobItem(
            url=response.url,
            title=title.strip(),
            company=company.strip(),
            board="simplyhired",
            location=location,
            salary_text=salary_text,
            jd_html=jd_html,
            source=self.name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
