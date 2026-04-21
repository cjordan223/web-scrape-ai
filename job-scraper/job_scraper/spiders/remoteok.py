"""Spider for RemoteOK JSON API."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import scrapy
from job_scraper.items import JobItem

logger = logging.getLogger(__name__)

_API_URL = "https://remoteok.com/api"


class RemoteOKSpider(scrapy.Spider):
    name = "remoteok"

    def __init__(self, tag_filter=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tag_filter = set(tag_filter or [])

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        if not cfg.remoteok.enabled:
            kwargs["tag_filter"] = []
        else:
            kwargs["tag_filter"] = cfg.remoteok.tag_filter
        return super().from_crawler(crawler, *args, **kwargs)

    def start_requests(self):
        if not self._tag_filter:
            logger.info("RemoteOK spider disabled or no tag filters configured")
            return
        yield scrapy.Request(
            url=_API_URL,
            callback=self.parse_api,
            headers={"User-Agent": "TexTailor/2.0"},
            dont_filter=True,
        )

    def parse_api(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("RemoteOK returned non-JSON response")
            return

        for entry in data:
            if not isinstance(entry, dict) or "position" not in entry:
                continue

            tags = {t.lower() for t in entry.get("tags", [])}
            if not tags & self._tag_filter:
                continue

            title = entry.get("position", "Unknown")
            company = entry.get("company", "Unknown")
            description = entry.get("description", "")
            url = entry.get("url", f"https://remoteok.com/remote-jobs/{entry.get('id', '')}")
            location = entry.get("location", "Remote")

            salary_min = entry.get("salary_min")
            salary_max = entry.get("salary_max")
            salary_text = ""
            if salary_min and salary_max:
                salary_text = f"${salary_min} - ${salary_max}"
            elif salary_min:
                salary_text = f"${salary_min}+"

            yield JobItem(
                url=url,
                title=title.strip(),
                company=company.strip(),
                board="remoteok",
                location=location,
                salary_text=salary_text,
                jd_html=description,
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
