"""Spider for Hacker News 'Who is Hiring?' monthly threads."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

import scrapy
from job_scraper.items import JobItem

logger = logging.getLogger(__name__)

_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
_FIREBASE_URL = "https://hacker-news.firebaseio.com/v0/item"
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")


def parse_hn_comment(text: str) -> dict:
    """Parse a Who's Hiring comment into structured fields.

    Convention: Company | Role | Location | Salary | URL
    But many comments don't follow this exactly.
    """
    result = {"company": "", "title": "", "location": "", "url": None}

    # Extract first URL from text
    url_match = _URL_PATTERN.search(text)
    if url_match:
        result["url"] = url_match.group(0).rstrip(".,;)")

    # Try pipe-delimited parsing (first line)
    first_line = text.split("\n")[0].strip()
    # Strip HTML tags
    first_line = re.sub(r"<[^>]+>", "", first_line)
    parts = [p.strip() for p in first_line.split("|")]

    if len(parts) >= 2:
        result["company"] = parts[0]
        result["title"] = parts[1]
    if len(parts) >= 3:
        result["location"] = parts[2]

    return result


class HNHiringSpider(scrapy.Spider):
    name = "hn_hiring"

    def __init__(self, max_comments=500, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._max_comments = max_comments

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        if not cfg.hn_hiring.enabled:
            kwargs["max_comments"] = 0
        else:
            kwargs["max_comments"] = cfg.hn_hiring.max_comments
        return super().from_crawler(crawler, *args, **kwargs)

    def start_requests(self):
        if self._max_comments <= 0:
            logger.info("HN Hiring spider disabled")
            return
        query = quote('"Who is hiring"')
        url = f"{_ALGOLIA_URL}?query={query}&tags=ask_hn&hitsPerPage=1"
        yield scrapy.Request(url=url, callback=self.parse_search, dont_filter=True)

    def parse_search(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Failed to parse Algolia response")
            return

        hits = data.get("hits", [])
        if not hits:
            logger.warning("No 'Who is hiring' thread found")
            return

        thread_id = hits[0].get("objectID")
        if not thread_id:
            return

        logger.info("Found HN hiring thread: %s (id=%s)", hits[0].get("title", "?"), thread_id)
        yield scrapy.Request(
            url=f"{_FIREBASE_URL}/{thread_id}.json",
            callback=self.parse_thread,
            dont_filter=True,
        )

    def parse_thread(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Failed to parse HN thread response")
            return

        kids = data.get("kids", [])
        logger.info("HN thread has %d top-level comments (limit %d)", len(kids), self._max_comments)

        for kid_id in kids[: self._max_comments]:
            yield scrapy.Request(
                url=f"{_FIREBASE_URL}/{kid_id}.json",
                callback=self.parse_comment,
                dont_filter=True,
                priority=-1,
            )

    def parse_comment(self, response):
        try:
            data = response.json()
        except Exception:
            return

        if not data or data.get("deleted") or data.get("dead"):
            return

        comment_id = data.get("id", "")
        text = data.get("text", "")
        if not text:
            return

        parsed = parse_hn_comment(text)
        hn_url = f"https://news.ycombinator.com/item?id={comment_id}"
        job_url = parsed.get("url")

        if job_url:
            yield scrapy.Request(
                url=job_url,
                callback=self.parse_job_page,
                meta={
                    "hn_url": hn_url,
                    "hn_company": parsed.get("company", ""),
                    "hn_title": parsed.get("title", ""),
                    "hn_location": parsed.get("location", ""),
                    "hn_text": text,
                },
                errback=self.errback_job_page,
                dont_filter=True,
                priority=-2,
            )
        else:
            if parsed.get("title"):
                yield JobItem(
                    url=hn_url,
                    title=parsed["title"],
                    company=parsed.get("company", "Unknown"),
                    board="hn_hiring",
                    location=parsed.get("location", ""),
                    jd_text=re.sub(r"<[^>]+>", " ", text),
                    source=self.name,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )

    def parse_job_page(self, response):
        meta = response.meta
        title = meta.get("hn_title") or "Unknown"
        company = meta.get("hn_company") or "Unknown"
        location = meta.get("hn_location") or ""

        yield JobItem(
            url=response.url,
            title=title.strip(),
            company=company.strip(),
            board="hn_hiring",
            location=location,
            jd_html=response.text,
            source=self.name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def errback_job_page(self, failure):
        request = failure.request
        meta = request.meta
        hn_url = meta.get("hn_url", "")
        title = meta.get("hn_title", "Unknown")
        company = meta.get("hn_company", "Unknown")
        text = meta.get("hn_text", "")

        if title and title != "Unknown":
            yield JobItem(
                url=hn_url,
                title=title,
                company=company,
                board="hn_hiring",
                location=meta.get("hn_location", ""),
                jd_text=re.sub(r"<[^>]+>", " ", text),
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
