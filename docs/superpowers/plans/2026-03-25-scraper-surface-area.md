# Scraper Surface Area Expansion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Increase the number of relevant jobs discovered per scrape run from 0-5 to 20-50 by fixing broken spiders, adding new sources, and reducing noise.

**Architecture:** All changes follow the existing Scrapy spider + pipeline pattern. Two new spiders (RemoteOK, HN Hiring), config expansions (LinkedIn queries, new Pydantic models), and surgical edits to existing spiders (board pre-filtering, time range rotation). One new dependency (`python-dotenv`).

**Tech Stack:** Scrapy, Pydantic, python-dotenv, HN Firebase/Algolia APIs, RemoteOK JSON API

**Spec:** `docs/superpowers/specs/2026-03-25-scraper-surface-area-design.md`

**Existing test baseline:** Some pre-existing test failures in `test_ashby_spider.py`, `test_greenhouse_spider.py`, `test_db.py`, `test_pipelines.py`. These are not caused by our changes. All tests we write must pass.

**Working directory:** All paths relative to `job-scraper/` unless otherwise noted. Run all commands from `/Users/conner/Documents/JobForge/job-scraper/`.

---

### Task 1: Add python-dotenv and fix USAJobs env loading

**Files:**
- Modify: `pyproject.toml:10-19` (add dependency)
- Modify: `job_scraper/settings.py:1-3` (add dotenv loading)
- Test: `tests/test_config.py` (add env loading test)

- [ ] **Step 1: Write test that dotenv loads .env file**

Add to `tests/test_config.py`:

```python
import os

def test_dotenv_loads_env_file(tmp_path, monkeypatch):
    """settings.py should load .env via python-dotenv."""
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_DOTENV_VAR=hello_from_dotenv\n")
    monkeypatch.chdir(tmp_path)
    # Remove if already set
    monkeypatch.delenv("TEST_DOTENV_VAR", raising=False)
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_file)
    assert os.environ.get("TEST_DOTENV_VAR") == "hello_from_dotenv"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py::test_dotenv_loads_env_file -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dotenv'`

- [ ] **Step 3: Add python-dotenv dependency**

In `pyproject.toml`, add `"python-dotenv>=1.0"` to the dependencies list:

```toml
dependencies = [
    "scrapy>=2.11",
    "scrapy-playwright>=0.0.40",
    "trafilatura>=1.12",
    "httpx>=0.27",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "typer>=0.12",
    "rich>=13.0",
    "python-dotenv>=1.0",
]
```

Then install: `pip install -e .`

- [ ] **Step 4: Add dotenv loading to settings.py**

Add these two lines at the very top of `job_scraper/settings.py`, before all other code:

```python
from dotenv import load_dotenv
load_dotenv()
```

The full file top should read:

```python
from dotenv import load_dotenv
load_dotenv()

"""Scrapy settings for job_scraper."""

BOT_NAME = "job_scraper"
...
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: All tests PASS (including `test_dotenv_loads_env_file`)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml job_scraper/settings.py tests/test_config.py
git commit -m "feat: add python-dotenv to load .env for USAJobs API keys"
```

---

### Task 2: Add config models for RemoteOK, HN Hiring, and title_keywords

**Files:**
- Modify: `job_scraper/config.py:44-57,66-76,132-194` (add models + load logic)
- Test: `tests/test_config.py` (add tests for new config sections)

- [ ] **Step 1: Write tests for new config models**

Add to `tests/test_config.py`:

```python
def test_title_keywords_loaded():
    cfg = load_config()
    assert len(cfg.hard_filters.title_keywords) > 0
    assert "security" in cfg.hard_filters.title_keywords


def test_remoteok_config_loaded():
    cfg = load_config()
    assert cfg.remoteok is not None
    assert cfg.remoteok.enabled is True
    assert len(cfg.remoteok.tag_filter) > 0


def test_hn_hiring_config_loaded():
    cfg = load_config()
    assert cfg.hn_hiring is not None
    assert cfg.hn_hiring.enabled is True
    assert cfg.hn_hiring.max_comments > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py::test_title_keywords_loaded tests/test_config.py::test_remoteok_config_loaded tests/test_config.py::test_hn_hiring_config_loaded -v`
Expected: FAIL — `AttributeError: 'HardFilterConfig' object has no attribute 'title_keywords'`

