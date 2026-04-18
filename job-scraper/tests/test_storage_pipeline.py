"""Tests for the storage pipeline lead-status routing."""
from unittest.mock import MagicMock

from job_scraper.pipelines.storage import SQLitePipeline


def _make_pipeline() -> tuple[SQLitePipeline, MagicMock]:
    db = MagicMock()
    p = SQLitePipeline(db=db, run_id="test-run")
    return p, db


def _item(source: str = "searxng", status: str | None = None) -> dict:
    base = {
        "url": "https://example.com/job",
        "title": "Engineer",
        "company": "Acme",
        "source": source,
    }
    if status:
        base["status"] = status
    return base


def _spider(name: str) -> MagicMock:
    s = MagicMock()
    s.name = name
    return s


def test_hn_hiring_gets_lead_status():
    p, db = _make_pipeline()
    item = _item(source="hn_hiring")
    p.process_item(item, spider=_spider("hn_hiring"))
    job = db.insert_job.call_args[0][0]
    assert job["status"] == "lead"


def test_hn_hiring_rejected_stays_rejected():
    p, db = _make_pipeline()
    item = _item(source="hn_hiring", status="rejected")
    p.process_item(item, spider=_spider("hn_hiring"))
    job = db.insert_job.call_args[0][0]
    assert job["status"] == "rejected"


def test_non_hn_source_unchanged():
    p, db = _make_pipeline()
    item = _item(source="searxng")
    p.process_item(item, spider=_spider("searxng"))
    job = db.insert_job.call_args[0][0]
    assert "status" not in job or job.get("status") != "lead"


def test_non_hn_source_preserves_existing_status():
    p, db = _make_pipeline()
    item = _item(source="ashby", status="rejected")
    p.process_item(item, spider=_spider("ashby"))
    job = db.insert_job.call_args[0][0]
    assert job["status"] == "rejected"
