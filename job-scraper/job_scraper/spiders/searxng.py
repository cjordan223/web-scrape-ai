"""Spider for SearXNG (optional discovery)."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urlencode
import scrapy
from job_scraper.items import JobItem

logger = logging.getLogger(__name__)

class SearXNGSpider(scrapy.Spider):
    name = "searxng"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._searxng_url = "http://localhost:8888/search"
        self._queries = []
        self._domain_blocklist = set()

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider._searxng_url = cfg.searxng.url
        spider._queries = cfg.queries
        spider._domain_blocklist = set(cfg.hard_filters.domain_blocklist)
        return spider

    def start_requests(self):
        for query in self._queries:
            q_parts = []
            if query.board_site:
                q_parts.append(f"site:{query.board_site}")
            q_parts.append(f'"{query.title_phrase}"')
            if query.suffix:
                q_parts.append(query.suffix)
            params = urlencode({"q": " ".join(q_parts), "format": "json"})
            yield scrapy.Request(url=f"{self._searxng_url}?{params}", callback=self.parse_results, meta={"query_phrase": query.title_phrase}, dont_filter=True, errback=self.errback_searxng)

    def parse_results(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("SearXNG returned non-JSON: %s", response.url)
            return
        query_phrase = response.meta.get("query_phrase", "")
        for result in data.get("results", []):
            url = result.get("url", "")
            if not url:
                continue
            host = urlparse(url).netloc.lower()
            if any(bl in host for bl in self._domain_blocklist):
                continue
            # Follow URL to get full JD HTML — yield only from follow-up
            yield scrapy.Request(url=url, callback=self.parse_job_page, meta={"item_title": result.get("title", "Unknown"), "item_snippet": result.get("content", ""), "item_query": query_phrase}, priority=-1)

    def parse_job_page(self, response):
        parsed = urlparse(response.url)
        host = parsed.netloc.lower()
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        company = path_parts[0] if path_parts else host.split(".")[0]
        board = "unknown"
        if "ashbyhq.com" in host: board = "ashby"
        elif "greenhouse.io" in host: board = "greenhouse"
        elif "lever.co" in host: board = "lever"
        elif "usajobs.gov" in host: board = "usajobs"
        yield JobItem(url=response.url, title=response.meta["item_title"], company=company, board=board, snippet=response.meta["item_snippet"], query=response.meta["item_query"], jd_html=response.text, source=self.name, discovered_at=datetime.now(timezone.utc).isoformat())

    def errback_searxng(self, failure):
        logger.warning("SearXNG request failed: %s", failure.value)
