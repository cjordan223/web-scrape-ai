"""Spider for Ashby job boards via GraphQL API (jobs.ashbyhq.com)."""
from __future__ import annotations
import json, logging
from datetime import datetime, timezone
import scrapy
from job_scraper.items import JobItem
from job_scraper.spiders import diversified_subset, title_matches
from job_scraper.tiers import rotation_filter

logger = logging.getLogger(__name__)

_MAX_BOARDS_PER_RUN = 12

ASHBY_GQL_URL = "https://jobs.ashbyhq.com/api/non-user-graphql"

LIST_QUERY = """
query ApiJobBoardWithTeams($org: String!) {
  jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $org) {
    jobPostings { id title locationName }
  }
}
"""

DETAIL_QUERY = """
query ApiJobPosting($org: String!, $id: String!) {
  jobPosting(organizationHostedJobsPageName: $org, jobPostingId: $id) {
    id title descriptionHtml locationName employmentType compensationTierSummary
  }
}
"""


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
            # Extract org slug from URL: https://jobs.ashbyhq.com/ramp -> ramp
            org = board["url"].rstrip("/").split("/")[-1]
            yield scrapy.Request(
                url=ASHBY_GQL_URL,
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({
                    "operationName": "ApiJobBoardWithTeams",
                    "variables": {"org": org},
                    "query": LIST_QUERY,
                }),
                callback=self.parse_board,
                meta={"company": board["company"], "org": org},
                dont_filter=True,
            )

    def parse_board(self, response):
        company = response.meta["company"]
        org = response.meta["org"]
        try:
            data = json.loads(response.text)
            board_data = (data.get("data") or {}).get("jobBoard") or {}
            postings = board_data.get("jobPostings") or []
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Failed to parse Ashby API response for %s", org)
            return

        logger.info("Ashby %s: %d job postings (limit %d)", org, len(postings), self._max_per_board)
        for posting in postings[:self._max_per_board]:
            job_id = posting["id"]
            yield scrapy.Request(
                url=ASHBY_GQL_URL,
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({
                    "operationName": "ApiJobPosting",
                    "variables": {"org": org, "id": job_id},
                    "query": DETAIL_QUERY,
                }),
                callback=self.parse_job,
                meta={
                    "company": company,
                    "org": org,
                    "brief_title": posting.get("title", ""),
                    "brief_location": posting.get("locationName", ""),
                },
                dont_filter=True,
            )

    def parse_job(self, response):
        company = response.meta["company"]
        org = response.meta["org"]
        try:
            data = json.loads(response.text)
            job = data.get("data", {}).get("jobPosting")
        except (json.JSONDecodeError, KeyError):
            logger.warning("Failed to parse Ashby job detail for %s", org)
            return

        if not job:
            logger.warning("Empty job posting response for %s", org)
            return

        job_id = job["id"]
        title = job.get("title") or response.meta.get("brief_title") or "Unknown"
        if not title_matches(title):
            logger.debug("Ashby %s: skipping non-matching title: %s", org, title)
            return
        location = job.get("locationName") or response.meta.get("brief_location") or ""
        salary_text = job.get("compensationTierSummary") or ""
        jd_html = job.get("descriptionHtml") or ""
        url = f"https://jobs.ashbyhq.com/{org}/{job_id}"

        yield JobItem(
            url=url,
            title=title.strip(),
            company=company,
            board="ashby",
            location=location,
            salary_text=salary_text,
            jd_html=jd_html,
            source=self.name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
