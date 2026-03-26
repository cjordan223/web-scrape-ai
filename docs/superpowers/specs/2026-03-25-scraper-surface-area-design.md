# Scraper Surface Area Expansion

**Date:** 2026-03-25
**Goal:** Increase the number of relevant jobs discovered without sacrificing quality.

## Context

Current pipeline stats (as of 2026-03-25):
- 1,980 total jobs in DB: 135 approved (6.8%), 531 hard-rejected, 1,308 QA-rejected
- SearXNG produces 76% of all approved jobs at 14.5% approval rate
- Board crawlers (Ashby/Greenhouse/Lever) produce 1,218 jobs but only 18 approvals (1.5%)
- 3 spider types produce zero results: USAJobs (env var not loaded), SimplyHired (no targets), Generic (no targets)
- Pipeline is saturated: ~680 URLs/run, 0-5 new per run after dedup
- Broken links are a significant portion of QA rejections

## Changes

### 1. Fix USAJobs Spider (env var loading)

**Problem:** API credentials exist in `.env` but Scrapy doesn't load `.env` files. The spider silently skips when `USAJOBS_API_KEY` is empty. The launchd plist also doesn't set these vars.

**Solution:** Add `python-dotenv` to dependencies. In `job_scraper/settings.py`, add:
```python
from dotenv import load_dotenv
load_dotenv()
```
This runs before any spider `__init__`, so `os.environ.get("USAJOBS_API_KEY")` will find the value.

**No spider code changes needed.** The spider, config keywords (cybersecurity, software engineer, platform engineer, cloud security, DevSecOps), agencies (DoE, EPA, NSA), and series codes (2210, 1550, 0854, 0861, 1560, 1301) are all correctly implemented.

**Expected yield:** Up to 500 federal postings/run across 5 keyword searches, pre-filtered for remote. High quality — real postings with full JD text from the API.

### 2. Add RemoteOK API Spider

**Problem:** No aggregator sources producing results. SimplyHired was removed from config during Scrapy v2 migration and is low quality.

**Solution:** New spider at `job_scraper/spiders/remoteok.py`:
- Hits `GET https://remoteok.com/api` — returns JSON array, no auth required
- First element is metadata, rest are job objects with fields: `id`, `position`, `company`, `description`, `tags[]`, `url`, `salary_min`, `salary_max`, `location`
- Pre-filter on `tags` matching relevant keywords before yielding: `security`, `devops`, `cloud`, `infrastructure`, `sre`, `platform`, `backend`, `ai`, `ml`, `engineer`
- Map to `JobItem`: `jd_text` from `description` (HTML), `salary_text` from salary fields, `board` = `"remoteok"`
- URL format: `https://remoteok.com/remote-jobs/{id}`
- No Playwright needed — plain HTTP JSON response

**Config:** Add `remoteok` top-level section to `config.default.yaml` and corresponding `RemoteOKConfig` Pydantic model to `config.py`:
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
```

**Config model addition in `config.py`:**
```python
class RemoteOKConfig(BaseModel):
    enabled: bool = True
    tag_filter: list[str] = Field(default_factory=list)
```
Add `remoteok: RemoteOKConfig` to `ScraperConfig` and parse in `load_config()`.

**Register in `__init__.py`:** Add `RemoteOKSpider` to `ALL_SPIDERS`.

**Expected yield:** ~10-30 relevant jobs per run after tag filtering.

### 3. LinkedIn Queries via SearXNG

**Problem:** SearXNG is the best source but is saturated. LinkedIn job pages are not queried despite being the largest job posting platform and having public `/jobs/view/{id}` pages with full JD HTML.

**Validated:** `site:linkedin.com/jobs/view` queries through SearXNG return 30 individual job posting URLs. The existing SearXNG spider already follows result URLs and extracts JD HTML. The dashboard's JD fetcher already handles LinkedIn pages.

**Solution:** Add 10 new queries to `config.default.yaml`:
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

The SearXNG spider infers `board` from the URL host automatically (line 64 of `searxng.py` already handles `linkedin`). The `board` field in the YAML queries above is for documentation only — `SearXNGQuery` only parses `title_phrase`, `board_site`, and `suffix`. No spider code changes needed — config only.

**Expected yield:** ~200-300 new LinkedIn URLs per run. At SearXNG's 14.5% open-web approval rate, ~30-45 new approved jobs.

### 4. Hacker News "Who's Hiring" Spider

**Problem:** HN Who's Hiring threads are high-signal, curated job postings from actively hiring companies. March 2026 thread has 483 comments. This source is untapped.

**Solution:** New spider at `job_scraper/spiders/hn_hiring.py`:

**Discovery phase:**
- Use HN Algolia API to find the latest "Who is hiring?" thread: `GET https://hn.algolia.com/api/v1/search?query="Who is hiring"&tags=ask_hn&hitsPerPage=1`
- Extract thread `objectID` (the HN item ID)

**Comment fetching:**
- Fetch thread item from Firebase API: `GET https://hacker-news.firebaseio.com/v0/item/{id}.json`
- Get list of `kids` (top-level comment IDs — each is one job posting)
- Fetch each comment: `GET https://hacker-news.firebaseio.com/v0/item/{kid_id}.json`

**Comment parsing:**
- HN Who's Hiring comments follow a loose convention: first line is `Company | Role | Location | Remote/Onsite | URL`
- Parse company, title, location from first line using `|` splitting
- Extract any URL from the comment text — this is the link to the full job posting
- If a URL is found, follow it to get the full JD HTML (like SearXNG spider does)
- If no URL, use the comment text as `jd_text` and HN permalink as URL

