# Scraper Pipeline Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Crawl4AI + 15-stage regex scraper with a Scrapy + Playwright + Trafilatura pipeline that feeds the tailoring QA phase.

**Architecture:** Scrapy project with one spider per board type, 4 pipeline stages (text extraction, dedup, hard filter, storage), SQLite with modernized schema. No LLM in scraper. SearXNG optional.

**Tech Stack:** Scrapy, scrapy-playwright, Trafilatura, httpx, Pydantic 2, SQLite, typer, rich

**Spec:** `docs/superpowers/specs/2026-03-19-scraper-pipeline-rewrite-design.md`

---

### Task 1: Project Scaffold & Dependencies

**Files:**
- Create: `job-scraper/scrapy.cfg`
- Rewrite: `job-scraper/pyproject.toml`
- Create: `job-scraper/job_scraper/settings.py`
- Create: `job-scraper/job_scraper/items.py`

- [ ] **Step 1: Write `scrapy.cfg`**

```ini
[settings]
default = job_scraper.settings

[deploy]
project = job_scraper
```

- [ ] **Step 2: Update `pyproject.toml`**

Replace dependencies section:

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "job-scraper"
version = "2.0.0"
description = "Job discovery via Scrapy + Playwright"
requires-python = ">=3.10"
dependencies = [
    "scrapy>=2.11",
    "scrapy-playwright>=0.0.40",
    "trafilatura>=1.12",
    "httpx>=0.27",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "typer>=0.12",
    "rich>=13.0",
]

[project.scripts]
job-scraper = "job_scraper.__main__:app"

[tool.setuptools.packages.find]
include = ["job_scraper*"]
```

- [ ] **Step 3: Write `settings.py`**

```python
"""Scrapy settings for job_scraper."""

BOT_NAME = "job_scraper"
SPIDER_MODULES = ["job_scraper.spiders"]
NEWSPIDER_MODULE = "job_scraper.spiders"

# Respect robots.txt
ROBOTSTXT_OBEY = False

# Concurrency
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1.0

# Auto-throttle
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0

# Retry
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# Timeouts
DOWNLOAD_TIMEOUT = 30

# Pipelines (order matters)
ITEM_PIPELINES = {
    "job_scraper.pipelines.text_extraction.TextExtractionPipeline": 100,
    "job_scraper.pipelines.dedup.DeduplicationPipeline": 200,
    "job_scraper.pipelines.hard_filter.HardFilterPipeline": 300,
    "job_scraper.pipelines.storage.SQLitePipeline": 400,
}

# Playwright
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True}

# Logging
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

# Disable default user-agent; set a realistic one
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# Stats
STATS_CLASS = "scrapy.statscollectors.MemoryStatsCollector"
```

- [ ] **Step 4: Write `items.py`**

```python
"""Scrapy Item definition for scraped jobs."""

from __future__ import annotations

import scrapy


class JobItem(scrapy.Item):
    url = scrapy.Field()            # canonical URL
    title = scrapy.Field()          # job title
    company = scrapy.Field()        # parsed at crawl time
    board = scrapy.Field()          # ashby, greenhouse, lever, usajobs, etc.
    location = scrapy.Field()       # raw location string
    seniority = scrapy.Field()      # raw if available
    salary_text = scrapy.Field()    # raw salary string
    jd_html = scrapy.Field()        # raw HTML for Trafilatura
    jd_text = scrapy.Field()        # populated by TextExtractionPipeline
    snippet = scrapy.Field()        # search result snippet
    query = scrapy.Field()          # search query that found this (diagnostics)
    source = scrapy.Field()         # spider class name
    discovered_at = scrapy.Field()  # ISO timestamp
```

- [ ] **Step 5: Create spiders and pipelines packages**

```bash
mkdir -p job-scraper/job_scraper/spiders job-scraper/job_scraper/pipelines
touch job-scraper/job_scraper/spiders/__init__.py
touch job-scraper/job_scraper/pipelines/__init__.py
```

- [ ] **Step 6: Install dependencies and verify Scrapy loads**

```bash
cd /Users/conner/Documents/JobForge
pip install -e ./job-scraper/
cd job-scraper
python -c "from job_scraper.settings import BOT_NAME; print(BOT_NAME)"
```

Expected: `job_scraper`

- [ ] **Step 7: Commit**

```bash
git add job-scraper/scrapy.cfg job-scraper/pyproject.toml job-scraper/job_scraper/settings.py job-scraper/job_scraper/items.py job-scraper/job_scraper/spiders/__init__.py job-scraper/job_scraper/pipelines/__init__.py
git commit -m "feat(scraper-v2): project scaffold with Scrapy settings and JobItem"
```

---

### Task 2: Database Layer (`db.py`)

**Files:**
- Create: `job-scraper/job_scraper/db.py`
- Create: `job-scraper/tests/test_db.py`

- [ ] **Step 1: Write failing tests for DB schema and operations**

```python
"""Tests for job_scraper.db module."""

import sqlite3
import tempfile
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
    # Insert with old first_seen
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/conner/Documents/JobForge/job-scraper
python -m pytest tests/test_db.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'job_scraper.db'`

- [ ] **Step 3: Implement `db.py`**

```python
"""SQLite database layer for job_scraper v2."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_urls (
    url TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seen_urls_first_seen ON seen_urls(first_seen);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    board TEXT,
    location TEXT,
    seniority TEXT,
    salary_text TEXT,
    jd_text TEXT,
    approved_jd_text TEXT,
    snippet TEXT,
    query TEXT,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    rejection_stage TEXT,
    rejection_reason TEXT,
    run_id TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_run_id ON jobs(run_id);
CREATE INDEX IF NOT EXISTS idx_jobs_discovered_at ON jobs(discovered_at);
CREATE INDEX IF NOT EXISTS idx_jobs_board ON jobs(board);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    elapsed REAL,
    items_scraped INTEGER DEFAULT 0,
    items_new INTEGER DEFAULT 0,
    items_filtered INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    trigger_source TEXT NOT NULL DEFAULT 'scheduled'
);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);

-- Compatibility view for code still referencing 'results'
CREATE VIEW IF NOT EXISTS results AS
    SELECT *, status AS decision FROM jobs;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobDB:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            from job_scraper.config import DB_PATH
            db_path = DB_PATH
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def tables(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]

    # --- seen_urls ---

    def is_seen(self, url: str, ttl_days: int = 14) -> bool:
        row = self._conn.execute(
            "SELECT first_seen FROM seen_urls WHERE url = ?", (url,)
        ).fetchone()
        if row is None:
            return False
        first = datetime.fromisoformat(row["first_seen"])
        age = (datetime.now(timezone.utc) - first).days
        return age < ttl_days

    def mark_seen(self, url: str) -> None:
        now = _now()
        self._conn.execute(
            "INSERT INTO seen_urls (url, first_seen, last_seen) VALUES (?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET last_seen = ?",
            (url, now, now, now),
        )
        self._conn.commit()

    # --- jobs ---

    def insert_job(self, job: dict) -> int:
        now = _now()
        cur = self._conn.execute(
            """INSERT INTO jobs (url, title, company, board, location, seniority,
               salary_text, jd_text, snippet, query, source, status,
               rejection_stage, rejection_reason, run_id, discovered_at, updated_at)
            VALUES (:url, :title, :company, :board, :location, :seniority,
                    :salary_text, :jd_text, :snippet, :query, :source, :status,
                    :rejection_stage, :rejection_reason, :run_id, :discovered_at, :updated_at)""",
            {
                "url": job["url"],
                "title": job["title"],
                "company": job["company"],
                "board": job.get("board"),
                "location": job.get("location"),
                "seniority": job.get("seniority"),
                "salary_text": job.get("salary_text"),
                "jd_text": job.get("jd_text"),
                "snippet": job.get("snippet"),
                "query": job.get("query"),
                "source": job["source"],
                "status": job.get("status", "pending"),
                "rejection_stage": job.get("rejection_stage"),
                "rejection_reason": job.get("rejection_reason"),
                "run_id": job["run_id"],
                "discovered_at": job.get("discovered_at", now),
                "updated_at": now,
            },
        )
        self._conn.commit()
        return cur.lastrowid

    def job_count(self, status: str | None = None) -> int:
        if status:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM jobs WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()
        return row["c"]

    def recent_jobs(self, limit: int = 50, status: str | None = None) -> list[dict]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY discovered_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY discovered_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # --- runs ---

    def start_run(self, run_id: str, trigger: str = "scheduled") -> None:
        self._conn.execute(
            "INSERT INTO runs (run_id, started_at, status, trigger_source) VALUES (?, ?, 'running', ?)",
            (run_id, _now(), trigger),
        )
        self._conn.commit()

    def finish_run(self, run_id: str, *, items_scraped: int = 0, items_new: int = 0,
                   items_filtered: int = 0, errors: int = 0) -> None:
        now = _now()
        started = self._conn.execute(
            "SELECT started_at FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        elapsed = None
        if started:
            start_dt = datetime.fromisoformat(started["started_at"])
            elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()
        self._conn.execute(
            """UPDATE runs SET completed_at = ?, elapsed = ?, items_scraped = ?,
               items_new = ?, items_filtered = ?, errors = ?, status = 'completed'
            WHERE run_id = ?""",
            (now, elapsed, items_scraped, items_new, items_filtered, errors, run_id),
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/conner/Documents/JobForge/job-scraper
python -m pytest tests/test_db.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/db.py job-scraper/tests/test_db.py
git commit -m "feat(scraper-v2): database layer with jobs/runs/seen_urls schema"
```

---

### Task 3: Config Loader

**Files:**
- Rewrite: `job-scraper/job_scraper/config.py`
- Keep: `job-scraper/job_scraper/config.default.yaml` (modify structure)
- Create: `job-scraper/tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for config loader."""

