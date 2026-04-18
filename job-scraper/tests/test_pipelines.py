"""Tests for pipeline stages."""

import sqlite3
import pytest
from scrapy import Spider
from scrapy.exceptions import DropItem
from job_scraper.items import JobItem
from job_scraper.pipelines.text_extraction import TextExtractionPipeline
from job_scraper.pipelines.dedup import DeduplicationPipeline
from job_scraper.pipelines.hard_filter import HardFilterPipeline
from job_scraper.pipelines.storage import SQLitePipeline
from job_scraper.db import JobDB
from job_scraper.config import HardFilterConfig


@pytest.fixture
def spider():
    class FakeSpider(Spider):
        name = "searxng"
    return FakeSpider()


# --- Text Extraction ---

def test_extracts_text_from_html(spider):
    pipe = TextExtractionPipeline()
    item = JobItem(
        url="https://example.com/job/1", title="Engineer", company="Test",
        board="test", source="test",
        jd_html="<html><body><h1>Job</h1><p>We are looking for an engineer.</p></body></html>",
        created_at="2026-01-01T00:00:00Z",
    )
    result = pipe.process_item(item, spider)
    assert result["jd_text"]
    assert "engineer" in result["jd_text"].lower()


def test_falls_back_to_snippet_when_html_empty(spider):
    pipe = TextExtractionPipeline()
    item = JobItem(
        url="https://example.com/job/1", title="Engineer", company="Test",
        board="test", source="test", jd_html="", snippet="Great job opportunity for backend security engineering",
        created_at="2026-01-01T00:00:00Z",
    )
    result = pipe.process_item(item, spider)
    assert result["jd_text"] == "Great job opportunity for backend security engineering"


def test_handles_none_html(spider):
    pipe = TextExtractionPipeline()
    item = JobItem(
        url="https://example.com/job/1", title="Engineer", company="Test",
        board="test", source="test", snippet="Snippet text for a longer backend platform engineering role",
        created_at="2026-01-01T00:00:00Z",
    )
    result = pipe.process_item(item, spider)
    assert result["jd_text"] == "Snippet text for a longer backend platform engineering role"


# --- Dedup ---

@pytest.fixture
def dedup_pipeline(tmp_path):
    db = JobDB(tmp_path / "test.db")
    pipe = DeduplicationPipeline(db=db)
    return pipe, db


def test_new_url_passes(dedup_pipeline, spider):
    pipe, db = dedup_pipeline
    item = JobItem(url="https://example.com/job/new", title="E", company="C",
                   board="b", source="s", created_at="2026-01-01T00:00:00Z")
    result = pipe.process_item(item, spider)
    assert result["url"] == "https://example.com/job/new"


def test_seen_url_dropped(dedup_pipeline, spider):
    pipe, db = dedup_pipeline
    db.mark_seen("https://example.com/job/dup")
    item = JobItem(url="https://example.com/job/dup", title="E", company="C",
                   board="b", source="s", created_at="2026-01-01T00:00:00Z")
    with pytest.raises(DropItem):
        pipe.process_item(item, spider)


def test_marks_url_as_seen_after_pass(dedup_pipeline, spider):
    pipe, db = dedup_pipeline
    item = JobItem(url="https://example.com/job/mark", title="E", company="C",
                   board="b", source="s", created_at="2026-01-01T00:00:00Z")
    pipe.process_item(item, spider)
    assert db.is_seen("https://example.com/job/mark")


# --- Hard Filter ---

@pytest.fixture
def filter_pipeline():
    cfg = HardFilterConfig(
        domain_blocklist=["dictionary.com", "wikipedia.org"],
        title_blocklist=["staff", "principal", "manager", "director"],
        content_blocklist=["ts/sci", "top secret", "polygraph"],
        min_salary_k=100,
        target_salary_k=150,
    )
    return HardFilterPipeline(config=cfg)


def test_blocklisted_domain_rejected(filter_pipeline, spider):
    item = JobItem(url="https://dictionary.com/security-engineer", title="Engineer",
                   company="C", board="b", source="s", created_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result["status"] == "rejected"
    assert result["rejection_stage"] == "domain_blocklist"


def test_blocklisted_title_rejected(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/1", title="Staff Security Engineer",
                   company="C", board="b", source="s", created_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result["status"] == "rejected"
    assert result["rejection_stage"] == "title_blocklist"


def test_salary_below_floor_rejected(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/2", title="Engineer",
                   company="C", board="b", source="s", salary_text="$50,000 - $60,000",
                   created_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result["status"] == "rejected"
    assert result["rejection_stage"] == "salary_floor"


def test_unparseable_salary_passes(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/3", title="Engineer",
                   company="C", board="b", source="s", salary_text="competitive",
                   created_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result.get("status") != "rejected"


def test_salary_at_floor_but_below_target_passes(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/3b", title="Engineer",
                   company="C", board="b", source="s", salary_text="$100,000 - $120,000",
                   created_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result.get("status") != "rejected"


def test_clean_job_passes(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/4", title="Security Engineer",
                   company="Acme", board="greenhouse", source="s",
                   created_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result.get("status") != "rejected"


def test_international_location_rejected(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/4b", title="Security Engineer",
                   company="Acme", board="remoteok", source="s",
                   location="International",
                   created_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result["status"] == "rejected"
    assert result["rejection_stage"] == "geo_non_us"


def test_content_blocklist_rejected(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/5", title="Engineer",
                   company="C", board="b", source="s",
                   jd_text="Requires active TS/SCI clearance and polygraph.",
                   created_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result["status"] == "rejected"
    assert result["rejection_stage"] == "content_blocklist"


# --- Storage ---

@pytest.fixture
def storage_pipeline(tmp_path):
    db = JobDB(tmp_path / "test.db")
    return SQLitePipeline(db=db, run_id="test-run"), db


def test_stores_pending_job(storage_pipeline, spider):
    pipe, db = storage_pipeline
    item = JobItem(url="https://example.com/job/store1", title="Engineer",
                   company="Acme", board="greenhouse", source="GreenhouseSpider",
                   created_at="2026-01-01T00:00:00Z")
    pipe.process_item(item, spider)
    assert db.job_count() == 1


def test_stores_rejected_job(storage_pipeline, spider):
    pipe, db = storage_pipeline
    item = JobItem(url="https://example.com/job/store2", title="Staff Engineer",
                   company="Acme", board="test", source="test",
                   created_at="2026-01-01T00:00:00Z")
    item["status"] = "rejected"
    item["rejection_stage"] = "title_blocklist"
    item["rejection_reason"] = "staff"
    pipe.process_item(item, spider)
    rows = db.recent_jobs(limit=10)
    assert len(rows) == 1
    assert rows[0]["status"] == "rejected"