- [ ] **Step 3: Add title_keywords to HardFilterConfig**

In `job_scraper/config.py`, add `title_keywords` field to `HardFilterConfig`:

```python
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
    title_keywords: list[str] = Field(default_factory=list)
    min_salary_k: int = 70
```

- [ ] **Step 4: Add RemoteOKConfig and HNHiringConfig models**

Add these two classes in `job_scraper/config.py`, after `HardFilterConfig` and before `SearXNGQuery`:

```python
class RemoteOKConfig(BaseModel):
    enabled: bool = True
    tag_filter: list[str] = Field(default_factory=list)


class HNHiringConfig(BaseModel):
    enabled: bool = True
    max_comments: int = 500
```

- [ ] **Step 5: Add new fields to ScraperConfig**

Update `ScraperConfig` to include the new config models:

```python
class ScraperConfig(BaseModel):
    boards: list[BoardTarget] = Field(default_factory=list)
    searxng: SearXNGConfig = Field(default_factory=SearXNGConfig)
    usajobs: USAJobsConfig = Field(default_factory=USAJobsConfig)
    remoteok: RemoteOKConfig = Field(default_factory=RemoteOKConfig)
    hn_hiring: HNHiringConfig = Field(default_factory=HNHiringConfig)
    hard_filters: HardFilterConfig = Field(default_factory=HardFilterConfig)
    queries: list[SearXNGQuery] = Field(default_factory=list)
    seen_ttl_days: int = 14
    target_max_results: int = 50
    pipeline_order: list[str] = Field(default_factory=lambda: [
        "text_extraction", "dedup", "hard_filter", "storage",
    ])
```

- [ ] **Step 6: Update load_config() to parse new sections**

In `load_config()`, after the `hard_filters` parsing block (around line 179), add parsing for `title_keywords`, `remoteok`, and `hn_hiring`:

```python
    hard_filters = HardFilterConfig(
        domain_blocklist=filter_raw.get("url_domain_blocklist", HardFilterConfig().domain_blocklist),
        title_blocklist=filter_raw.get("seniority_exclude", HardFilterConfig().title_blocklist),
        content_blocklist=filter_raw.get("content_blocklist", HardFilterConfig().content_blocklist),
        title_keywords=filter_raw.get("title_keywords", []),
        min_salary_k=filter_raw.get("min_salary_k", 70),
    )

    remoteok_raw = raw.get("remoteok", {})
    remoteok = RemoteOKConfig(
        enabled=remoteok_raw.get("enabled", True),
        tag_filter=remoteok_raw.get("tag_filter", []),
    )

    hn_hiring_raw = raw.get("hn_hiring", {})
    hn_hiring = HNHiringConfig(
        enabled=hn_hiring_raw.get("enabled", True),
        max_comments=hn_hiring_raw.get("max_comments", 500),
    )
```

Update the `return ScraperConfig(...)` call to include:

```python
    return ScraperConfig(
        boards=boards,
        searxng=searxng,
        usajobs=usajobs,
        remoteok=remoteok,
        hn_hiring=hn_hiring,
        hard_filters=hard_filters,
        queries=queries,
        seen_ttl_days=filter_raw.get("seen_ttl_days", 14),
        target_max_results=filter_raw.get("target_max_results", 50),
        pipeline_order=pipeline_order,
    )
```

- [ ] **Step 7: Add remoteok and hn_hiring sections to config.default.yaml**

Append to `job_scraper/config.default.yaml` (after the `queries:` section):

```yaml
remoteok:
  enabled: true
  tag_filter:
    - security
    - devops
    - cloud
    - infrastructure
    - sre
    - platform
    - backend
    - engineer
    - ai
    - ml
hn_hiring:
  enabled: true
  max_comments: 500
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: All config tests PASS

- [ ] **Step 9: Commit**

```bash
git add job_scraper/config.py job_scraper/config.default.yaml tests/test_config.py
git commit -m "feat: add RemoteOK, HN Hiring, and title_keywords config models"
```

---

### Task 3: Add LinkedIn queries to config

**Files:**
- Modify: `job_scraper/config.default.yaml` (add 10 LinkedIn queries to `queries:` list)
- Test: `tests/test_config.py` (verify LinkedIn queries load)

- [ ] **Step 1: Write test for LinkedIn queries**

Add to `tests/test_config.py`:

```python
def test_linkedin_queries_present():
    cfg = load_config()
    linkedin_queries = [q for q in cfg.queries if "linkedin.com" in q.board_site]
    assert len(linkedin_queries) >= 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py::test_linkedin_queries_present -v`
Expected: FAIL — `assert 0 >= 10`

- [ ] **Step 3: Add LinkedIn queries to config.default.yaml**

Append these 10 entries to the `queries:` list in `job_scraper/config.default.yaml`:

```yaml
- title_phrase: security engineer
  board_site: linkedin.com/jobs/view
  suffix: remote