from pathlib import Path
from job_scraper.config import load_config, ScraperConfig


def test_load_default_config():
    cfg = load_config()
    assert isinstance(cfg, ScraperConfig)
    assert len(cfg.boards) > 0


def test_boards_have_required_fields():
    cfg = load_config()
    for board in cfg.boards:
        assert board.url
        assert board.board_type
        assert board.company


def test_hard_filters_loaded():
    cfg = load_config()
    assert len(cfg.hard_filters.domain_blocklist) > 0
    assert len(cfg.hard_filters.title_blocklist) > 0
    assert cfg.hard_filters.min_salary_k > 0


def test_searxng_optional():
    cfg = load_config()
    assert cfg.searxng is not None  # config exists
    # but pipeline works without it (tested elsewhere)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_config.py -v
```

Expected: FAIL — import errors (new config shape)

- [ ] **Step 3: Rewrite `config.py`**

```python
"""YAML config loader for scraper v2."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

_DEFAULT_CONFIG = Path(__file__).parent / "config.default.yaml"

DB_PATH = Path(
    os.environ.get("JOB_SCRAPER_DB", Path.home() / ".local" / "share" / "job_scraper" / "jobs.db")
)


class BoardTarget(BaseModel):
    url: str
    board_type: str  # ashby, greenhouse, lever, simplyhired, usajobs
    company: str     # parsed from URL or explicit
    enabled: bool = True


class SearXNGConfig(BaseModel):
    enabled: bool = True
    url: str = "http://localhost:8888/search"
    timeout: int = 15
    engines: str = "google,startpage"
    time_range: str = "week"
    request_delay: float = 1.0


class USAJobsConfig(BaseModel):
    enabled: bool = True
    series: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    agencies: list[str] = Field(default_factory=list)
    days: int = 14
    remote: bool = True


class HardFilterConfig(BaseModel):
    domain_blocklist: list[str] = Field(default_factory=lambda: [
        "dictionary.com", "collinsdictionary.com", "techtarget.com",
        "wikipedia.org", "merriam-webster.com", "investopedia.com",
        "reddit.com", "quora.com", "youtube.com", "medium.com",
    ])
    title_blocklist: list[str] = Field(default_factory=lambda: [
        "staff", "principal", "manager", "director",
    ])
    content_blocklist: list[str] = Field(default_factory=lambda: [
        "clearance", "ts/sci", "ts-sci", "polygraph", "top secret",
        "secret clearance",
    ])
    min_salary_k: int = 70


class SearXNGQuery(BaseModel):
    title_phrase: str
    board_site: str = ""
    suffix: str = ""


class ScraperConfig(BaseModel):
    boards: list[BoardTarget] = Field(default_factory=list)
    searxng: SearXNGConfig = Field(default_factory=SearXNGConfig)
    usajobs: USAJobsConfig = Field(default_factory=USAJobsConfig)
    hard_filters: HardFilterConfig = Field(default_factory=HardFilterConfig)
    queries: list[SearXNGQuery] = Field(default_factory=list)
    seen_ttl_days: int = 14
    target_max_results: int = 50


def _company_from_board_url(url: str, board_type: str) -> str:
    """Extract company name from board URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]

    if board_type == "ashby" and "ashbyhq.com" in parsed.netloc:
        return path_parts[0] if path_parts else "unknown"
    if board_type == "greenhouse" and "greenhouse.io" in parsed.netloc:
        return path_parts[0] if path_parts else "unknown"
    if board_type == "lever" and "lever.co" in parsed.netloc:
        return path_parts[0] if path_parts else "unknown"

    # Fallback: second-level domain
    host = parsed.netloc.replace("www.", "")
    parts = host.split(".")
    return parts[0] if parts else "unknown"


def load_config(path: str | Path | None = None) -> ScraperConfig:
    """Load config from YAML file."""
    config_path = Path(path) if path else _DEFAULT_CONFIG
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    # Map old-style crawl targets to BoardTarget list
    boards: list[BoardTarget] = []
    for target in raw.get("crawl", {}).get("targets", []):
        board_type = target.get("board", "unknown")
        company = target.get("company") or _company_from_board_url(target["url"], board_type)
        boards.append(BoardTarget(
            url=target["url"],
            board_type=board_type,
            company=company,
        ))

    # Map old-style queries
    queries = []
    for q in raw.get("queries", []):
        queries.append(SearXNGQuery(
            title_phrase=q.get("title_phrase", ""),
            board_site=q.get("board_site", ""),
            suffix=q.get("suffix", ""),
        ))

    # SearXNG config
    searxng_raw = raw.get("search", {})
    searxng = SearXNGConfig(
        url=searxng_raw.get("searx_url", "http://localhost:8888/search"),
        timeout=searxng_raw.get("timeout", 15),
        engines=searxng_raw.get("engines", "google,startpage"),
        time_range=searxng_raw.get("time_range", "week"),
        request_delay=searxng_raw.get("request_delay", 1.0),
    )

    # USAJobs config
    usajobs_raw = {}
    for w in raw.get("watchers", []):
        if w.get("name") == "usajobs":
            usajobs_raw = w.get("params", {})
            break
    usajobs = USAJobsConfig(
        series=usajobs_raw.get("series", "").split(";") if usajobs_raw.get("series") else [],
        keywords=usajobs_raw.get("keywords", "").split(";") if usajobs_raw.get("keywords") else [],
        agencies=usajobs_raw.get("agencies", "").split(";") if usajobs_raw.get("agencies") else [],
        days=int(usajobs_raw.get("days", "14")),
        remote=usajobs_raw.get("remote", "true") == "true",
    )

    # Hard filters
    filter_raw = raw.get("filter", {})
    hard_filters = HardFilterConfig(
        domain_blocklist=filter_raw.get("url_domain_blocklist", HardFilterConfig().domain_blocklist),
        title_blocklist=filter_raw.get("seniority_exclude", HardFilterConfig().title_blocklist),
        content_blocklist=filter_raw.get("content_blocklist", HardFilterConfig().content_blocklist),
        min_salary_k=filter_raw.get("min_salary_k", 70),
    )

    return ScraperConfig(
        boards=boards,
        searxng=searxng,
        usajobs=usajobs,
        hard_filters=hard_filters,
        queries=queries,
        seen_ttl_days=filter_raw.get("seen_ttl_days", 14),
        target_max_results=filter_raw.get("target_max_results", 50),
    )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_config.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/config.py job-scraper/tests/test_config.py
