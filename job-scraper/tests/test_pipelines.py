"""Tests for pipeline stages."""

import sqlite3
import pytest
from scrapy import Spider
from scrapy.exceptions import DropItem
from job_scraper.fingerprints import content_hash
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


def test_extracts_text_from_escaped_greenhouse_html(spider):
    pipe = TextExtractionPipeline()
    item = JobItem(
        url="https://job-boards.greenhouse.io/example/jobs/1",
        title="Security Engineer",
        company="Example",
        board="greenhouse",
        source="greenhouse",
        jd_html="&lt;p&gt;We need a security engineer to improve cloud detection and response.&lt;/p&gt;",
        created_at="2026-01-01T00:00:00Z",
    )
    result = pipe.process_item(item, spider)
    assert "cloud detection" in result["jd_text"].lower()


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
    assert result["canonical_url"] == "https://example.com/job/new"
    assert result["duplicate_status"] == "new"


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


def test_tracking_url_variant_dropped(dedup_pipeline, spider):
    pipe, db = dedup_pipeline
    db.mark_seen("https://example.com/job/mark")
    item = JobItem(url="https://example.com/job/mark?utm_source=search", title="E", company="C",
                   board="b", source="s", created_at="2026-01-01T00:00:00Z")
    with pytest.raises(DropItem):
        pipe.process_item(item, spider)


def test_duplicate_ats_id_dropped(dedup_pipeline, spider):
    pipe, db = dedup_pipeline
    db.save_job_fingerprint(1, {
        "canonical_url": "https://jobs.lever.co/acme/old",
        "ats_provider": "lever",
        "ats_job_id": "abc",
        "company_norm": "acme",
        "title_norm": "security-engineer",
        "location_bucket": "us-remote",
        "remote_flag": "true",
        "salary_bucket": "unknown",
        "fingerprint": "acme|security-engineer|us-remote|true|unknown",
        "content_hash": "",
    })
    item = JobItem(
        url="https://jobs.lever.co/acme/new-path",
        ats_provider="lever",
        ats_job_id="abc",
        title="Security Engineer",
        company="Acme",
        board="lever",
        location="Remote, United States",
        source="lever",
        created_at="2026-01-01T00:00:00Z",
    )
    with pytest.raises(DropItem):
        pipe.process_item(item, spider)


def test_duplicate_fingerprint_dropped(dedup_pipeline, spider):
    pipe, db = dedup_pipeline
    db.save_job_fingerprint(2, {
        "canonical_url": "https://jobs.ashbyhq.com/acme/one",
        "ats_provider": "ashby",
        "ats_job_id": "one",
        "company_norm": "acme",
        "title_norm": "security-engineer",
        "location_bucket": "us-remote",
        "remote_flag": "true",
        "salary_bucket": "160k-200k",
        "fingerprint": "acme|security-engineer|us-remote|true|160k-200k",
        "content_hash": content_hash("same text"),
    })
    item = JobItem(
        url="https://job-boards.greenhouse.io/acme/jobs/123",
        title="Security Engineer - Remote US",
        company="Acme Inc.",
        board="greenhouse",
        location="Remote, United States",
        salary_k=180,
        jd_text="same text",
        source="greenhouse",
        created_at="2026-01-01T00:00:00Z",
    )
    with pytest.raises(DropItem):
        pipe.process_item(item, spider)


def test_similar_posting_dropped(dedup_pipeline, spider):
    pipe, db = dedup_pipeline
    db.save_job_fingerprint(3, {
        "canonical_url": "https://jobs.example.com/acme/one",
        "ats_provider": "",
        "ats_job_id": "",
        "company_norm": "acme",
        "title_norm": "cloud-security-engineer",
        "location_bucket": "us-remote",
        "remote_flag": "true",
        "salary_bucket": "unknown",
        "fingerprint": "acme|cloud-security-engineer|us-remote|true|unknown",
        "content_hash": "",
    })
    item = JobItem(
        url="https://jobs.example.com/acme/two",
        title="Cloud Security Engineering",
        company="Acme",
        board="custom",
        location="Remote, United States",
        source="custom",
        created_at="2026-01-01T00:00:00Z",
    )
    with pytest.raises(DropItem):
        pipe.process_item(item, spider)


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
                   location="Remote, USA",
                   created_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result.get("status") != "rejected"


