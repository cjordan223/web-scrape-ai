import tempfile
from pathlib import Path
from job_scraper.db import JobDB
from job_scraper.pipelines.dedup import DeduplicationPipeline
from job_scraper.pipelines.storage import SQLitePipeline
from job_scraper.pipelines.tier_stats import TierStatsWriter


class _FakeSpider:
    def __init__(self, name="ashby"):
        self.name = name


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