- title_phrase: platform engineer
  board_site: linkedin.com/jobs/view
  suffix: remote
- title_phrase: cloud engineer
  board_site: linkedin.com/jobs/view
  suffix: remote
- title_phrase: devsecops
  board_site: linkedin.com/jobs/view
  suffix: remote
- title_phrase: detection engineer
  board_site: linkedin.com/jobs/view
  suffix: remote
- title_phrase: infrastructure engineer
  board_site: linkedin.com/jobs/view
  suffix: remote
- title_phrase: application security
  board_site: linkedin.com/jobs/view
  suffix: remote
- title_phrase: AI engineer
  board_site: linkedin.com/jobs/view
  suffix: remote
- title_phrase: site reliability engineer
  board_site: linkedin.com/jobs/view
  suffix: remote
- title_phrase: devops engineer
  board_site: linkedin.com/jobs/view
  suffix: remote
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job_scraper/config.default.yaml tests/test_config.py
git commit -m "feat: add 10 LinkedIn site: queries to SearXNG config"
```

---

### Task 4: Add SearXNG time range rotation

**Files:**
- Modify: `job_scraper/spiders/searxng.py:29-38` (add time range selection)
- Test: `tests/test_searxng_spider.py` (add test for time range in query params)

- [ ] **Step 1: Write test for time range rotation**

Add to `tests/test_searxng_spider.py`:

```python
from unittest.mock import patch
from job_scraper.config import SearXNGQuery

def test_time_range_rotates_by_hour():
    spider = SearXNGSpider()
    spider._searxng_url = "http://localhost:8888/search"
    spider._queries = [SearXNGQuery(title_phrase="test engineer", board_site="", suffix="remote")]
    spider._domain_blocklist = set()

    # Even hour -> "day"
    with patch("job_scraper.spiders.searxng.datetime") as mock_dt:
        mock_now = mock_dt.now.return_value
        mock_now.hour = 10
        mock_now.isoformat.return_value = "2026-03-25T10:00:00"
        mock_dt.now.return_value = mock_now
        requests = list(spider.start_requests())
        assert len(requests) == 1
        assert "time_range=day" in requests[0].url

    # Odd hour -> "week"
    with patch("job_scraper.spiders.searxng.datetime") as mock_dt:
        mock_now = mock_dt.now.return_value
        mock_now.hour = 11
        mock_now.isoformat.return_value = "2026-03-25T11:00:00"
        mock_dt.now.return_value = mock_now
        requests = list(spider.start_requests())
        assert "time_range=week" in requests[0].url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_searxng_spider.py::test_time_range_rotates_by_hour -v`
Expected: FAIL — `assert 'time_range=day' in ...` (no time_range param currently)

- [ ] **Step 3: Add time range rotation to SearXNG spider**

Modify `start_requests()` in `job_scraper/spiders/searxng.py` to add time range rotation:

```python
    def start_requests(self):
        # Alternate time_range: even hours = "day" (fresh), odd = "week" (broader)
        hour = datetime.now().hour
        time_range = "day" if hour % 2 == 0 else "week"
        for query in self._queries:
            q_parts = []
            if query.board_site:
                q_parts.append(f"site:{query.board_site}")
            q_parts.append(f'"{query.title_phrase}"')
            if query.suffix:
                q_parts.append(query.suffix)
            params = urlencode({"q": " ".join(q_parts), "format": "json", "time_range": time_range})
            yield scrapy.Request(url=f"{self._searxng_url}?{params}", callback=self.parse_results, meta={"query_phrase": query.title_phrase}, dont_filter=True, errback=self.errback_searxng)
```

Also add `linkedin` detection in `parse_job_page()` — add after the `usajobs.gov` line:

```python
        elif "linkedin.com" in host: board = "linkedin"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_searxng_spider.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add job_scraper/spiders/searxng.py tests/test_searxng_spider.py
