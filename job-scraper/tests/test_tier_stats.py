import tempfile
from pathlib import Path
from job_scraper.db import JobDB
from job_scraper.pipelines.tier_stats import TierStatsWriter
from job_scraper.tiers import Tier


def _db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return JobDB(Path(tmp.name)), Path(tmp.name)


def test_tier_stats_table_created():
    db, _ = _db()
    assert "run_tier_stats" in db.tables()


def test_runs_has_new_columns():
    db, _ = _db()
    cols = {r[1] for r in db._conn.execute("PRAGMA table_info(runs)")}
    assert "net_new" in cols
    assert "gate_mode" in cols
    assert "rotation_group" in cols


def test_writer_increments_and_persists():
    db, path = _db()
    w = TierStatsWriter(db, run_id="r1")
    w.bump("searxng", Tier.DISCOVERY, "raw_hits", 5)
    w.bump("searxng", Tier.DISCOVERY, "raw_hits", 3)
    w.bump("searxng", Tier.DISCOVERY, "stored_pending", 2)
    w.bump("ashby", Tier.WORKHORSE, "raw_hits", 10)
    w.flush()

    rows = list(db._conn.execute(
        "SELECT source, tier, raw_hits, stored_pending FROM run_tier_stats WHERE run_id = ?",
        ("r1",),
    ))
    by_source = {r["source"]: r for r in rows}
    assert by_source["searxng"]["raw_hits"] == 8
    assert by_source["searxng"]["stored_pending"] == 2
    assert by_source["ashby"]["raw_hits"] == 10


def test_writer_flush_is_idempotent():
    db, _ = _db()
    w = TierStatsWriter(db, run_id="r2")
    w.bump("ashby", Tier.WORKHORSE, "raw_hits", 5)
    w.flush()
    w.flush()  # Second flush must not double-count
    row = db._conn.execute(
        "SELECT raw_hits FROM run_tier_stats WHERE run_id = ? AND source = 'ashby'",
        ("r2",),
    ).fetchone()
    assert row["raw_hits"] == 5
