"""Pipeline: URL deduplication against seen_urls table."""

from __future__ import annotations

import logging

from scrapy.exceptions import DropItem

from job_scraper.db import JobDB

logger = logging.getLogger(__name__)


def _get_shared_db(crawler) -> JobDB:
    """Get or create a shared JobDB on the crawler instance."""
    if not hasattr(crawler, "_shared_db"):
        from job_scraper.config import DB_PATH
        crawler._shared_db = JobDB(DB_PATH)
    return crawler._shared_db


class DeduplicationPipeline:
    def __init__(self, db: JobDB | None = None, ttl_days: int = 14):
        self._db = db
        self._ttl_days = ttl_days

    @classmethod
    def from_crawler(cls, crawler):
        db = _get_shared_db(crawler)
        ttl = crawler.settings.getint("SEEN_TTL_DAYS", 14)
        return cls(db=db, ttl_days=ttl)

    def process_item(self, item, spider):
        url = item["url"]
        if self._db.is_seen(url, ttl_days=self._ttl_days):
            raise DropItem(f"Already seen: {url}")
        self._db.mark_seen(url)
        return item

    def close_spider(self, spider):
        if self._db:
            self._db.commit()