git commit -m "feat: add time range rotation and LinkedIn board detection to SearXNG spider"
```

---

### Task 5: Add board crawler title pre-filtering

**Files:**
- Modify: `job_scraper/spiders/__init__.py` (add `title_matches()`)
- Modify: `job_scraper/spiders/ashby.py:98-129` (gate `parse_job` yield)
- Modify: `job_scraper/spiders/greenhouse.py:65-88` (gate `parse_job` yield)
- Modify: `job_scraper/spiders/lever.py:48-53` (gate `parse_job` yield)
- Test: `tests/test_title_filter.py` (new — test `title_matches()`)

- [ ] **Step 1: Write tests for title_matches()**

Create `tests/test_title_filter.py`:

```python
from job_scraper.spiders import title_matches


def test_matches_security_engineer():
    assert title_matches("Security Engineer") is True


def test_matches_cloud_in_title():
    assert title_matches("Cloud Infrastructure Lead") is True


def test_matches_platform_engineer():
    assert title_matches("Platform Engineer - Remote") is True


def test_rejects_sales_title():
    assert title_matches("Account Executive") is False


def test_rejects_marketing_title():
    assert title_matches("Marketing Manager") is False


def test_rejects_hr_title():
    assert title_matches("People Operations Coordinator") is False


def test_case_insensitive():
    assert title_matches("SECURITY ENGINEER") is True
    assert title_matches("devops engineer") is True


def test_matches_sre():
    assert title_matches("Site Reliability Engineer") is True


def test_matches_ai_engineer():
    assert title_matches("AI Engineer") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_title_filter.py -v`
Expected: FAIL — `ImportError: cannot import name 'title_matches' from 'job_scraper.spiders'`

- [ ] **Step 3: Implement title_matches() in spiders/__init__.py**

Replace the contents of `job_scraper/spiders/__init__.py` with:

```python
"""Scrapy spiders for job_scraper — shared utilities."""
from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=1)
def _get_title_patterns() -> tuple[re.Pattern, ...]:
    from job_scraper.config import load_config
    cfg = load_config()
    return tuple(
        re.compile(rf"\b{re.escape(kw)}\b", re.I)
        for kw in cfg.hard_filters.title_keywords
    )


def title_matches(title: str) -> bool:
    """Return True if the job title contains at least one inclusion keyword."""
    return any(p.search(title) for p in _get_title_patterns())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_title_filter.py -v`
Expected: All PASS

- [ ] **Step 5: Add pre-filter gate to AshbySpider.parse_job()**

In `job_scraper/spiders/ashby.py`, add import at the top:

```python
from job_scraper.spiders import title_matches
```

Then in `parse_job()`, after `title = ...` (line 113), add:

```python
        if not title_matches(title):
            logger.debug("Ashby %s: skipping non-matching title: %s", org, title)
            return
```

The modified section should read:

```python
    def parse_job(self, response):
        company = response.meta["company"]
        org = response.meta["org"]
        try:
            data = json.loads(response.text)
            job = data.get("data", {}).get("jobPosting")
        except (json.JSONDecodeError, KeyError):
            logger.warning("Failed to parse Ashby job detail for %s", org)
            return

        if not job:
            logger.warning("Empty job posting response for %s", org)
            return

        job_id = job["id"]
        title = job.get("title") or response.meta.get("brief_title") or "Unknown"
        if not title_matches(title):
            logger.debug("Ashby %s: skipping non-matching title: %s", org, title)
            return
        location = job.get("locationName") or response.meta.get("brief_location") or ""
        ...
```

- [ ] **Step 6: Add pre-filter gate to GreenhouseSpider.parse_job()**

In `job_scraper/spiders/greenhouse.py`, add import at the top:

```python
from job_scraper.spiders import title_matches
```

Then in `parse_job()`, after `title = ...` (line 74), add:

```python
        if not title_matches(title):
            logger.debug("Greenhouse %s: skipping non-matching title: %s", org, title)
            return
```

- [ ] **Step 7: Add pre-filter gate to LeverSpider.parse_job()**

In `job_scraper/spiders/lever.py`, add import at the top:

```python
from job_scraper.spiders import title_matches
```

Then in `parse_job()`, after `title = ...` (line 50), add:

```python
        if not title_matches(title):
            logger.debug("Lever %s: skipping non-matching title: %s", company, title)
            return