git commit -m "feat(scraper-v2): config loader mapping existing YAML to new Pydantic models"
```

---

### Task 4: Pipelines — Text Extraction

**Files:**
- Create: `job-scraper/job_scraper/pipelines/text_extraction.py`
- Create: `job-scraper/tests/test_pipelines.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for pipeline stages."""

import pytest
from scrapy import Spider
from job_scraper.items import JobItem
from job_scraper.pipelines.text_extraction import TextExtractionPipeline


@pytest.fixture
def spider():
    class FakeSpider(Spider):
        name = "test"
    return FakeSpider()


def test_extracts_text_from_html(spider):
    pipe = TextExtractionPipeline()
    item = JobItem(
        url="https://example.com/job/1",
        title="Engineer",
        company="Test",
        board="test",
        source="test",
        jd_html="<html><body><h1>Job</h1><p>We are looking for an engineer.</p></body></html>",
        discovered_at="2026-01-01T00:00:00Z",
    )
    result = pipe.process_item(item, spider)
    assert result["jd_text"]
    assert "engineer" in result["jd_text"].lower()


def test_falls_back_to_snippet_when_html_empty(spider):
    pipe = TextExtractionPipeline()
    item = JobItem(
        url="https://example.com/job/1",
        title="Engineer",
        company="Test",
        board="test",
        source="test",
        jd_html="",
        snippet="Great job opportunity",
        discovered_at="2026-01-01T00:00:00Z",
    )
    result = pipe.process_item(item, spider)
    assert result["jd_text"] == "Great job opportunity"


def test_handles_none_html(spider):
    pipe = TextExtractionPipeline()
    item = JobItem(
        url="https://example.com/job/1",
        title="Engineer",
        company="Test",
        board="test",
        source="test",
        snippet="Snippet text",
        discovered_at="2026-01-01T00:00:00Z",
    )
    result = pipe.process_item(item, spider)
    assert result["jd_text"] == "Snippet text"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pipelines.py::test_extracts_text_from_html -v
```

Expected: FAIL — module not found

- [ ] **Step 3: Implement `text_extraction.py`**

```python
"""Pipeline: extract clean text from JD HTML using Trafilatura."""

from __future__ import annotations

import logging

import trafilatura

logger = logging.getLogger(__name__)


class TextExtractionPipeline:
    def process_item(self, item, spider):
        html = item.get("jd_html")
        if html:
            text = trafilatura.extract(html, include_comments=False, include_tables=True)
            if text:
                item["jd_text"] = text
                return item

        # Fallback to snippet
        snippet = item.get("snippet")
        if snippet:
            item["jd_text"] = snippet
        else:
            item["jd_text"] = None

        return item
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_pipelines.py -v -k "text"
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/pipelines/text_extraction.py job-scraper/tests/test_pipelines.py
git commit -m "feat(scraper-v2): text extraction pipeline with Trafilatura"
```

---

### Task 5: Pipelines — Dedup

**Files:**
- Create: `job-scraper/job_scraper/pipelines/dedup.py`
- Modify: `job-scraper/tests/test_pipelines.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_pipelines.py`:

```python
from scrapy.exceptions import DropItem
from job_scraper.pipelines.dedup import DeduplicationPipeline
from job_scraper.db import JobDB


@pytest.fixture
def dedup_pipeline(tmp_path):
    db = JobDB(tmp_path / "test.db")
    pipe = DeduplicationPipeline(db=db)
    return pipe, db


def test_new_url_passes(dedup_pipeline, spider):
    pipe, db = dedup_pipeline
    item = JobItem(url="https://example.com/job/new", title="E", company="C",
                   board="b", source="s", discovered_at="2026-01-01T00:00:00Z")
    result = pipe.process_item(item, spider)
    assert result["url"] == "https://example.com/job/new"


def test_seen_url_dropped(dedup_pipeline, spider):
    pipe, db = dedup_pipeline
    db.mark_seen("https://example.com/job/dup")
    item = JobItem(url="https://example.com/job/dup", title="E", company="C",
                   board="b", source="s", discovered_at="2026-01-01T00:00:00Z")
    with pytest.raises(DropItem):
        pipe.process_item(item, spider)


def test_marks_url_as_seen_after_pass(dedup_pipeline, spider):
    pipe, db = dedup_pipeline
    item = JobItem(url="https://example.com/job/mark", title="E", company="C",
                   board="b", source="s", discovered_at="2026-01-01T00:00:00Z")
    pipe.process_item(item, spider)
    assert db.is_seen("https://example.com/job/mark")
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_pipelines.py -v -k "dedup"
```

- [ ] **Step 3: Implement `dedup.py`**

```python
"""Pipeline: URL deduplication against seen_urls table."""

from __future__ import annotations

import logging

from scrapy.exceptions import DropItem

from job_scraper.db import JobDB

logger = logging.getLogger(__name__)


class DeduplicationPipeline:
    def __init__(self, db: JobDB | None = None, ttl_days: int = 14):
        self._db = db
        self._ttl_days = ttl_days

    @classmethod
    def from_crawler(cls, crawler):
        from job_scraper.config import DB_PATH
        db = JobDB(DB_PATH)
        ttl = crawler.settings.getint("SEEN_TTL_DAYS", 14)
        return cls(db=db, ttl_days=ttl)

    def process_item(self, item, spider):
        url = item["url"]
        if self._db.is_seen(url, ttl_days=self._ttl_days):
            raise DropItem(f"Already seen: {url}")
        self._db.mark_seen(url)
        return item
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_pipelines.py -v -k "dedup"
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/pipelines/dedup.py job-scraper/tests/test_pipelines.py
git commit -m "feat(scraper-v2): dedup pipeline with TTL-based seen_urls check"
```

---

### Task 6: Pipelines — Hard Filter

**Files:**
- Create: `job-scraper/job_scraper/pipelines/hard_filter.py`
- Modify: `job-scraper/tests/test_pipelines.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pipelines.py`:

```python
from job_scraper.pipelines.hard_filter import HardFilterPipeline
from job_scraper.config import HardFilterConfig


@pytest.fixture
def filter_pipeline():
    cfg = HardFilterConfig(
        domain_blocklist=["dictionary.com", "wikipedia.org"],
        title_blocklist=["staff", "principal", "manager", "director"],
        content_blocklist=["ts/sci", "top secret", "polygraph"],
        min_salary_k=70,
    )
    return HardFilterPipeline(config=cfg)


def test_blocklisted_domain_rejected(filter_pipeline, spider):
    item = JobItem(url="https://dictionary.com/security-engineer", title="Engineer",
                   company="C", board="b", source="s", discovered_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result["status"] == "rejected"
    assert result["rejection_stage"] == "domain_blocklist"


def test_blocklisted_title_rejected(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/1", title="Staff Security Engineer",
                   company="C", board="b", source="s", discovered_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result["status"] == "rejected"
    assert result["rejection_stage"] == "title_blocklist"


def test_salary_below_floor_rejected(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/2", title="Engineer",
                   company="C", board="b", source="s", salary_text="$50,000 - $60,000",
                   discovered_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result["status"] == "rejected"
    assert result["rejection_stage"] == "salary_floor"


def test_unparseable_salary_passes(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/3", title="Engineer",
                   company="C", board="b", source="s", salary_text="competitive",
                   discovered_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result.get("status") != "rejected"


def test_clean_job_passes(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/4", title="Security Engineer",
                   company="Acme", board="greenhouse", source="s",
                   discovered_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result.get("status") != "rejected"


def test_content_blocklist_rejected(filter_pipeline, spider):
    item = JobItem(url="https://example.com/job/5", title="Engineer",
                   company="C", board="b", source="s",
                   jd_text="Requires active TS/SCI clearance and polygraph.",
                   discovered_at="2026-01-01T00:00:00Z")
    result = filter_pipeline.process_item(item, spider)
    assert result["status"] == "rejected"
    assert result["rejection_stage"] == "content_blocklist"
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_pipelines.py -v -k "filter"
```

- [ ] **Step 3: Implement `hard_filter.py`**

```python
"""Pipeline: hard filters — domain blocklist, title blocklist, salary floor, content blocklist."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from job_scraper.config import HardFilterConfig

logger = logging.getLogger(__name__)

_SALARY_PATTERN = re.compile(r"\$\s*([\d,]+)")


def _parse_salary_k(text: str) -> int | None:
    """Extract lowest salary figure in thousands. Returns None if unparseable."""
    matches = _SALARY_PATTERN.findall(text)
    if not matches:
        return None
    values = []
    for m in matches:
        try:
            val = int(m.replace(",", ""))
            if 20_000 <= val <= 500_000:
                values.append(val // 1000)
        except ValueError:
            continue
    return min(values) if values else None


class HardFilterPipeline:
    def __init__(self, config: HardFilterConfig | None = None):
        self._config = config or HardFilterConfig()
        # Pre-compile title blocklist patterns
        self._title_patterns = [
            re.compile(rf"\b{re.escape(word)}\b", re.I)
            for word in self._config.title_blocklist
        ]
        self._content_patterns = [
            re.compile(rf"\b{re.escape(phrase)}\b", re.I)
            for phrase in self._config.content_blocklist
        ]

    @classmethod
    def from_crawler(cls, crawler):
        from job_scraper.config import load_config
        cfg = load_config()
        return cls(config=cfg.hard_filters)

    def _reject(self, item, stage: str, reason: str):
        item["status"] = "rejected"
        item["rejection_stage"] = stage
        item["rejection_reason"] = reason
        return item

    def process_item(self, item, spider):
        url = item["url"]
        title = item.get("title", "")

        # 1. Domain blocklist
        host = urlparse(url).netloc.lower()
        for domain in self._config.domain_blocklist:
            if domain in host:
                logger.debug("Rejected (domain): %s", url)
                return self._reject(item, "domain_blocklist", f"Blocked domain: {domain}")

        # 2. Title blocklist
        for pattern in self._title_patterns:
            if pattern.search(title):
                logger.debug("Rejected (title): %s — %s", title, pattern.pattern)
                return self._reject(item, "title_blocklist", f"Blocked title word: {pattern.pattern}")

        # 3. Content blocklist (check jd_text)
        jd_text = item.get("jd_text") or ""
        for pattern in self._content_patterns:
            if pattern.search(jd_text):
                logger.debug("Rejected (content): %s — %s", url, pattern.pattern)
                return self._reject(item, "content_blocklist", f"Blocked content: {pattern.pattern}")

        # 4. Salary floor
        salary_text = item.get("salary_text") or ""
        if salary_text:
            salary_k = _parse_salary_k(salary_text)
            if salary_k is not None and salary_k < self._config.min_salary_k:
                logger.debug("Rejected (salary): %s — $%dk < $%dk", url, salary_k, self._config.min_salary_k)
                return self._reject(item, "salary_floor", f"Salary ${salary_k}k below ${self._config.min_salary_k}k floor")

        return item
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_pipelines.py -v -k "filter"
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/pipelines/hard_filter.py job-scraper/tests/test_pipelines.py
git commit -m "feat(scraper-v2): hard filter pipeline — domain, title, content blocklist, salary floor"
```

---

### Task 7: Pipelines — SQLite Storage

**Files:**
- Create: `job-scraper/job_scraper/pipelines/storage.py`
- Modify: `job-scraper/tests/test_pipelines.py`

- [ ] **Step 1: Write failing test**

```python
from job_scraper.pipelines.storage import SQLitePipeline


@pytest.fixture
def storage_pipeline(tmp_path):
    db = JobDB(tmp_path / "test.db")
    return SQLitePipeline(db=db, run_id="test-run"), db


def test_stores_pending_job(storage_pipeline, spider):
    pipe, db = storage_pipeline
    item = JobItem(url="https://example.com/job/store1", title="Engineer",
                   company="Acme", board="greenhouse", source="GreenhouseSpider",
                   discovered_at="2026-01-01T00:00:00Z")
    pipe.process_item(item, spider)
    assert db.job_count() == 1


def test_stores_rejected_job(storage_pipeline, spider):
    pipe, db = storage_pipeline
    item = JobItem(url="https://example.com/job/store2", title="Staff Engineer",
                   company="Acme", board="test", source="test",
                   discovered_at="2026-01-01T00:00:00Z")
    item["status"] = "rejected"
    item["rejection_stage"] = "title_blocklist"
    item["rejection_reason"] = "staff"
    pipe.process_item(item, spider)
    rows = db.recent_jobs(limit=10)
    assert len(rows) == 1
    assert rows[0]["status"] == "rejected"
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_pipelines.py -v -k "store"
```

- [ ] **Step 3: Implement `storage.py`**

```python
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
        return cls(db=db)

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
                items_scraped=stats.get("item_scraped_count", self._stats["new"] + self._stats["filtered"]),
                items_new=self._stats["new"],
                items_filtered=self._stats["filtered"],
                errors=stats.get("log_count/ERROR", 0),
            )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_pipelines.py -v -k "store"
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/pipelines/storage.py job-scraper/tests/test_pipelines.py
git commit -m "feat(scraper-v2): SQLite storage pipeline with run tracking"
```

---

### Task 8: AshbySpider

**Files:**
- Create: `job-scraper/job_scraper/spiders/ashby.py`
- Create: `job-scraper/tests/test_ashby_spider.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for AshbySpider."""

import json
from scrapy.http import HtmlResponse, Request
from job_scraper.spiders.ashby import AshbySpider
from job_scraper.items import JobItem


def _fake_response(url, body):
    request = Request(url=url)
    return HtmlResponse(url=url, request=request, body=body, encoding="utf-8")


def test_parses_ashby_job_listing_page():
    """Ashby embeds job data as JSON. Spider should extract it."""
    spider = AshbySpider()
    spider._boards = [{"url": "https://jobs.ashbyhq.com/testco", "company": "testco"}]

    # Ashby pages embed job data in a script tag
    embedded_data = {
        "jobs": [
            {
                "title": "Security Engineer",
                "id": "abc-123",
                "location": "Remote, US",
                "departmentName": "Engineering",
            }
        ]
    }
    html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": {"pageProps": {"jobBoard": embedded_data}}})}</script></body></html>'

    response = _fake_response("https://jobs.ashbyhq.com/testco", html)
    results = list(spider.parse_board(response))

    # Should yield Requests for individual job pages
    assert len(results) > 0


def test_parses_ashby_job_detail():
    spider = AshbySpider()
    html = '<html><body><div class="ashby-job-posting-description"><p>Great opportunity for a security engineer.</p></div></body></html>'
    response = _fake_response("https://jobs.ashbyhq.com/testco/abc-123", html)
    response.meta["company"] = "testco"
    response.meta["board"] = "ashby"
    results = list(spider.parse_job(response))
    assert len(results) == 1
    item = results[0]
    assert isinstance(item, JobItem)
    assert item["company"] == "testco"
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_ashby_spider.py -v
```

- [ ] **Step 3: Implement `ashby.py`**

```python
"""Spider for Ashby job boards (jobs.ashbyhq.com)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import scrapy

