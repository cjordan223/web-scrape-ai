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
    assert rows[0]["status"] == "pending"


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
    db.finish_run("run-1", items_scraped=10, items_new=5, items_filtered=2, errors=0)
    run = db.get_run("run-1")
    assert run["status"] == "completed"
    assert run["items_new"] == 5


def test_job_count(db):
    assert db.job_count() == 0
    db.insert_job({
        "url": "https://example.com/1", "title": "E", "company": "C",
        "board": "b", "source": "s", "run_id": "r",
    })
    assert db.job_count() == 1
