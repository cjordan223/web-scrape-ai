"""Tests for job_scraper.db module."""

import sqlite3
from pathlib import Path

import pytest

from job_scraper.db import JobDB


@pytest.fixture
def db(tmp_path):
    return JobDB(tmp_path / "test.db")


def test_schema_creates_tables(db):
    tables = db.tables()
    assert "jobs" in tables
    assert "runs" in tables
    assert "seen_urls" in tables
    assert "job_fingerprints" in tables


def test_is_seen_returns_false_for_new_url(db):
    assert db.is_seen("https://example.com/job/1") is False


def test_mark_seen_then_is_seen(db):
    db.mark_seen("https://example.com/job/1")
    assert db.is_seen("https://example.com/job/1") is True


def test_seen_ttl_expires(db):
    db._conn.execute(
        "INSERT INTO seen_urls (url, first_seen, last_seen) VALUES (?, datetime('now', '-30 days'), datetime('now'))",
        ("https://example.com/old",),
    )
    db._conn.commit()
    assert db.is_seen("https://example.com/old", ttl_days=14) is False


def test_insert_job(db):
    job = {
        "url": "https://example.com/job/1",
        "title": "Security Engineer",
        "company": "Acme",
        "board": "greenhouse",
        "source": "GreenhouseSpider",
        "run_id": "test-run-1",
    }
    db.insert_job(job)
    rows = db.recent_jobs(limit=1)
    assert len(rows) == 1
    assert rows[0]["title"] == "Security Engineer"
    assert rows[0]["status"] == "qa_pending"


def test_insert_duplicate_url_raises(db):
    job = {
        "url": "https://example.com/job/1",
        "title": "Engineer",
        "company": "Acme",
        "board": "test",
        "source": "test",
        "run_id": "run-1",
    }
    db.insert_job(job)
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_job(job)


def test_start_and_finish_run(db):
    db.start_run("run-1")
    db.finish_run("run-1", raw_count=10, dedup_count=5, filtered_count=2, error_count=0)
    run = db.get_run("run-1")
    assert run["status"] == "completed"
    assert run["dedup_count"] == 5


def test_finish_run_can_mark_failed(db):
    db.start_run("run-fail")
    db.finish_run("run-fail", error_count=1, errors="LLM gate failed", status="failed")
    run = db.get_run("run-fail")
    assert run["status"] == "failed"
    assert run["errors"] == "LLM gate failed"


def test_job_count(db):
    assert db.job_count() == 0
    db.insert_job({
        "url": "https://example.com/1", "title": "E", "company": "C",
        "board": "b", "source": "s", "run_id": "r",
    })
    assert db.job_count() == 1


def test_classifies_duplicate_ats_id(db):
    meta = {
        "canonical_url": "https://jobs.lever.co/acme/abc",
        "ats_provider": "lever",
        "ats_job_id": "abc",
        "company_norm": "acme",
        "title_norm": "security-engineer",
        "location_bucket": "us-remote",
        "remote_flag": "true",
        "salary_bucket": "160k-200k",
        "fingerprint": "acme|security-engineer|us-remote|true|160k-200k",
        "content_hash": "hash1",
    }
    db.save_job_fingerprint(12, meta, "new")
    changed_url = dict(meta, canonical_url="https://jobs.lever.co/acme/abc-new")
    decision = db.classify_fingerprint(changed_url, ttl_days=45)
    assert decision["duplicate_status"] == "duplicate_ats_id"
    assert decision["duplicate_of_job_id"] == 12


def test_classifies_content_mirror(db):
    meta = {
        "canonical_url": "https://jobs.ashbyhq.com/acme/one",
        "ats_provider": "ashby",
        "ats_job_id": "one",
        "company_norm": "acme",
        "title_norm": "security-engineer",
        "location_bucket": "us-remote",
        "remote_flag": "true",
        "salary_bucket": "unknown",
        "fingerprint": "acme|security-engineer|us-remote|true|unknown",
        "content_hash": "same-content",
    }
    db.save_job_fingerprint(44, meta, "new")
    mirror = dict(
        meta,
        canonical_url="https://linkedin.com/jobs/view/999",
        ats_provider="linkedin",
        ats_job_id="999",
        fingerprint="other|security-engineer|us-remote|true|unknown",
    )
    decision = db.classify_fingerprint(mirror, ttl_days=45)
    assert decision["duplicate_status"] == "mirror"
    assert decision["duplicate_of_job_id"] == 44


