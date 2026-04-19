"""Pipeline: persist JobItems to SQLite."""

from __future__ import annotations

import logging

from job_scraper.db import JobDB
from job_scraper.pipelines.dedup import _get_shared_db, _get_shared_stats
from job_scraper.tiers import Tier, spider_tier

logger = logging.getLogger(__name__)


class SQLitePipeline:
    def __init__(self, db: JobDB | None = None, run_id: str = "", tier_stats=None):
        self._db = db
        self._run_id = run_id
        self._tier_stats = tier_stats

    @classmethod
    def from_crawler(cls, crawler):
        db = _get_shared_db(crawler)
        run_id = crawler.settings.get("SCRAPE_RUN_ID", "")
        return cls(db=db, run_id=run_id, tier_stats=_get_shared_stats(crawler))

    def open_spider(self, spider):
        if not self._run_id:
            import uuid
            self._run_id = str(uuid.uuid4())[:12]

    def process_item(self, item, spider):
        job = dict(item)
        job["run_id"] = self._run_id
        tier = spider_tier(spider.name)
        # Tier-aware status routing (generalizes old hn_hiring-specific rule).
        if tier is Tier.LEAD and job.get("status") != "rejected":
            job["status"] = "lead"
        try:
            self._db.insert_job(job)
            if self._tier_stats is not None:
                status = job.get("status", "pending")
                if status == "lead":
                    self._tier_stats.bump(spider.name, tier, "stored_lead")
                elif status != "rejected":
                    self._tier_stats.bump(spider.name, tier, "stored_pending")
        except Exception:
            logger.exception("Failed to store job: %s", job.get("url"))
        return item

    def close_spider(self, spider):
        if self._db:
            self._db.commit()
        if self._tier_stats is not None:
            self._tier_stats.flush()
