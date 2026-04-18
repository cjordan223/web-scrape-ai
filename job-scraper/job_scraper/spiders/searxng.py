"""Spider for SearXNG (optional discovery)."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urlencode
import scrapy
from job_scraper.items import JobItem
from job_scraper.spiders import diversified_subset, run_seed

logger = logging.getLogger(__name__)

_QUERY_BATCH_SIZE = 20
_PAGES_PER_QUERY = 2
_LOW_SIGNAL_HOST_FRAGMENTS = {
    "indeed.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "tealhq.com",
    "himalayas.app",
    "jobera.com",
    "hireza.",
    "monster.com",
    "simplyhired.com",
    "careerjet.com",
    "jooble.org",
    "learn4good.com",
    "talent.com",
    "lensa.com",
    "beBee.com".lower(),
    "builtin.com",
}
_TRUSTED_BOARD_PATTERNS: tuple[tuple[str, str], ...] = (
    ("ashbyhq.com", "ashby"),
    ("greenhouse.io", "greenhouse"),
    ("lever.co", "lever"),
    ("linkedin.com", "linkedin"),
    ("myworkdayjobs.com", "workday"),
    ("wd1.myworkdaysite.com", "workday"),
    ("wd5.myworkdaysite.com", "workday"),
    ("bamboohr.com", "bamboohr"),
    ("icims.com", "icims"),
    ("jobvite.com", "jobvite"),
    ("jobs.jobvite.com", "jobvite"),
    ("smartrecruiters.com", "smartrecruiters"),
    ("jobs.smartrecruiters.com", "smartrecruiters"),
    ("workable.com", "workable"),
    ("applytojob.com", "applytojob"),
)

class SearXNGSpider(scrapy.Spider):
    name = "searxng"
    def __init__(self, run_id="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._searxng_url = "http://localhost:8888/search"
        self._queries = []
        self._domain_blocklist = set()
        self._run_id = run_id
        self._emitted_urls = set()
        self._discovery_fire = True

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider._searxng_url = cfg.searxng.url
        spider._queries = cfg.queries
        spider._domain_blocklist = set(cfg.hard_filters.domain_blocklist)
        spider._run_id = crawler.settings.get("SCRAPE_RUN_ID", "")
        spider._discovery_fire = crawler.settings.getbool("SCRAPE_DISCOVERY_FIRE", True)
        return spider

    def start_requests(self):
        if not self._discovery_fire:
            logger.info("SearXNG: discovery alternation says skip this run")
            return
        time_ranges = ["day", "week", "month"]
        seed = run_seed(self._run_id or datetime.now(timezone.utc).isoformat(), self.name)
        primary_time_range = time_ranges[seed % len(time_ranges)]
        secondary_time_range = time_ranges[(seed + 1) % len(time_ranges)]
        selected_queries = diversified_subset(
            self._queries,
            run_id=self._run_id or primary_time_range,
            scope=self.name,
            limit=_QUERY_BATCH_SIZE,
            key=lambda query: f"{query.board_site}|{query.title_phrase}|{query.suffix}",
        )
        logger.info(
            "SearXNG: querying %d/%d phrases this run across %d pages",
            len(selected_queries),
            len(self._queries),
            _PAGES_PER_QUERY,
        )
        for index, query in enumerate(selected_queries):
            q_parts = []
            if query.board_site:
                q_parts.append(f"site:{query.board_site}")
            q_parts.append(f'"{query.title_phrase}"')
            if query.suffix:
                q_parts.append(query.suffix)
            q = " ".join(q_parts)
            for page in range(1, _PAGES_PER_QUERY + 1):
                time_range = primary_time_range if (index + page) % 2 == 0 else secondary_time_range
                params = urlencode({
                    "q": q,
                    "format": "json",
                    "time_range": time_range,
                    "pageno": page,
                })
                yield scrapy.Request(
                    url=f"{self._searxng_url}?{params}",
                    callback=self.parse_results,
                    meta={
                        "query_phrase": query.title_phrase,
                        "query_board_site": query.board_site,
                        "query_page": page,
                        "query_time_range": time_range,
                    },
                    dont_filter=True,
                    errback=self.errback_searxng,
                )

    def parse_results(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("SearXNG returned non-JSON: %s", response.url)
            return
        query_phrase = response.meta.get("query_phrase", "")
        query_board_site = (response.meta.get("query_board_site", "") or "").lower()
        for result in data.get("results", []):
            url = result.get("url", "")
            if not url:
                continue
            parsed = urlparse(url)
            host = parsed.netloc.lower()
            if "usajobs.gov" in host:
                continue
            if any(bl in host for bl in self._domain_blocklist):
                continue
            if any(fragment in host for fragment in _LOW_SIGNAL_HOST_FRAGMENTS):
                continue
            if query_board_site and not self._matches_board_site(parsed, query_board_site):
                continue
            title = result.get("title", "Unknown")
            snippet = result.get("content", "") or ""
            company, board = self._company_and_board(parsed)
            if board == "unknown":
                continue
            normalized_url = parsed._replace(fragment="", query="").geturl().rstrip("/")
            if normalized_url in self._emitted_urls:
                continue
            self._emitted_urls.add(normalized_url)
            yield JobItem(
                url=normalized_url,
                title=title,
                company=company,
                board=board,
                snippet=snippet,
                query=query_phrase,
                jd_text=snippet,
                jd_html=snippet,
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )

    def _company_and_board(self, parsed) -> tuple[str, str]:
        host = parsed.netloc.lower()
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        board = "unknown"
        for pattern, detected_board in _TRUSTED_BOARD_PATTERNS:
            if pattern in host:
                board = detected_board
                break
        company = self._extract_company(board, host, path_parts)
        return company, board

    def _extract_company(self, board: str, host: str, path_parts: list[str]) -> str:
        if board in {"ashby", "greenhouse", "lever"} and path_parts:
            return path_parts[0]
        if board == "workday":
            if path_parts:
                return path_parts[0]
            host_parts = [part for part in host.split(".") if part not in {"www", "wd1", "wd5"}]
            return host_parts[0] if host_parts else "unknown"
        if board in {"jobvite", "smartrecruiters"} and path_parts:
            return path_parts[0]
        if board == "applytojob" and path_parts:
            return path_parts[0]
        host_parts = [part for part in host.split(".") if part != "www"]
        return host_parts[0] if host_parts else "unknown"

    def _matches_board_site(self, parsed, board_site: str) -> bool:
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        if "/" in board_site:
            host_part, path_part = board_site.split("/", 1)
            return host_part in host and f"/{path_part}".rstrip("/") in path
        return board_site in host

    def errback_searxng(self, failure):
        logger.warning("SearXNG request failed: %s", failure.value)