```

- [ ] **Step 8: Run all spider tests**

Run: `python -m pytest tests/test_title_filter.py tests/test_searxng_spider.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add job_scraper/spiders/__init__.py job_scraper/spiders/ashby.py job_scraper/spiders/greenhouse.py job_scraper/spiders/lever.py tests/test_title_filter.py
git commit -m "feat: add title keyword pre-filtering to board crawlers"
```

---

### Task 6: Add RemoteOK API spider

**Files:**
- Create: `job_scraper/spiders/remoteok.py`
- Modify: `job_scraper/__init__.py:26-42` (register spider)
- Test: `tests/test_remoteok_spider.py` (new)

- [ ] **Step 1: Write tests for RemoteOK spider**

Create `tests/test_remoteok_spider.py`:

```python
import json
from scrapy.http import TextResponse, Request
from job_scraper.spiders.remoteok import RemoteOKSpider
from job_scraper.items import JobItem


def _fake_json_response(url, data):
    return TextResponse(url=url, request=Request(url=url), body=json.dumps(data).encode(), encoding="utf-8")


def test_parses_remoteok_api():
    spider = RemoteOKSpider(tag_filter=["security", "engineer"])
    data = [
        {"legal": "RemoteOK API"},  # metadata element
        {
            "id": "12345",
            "position": "Security Engineer",
            "company": "Acme Corp",
            "description": "<p>We are looking for a security engineer to join our team.</p>",
            "tags": ["security", "engineer"],
            "url": "https://remoteok.com/remote-jobs/12345",
            "salary_min": 120000,
            "salary_max": 180000,
            "location": "Remote",
        },
    ]
    response = _fake_json_response("https://remoteok.com/api", data)
    items = list(spider.parse_api(response))
    assert len(items) == 1
    assert isinstance(items[0], JobItem)
    assert items[0]["board"] == "remoteok"
    assert items[0]["title"] == "Security Engineer"
    assert items[0]["company"] == "Acme Corp"
    assert "$120000" in items[0]["salary_text"] or "120000" in items[0]["salary_text"]


def test_filters_by_tags():
    spider = RemoteOKSpider(tag_filter=["security"])
    data = [
        {"legal": "metadata"},
        {
            "id": "111",
            "position": "Marketing Manager",
            "company": "Foo",
            "description": "<p>Marketing role</p>",
            "tags": ["marketing", "manager"],
            "url": "https://remoteok.com/remote-jobs/111",
            "location": "Remote",
        },
        {
            "id": "222",
            "position": "Security Analyst",
            "company": "Bar",
            "description": "<p>Security role</p>",
            "tags": ["security", "analyst"],
            "url": "https://remoteok.com/remote-jobs/222",
            "location": "Remote",
        },
    ]
    response = _fake_json_response("https://remoteok.com/api", data)
    items = list(spider.parse_api(response))
    assert len(items) == 1
    assert items[0]["title"] == "Security Analyst"


