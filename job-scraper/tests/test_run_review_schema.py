"""Tests for rotation_members / llm_review columns and zero-seed helper."""
import json
import tempfile
from pathlib import Path

from job_scraper.db import JobDB


def _db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return JobDB(Path(tmp.name)), Path(tmp.name)


def test_runs_has_new_columns():
    db, _ = _db()
    cols = {r[1] for r in db._conn.execute("PRAGMA table_info(runs)")}
    assert {"rotation_members", "llm_review", "llm_review_at"} <= cols


def test_finish_run_persists_rotation_members():
    db, _ = _db()
    db.start_run("r-rm", trigger="scheduled")
    db.finish_run(
        "r-rm",
        raw_count=10, dedup_count=3, filtered_count=1,
        net_new=2, gate_mode="normal",
        rotation_group=0, rotation_members=["ashby", "remoteok"],
    )
    row = db._conn.execute(
        "SELECT rotation_members, gate_mode FROM runs WHERE run_id = ?", ("r-rm",),
    ).fetchone()
    assert row["gate_mode"] == "normal"
    assert json.loads(row["rotation_members"]) == ["ashby", "remoteok"]


def test_seed_tier_stats_creates_zero_rows():
    db, _ = _db()
    db.start_run("r-seed", trigger="scheduled")
    db.seed_tier_stats(
        "r-seed",
        [("ashby", "workhorse"), ("remoteok", "lead"), ("searxng", "discovery")],
    )
    rows = db._conn.execute(
        "SELECT source, tier, raw_hits FROM run_tier_stats WHERE run_id = ? ORDER BY source",
        ("r-seed",),
    ).fetchall()
    names = [r["source"] for r in rows]
    assert names == ["ashby", "remoteok", "searxng"]
    assert all(r["raw_hits"] == 0 for r in rows)


def test_seed_tier_stats_idempotent_with_pipeline_writes():
    """Pre-seed, then a TierStatsWriter flush for the same (run,tier,source) should
    overwrite raw_hits without duplicating rows."""
    from job_scraper.pipelines.tier_stats import TierStatsWriter
    from job_scraper.tiers import Tier

    db, _ = _db()
    db.start_run("r-upsert", trigger="scheduled")
    db.seed_tier_stats("r-upsert", [("ashby", "workhorse")])
    writer = TierStatsWriter(db, run_id="r-upsert")
    writer.bump("ashby", Tier.WORKHORSE, "raw_hits", 7)
    writer.flush()
    rows = db._conn.execute(
        "SELECT source, raw_hits FROM run_tier_stats WHERE run_id = ?", ("r-upsert",),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["raw_hits"] == 7


def test_save_run_review():
    db, _ = _db()
    db.start_run("r-rev", trigger="scheduled")
    db.save_run_review("r-rev", json.dumps({"health": "green", "summary": "ok"}))
    row = db._conn.execute(
        "SELECT llm_review, llm_review_at FROM runs WHERE run_id = ?", ("r-rev",),
    ).fetchone()
    assert json.loads(row["llm_review"]) == {"health": "green", "summary": "ok"}
    assert row["llm_review_at"] is not None
