"""Pipeline: persist JobItems to SQLite."""

from __future__ import annotations

import logging

from job_scraper.db import JobDB

logger = logging.getLogger(__name__)


class SQLitePipeline:
    def __init__(self, db: JobDB | None = None, run_id: str = ""):
        self._db = db
        self._run_id = run_id
        self._stats = {"new": 0, "filtered": 0}

    @classmethod
    def from_crawler(cls, crawler):
        from job_scraper.config import DB_PATH
        db = JobDB(DB_PATH)
        run_id = crawler.settings.get("SCRAPE_RUN_ID", "")
        return cls(db=db, run_id=run_id)

    def open_spider(self, spider):
        if not self._run_id:
            import uuid
            self._run_id = str(uuid.uuid4())[:12]
        if self._db:
            self._db.start_run(self._run_id)

    def process_item(self, item, spider):
        job = dict(item)
        job["run_id"] = self._run_id
        try:
            self._db.insert_job(job)
            if job.get("status") == "rejected":
                self._stats["filtered"] += 1
            else:
                self._stats["new"] += 1
        except Exception:
            logger.exception("Failed to store job: %s", job.get("url"))
        return item

    def close_spider(self, spider):
        if self._db:
            stats = spider.crawler.stats.get_stats() if hasattr(spider, "crawler") else {}
            self._db.finish_run(
                self._run_id,
                raw_count=stats.get("item_scraped_count", self._stats["new"] + self._stats["filtered"]),
                dedup_count=self._stats["new"],
                filtered_count=self._stats["filtered"],
                error_count=stats.get("log_count/ERROR", 0),
            )
