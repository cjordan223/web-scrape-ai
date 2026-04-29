"""Spider for SmartRecruiters public Posting API."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import scrapy

from job_scraper.items import JobItem
from job_scraper.spiders import diversified_subset
from job_scraper.tiers import rotation_filter

logger = logging.getLogger(__name__)

_MAX_BOARDS_PER_RUN = 6
_MAX_JOBS_PER_BOARD = 20


class SmartRecruitersSpider(scrapy.Spider):
    name = "smartrecruiters"

    def __init__(self, boards=None, max_per_board=50, run_id="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boards = boards or []
        self._max_per_board = max_per_board
        self._run_id = run_id

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        boards = [
            {"url": b.url, "company": b.company}
            for b in cfg.boards
            if b.board_type == "smartrecruiters" and b.enabled
        ]
        kwargs["boards"] = boards
        kwargs["max_per_board"] = cfg.target_max_results
        kwargs["run_id"] = crawler.settings.get("SCRAPE_RUN_ID", "")
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider._rotation_group = crawler.settings.get("SCRAPE_ROTATION_GROUP")
        spider._rotation_total = crawler.settings.getint("SCRAPE_ROTATION_TOTAL", 4)
        return spider

    @staticmethod
    def _company_from_url(url: str) -> str:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if "api.smartrecruiters.com" in parsed.netloc and "companies" in parts:
            idx = parts.index("companies")
            if len(parts) > idx + 1:
                return parts[idx + 1]
        return parts[0] if parts else ""

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
            "SmartRecruiters: scraping %d/%d boards this run (group=%s, rotated=%d)",
            len(boards), len(self._boards), self._rotation_group, len(rotated),
        )
        for board in boards:
            company = self._company_from_url(board["url"]) or board["company"]
            limit = min(self._max_per_board, _MAX_JOBS_PER_BOARD)
            yield scrapy.Request(
                url=(
                    "https://api.smartrecruiters.com/v1/companies/"
                    f"{company}/postings?limit={limit}"
                ),
                callback=self.parse_board_json,
                meta={"company": board["company"], "company_identifier": company},
                dont_filter=True,
                headers={"Accept": "application/json"},
            )

    def parse_board_json(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("SmartRecruiters JSON endpoint returned non-JSON: %s", response.url)
            return
        company = response.meta.get("company", "unknown")
        company_identifier = response.meta.get("company_identifier") or company
        for job in data.get("content", []):
            job_id = str(job.get("id") or job.get("uuid") or "")
            detail_url = job.get("ref") or (
                "https://api.smartrecruiters.com/v1/companies/"
                f"{company_identifier}/postings/{job_id}"
            )
            yield scrapy.Request(
                url=detail_url,
                callback=self.parse_job_detail,
                meta={"company": company, "summary": job, "company_identifier": company_identifier},
                dont_filter=True,
                headers={"Accept": "application/json"},
            )

    def parse_job_detail(self, response):
        try:
            detail = response.json()
        except Exception:
            logger.warning("SmartRecruiters detail endpoint returned non-JSON: %s", response.url)
            return
        summary = response.meta.get("summary") or {}
        company = response.meta.get("company", "unknown")
        company_identifier = response.meta.get("company_identifier") or company
        job = {**summary, **detail}
        job_id = str(job.get("id") or job.get("uuid") or "")
        location = self._location_text(job.get("location") or {})
        salary_text = self._salary_text(job.get("customField") or [])
        jd_html = self._description_html(job.get("jobAd") or {})
        yield JobItem(
            url=job.get("postingUrl") or f"https://jobs.smartrecruiters.com/{company_identifier}/{job_id}",
            ats_provider="smartrecruiters",
            ats_job_id=job_id,
            title=job.get("name", "Unknown"),
            company=(job.get("company") or {}).get("name") or company,
            board="smartrecruiters",
            location=location,
            salary_text=salary_text,
            salary_k=self._salary_k(salary_text),
            jd_html=jd_html,
            jd_text="",
            source=self.name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _description_html(job_ad: dict) -> str:
        sections = (job_ad.get("sections") or {}).values()
        parts = [section.get("text", "") for section in sections if section.get("text")]
        return "\n".join(parts)

    @staticmethod
    def _location_text(location: dict) -> str:
        full = location.get("fullLocation") or ", ".join(
            value for value in (
                location.get("city"),
                location.get("region"),
                location.get("country"),
            ) if value
        )
        labels = [full]
        if location.get("remote") is True and "remote" not in full.lower():
            labels.append("Remote")
        if location.get("hybrid") is True and "hybrid" not in full.lower():
            labels.append("Hybrid")
        return ", ".join(label for label in labels if label)

    @staticmethod
    def _salary_text(custom_fields: list[dict]) -> str:
        for field in custom_fields:
            label = str(field.get("fieldLabel") or "").lower()
            if any(term in label for term in ("salary", "compensation", "pay")):
                return str(field.get("valueLabel") or "")
        return ""

    @staticmethod
    def _salary_k(text: str) -> float | None:
        numbers = [float(value.replace(",", "")) for value in re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")]
        if not numbers:
            return None
        value = max(numbers)
        return value / 1000.0 if value > 1000 else value