def test_classifies_similar_posting(db):
    meta = {
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
    }
    db.save_job_fingerprint(55, meta, "new")
    variant = dict(
        meta,
        canonical_url="https://jobs.example.com/acme/two",
        title_norm="cloud-security-engineering",
        fingerprint="acme|cloud-security-engineering|us-remote|true|unknown",
    )
    decision = db.classify_fingerprint(variant, ttl_days=45)
    assert decision["duplicate_status"] == "similar_posting"
    assert decision["duplicate_of_job_id"] == 55


def test_backfill_job_fingerprints_classifies_existing_rows(db):
    db.insert_job({
        "url": "https://jobs.lever.co/acme/abc",
        "title": "Security Engineer",
        "company": "Acme",
        "board": "lever",
        "source": "lever",
        "location": "Remote, United States",
        "run_id": "r1",
        "jd_text": "Remote role in the United States.",
    })
    db.insert_job({
        "url": "https://jobs.lever.co/acme/abc-copy",
        "title": "Security Engineer - Remote US",
        "company": "Acme Inc.",
        "board": "lever",
        "source": "lever",
        "location": "Remote, United States",
        "run_id": "r1",
        "jd_text": "Remote role in the United States.",
    })
    result = db.backfill_job_fingerprints()
    assert result["processed"] == 2
    assert result["counts"]["new"] == 1
    assert result["counts"]["duplicate_fingerprint"] == 1
    rows = db._conn.execute("SELECT duplicate_status FROM job_fingerprints ORDER BY id").fetchall()
    assert [r["duplicate_status"] for r in rows] == ["new", "duplicate_fingerprint"]


def test_backfill_job_fingerprints_dry_run_does_not_write(db):
    db.insert_job({
        "url": "https://example.com/job/1",
        "title": "Engineer",
        "company": "Acme",
        "board": "greenhouse",
        "source": "greenhouse",
        "run_id": "r1",
    })
    result = db.backfill_job_fingerprints(dry_run=True)
    assert result["processed"] == 1
    count = db._conn.execute("SELECT COUNT(*) AS n FROM job_fingerprints").fetchone()["n"]
    assert count == 0


def test_reclassify_similar_fingerprints_dry_run_does_not_write(db):
    first = {
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
    }
    second = dict(
        first,
        canonical_url="https://jobs.example.com/acme/two",
        title_norm="cloud-security-engineering",
        fingerprint="acme|cloud-security-engineering|us-remote|true|unknown",
    )
    db.save_job_fingerprint(1, first, "new")
    db.save_job_fingerprint(2, second, "new")

    result = db.reclassify_similar_fingerprints(dry_run=True)

    assert result["processed"] == 2
    assert result["counts"]["similar_posting"] == 1
    rows = db._conn.execute(
        "SELECT job_id, duplicate_status, duplicate_of_job_id FROM job_fingerprints ORDER BY id"
    ).fetchall()
    assert [(r["job_id"], r["duplicate_status"], r["duplicate_of_job_id"]) for r in rows] == [
        (1, "new", None),
        (2, "new", None),
    ]


def test_reclassify_similar_fingerprints_updates_later_new_rows(db):
    first = {
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
    }
    second = dict(
        first,
        canonical_url="https://jobs.example.com/acme/two",
        title_norm="cloud-security-engineering",
        fingerprint="acme|cloud-security-engineering|us-remote|true|unknown",
    )
    db.save_job_fingerprint(1, first, "new")
    db.save_job_fingerprint(2, second, "new")

    result = db.reclassify_similar_fingerprints(dry_run=False)

    assert result["processed"] == 2
    assert result["counts"]["similar_posting"] == 1
    rows = db._conn.execute(
        "SELECT job_id, duplicate_status, duplicate_of_job_id FROM job_fingerprints ORDER BY id"
    ).fetchall()
    assert [(r["job_id"], r["duplicate_status"], r["duplicate_of_job_id"]) for r in rows] == [
        (1, "new", None),
        (2, "similar_posting", 1),
    ]