from job_scraper.items import JobItem

logger = logging.getLogger(__name__)


class AshbySpider(scrapy.Spider):
    name = "ashby"

    def __init__(self, boards: list[dict] | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boards = boards or []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        boards = [
            {"url": b.url, "company": b.company}
            for b in cfg.boards if b.board_type == "ashby" and b.enabled
        ]
        return cls(boards=boards, *args, **kwargs)

    def start_requests(self):
        for board in self._boards:
            yield scrapy.Request(
                url=board["url"],
                callback=self.parse_board,
                meta={"company": board["company"]},
                dont_filter=True,
            )

    def parse_board(self, response):
        company = response.meta["company"]

        # Ashby embeds job data in __NEXT_DATA__ script
        script = response.css('script#__NEXT_DATA__::text').get()
        if script:
            try:
                data = json.loads(script)
                jobs = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("jobBoard", {})
                    .get("jobs", [])
                )
                for job in jobs:
                    job_id = job.get("id", "")
                    job_url = f"{response.url}/{job_id}"
                    yield scrapy.Request(
                        url=job_url,
                        callback=self.parse_job,
                        meta={
                            "company": company,
                            "board": "ashby",
                            "title": job.get("title", ""),
                            "location": job.get("location", ""),
                        },
                    )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to parse Ashby JSON for %s: %s", response.url, e)
                return

        # Fallback: extract links from page
        for link in response.css('a[href*="/"]::attr(href)').getall():
            if company in link and link.count("/") >= 3:
                yield scrapy.Request(
                    url=response.urljoin(link),
                    callback=self.parse_job,
                    meta={"company": company, "board": "ashby"},
                )

    def parse_job(self, response):
        company = response.meta.get("company", "unknown")

        # Extract JD HTML from the posting description div
        jd_html = response.css(".ashby-job-posting-description").get() or response.text

        # Try to get title from meta or page
        title = response.meta.get("title") or response.css("h1::text").get() or "Unknown"
        location = response.meta.get("location") or ""

        yield JobItem(
            url=response.url,
            title=title.strip(),
            company=company,
            board="ashby",
            location=location,
            jd_html=jd_html,
            source=self.name,
            discovered_at=datetime.now(timezone.utc).isoformat(),
        )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_ashby_spider.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/spiders/ashby.py job-scraper/tests/test_ashby_spider.py
git commit -m "feat(scraper-v2): AshbySpider with JSON extraction and job detail parsing"
```

---

### Task 9: GreenhouseSpider (Playwright)

**Files:**
- Create: `job-scraper/job_scraper/spiders/greenhouse.py`
- Create: `job-scraper/tests/test_greenhouse_spider.py`

**Note:** This spider uses scrapy-playwright for JS rendering. Tests use static HTML responses for unit testing; integration testing against live boards is Task 14.

- [ ] **Step 1: Write failing test**

```python
"""Tests for GreenhouseSpider."""

from scrapy.http import HtmlResponse, Request
from job_scraper.spiders.greenhouse import GreenhouseSpider
from job_scraper.items import JobItem


def _fake_response(url, body):
    request = Request(url=url)
    return HtmlResponse(url=url, request=request, body=body, encoding="utf-8")


def test_parses_greenhouse_job_list():
    spider = GreenhouseSpider()
    spider._boards = [{"url": "https://job-boards.greenhouse.io/testco", "company": "testco"}]

    html = '''<html><body>
    <div class="opening"><a href="https://job-boards.greenhouse.io/testco/jobs/12345">Security Engineer</a>
    <span class="location">Remote</span></div>
    <div class="opening"><a href="https://job-boards.greenhouse.io/testco/jobs/67890">Platform Engineer</a>
    <span class="location">New York, NY</span></div>
    </body></html>'''

    response = _fake_response("https://job-boards.greenhouse.io/testco", html)
    response.meta["company"] = "testco"
    results = list(spider.parse_board(response))
    assert len(results) == 2  # Two requests for job detail pages


def test_parses_greenhouse_job_detail():
    spider = GreenhouseSpider()
    html = '<html><body><div id="content"><h1>Security Engineer</h1><div class="job-post-content"><p>Join our team.</p></div></div></body></html>'
    response = _fake_response("https://job-boards.greenhouse.io/testco/jobs/12345", html)
    response.meta["company"] = "testco"
    response.meta["board"] = "greenhouse"
    results = list(spider.parse_job(response))
    assert len(results) == 1
    item = results[0]
    assert isinstance(item, JobItem)
    assert item["board"] == "greenhouse"
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_greenhouse_spider.py -v
```

- [ ] **Step 3: Implement `greenhouse.py`**

```python
"""Spider for Greenhouse job boards (job-boards.greenhouse.io).

Uses scrapy-playwright to render JS-heavy career SPAs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import scrapy

from job_scraper.items import JobItem

logger = logging.getLogger(__name__)


class GreenhouseSpider(scrapy.Spider):
    name = "greenhouse"

    def __init__(self, boards: list[dict] | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boards = boards or []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        boards = [
            {"url": b.url, "company": b.company}
            for b in cfg.boards if b.board_type == "greenhouse" and b.enabled
        ]
        return cls(boards=boards, *args, **kwargs)

    def start_requests(self):
        for board in self._boards:
            yield scrapy.Request(
                url=board["url"],
                callback=self.parse_board,
                meta={
                    "company": board["company"],
                    "playwright": True,
                    "playwright_include_page": False,
                    "playwright_page_methods": [
                        {"method": "wait_for_timeout", "args": [3000]},
                    ],
                },
                dont_filter=True,
            )

    def parse_board(self, response):
        company = response.meta.get("company", "unknown")

        # Greenhouse job listings have links with /jobs/ pattern
        for link in response.css('a[href*="/jobs/"]::attr(href)').getall():
            full_url = response.urljoin(link)
            if "/jobs/" in full_url:
                yield scrapy.Request(
                    url=full_url,
                    callback=self.parse_job,
                    meta={
                        "company": company,
                        "board": "greenhouse",
                        "playwright": True,
                        "playwright_include_page": False,
                        "playwright_page_methods": [
                            {"method": "wait_for_timeout", "args": [2000]},
                        ],
                    },
                )

    def parse_job(self, response):
        company = response.meta.get("company", "unknown")
        title = response.css("h1::text").get() or "Unknown"
        jd_html = (
            response.css(".job-post-content").get()
            or response.css("#content").get()
            or response.text
        )
        location = response.css(".location::text").get() or ""

        yield JobItem(
            url=response.url,
            title=title.strip(),
            company=company,
            board="greenhouse",
            location=location.strip(),
            jd_html=jd_html,
            source=self.name,
            discovered_at=datetime.now(timezone.utc).isoformat(),
        )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_greenhouse_spider.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/spiders/greenhouse.py job-scraper/tests/test_greenhouse_spider.py
git commit -m "feat(scraper-v2): GreenhouseSpider with Playwright JS rendering"
```

---

### Task 10: LeverSpider (Playwright + Stealth)

**Files:**
- Create: `job-scraper/job_scraper/spiders/lever.py`
- Create: `job-scraper/tests/test_lever_spider.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for LeverSpider."""