**Dedup consideration:** Thread changes monthly. Comments can be edited. Use the HN comment permalink (`https://news.ycombinator.com/item?id={kid_id}`) as the dedup URL so each comment is only processed once per TTL window.

**Config:** Add `hn_hiring` top-level section to `config.default.yaml` and corresponding `HNHiringConfig` Pydantic model to `config.py`:
```yaml
hn_hiring:
  enabled: true
  max_comments: 500
```

**Config model addition in `config.py`:**
```python
class HNHiringConfig(BaseModel):
    enabled: bool = True
    max_comments: int = 500
```
Add `hn_hiring: HNHiringConfig` to `ScraperConfig` and parse in `load_config()`.

**Register in `__init__.py`:** Add `HNHiringSpider` to `ALL_SPIDERS`.

**Expected yield:** ~400-600 comments/month. After keyword filtering and hard filters, ~30-50 relevant postings per month. High quality — companies self-select into these threads.

### 5. Board Crawler Pre-filtering

**Problem:** Ashby/Greenhouse/Lever spiders scrape every open role at each company regardless of relevance. This produces ~1,000 irrelevant items per run (sales, marketing, HR roles) that get hard-filtered or QA-rejected.

**Solution:** Add title keyword pre-filtering at the spider level.

**Solution:**
1. Add `title_keywords: list[str]` to `HardFilterConfig` in `config.py` (currently only exclusion lists are modeled — the positive keyword list from `filter.title_keywords` in YAML is not parsed)
2. Load `filter.title_keywords` from YAML in `load_config()`
3. Add `title_matches()` in `spiders/__init__.py` that checks job title against these keywords using word-boundary regex (case-insensitive)
4. Call `title_matches(title)` in `AshbySpider.parse_job()`, `GreenhouseSpider.parse_job()`, and `LeverSpider.parse_job()` — skip yield if no match

```python
# spiders/__init__.py
import re
from functools import lru_cache
from job_scraper.config import load_config

@lru_cache(maxsize=1)
def _get_title_patterns() -> list[re.Pattern]:
    cfg = load_config()
    return [re.compile(rf"\b{re.escape(kw)}\b", re.I) for kw in cfg.hard_filters.title_keywords]

def title_matches(title: str) -> bool:
    return any(p.search(title) for p in _get_title_patterns())
```

**Safety:** All 18 approved board-crawl jobs had titles matching these keywords. Zero false negatives expected.

**Impact:** Eliminates ~1,000+ noise items/run from entering the pipeline. Reduces DB bloat, speeds up runs.

### 6. SearXNG Time Range Rotation

**Problem:** `time_range: week` is static. Every hourly run gets the same result set. With 14-day dedup TTL, URLs churn without producing new items.

**Solution:** In `SearXNGSpider.start_requests()`, alternate time range based on current hour:
```python
from datetime import datetime
time_range = "day" if datetime.now().hour % 2 == 0 else "week"
```

- Even hours: `day` — surfaces freshly indexed results
- Odd hours: `week` — broader window catches recently posted jobs

**No config change.** Override the config's `time_range` in the spider at request time.

**Expected impact:** More URL churn in results = more new items passing dedup. `day` queries are more likely to surface postings indexed in the last 24 hours that would otherwise be buried in `week` results.

## Dependencies

- `python-dotenv` — new pip dependency for `.env` loading

## Files Changed

| File | Change |
|------|--------|
| `job_scraper/settings.py` | Add `dotenv.load_dotenv()` |
| `job_scraper/config.py` | Add `title_keywords` to `HardFilterConfig`, add `RemoteOKConfig` and `HNHiringConfig` models, parse from YAML |
| `job_scraper/config.default.yaml` | Add 10 LinkedIn queries, `remoteok` section, `hn_hiring` section |
| `job_scraper/spiders/__init__.py` | Add `title_matches()` utility |
| `job_scraper/spiders/remoteok.py` | New spider |
| `job_scraper/spiders/hn_hiring.py` | New spider |
| `job_scraper/spiders/ashby.py` | Add `title_matches()` gate in `parse_job()` |
| `job_scraper/spiders/greenhouse.py` | Add `title_matches()` gate in `parse_job()` |
| `job_scraper/spiders/lever.py` | Add `title_matches()` gate in `parse_job()` |
| `job_scraper/spiders/searxng.py` | Add time range rotation in `start_requests()` |
| `job_scraper/__init__.py` | Register `RemoteOKSpider` and `HNHiringSpider` in `ALL_SPIDERS` |
| `pyproject.toml` | Add `python-dotenv` dependency |

## Files Not Changed

- Pipeline files (`text_extraction.py`, `dedup.py`, `hard_filter.py`, `storage.py`) — no changes needed
- `db.py` — no schema changes
- Dashboard — no changes needed
- USAJobs spider — already correct, just needs env vars loaded

## Expected Outcome

Conservative estimate of new relevant jobs per run cycle:
- USAJobs: 5-15 (federal cyber/IT roles, high quality)
- RemoteOK: 5-10 (remote tech roles)
- LinkedIn via SearXNG: 10-20 (broad tech market)
- HN Who's Hiring: 1-2/run (monthly thread, ~30-50/month)
- Board pre-filtering: 0 new jobs, but eliminates ~1,000 noise items
- Time range rotation: 2-5 additional new URLs/run from freshness

**Total estimated increase: 20-50 new relevant jobs per run**, up from the current 0-5. This is a ~10x improvement in new job discovery rate.