def test_salary_at_floor_but_below_target_passes(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/3b", title="Engineer",
                   company="C", board="b", source="s", salary_text="$100,000 - $120,000",
                   location="Remote, USA",
                   created_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result.get("status") != "rejected"


def test_clean_job_passes(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/4", title="Security Engineer",
                   company="Acme", board="greenhouse", source="s",
                   location="Remote, USA",
                   created_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result.get("status") != "rejected"


def test_international_location_rejected(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/4b", title="Security Engineer",
                   company="Acme", board="greenhouse", source="s",
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


def test_eu_marker_in_title_rejected(filter_pipeline, spider):
    item = JobItem(
        url="https://jobs.ashbyhq.com/bunch/abc",
        title="Senior Platform Engineer (m/f/d) @ bunch",
        company="bunch", board="ashby", source="searxng",
        location="", jd_text="snippet text",
        created_at="2026-01-01T00:00:00Z",
    )
    result = filter_pipeline.process_item(item, spider)
    assert result["status"] == "rejected"
    assert result["rejection_stage"] == "title_geo"
    assert "EU equality marker" in result["rejection_reason"]


def test_eu_city_in_title_rejected(filter_pipeline, spider):
    item = JobItem(
        url="https://jobs.lever.co/emburse/xyz",
        title="Senior Security Engineer Barcelona",
        company="emburse", board="lever", source="searxng",
        location="", jd_text="snippet",
        created_at="2026-01-01T00:00:00Z",
    )
    result = filter_pipeline.process_item(item, spider)
    assert result["status"] == "rejected"
    assert result["rejection_stage"] == "title_geo"


def test_empty_location_with_no_us_signal_rejected(
    filter_pipeline, spider
):
    """Empty location must fail closed — silent passes on missing data hide bugs."""
    item = JobItem(
        url="https://jobs.ashbyhq.com/abound/xyz",
        title="Senior Security Engineer",
        company="Abound", board="ashby", source="searxng",
        location="", jd_text="Help build secure systems.",
        created_at="2026-01-01T00:00:00Z",
    )
    result = filter_pipeline.process_item(item, spider)
    assert result["status"] == "rejected"
    # Either geo_non_us (no US signal) OR not_remote (no remote signal) gate
    # catches it — both encode the same "missing-data fail-closed" intent.
    assert result["rejection_stage"] in {"geo_non_us", "not_remote"}


def test_empty_location_with_us_jd_signal_passes_geo(filter_pipeline, spider):
    """Empty location + US signal in JD passes geo (still hits remote gate)."""
    item = JobItem(
        url="https://jobs.ashbyhq.com/co/xyz",
        title="Security Engineer",
        company="co", board="ashby", source="searxng",
        location="",
        jd_text="Remote role open to candidates anywhere in the USA.",
        created_at="2026-01-01T00:00:00Z",
    )
    result = filter_pipeline.process_item(item, spider)
    # Should not be rejected on geo; remote signal also present.
    assert result.get("rejection_stage") not in {"geo_non_us", "not_remote"}


def test_aggregator_path_on_legit_ats_rejected(filter_pipeline, spider):
    """jobs.lever.co/jobgether/... should be caught by jobgether.com blocklist."""
    cfg = HardFilterConfig(
        domain_blocklist=["jobgether.com"],
        title_blocklist=["staff"],
        content_blocklist=[],
        min_salary_k=100,
        target_salary_k=150,
    )
    pipe = HardFilterPipeline(config=cfg)
    item = JobItem(
        url="https://jobs.lever.co/jobgether/abc-123",
        title="Senior DevOps Engineer",
        company="jobgether", board="lever", source="searxng",
        location="Remote, USA", jd_text="Remote role.",
        created_at="2026-01-01T00:00:00Z",
    )
    result = pipe.process_item(item, spider)
    assert result["status"] == "rejected"
    assert result["rejection_stage"] == "domain_blocklist"


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


def test_storage_writes_fingerprint_record(storage_pipeline, spider):
    pipe, db = storage_pipeline
    item = JobItem(
        url="https://jobs.lever.co/acme/abc",
        canonical_url="https://jobs.lever.co/acme/abc",
        ats_provider="lever",
        ats_job_id="abc",
        title="Engineer",
        company="Acme",
        board="lever",
        source="lever",
        fingerprint="acme|engineer|unclear|unclear|unknown",
        content_hash="hash",
        duplicate_status="new",
        created_at="2026-01-01T00:00:00Z",
    )
    pipe.process_item(item, spider)
    row = db._conn.execute("SELECT job_id, ats_provider, ats_job_id, fingerprint FROM job_fingerprints").fetchone()
    assert row["job_id"] == 1
    assert row["ats_provider"] == "lever"
    assert row["ats_job_id"] == "abc"


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