from scrapy.http import HtmlResponse, Request
from job_scraper.spiders.lever import LeverSpider
from job_scraper.items import JobItem


def _fake_response(url, body):
    request = Request(url=url)
    return HtmlResponse(url=url, request=request, body=body, encoding="utf-8")


def test_parses_lever_job_list():
    spider = LeverSpider()
    spider._boards = [{"url": "https://jobs.lever.co/testco", "company": "testco"}]
    html = '''<html><body>
    <div class="posting"><a class="posting-title" href="https://jobs.lever.co/testco/abc-def-123">
    <h5>Security Engineer</h5><span class="sort-by-location">Remote</span></a></div>
    </body></html>'''

    response = _fake_response("https://jobs.lever.co/testco", html)
    response.meta["company"] = "testco"
    results = list(spider.parse_board(response))
    assert len(results) >= 1


def test_parses_lever_job_detail():
    spider = LeverSpider()
    html = '<html><body><div class="posting-headline"><h2>Security Engineer</h2></div><div class="posting-page-content"><p>Join us.</p></div></body></html>'
    response = _fake_response("https://jobs.lever.co/testco/abc-def-123", html)
    response.meta["company"] = "testco"
    response.meta["board"] = "lever"
    results = list(spider.parse_job(response))
    assert len(results) == 1
    assert results[0]["board"] == "lever"
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_lever_spider.py -v
```

- [ ] **Step 3: Implement `lever.py`**

```python
"""Spider for Lever job boards (jobs.lever.co).

Uses scrapy-playwright with stealth to bypass headless detection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import scrapy

from job_scraper.items import JobItem

logger = logging.getLogger(__name__)


class LeverSpider(scrapy.Spider):
    name = "lever"

    # Playwright context kwargs for stealth
    custom_settings = {
        "PLAYWRIGHT_CONTEXTS": {
            "lever": {
                "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "viewport": {"width": 1920, "height": 1080},
                "java_script_enabled": True,
            }
        }
    }

    def __init__(self, boards: list[dict] | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boards = boards or []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        boards = [
            {"url": b.url, "company": b.company}
            for b in cfg.boards if b.board_type == "lever" and b.enabled
        ]
        return cls(boards=boards, *args, **kwargs)

    def start_requests(self):
        for board in self._boards:
            yield scrapy.Request(
                url=board["url"],
                callback=self.parse_board,
                meta={
                    "company": board["company"],
                    "playwright": True,
                    "playwright_context": "lever",
                    "playwright_include_page": False,
                    "playwright_page_methods": [
                        {"method": "wait_for_timeout", "args": [3000]},
                    ],
                },
                dont_filter=True,
            )

    def parse_board(self, response):
        company = response.meta.get("company", "unknown")

        for link in response.css('a.posting-title::attr(href)').getall():
            full_url = response.urljoin(link)
            yield scrapy.Request(
                url=full_url,
                callback=self.parse_job,
                meta={
                    "company": company,
                    "board": "lever",
                    "playwright": True,
                    "playwright_context": "lever",
                    "playwright_include_page": False,
                    "playwright_page_methods": [
                        {"method": "wait_for_timeout", "args": [2000]},
                    ],
                },
            )

        # Fallback: generic link extraction
        if not response.css('a.posting-title').getall():
            for link in response.css('a[href*="/"]::attr(href)').getall():
                full_url = response.urljoin(link)
                if company in full_url and full_url.count("/") >= 4:
                    yield scrapy.Request(
                        url=full_url,
                        callback=self.parse_job,
                        meta={"company": company, "board": "lever",
                              "playwright": True, "playwright_context": "lever"},
                    )

    def parse_job(self, response):
        company = response.meta.get("company", "unknown")
        title = (
            response.css(".posting-headline h2::text").get()
            or response.css("h1::text").get()
            or "Unknown"
        )
        jd_html = (
            response.css(".posting-page-content").get()
            or response.css(".content").get()
            or response.text
        )
        location = response.css(".sort-by-location::text").get() or ""

        yield JobItem(
            url=response.url,
            title=title.strip(),
            company=company,
            board="lever",
            location=location.strip(),
            jd_html=jd_html,
            source=self.name,
            discovered_at=datetime.now(timezone.utc).isoformat(),
        )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_lever_spider.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/spiders/lever.py job-scraper/tests/test_lever_spider.py
git commit -m "feat(scraper-v2): LeverSpider with Playwright stealth context"
```

---

### Task 11: USAJobsSpider

**Files:**
- Create: `job-scraper/job_scraper/spiders/usajobs.py`
- Create: `job-scraper/tests/test_usajobs_spider.py`

Ports existing `usajobs.py` logic into a Scrapy spider using httpx for API calls.

- [ ] **Step 1: Write failing test**

```python
"""Tests for USAJobsSpider."""

import json
from unittest.mock import patch, MagicMock
from job_scraper.spiders.usajobs import USAJobsSpider
from job_scraper.items import JobItem


def test_parses_api_response():
    spider = USAJobsSpider()
    # Simulate API JSON structure
    api_data = {
        "SearchResult": {
            "SearchResultItems": [
                {
                    "MatchedObjectDescriptor": {
                        "PositionTitle": "IT Specialist (Security)",
                        "PositionURI": "https://www.usajobs.gov/job/123456",
                        "PositionLocationDisplay": "Remote",
                        "OrganizationName": "NASA",
                        "PositionRemuneration": [{"MinimumRange": "90000", "MaximumRange": "120000"}],
                        "QualificationSummary": "Looking for cybersecurity specialist...",
                        "UserArea": {"Details": {"MajorDuties": ["Perform security assessments"]}},
                    }
                }
            ]
        }
    }
    items = list(spider._parse_results(api_data))
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, JobItem)
    assert item["board"] == "usajobs"
    assert "NASA" in item["company"]
    assert item["salary_text"]
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_usajobs_spider.py -v
```

- [ ] **Step 3: Implement `usajobs.py`**

```python
"""Spider for USAJobs API (data.usajobs.gov)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx
import scrapy

from job_scraper.items import JobItem

logger = logging.getLogger(__name__)

_BASE_URL = "https://data.usajobs.gov/api/search"