def test_handles_empty_api_response():
    spider = RemoteOKSpider(tag_filter=["security"])
    data = [{"legal": "metadata"}]
    response = _fake_json_response("https://remoteok.com/api", data)
    items = list(spider.parse_api(response))
    assert len(items) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_remoteok_spider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'job_scraper.spiders.remoteok'`

- [ ] **Step 3: Implement RemoteOK spider**

Create `job_scraper/spiders/remoteok.py`:

```python
"""Spider for RemoteOK JSON API."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import scrapy
from job_scraper.items import JobItem

logger = logging.getLogger(__name__)

_API_URL = "https://remoteok.com/api"


class RemoteOKSpider(scrapy.Spider):
    name = "remoteok"

    def __init__(self, tag_filter=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tag_filter = set(tag_filter or [])

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        if not cfg.remoteok.enabled:
            kwargs["tag_filter"] = []
        else:
            kwargs["tag_filter"] = cfg.remoteok.tag_filter
        return super().from_crawler(crawler, *args, **kwargs)

    def start_requests(self):
        if not self._tag_filter:
            logger.info("RemoteOK spider disabled or no tag filters configured")
            return
        yield scrapy.Request(
            url=_API_URL,
            callback=self.parse_api,
            headers={"User-Agent": "JobForge/2.0"},
            dont_filter=True,
        )

    def parse_api(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("RemoteOK returned non-JSON response")
            return

        for entry in data:
            # Skip metadata entry (first element) and non-job entries
            if not isinstance(entry, dict) or "position" not in entry:
                continue

            tags = {t.lower() for t in entry.get("tags", [])}
            if not tags & self._tag_filter:
                continue

            title = entry.get("position", "Unknown")
            company = entry.get("company", "Unknown")
            description = entry.get("description", "")
            url = entry.get("url", f"https://remoteok.com/remote-jobs/{entry.get('id', '')}")
            location = entry.get("location", "Remote")

            salary_min = entry.get("salary_min")
            salary_max = entry.get("salary_max")
            salary_text = ""
            if salary_min and salary_max:
                salary_text = f"${salary_min} - ${salary_max}"
            elif salary_min:
                salary_text = f"${salary_min}+"

            yield JobItem(
                url=url,
                title=title.strip(),
                company=company.strip(),
                board="remoteok",
                location=location,
                salary_text=salary_text,
                jd_html=description,
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_remoteok_spider.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Register RemoteOK spider in __init__.py**

In `job_scraper/__init__.py`, add the import and registration:

Add after the other spider imports:
```python
    from .spiders.remoteok import RemoteOKSpider
```

Add to `ALL_SPIDERS` dict:
```python
        "remoteok": RemoteOKSpider,
```

- [ ] **Step 6: Commit**

```bash
git add job_scraper/spiders/remoteok.py job_scraper/__init__.py tests/test_remoteok_spider.py
git commit -m "feat: add RemoteOK API spider for remote tech jobs"
```

---

### Task 7: Add Hacker News "Who's Hiring" spider

**Files:**
- Create: `job_scraper/spiders/hn_hiring.py`
- Modify: `job_scraper/__init__.py` (register spider)
- Test: `tests/test_hn_hiring_spider.py` (new)

- [ ] **Step 1: Write tests for HN Hiring spider**

Create `tests/test_hn_hiring_spider.py`:

```python
import json
from scrapy.http import TextResponse, Request
from job_scraper.spiders.hn_hiring import HNHiringSpider, parse_hn_comment
from job_scraper.items import JobItem


def _fake_json_response(url, data):
    return TextResponse(url=url, request=Request(url=url), body=json.dumps(data).encode(), encoding="utf-8")


def test_parse_hn_comment_pipe_format():
    text = "Acme Corp | Security Engineer | Remote (US) | $150k-$200k | https://acme.com/jobs/123"
    result = parse_hn_comment(text)
    assert result["company"] == "Acme Corp"
    assert result["title"] == "Security Engineer"
    assert result["location"] == "Remote (US)"
    assert result["url"] == "https://acme.com/jobs/123"


def test_parse_hn_comment_no_url():
    text = "BigCo | Platform Engineer | San Francisco | $180k"
    result = parse_hn_comment(text)
    assert result["company"] == "BigCo"
    assert result["title"] == "Platform Engineer"
    assert result["url"] is None


def test_parse_hn_comment_minimal():
    text = "We're hiring engineers at StartupXYZ. Check out https://startupxyz.com/careers"
    result = parse_hn_comment(text)
    assert result["url"] == "https://startupxyz.com/careers"


def test_parses_thread_kids():
    spider = HNHiringSpider(max_comments=500)
    thread_data = {
        "id": 47219668,
        "kids": [100, 200, 300],
        "title": "Ask HN: Who is hiring? (March 2026)",
    }
    response = _fake_json_response("https://hacker-news.firebaseio.com/v0/item/47219668.json", thread_data)
    requests = list(spider.parse_thread(response))
    assert len(requests) == 3
    assert "item/100.json" in requests[0].url


def test_parses_comment_into_job_item():
    spider = HNHiringSpider(max_comments=500)
    comment_data = {
        "id": 100,
        "text": "Acme Corp | Cloud Security Engineer | Remote | $160k-$200k | https://acme.com/apply",
        "by": "acme_recruiter",
    }
    response = _fake_json_response("https://hacker-news.firebaseio.com/v0/item/100.json", comment_data)
    results = list(spider.parse_comment(response))
    # Should yield a follow-up request to the job URL
    assert len(results) >= 1


def test_skips_deleted_comment():
    spider = HNHiringSpider(max_comments=500)
    comment_data = {"id": 100, "deleted": True}
    response = _fake_json_response("https://hacker-news.firebaseio.com/v0/item/100.json", comment_data)
    results = list(spider.parse_comment(response))
    assert len(results) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hn_hiring_spider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'job_scraper.spiders.hn_hiring'`

- [ ] **Step 3: Implement HN Hiring spider**

Create `job_scraper/spiders/hn_hiring.py`:

```python
"""Spider for Hacker News 'Who is Hiring?' monthly threads."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

