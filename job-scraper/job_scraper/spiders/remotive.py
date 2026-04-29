"""Spider for Remotive's public remote-jobs API."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import scrapy

from job_scraper.items import JobItem

logger = logging.getLogger(__name__)


class RemotiveSpider(scrapy.Spider):
    name = "remotive"
    _api_url = "https://remotive.com/api/remote-jobs"

    def start_requests(self):
        yield scrapy.Request(
            url=self._api_url,
            callback=self.parse_jobs,
            dont_filter=True,
            headers={"Accept": "application/json"},
        )

    def parse_jobs(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Remotive returned non-JSON: %s", response.url)
            return
        for job in data.get("jobs", []):
            tags = job.get("tags") or []
            yield JobItem(
                url=job.get("url", ""),
                title=job.get("title") or "Unknown",
                company=job.get("company_name") or "Unknown",
                board="remotive",
                location=job.get("candidate_required_location") or "Remote",
                salary_text=job.get("salary") or "",
                snippet=", ".join(str(tag) for tag in tags[:8]),
                query=job.get("category") or "",
                jd_html=job.get("description") or "",
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