class USAJobsSpider(scrapy.Spider):
    name = "usajobs"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._api_key = os.environ.get("USAJOBS_API_KEY", "")
        self._email = os.environ.get("USAJOBS_EMAIL", "")

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        return cls(*args, **kwargs)

    def start_requests(self):
        # USAJobs is API-based, so we use a dummy request to trigger parse
        from job_scraper.config import load_config
        cfg = load_config()

        if not self._api_key:
            logger.warning("USAJOBS_API_KEY not set, skipping USAJobs spider")
            return

        for keyword in cfg.usajobs.keywords:
            yield scrapy.Request(
                url=f"{_BASE_URL}?Keyword={keyword}&ResultsPerPage=100"
                    + ("&RemoteIndicator=true" if cfg.usajobs.remote else ""),
                callback=self.parse_api,
                meta={"keyword": keyword, "dont_redirect": True},
                headers={
                    "Authorization-Key": self._api_key,
                    "User-Agent": self._email,
                    "Host": "data.usajobs.gov",
                },
                dont_filter=True,
            )

    def parse_api(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Failed to parse USAJobs response for %s", response.url)
            return
        yield from self._parse_results(data)

    def _parse_results(self, data: dict):
        items = (
            data.get("SearchResult", {})
            .get("SearchResultItems", [])
        )
        for item in items:
            desc = item.get("MatchedObjectDescriptor", {})
            title = desc.get("PositionTitle", "Unknown")
            url = desc.get("PositionURI", "")
            org = desc.get("OrganizationName", "USGov")
            location = desc.get("PositionLocationDisplay", "")

            # Salary
            remuneration = desc.get("PositionRemuneration", [])
            salary_text = ""
            if remuneration:
                r = remuneration[0]
                salary_text = f"${r.get('MinimumRange', '')} - ${r.get('MaximumRange', '')}"

            # JD text from qualification summary + major duties
            qual = desc.get("QualificationSummary", "")
            duties = desc.get("UserArea", {}).get("Details", {}).get("MajorDuties", [])
            jd_text = qual + "\n\n" + "\n".join(duties) if duties else qual

            yield JobItem(
                url=url,
                title=title,
                company=org,
                board="usajobs",
                location=location,
                salary_text=salary_text,
                jd_text=jd_text,
                source=self.name,
                discovered_at=datetime.now(timezone.utc).isoformat(),
            )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_usajobs_spider.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/spiders/usajobs.py job-scraper/tests/test_usajobs_spider.py
git commit -m "feat(scraper-v2): USAJobsSpider with API-based discovery"
```

---

### Task 12: SearXNGSpider (Optional)

**Files:**
- Create: `job-scraper/job_scraper/spiders/searxng.py`
- Create: `job-scraper/tests/test_searxng_spider.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for SearXNGSpider."""

import json
from scrapy.http import TextResponse, Request
from job_scraper.spiders.searxng import SearXNGSpider
from job_scraper.items import JobItem


def _fake_json_response(url, data):
    request = Request(url=url)
    body = json.dumps(data).encode()
    return TextResponse(url=url, request=request, body=body, encoding="utf-8")


def test_parses_searxng_results():
    spider = SearXNGSpider()
    data = {
        "results": [
            {
                "url": "https://jobs.ashbyhq.com/testco/abc123",
                "title": "Security Engineer - TestCo",
                "content": "Great security role...",
            },
            {
                "url": "https://job-boards.greenhouse.io/acme/jobs/456",
                "title": "Platform Engineer",
                "content": "Cloud platform role...",
            },
        ]
    }
    response = _fake_json_response("http://localhost:8888/search?q=test&format=json", data)
    response.meta["query_phrase"] = "security engineer"
    results = list(spider.parse_results(response))
    # Should yield JobItems with jd_html=None (SearXNG doesn't have it) and follow-up requests
    assert len(results) >= 2


def test_skips_blocklisted_urls():
    spider = SearXNGSpider()
    spider._domain_blocklist = {"wikipedia.org"}
    data = {
        "results": [
            {"url": "https://en.wikipedia.org/wiki/Security", "title": "Security", "content": "..."},
        ]
    }
    response = _fake_json_response("http://localhost:8888/search?q=test&format=json", data)
    response.meta["query_phrase"] = "test"
    results = list(spider.parse_results(response))
    assert len(results) == 0
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_searxng_spider.py -v
```

- [ ] **Step 3: Implement `searxng.py`**

```python
"""Spider for SearXNG search engine (optional discovery source)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urlencode

import scrapy

from job_scraper.items import JobItem

logger = logging.getLogger(__name__)


class SearXNGSpider(scrapy.Spider):
    name = "searxng"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._searxng_url = "http://localhost:8888/search"
        self._queries = []
        self._domain_blocklist = set()

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        spider = cls(*args, **kwargs)
        spider._searxng_url = cfg.searxng.url
        spider._queries = cfg.queries
        spider._domain_blocklist = set(cfg.hard_filters.domain_blocklist)
        return spider

    def start_requests(self):
        for query in self._queries:
            q_parts = []
            if query.board_site:
                q_parts.append(f"site:{query.board_site}")
            q_parts.append(f'"{query.title_phrase}"')
            if query.suffix:
                q_parts.append(query.suffix)
            q_str = " ".join(q_parts)

            params = urlencode({"q": q_str, "format": "json"})
            yield scrapy.Request(
                url=f"{self._searxng_url}?{params}",
                callback=self.parse_results,
                meta={"query_phrase": query.title_phrase},
                dont_filter=True,
                errback=self.errback_searxng,
            )

    def parse_results(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("SearXNG returned non-JSON: %s", response.url)
            return

        query_phrase = response.meta.get("query_phrase", "")

        for result in data.get("results", []):
            url = result.get("url", "")
            if not url:
                continue

            # Skip blocklisted domains
            host = urlparse(url).netloc.lower()
            if any(bl in host for bl in self._domain_blocklist):
                continue

            title = result.get("title", "Unknown")
            snippet = result.get("content", "")

            # Best-effort company extraction from URL
            parsed = urlparse(url)
            path_parts = [p for p in parsed.path.strip("/").split("/") if p]
            company = path_parts[0] if path_parts else parsed.netloc.split(".")[0]

            # Determine board type from URL
            board = "unknown"
            if "ashbyhq.com" in host:
                board = "ashby"
            elif "greenhouse.io" in host:
                board = "greenhouse"
            elif "lever.co" in host:
                board = "lever"
            elif "usajobs.gov" in host:
                board = "usajobs"

            # Follow the URL to get full JD HTML (don't yield a partial item here)
            yield scrapy.Request(
                url=url,
                callback=self.parse_job_page,
                meta={"item_url": url, "item_title": title, "item_company": company,
                      "item_board": board, "item_snippet": snippet, "item_query": query_phrase},
                priority=-1,  # Lower priority than direct board crawling
            )

    def parse_job_page(self, response):
        """Follow-up: fetch the actual job page for JD HTML."""
        yield JobItem(
            url=response.meta["item_url"],
            title=response.meta["item_title"],
            company=response.meta["item_company"],
            board=response.meta["item_board"],
            snippet=response.meta["item_snippet"],
            query=response.meta["item_query"],
            jd_html=response.text,
            source=self.name,
            discovered_at=datetime.now(timezone.utc).isoformat(),
        )

    def errback_searxng(self, failure):
        logger.warning("SearXNG request failed (service may be down): %s", failure.value)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_searxng_spider.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/spiders/searxng.py job-scraper/tests/test_searxng_spider.py
git commit -m "feat(scraper-v2): SearXNGSpider as optional search discovery source"
```

---

### Task 13: AggregatorSpider (SimplyHired)

**Files:**
- Create: `job-scraper/job_scraper/spiders/aggregator.py`
- Create: `job-scraper/tests/test_aggregator_spider.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for AggregatorSpider."""

from scrapy.http import HtmlResponse, Request
from job_scraper.spiders.aggregator import AggregatorSpider
from job_scraper.items import JobItem


def _fake_response(url, body):
    request = Request(url=url)
    return HtmlResponse(url=url, request=request, body=body, encoding="utf-8")


def test_parses_simplyhired_results():
    spider = AggregatorSpider()
    html = '''<html><body>
    <article class="SerpJob"><a class="SerpJob-link card-link" href="/job/abc123" data-mdref="test">
    <h2 class="jobposting-title">Security Engineer</h2></a>
    <span class="jobposting-company">Acme Corp</span>
    <span class="jobposting-location">Remote</span>
    </article>
    </body></html>'''

    response = _fake_response("https://www.simplyhired.com/search?q=security+engineer", html)
    results = list(spider.parse_board(response))
    assert len(results) >= 1
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_aggregator_spider.py -v
```

- [ ] **Step 3: Implement `aggregator.py`**

```python
"""Spider for job aggregator sites (SimplyHired, etc.)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import scrapy

from job_scraper.items import JobItem

logger = logging.getLogger(__name__)


class AggregatorSpider(scrapy.Spider):
    name = "aggregator"

    def __init__(self, boards: list[dict] | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boards = boards or []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        boards = [
            {"url": b.url, "company": b.company, "board_type": b.board_type}
            for b in cfg.boards if b.board_type == "simplyhired" and b.enabled
        ]
        return cls(boards=boards, *args, **kwargs)

    def start_requests(self):
        for board in self._boards:
            yield scrapy.Request(
                url=board["url"],
                callback=self.parse_board,
                meta={
                    "playwright": True,
                    "playwright_include_page": False,
                    "playwright_page_methods": [
                        {"method": "wait_for_timeout", "args": [3000]},
                    ],
                },
                dont_filter=True,
            )

    def parse_board(self, response):
        # SimplyHired structure
        for article in response.css("article.SerpJob, li.SerpJob"):
            link = article.css("a.SerpJob-link::attr(href), a.card-link::attr(href)").get()
            title = article.css("h2.jobposting-title::text, h2::text").get() or "Unknown"
            company = article.css(".jobposting-company::text, .company::text").get() or "Unknown"
            location = article.css(".jobposting-location::text, .location::text").get() or ""

            if link:
                full_url = response.urljoin(link)
                yield scrapy.Request(
                    url=full_url,
                    callback=self.parse_job,
                    meta={
                        "title": title.strip(),
                        "company": company.strip(),
                        "location": location.strip(),
                        "playwright": True,
                        "playwright_include_page": False,
                    },
                )

        # Fallback: generic link extraction
        if not response.css("article.SerpJob, li.SerpJob"):
            for link in response.css('a[href*="/job/"]::attr(href)').getall():
                yield scrapy.Request(
                    url=response.urljoin(link),
                    callback=self.parse_job,
                    meta={"playwright": True},
                )

    def parse_job(self, response):
        title = response.meta.get("title") or response.css("h1::text").get() or "Unknown"
        company = response.meta.get("company") or "Unknown"
        location = response.meta.get("location") or ""
        jd_html = response.css(".viewjob-description, .job-description, #content").get() or response.text

        yield JobItem(
            url=response.url,
            title=title.strip(),
            company=company.strip(),
            board="simplyhired",
            location=location,
            jd_html=jd_html,
            source=self.name,
            discovered_at=datetime.now(timezone.utc).isoformat(),
        )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_aggregator_spider.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/spiders/aggregator.py job-scraper/tests/test_aggregator_spider.py
git commit -m "feat(scraper-v2): AggregatorSpider for SimplyHired with Playwright"
```

---

### Task 14: CLI Entry Point

**Files:**
- Rewrite: `job-scraper/job_scraper/__main__.py`
- Rewrite: `job-scraper/job_scraper/__init__.py`

- [ ] **Step 1: Read current `__main__.py`**

```bash
cat job-scraper/job_scraper/__main__.py
```

- [ ] **Step 2: Rewrite `__init__.py` as minimal package init**

```python
"""job_scraper — Job discovery via Scrapy + Playwright."""

__version__ = "2.0.0"
```

- [ ] **Step 3: Rewrite `__main__.py` with Scrapy CLI wrapper**

```python
"""CLI entry point for job_scraper v2."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Job discovery via Scrapy + Playwright")
console = Console()


@app.command()
def scrape(
    spider: str = typer.Option("", "-s", "--spider", help="Run a specific spider (ashby, greenhouse, lever, usajobs, searxng, aggregator)"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
):
    """Run the scraping pipeline."""
    from scrapy.crawler import CrawlerProcess
    from scrapy.utils.project import get_project_settings

    settings = get_project_settings()
    if verbose:
        settings.set("LOG_LEVEL", "DEBUG")

    process = CrawlerProcess(settings)

    if spider:
        # Run a single spider by name
        process.crawl(spider)
    else:
        # Run all spiders
        from job_scraper.spiders.ashby import AshbySpider
        from job_scraper.spiders.greenhouse import GreenhouseSpider
        from job_scraper.spiders.lever import LeverSpider
        from job_scraper.spiders.usajobs import USAJobsSpider
        from job_scraper.spiders.searxng import SearXNGSpider
        from job_scraper.spiders.aggregator import AggregatorSpider

        for spider_cls in [AshbySpider, GreenhouseSpider, LeverSpider,
                           USAJobsSpider, SearXNGSpider, AggregatorSpider]:
            process.crawl(spider_cls)

    process.start()


@app.command()
def stats():
    """Show database statistics."""
    from job_scraper.db import JobDB

    db = JobDB()
    total = db.job_count()
    pending = db.job_count(status="pending")
    approved = db.job_count(status="qa_approved")
    rejected = db.job_count(status="rejected")

    table = Table(title="Job Scraper Stats")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Total jobs", str(total))
    table.add_row("Pending QA", str(pending))
    table.add_row("QA Approved", str(approved))
    table.add_row("Rejected", str(rejected))
    console.print(table)
    db.close()


@app.command()
def recent(n: int = typer.Option(20, "-n", help="Number of recent jobs to show")):
    """Show recent jobs."""
    from job_scraper.db import JobDB

    db = JobDB()
    jobs = db.recent_jobs(limit=n)
    table = Table(title=f"Recent {n} Jobs")
    table.add_column("ID", style="dim")
    table.add_column("Title")
    table.add_column("Company")
    table.add_column("Board")
    table.add_column("Status")
    for job in jobs:
        table.add_row(
            str(job["id"]),
            job["title"][:50],
            job["company"],
            job.get("board", ""),
            job.get("status", "pending"),
        )
    console.print(table)
    db.close()


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Test CLI loads**

```bash
cd /Users/conner/Documents/JobForge/job-scraper
python -m job_scraper stats
```

Expected: Table output (possibly 0 jobs if using fresh DB)

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/__init__.py job-scraper/job_scraper/__main__.py
git commit -m "feat(scraper-v2): CLI entry point wrapping Scrapy CrawlerProcess"
```

---

### Task 15: Prototype Playwright Against Live Boards

**Note:** This is a validation task — test scrapy-playwright against the boards that Crawl4AI couldn't handle. Results determine whether Greenhouse/Lever spiders work or need aggregator-only fallback.

- [ ] **Step 1: Install Playwright browsers**

```bash
playwright install chromium
```

- [ ] **Step 2: Test GreenhouseSpider against one live board**

```bash
cd /Users/conner/Documents/JobForge/job-scraper
python -c "
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from job_scraper.spiders.greenhouse import GreenhouseSpider

settings = get_project_settings()
settings.set('LOG_LEVEL', 'DEBUG')
settings.set('CLOSESPIDER_ITEMCOUNT', 3)

process = CrawlerProcess(settings)
process.crawl(GreenhouseSpider, boards=[{'url': 'https://job-boards.greenhouse.io/bitwarden', 'company': 'bitwarden'}])
process.start()
"
```

Document: did it find job listings? Did Playwright render the JS SPA? Note results.

- [ ] **Step 3: Test LeverSpider against one live board**

```bash
python -c "
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from job_scraper.spiders.lever import LeverSpider

settings = get_project_settings()
settings.set('LOG_LEVEL', 'DEBUG')
settings.set('CLOSESPIDER_ITEMCOUNT', 3)

process = CrawlerProcess(settings)
process.crawl(LeverSpider, boards=[{'url': 'https://jobs.lever.co/spotify', 'company': 'spotify'}])
process.start()
"
```

Document results.

- [ ] **Step 4: If any spider fails, update config to mark those boards as aggregator-only**

Add `enabled: false` to failing board targets in config, and document which boards require SearXNG/aggregator discovery.

- [ ] **Step 5: Commit any config changes**

```bash
git add -A
git commit -m "chore(scraper-v2): document Playwright board compatibility results"
```

---

### Task 15.5: GenericSpider (RSS/Static HTML)

**Files:**
- Create: `job-scraper/job_scraper/spiders/generic.py`
- Create: `job-scraper/tests/test_generic_spider.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for GenericSpider."""

from scrapy.http import HtmlResponse, TextResponse, Request
from job_scraper.spiders.generic import GenericSpider
from job_scraper.items import JobItem


def _fake_response(url, body, cls=HtmlResponse):
    request = Request(url=url)
    return cls(url=url, request=request, body=body, encoding="utf-8")


def test_parses_static_html_job_list():
    spider = GenericSpider()
    html = '''<html><body>
    <a href="/careers/security-engineer">Security Engineer</a>
    <a href="/careers/platform-engineer">Platform Engineer</a>
    </body></html>'''
    response = _fake_response("https://careers.example.com/jobs", html)
    response.meta["company"] = "example"
    response.meta["board"] = "generic"
    results = list(spider.parse_board(response))
    assert len(results) >= 2


def test_parses_rss_feed():
    spider = GenericSpider()
    rss = '''<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Jobs</title>
    <item><title>Security Engineer</title><link>https://example.com/job/1</link>
    <description>Great role</description></item>
    </channel></rss>'''
    response = _fake_response("https://example.com/jobs.rss", rss.encode(), cls=TextResponse)
    results = list(spider.parse_rss(response))
    assert len(results) == 1
    assert results[0]["title"] == "Security Engineer"
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_generic_spider.py -v
```

- [ ] **Step 3: Implement `generic.py`**

```python
"""Spider for RSS feeds and static HTML job boards."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import scrapy

from job_scraper.items import JobItem

logger = logging.getLogger(__name__)


class GenericSpider(scrapy.Spider):
    name = "generic"

    def __init__(self, boards: list[dict] | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boards = boards or []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        boards = [
            {"url": b.url, "company": b.company, "board_type": b.board_type}
            for b in cfg.boards if b.board_type == "generic" and b.enabled
        ]
        return cls(boards=boards, *args, **kwargs)

    def start_requests(self):
        for board in self._boards:
            url = board["url"]
            callback = self.parse_rss if url.endswith((".rss", ".xml", "/feed")) else self.parse_board
            yield scrapy.Request(
                url=url,
                callback=callback,
                meta={"company": board["company"], "board": "generic"},
                dont_filter=True,
            )

    def parse_board(self, response):
        company = response.meta.get("company", "unknown")
        for link in response.css('a[href*="job"], a[href*="career"], a[href*="position"]::attr(href)').getall():
            yield scrapy.Request(
                url=response.urljoin(link),
                callback=self.parse_job,
                meta={"company": company, "board": "generic"},
            )

    def parse_rss(self, response):
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            logger.warning("Failed to parse RSS: %s", response.url)
            return
        for item in root.iter("item"):
            title = item.findtext("title", "Unknown")
            url = item.findtext("link", "")
            description = item.findtext("description", "")
            if url:
                yield JobItem(
                    url=url,
                    title=title,
                    company=response.meta.get("company", "unknown"),
                    board="generic",
                    snippet=description,
                    jd_html=description,
                    source=self.name,
                    discovered_at=datetime.now(timezone.utc).isoformat(),
                )

    def parse_job(self, response):
        company = response.meta.get("company", "unknown")
        title = response.css("h1::text").get() or "Unknown"
        jd_html = response.css(".job-description, .content, main").get() or response.text

        yield JobItem(
            url=response.url,
            title=title.strip(),
            company=company,
            board="generic",
            jd_html=jd_html,
            source=self.name,
            discovered_at=datetime.now(timezone.utc).isoformat(),
        )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_generic_spider.py -v
```

Expected: All PASS

- [ ] **Step 5: Update CLI to include GenericSpider**

In `__main__.py`, add `from job_scraper.spiders.generic import GenericSpider` and include it in the "run all spiders" list.

- [ ] **Step 6: Commit**

```bash
git add job-scraper/job_scraper/spiders/generic.py job-scraper/tests/test_generic_spider.py job-scraper/job_scraper/__main__.py
git commit -m "feat(scraper-v2): GenericSpider for RSS feeds and static HTML boards"
```

---

### Task 16: Dashboard Integration — Update Scraping Handlers

**Files:**
- Modify: `job-scraper/api/scraping_handlers.py`
- Modify: `dashboard/backend/routers/scraping.py` (if needed)

- [ ] **Step 1: Read current scraping_handlers.py fully**

```bash
cat job-scraper/api/scraping_handlers.py
```

- [ ] **Step 2: Update SQL queries from `results` to `jobs`, `decision` to `status`**

Replace all raw SQL references:
- `FROM results` → `FROM jobs`
- `decision` column → `status` column
- `filtered_count` → `items_filtered`
- Any column references that changed in the new schema

Use the `results` view as fallback where complex queries are hard to migrate.

- [ ] **Step 3: Test dashboard backend starts**

```bash
cd /Users/conner/Documents/JobForge
source venv/bin/activate
python -c "from dashboard.backend.app import app; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add job-scraper/api/scraping_handlers.py
git commit -m "feat(scraper-v2): update scraping handlers for new jobs table schema"
```

---

### Task 17: Tailoring Integration — Update Selector

**Files:**
- Modify: `tailoring/tailor/selector.py`

- [ ] **Step 1: Read current selector.py**

Already read. Key changes:
- Query `jobs` instead of `results`
- `decision = 'qa_approved'` → `status = 'qa_approved'`
- Remove `_parse_company()` — `company` is now a direct column
- Use `COALESCE(approved_jd_text, jd_text)` (unchanged, column exists in new schema)

- [ ] **Step 2: Update selector.py**

```python
# In select_job():
# Change: "FROM results WHERE id = ?" → "FROM jobs WHERE id = ?"
# Change: list_recent_jobs query to use jobs table
# Remove: _parse_company() function — company comes from column
# In SelectedJob: company field populated directly from row["company"]
```

- [ ] **Step 3: Run existing tailoring tests**

```bash
cd /Users/conner/Documents/JobForge/tailoring
python -m pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add tailoring/tailor/selector.py
git commit -m "feat(scraper-v2): update tailoring selector for jobs table schema"
```

---

### Task 17.5: Dashboard Services & Router SQL Updates

**Files:**
- Modify: `dashboard/backend/services/tailoring.py`
- Modify: `dashboard/backend/services/ops.py`
- Modify: `dashboard/backend/routers/tailoring.py`

These files contain raw SQL referencing the `results` table. The compatibility view prevents immediate breakage, but all references should be migrated to `jobs`.

- [ ] **Step 1: Grep for all `results` table references in dashboard backend**

```bash
grep -rn "FROM results\|INTO results\|UPDATE results\|results WHERE\|results SET\|results AS\|JOIN results" dashboard/backend/ --include="*.py"
```

- [ ] **Step 2: Update each file — change `results` to `jobs` and `decision` to `status`**

For each file, replace:
- `FROM results` → `FROM jobs`
- `INTO results` → `INTO jobs`
- `UPDATE results` → `UPDATE jobs`
- Column `decision` → `status` in WHERE clauses and SELECT lists
- Keep the `results` view reference in `db.py` as fallback

- [ ] **Step 3: Test dashboard backend starts and basic endpoints work**

```bash
cd /Users/conner/Documents/JobForge
python -c "
from dashboard.backend.app import app
print('App loaded OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/backend/services/tailoring.py dashboard/backend/services/ops.py dashboard/backend/routers/tailoring.py
git commit -m "feat(scraper-v2): migrate dashboard services from results to jobs table"
```

---

### Task 17.75: Data Migration Script

**Files:**
- Create: `job-scraper/scripts/migrate_v1_to_v2.py`

- [ ] **Step 1: Write migration script**

```python
"""One-time migration: copy results → jobs table for scraper v2.

Deduplicates by URL (keeps most recent row), maps decision → status,
preserves approved_jd_text if it exists.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path.home() / ".local" / "share" / "job_scraper" / "jobs.db"


def migrate(db_path: Path = DB_PATH):
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row

    # Check if old results table exists (not the view)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    if "results" not in tables:
        print("No 'results' table found — nothing to migrate.")
        return

    if "jobs" in tables:
        existing = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        if existing > 0:
            print(f"'jobs' table already has {existing} rows — skipping migration.")
            return

    # Check for approved_jd_text column
    cols = {r[1] for r in conn.execute("PRAGMA table_info(results)")}
    has_approved_jd = "approved_jd_text" in cols

    approved_col = ", approved_jd_text" if has_approved_jd else ""
    approved_val = ", approved_jd_text" if has_approved_jd else ""

    # Deduplicate by URL, keep most recent row
    query = f"""
    INSERT OR IGNORE INTO jobs (
        url, title, company, board, jd_text{approved_col}, snippet, source, status,
        run_id, discovered_at, updated_at
    )
    SELECT
        url, title,
        COALESCE(board, 'unknown') as company,
        board,
        jd_text{approved_val},
        snippet,
        COALESCE(source, 'migrated') as source,
        CASE
            WHEN decision = 'qa_approved' THEN 'qa_approved'
            WHEN decision = 'accepted' THEN 'pending'
            WHEN decision = 'manual' THEN 'pending'
            ELSE 'pending'
        END as status,
        run_id,
        created_at as discovered_at,
        created_at as updated_at
    FROM results
    WHERE rowid IN (
        SELECT MAX(rowid) FROM results GROUP BY url
    )
    """

    cursor = conn.execute(query)
    conn.commit()
    print(f"Migrated {cursor.rowcount} rows from results → jobs")
    conn.close()


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH
    migrate(path)
```

- [ ] **Step 2: Test migration with a copy of the DB**

```bash
cp ~/.local/share/job_scraper/jobs.db /tmp/test_migrate.db
python job-scraper/scripts/migrate_v1_to_v2.py /tmp/test_migrate.db
```

- [ ] **Step 3: Commit**

```bash
git add job-scraper/scripts/migrate_v1_to_v2.py
git commit -m "feat(scraper-v2): one-time data migration script results → jobs"
```

---

### Task 18: Full Integration Test

- [ ] **Step 1: Run all unit tests**

```bash
cd /Users/conner/Documents/JobForge/job-scraper
python -m pytest tests/ -v
```

Expected: All PASS

- [ ] **Step 2: Run a full scrape with one spider**

```bash
python -m job_scraper scrape -s ashby -v
```

Verify: Jobs appear in DB, stats command shows them.

- [ ] **Step 3: Check dashboard can read new data**

```bash
cd /Users/conner/Documents/JobForge
python dashboard/backend/server.py &
sleep 3
curl -s http://localhost:8899/api/overview | python -m json.tool
curl -s http://localhost:8899/api/jobs | python -m json.tool | head -20
kill %1
```

- [ ] **Step 4: Run full scrape (all spiders)**

```bash
cd /Users/conner/Documents/JobForge/job-scraper
python -m job_scraper scrape -v
```

Watch for errors, verify stats.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix(scraper-v2): integration test fixes"
```

---

### Task 19: Cleanup Old Code

**Only after Tasks 1-18 pass.**

- [ ] **Step 1: Remove old modules that are fully replaced**

Files to remove (verify each is no longer imported anywhere):
- `job-scraper/job_scraper/searcher.py`
- `job-scraper/job_scraper/crawler.py`
- `job-scraper/job_scraper/fetcher.py`
- `job-scraper/job_scraper/filters.py`
- `job-scraper/job_scraper/llm_reviewer.py`
- `job-scraper/job_scraper/urlnorm.py`
- `job-scraper/job_scraper/models.py`
- `job-scraper/job_scraper/runtime_controls.py`
- `job-scraper/job_scraper/watchers.py`
- `job-scraper/job_scraper/dedup.py` (replaced by `db.py`)

**Do NOT remove** until grep confirms no imports remain:

```bash
grep -r "from.*searcher\|from.*crawler\|from.*fetcher\|from.*filters\|from.*llm_reviewer\|from.*urlnorm\|from.*models\|from.*runtime_controls\|from.*watchers\|from.*dedup" --include="*.py" .
```

- [ ] **Step 2: Remove old usajobs.py (replaced by spider)**

```bash
rm job-scraper/job_scraper/usajobs.py
```

- [ ] **Step 3: Verify nothing is broken**

```bash
cd /Users/conner/Documents/JobForge/job-scraper
python -m pytest tests/ -v
python -m job_scraper stats
```

- [ ] **Step 4: Commit cleanup**

```bash
git add -A
git commit -m "chore(scraper-v2): remove old pipeline modules replaced by Scrapy architecture"
```

---

### Task 20: Update launchd Schedule

- [ ] **Step 1: Update launchd plist to use new CLI**

The plist at `~/Library/LaunchAgents/com.jobscraper.scrape.plist` should already work since the CLI interface is the same (`python -m job_scraper scrape -v`). Verify:

```bash
cat ~/Library/LaunchAgents/com.jobscraper.scrape.plist
```

If the working directory or command needs updating, edit the plist.

- [ ] **Step 2: Reload launchd**

```bash
launchctl unload ~/Library/LaunchAgents/com.jobscraper.scrape.plist
launchctl load ~/Library/LaunchAgents/com.jobscraper.scrape.plist
```

- [ ] **Step 3: Verify it triggers**

```bash
launchctl start com.jobscraper.scrape
tail -20 ~/.local/share/job_scraper/scrape.log
```

- [ ] **Step 4: Commit any plist changes**

```bash
git add -A
git commit -m "chore(scraper-v2): update launchd config for Scrapy pipeline"
```