import scrapy
from job_scraper.items import JobItem

logger = logging.getLogger(__name__)

_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
_FIREBASE_URL = "https://hacker-news.firebaseio.com/v0/item"
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")


def parse_hn_comment(text: str) -> dict:
    """Parse a Who's Hiring comment into structured fields.

    Convention: Company | Role | Location | Salary | URL
    But many comments don't follow this exactly.
    """
    result = {"company": "", "title": "", "location": "", "url": None}

    # Extract first URL from text
    url_match = _URL_PATTERN.search(text)
    if url_match:
        result["url"] = url_match.group(0).rstrip(".,;)")

    # Try pipe-delimited parsing (first line)
    first_line = text.split("\n")[0].strip()
    # Strip HTML tags
    first_line = re.sub(r"<[^>]+>", "", first_line)
    parts = [p.strip() for p in first_line.split("|")]

    if len(parts) >= 2:
        result["company"] = parts[0]
        result["title"] = parts[1]
    if len(parts) >= 3:
        result["location"] = parts[2]

    return result


class HNHiringSpider(scrapy.Spider):
    name = "hn_hiring"

    def __init__(self, max_comments=500, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._max_comments = max_comments

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        if not cfg.hn_hiring.enabled:
            kwargs["max_comments"] = 0
        else:
            kwargs["max_comments"] = cfg.hn_hiring.max_comments
        return super().from_crawler(crawler, *args, **kwargs)

    def start_requests(self):
        if self._max_comments <= 0:
            logger.info("HN Hiring spider disabled")
            return
        # Find the latest "Who is hiring?" thread via Algolia
        query = quote('"Who is hiring"')
        url = f"{_ALGOLIA_URL}?query={query}&tags=ask_hn&hitsPerPage=1"
        yield scrapy.Request(url=url, callback=self.parse_search, dont_filter=True)

    def parse_search(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Failed to parse Algolia response")
            return

        hits = data.get("hits", [])
        if not hits:
            logger.warning("No 'Who is hiring' thread found")
            return

        thread_id = hits[0].get("objectID")
        if not thread_id:
            return

        logger.info("Found HN hiring thread: %s (id=%s)", hits[0].get("title", "?"), thread_id)
        yield scrapy.Request(
            url=f"{_FIREBASE_URL}/{thread_id}.json",
            callback=self.parse_thread,
            dont_filter=True,
        )

    def parse_thread(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Failed to parse HN thread response")
            return

        kids = data.get("kids", [])
        logger.info("HN thread has %d top-level comments (limit %d)", len(kids), self._max_comments)

        for kid_id in kids[: self._max_comments]:
            yield scrapy.Request(
                url=f"{_FIREBASE_URL}/{kid_id}.json",
                callback=self.parse_comment,
                dont_filter=True,
                priority=-1,
            )

    def parse_comment(self, response):
        try:
            data = response.json()
        except Exception:
            return

        if not data or data.get("deleted") or data.get("dead"):
            return

        comment_id = data.get("id", "")
        text = data.get("text", "")
        if not text:
            return

        parsed = parse_hn_comment(text)
        hn_url = f"https://news.ycombinator.com/item?id={comment_id}"
        job_url = parsed.get("url")

        if job_url:
            # Follow the job URL to get full JD HTML
            yield scrapy.Request(
                url=job_url,
                callback=self.parse_job_page,
                meta={
                    "hn_url": hn_url,
                    "hn_company": parsed.get("company", ""),
                    "hn_title": parsed.get("title", ""),
                    "hn_location": parsed.get("location", ""),
                    "hn_text": text,
                },
                errback=self.errback_job_page,
                dont_filter=True,
                priority=-2,
            )
        else:
            # No URL — use comment text as JD
            if parsed.get("title"):
                yield JobItem(
                    url=hn_url,
                    title=parsed["title"],
                    company=parsed.get("company", "Unknown"),
                    board="hn_hiring",
                    location=parsed.get("location", ""),
                    jd_text=re.sub(r"<[^>]+>", " ", text),
                    source=self.name,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )

    def parse_job_page(self, response):
        meta = response.meta
        title = meta.get("hn_title") or "Unknown"
        company = meta.get("hn_company") or "Unknown"
        location = meta.get("hn_location") or ""

        yield JobItem(
            url=response.url,
            title=title.strip(),
            company=company.strip(),
            board="hn_hiring",
            location=location,
            jd_html=response.text,
            source=self.name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def errback_job_page(self, failure):
        # If the job URL fails, fall back to HN comment text
        request = failure.request
        meta = request.meta
        hn_url = meta.get("hn_url", "")
        title = meta.get("hn_title", "Unknown")
        company = meta.get("hn_company", "Unknown")
        text = meta.get("hn_text", "")

        if title and title != "Unknown":
            yield JobItem(
                url=hn_url,
                title=title,
                company=company,
                board="hn_hiring",
                location=meta.get("hn_location", ""),
                jd_text=re.sub(r"<[^>]+>", " ", text),
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hn_hiring_spider.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Register HN Hiring spider in __init__.py**

In `job_scraper/__init__.py`, add the import and registration:

Add after the other spider imports:
```python
    from .spiders.hn_hiring import HNHiringSpider
```

Add to `ALL_SPIDERS` dict:
```python
        "hn_hiring": HNHiringSpider,
```

- [ ] **Step 6: Commit**

```bash
git add job_scraper/spiders/hn_hiring.py job_scraper/__init__.py tests/test_hn_hiring_spider.py
git commit -m "feat: add Hacker News Who's Hiring spider"
```

---

### Task 8: Final integration verification

**Files:** None (verification only)

- [ ] **Step 1: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All new tests PASS. Pre-existing failures in `test_ashby_spider.py`, `test_greenhouse_spider.py`, `test_db.py`, `test_pipelines.py` are unchanged (not caused by our changes).

- [ ] **Step 2: Verify config loads cleanly with all new sections**

Run:
```bash
python -c "
from job_scraper.config import load_config
cfg = load_config()
print(f'Boards: {len(cfg.boards)}')
print(f'Queries: {len(cfg.queries)}')
print(f'Title keywords: {len(cfg.hard_filters.title_keywords)}')
print(f'RemoteOK tags: {cfg.remoteok.tag_filter}')
print(f'HN max comments: {cfg.hn_hiring.max_comments}')
linkedin_qs = [q for q in cfg.queries if 'linkedin' in q.board_site]
print(f'LinkedIn queries: {len(linkedin_qs)}')
print(f'USAJobs keywords: {cfg.usajobs.keywords}')
"
```

Expected output should show:
- 53 boards
- 61+ queries (51 original + 10 LinkedIn)
- Title keywords populated from YAML
- RemoteOK tags: `['security', 'devops', 'cloud', ...]`
- HN max comments: 500
- LinkedIn queries: 10
- USAJobs keywords: list of 5

- [ ] **Step 3: Verify dotenv loads USAJobs credentials**

Run:
```bash
python -c "
import os
from dotenv import load_dotenv
load_dotenv()
print('USAJOBS_API_KEY:', 'set' if os.environ.get('USAJOBS_API_KEY') else 'NOT SET')
print('USAJOBS_EMAIL:', 'set' if os.environ.get('USAJOBS_EMAIL') else 'NOT SET')
"
```

Expected: Both should print `set`

- [ ] **Step 4: Dry-run a single spider to verify no import errors**

Run:
```bash
python -c "
from job_scraper.spiders.remoteok import RemoteOKSpider
from job_scraper.spiders.hn_hiring import HNHiringSpider
from job_scraper.spiders.searxng import SearXNGSpider
from job_scraper.spiders.ashby import AshbySpider
from job_scraper.spiders import title_matches
print('All imports OK')
print('title_matches(\"Security Engineer\"):', title_matches('Security Engineer'))
print('title_matches(\"Account Executive\"):', title_matches('Account Executive'))
"
```

Expected:
```
All imports OK
title_matches("Security Engineer"): True
title_matches("Account Executive"): False
```

- [ ] **Step 5: Commit any fixes from verification**

If any issues found, fix and commit. Otherwise, no action needed.
