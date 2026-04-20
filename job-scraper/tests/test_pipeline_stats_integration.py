import tempfile
from pathlib import Path

import pytest
from scrapy.exceptions import DropItem

from job_scraper.db import JobDB
from job_scraper.pipelines.dedup import DeduplicationPipeline
from job_scraper.pipelines.storage import SQLitePipeline
from job_scraper.pipelines.tier_stats import TierStatsWriter


class _FakeSpider:
    def __init__(self, name="ashby"):
        self.name = name


def test_dedup_raw_hits_count_all_items_not_just_fresh():
    """raw_hits must reflect items the spider yielded, not only fresh ones.

    Before the fix, raw_hits was only bumped when an item survived dedup, which
    made the counter indistinguishable from 'stored' and hid silent spiders.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = JobDB(Path(tmp.name))
    writer = TierStatsWriter(db, run_id="r-dedup")
    pipe = DeduplicationPipeline(db=db, ttl_days=14, tier_stats=writer)

    spider = _FakeSpider("ashby")
    db.mark_seen("https://jobs.ashbyhq.com/acme/seen-1")
    db.mark_seen("https://jobs.ashbyhq.com/acme/seen-2")

    pipe.process_item({"url": "https://jobs.ashbyhq.com/acme/fresh-1"}, spider)
    with pytest.raises(DropItem):
        pipe.process_item({"url": "https://jobs.ashbyhq.com/acme/seen-1"}, spider)
    with pytest.raises(DropItem):
        pipe.process_item({"url": "https://jobs.ashbyhq.com/acme/seen-2"}, spider)

    writer.flush()
    row = db._conn.execute(
        "SELECT raw_hits, dedup_drops FROM run_tier_stats "
        "WHERE run_id = 'r-dedup' AND source = 'ashby'"
    ).fetchone()
    assert row["raw_hits"] == 3, "raw_hits should count all items the spider yielded"
    assert row["dedup_drops"] == 2


def test_storage_writes_tier_stat_stored_pending():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = JobDB(Path(tmp.name))
    writer = TierStatsWriter(db, run_id="r-stats")
    pipe = SQLitePipeline(db=db, run_id="r-stats", tier_stats=writer)
    pipe.open_spider(_FakeSpider("ashby"))

    pipe.process_item({
        "url": "https://jobs.ashbyhq.com/acme/1",
        "title": "Platform Engineer",
        "company": "acme",
        "board": "ashby",
        "source": "ashby",
        "created_at": "2026-04-18T00:00:00+00:00",
    }, _FakeSpider("ashby"))
    pipe.close_spider(_FakeSpider("ashby"))

    row = db._conn.execute(
        "SELECT stored_pending FROM run_tier_stats WHERE run_id = 'r-stats' AND source = 'ashby'"
    ).fetchone()
    assert row["stored_pending"] == 1
