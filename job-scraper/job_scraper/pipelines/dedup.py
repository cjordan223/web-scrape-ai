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


def _get_shared_stats(crawler):
    """Single TierStatsWriter per crawler — all pipelines write to it."""
    if not hasattr(crawler, "_shared_stats"):
        from job_scraper.pipelines.tier_stats import TierStatsWriter
        run_id = crawler.settings.get("SCRAPE_RUN_ID", "")
        db = _get_shared_db(crawler)
        crawler._shared_stats = TierStatsWriter(db, run_id=run_id)
    return crawler._shared_stats


class DeduplicationPipeline:
    def __init__(self, db: JobDB | None = None, ttl_days: int = 14, tier_stats=None):
        self._db = db
        self._ttl_days = ttl_days
        self._tier_stats = tier_stats

    @classmethod
    def from_crawler(cls, crawler):
        db = _get_shared_db(crawler)
        # Prefer profile TTL; fall back to legacy setting for safety.
        from job_scraper.config import load_config
        cfg = load_config()
        ttl = cfg.scrape_profile.seen_ttl_days
        return cls(db=db, ttl_days=ttl, tier_stats=_get_shared_stats(crawler))

    def process_item(self, item, spider):
        url = item["url"]
        if self._tier_stats is not None:
            from job_scraper.tiers import spider_tier
            self._tier_stats.bump(spider.name, spider_tier(spider.name), "raw_hits")
        if self._db.is_seen(url, ttl_days=self._ttl_days):
            if self._tier_stats is not None:
                from job_scraper.tiers import spider_tier
                self._tier_stats.bump(spider.name, spider_tier(spider.name), "dedup_drops")
            raise DropItem(f"Already seen: {url}")
        self._db.mark_seen(url)
        return item

    def close_spider(self, spider):
        if self._db:
            self._db.commit()
