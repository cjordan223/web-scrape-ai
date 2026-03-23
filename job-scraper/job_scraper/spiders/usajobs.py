"""Spider for USAJobs API."""
from __future__ import annotations
import logging, os
from datetime import datetime, timezone
import scrapy
from job_scraper.items import JobItem

logger = logging.getLogger(__name__)
_BASE_URL = "https://data.usajobs.gov/api/search"

class USAJobsSpider(scrapy.Spider):
    name = "usajobs"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._api_key = os.environ.get("USAJOBS_API_KEY", "")
        self._email = os.environ.get("USAJOBS_EMAIL", "")

    def start_requests(self):
        from job_scraper.config import load_config
        cfg = load_config()
        if not self._api_key:
            logger.warning("USAJOBS_API_KEY not set, skipping")
            return
        for keyword in cfg.usajobs.keywords:
            url = f"{_BASE_URL}?Keyword={keyword}&ResultsPerPage=100"
            if cfg.usajobs.remote:
                url += "&RemoteIndicator=true"
            yield scrapy.Request(url=url, callback=self.parse_api, meta={"keyword": keyword}, headers={"Authorization-Key": self._api_key, "User-Agent": self._email, "Host": "data.usajobs.gov"}, dont_filter=True)

    def parse_api(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Failed to parse USAJobs response")
            return
        yield from self._parse_results(data)

    def _parse_results(self, data):
        for item in data.get("SearchResult", {}).get("SearchResultItems", []):
            desc = item.get("MatchedObjectDescriptor", {})
            title = desc.get("PositionTitle", "Unknown")
            url = desc.get("PositionURI", "")
            org = desc.get("OrganizationName", "USGov")
            location = desc.get("PositionLocationDisplay", "")
            remuneration = desc.get("PositionRemuneration", [])
            salary_text = ""
            if remuneration:
                r = remuneration[0]
                salary_text = f"${r.get('MinimumRange', '')} - ${r.get('MaximumRange', '')}"
            qual = desc.get("QualificationSummary", "")
            duties = desc.get("UserArea", {}).get("Details", {}).get("MajorDuties", [])
            jd_text = qual + "\n\n" + "\n".join(duties) if duties else qual
            yield JobItem(url=url, title=title, company=org, board="usajobs", location=location, salary_text=salary_text, jd_text=jd_text, source=self.name, created_at=datetime.now(timezone.utc).isoformat())
