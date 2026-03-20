# Scraper Pipeline Rewrite — Design Spec

**Date:** 2026-03-19
**Status:** Draft
**Scope:** Full rewrite of `job-scraper/` package

## Summary

Replace the current SearXNG + Crawl4AI + 15-stage regex filter pipeline with a Scrapy + Playwright architecture. No LLM in the scraper — all classification deferred to the tailoring QA phase. SearXNG becomes an optional discovery source, not a dependency.

## Motivation

- Crawl4AI cannot handle Greenhouse (301 redirects) or Lever (headless blocking)
- 15 filter stages are a maintenance burden with recurring tuning incidents (98.6% rejection rate, TTL bugs, scoring safety rail removal)
- Missing declared dependencies (`feedparser`, `httpx`) break fresh installs
- Custom HTMLParser for JD extraction is outperformed by Trafilatura
- Filter logic duplicates work that tailoring's LLM analysis does better

## Architecture

```
SPIDERS (one per board type)
  → yield JobItem (structured Pydantic model)
    → TextExtractionPipeline (Trafilatura: jd_html → jd_text)
      → DeduplicationPipeline (seen_urls TTL + UNIQUE constraint)
        → HardFilterPipeline (blocklist, title blocklist, salary floor)
          → SQLitePipeline (persist to jobs table)
            → Dashboard QA → Tailoring
```

### Spiders

| Spider | Boards | Method |
|--------|--------|--------|
| AshbySpider | 31 boards (Ramp, Cloudflare, Tailscale, 1Password, etc.) | Embedded JSON extraction, no Playwright needed |
| GreenhouseSpider | 5 boards (Nansen, Adyen, Anduril, CrowdStrike, Bitwarden) | scrapy-playwright renders JS SPA |
| LeverSpider | 3 boards (EQ Bank, Spotify, Arcadia) | scrapy-playwright with stealth |
| USAJobsSpider | USAJobs API | httpx, no browser |
| SearXNGSpider | Local SearXNG (optional) | httpx, yields `JobItem` directly (extracts title/URL/snippet from search results; JD fetched via follow-up request in same spider) |
| AggregatorSpider | SimplyHired, similar | scrapy-playwright |
| GenericSpider | RSS feeds, static HTML | Plain Scrapy downloader |

All spiders:
- Yield `JobItem` with structured fields (company parsed at crawl time)
- Pass raw `jd_html` — text extraction happens in pipeline
- Board URLs configured in `config.default.yaml`

### JobItem

```python
class JobItem(scrapy.Item):
    url: str              # canonical URL
    title: str
    company: str          # parsed at crawl time per board type
    board: str            # ashby, greenhouse, lever, usajobs, etc.
    location: str | None  # raw location string from JD
    seniority: str | None # raw if available
    salary_text: str | None  # raw salary string, unparsed
    jd_html: str | None   # raw HTML for Trafilatura
    jd_text: str | None   # populated by TextExtractionPipeline
    snippet: str | None   # search result snippet (SearXNG)
    source: str           # spider class name
    discovered_at: str    # ISO timestamp
```

### Pipelines

**1. TextExtractionPipeline**
- Trafilatura: `jd_html` → `jd_text`
- Falls back to snippet if extraction returns nothing

**2. DeduplicationPipeline**
- Checks `seen_urls` table (14-day TTL on `first_seen`)
- Checks `jobs.url` UNIQUE constraint as safety net
- `DropItem` if seen (Scrapy logs automatically)

**3. HardFilterPipeline**
Three checks only:
- Domain blocklist (dictionary sites, etc.)
- Title blocklist (staff, principal, manager, director — hardest blocks only)
- Salary floor (if parseable and below threshold; unparseable passes through)

Dropped items saved to `jobs` with `status='rejected'` and `rejection_reason`.

**4. SQLitePipeline**
- Inserts into `jobs` table with `status='pending'`
- Updates `runs` table counters

### Scrapy Built-ins (free)

- `AUTOTHROTTLE_ENABLED` — adaptive rate limiting
- `RETRY_MIDDLEWARE` — exponential backoff (3 retries)
- `DUPEFILTER_CLASS` — in-memory URL dedup within a run
- `STATS_COLLECTOR` — items scraped/dropped/errors/timing
- `FEEDS` — optional JSON/CSV export

## Database Schema

```sql
CREATE TABLE seen_urls (
    url TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    board TEXT,
    location TEXT,
    seniority TEXT,
    salary_text TEXT,
    jd_text TEXT,
    approved_jd_text TEXT,           -- QA-edited JD (overrides jd_text for tailoring)
    snippet TEXT,
    query TEXT,                      -- search query that discovered this job (diagnostics)
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    rejection_stage TEXT,            -- which hard filter fired
    rejection_reason TEXT,
    run_id TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE runs (
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

-- Carried over from current schema (used by dashboard + tailoring)
CREATE TABLE applied_applications ( ... );  -- unchanged
CREATE TABLE applied_snapshots ( ... );     -- unchanged
CREATE TABLE job_state_log ( ... );         -- unchanged
CREATE TABLE tailoring_queue_items ( ... ); -- unchanged

-- Triggers protecting applied jobs (unchanged)
CREATE TRIGGER protect_applied_results_before_update ...;
CREATE TRIGGER protect_applied_results_before_delete ...;

-- Compatibility view: code referencing 'results' continues working during migration
CREATE VIEW results AS SELECT *, status AS decision FROM jobs;
```

### Schema changes from current

| Old | New |
|-----|-----|
| `results` table | `jobs` table |
| `rejected` table | `status='rejected'` + `rejection_reason` on `jobs` |
| `quarantine` table | Eliminated (no scoring/promotion) |
| `filter_verdicts` JSON blob | `rejection_stage` + `rejection_reason` (structured but simple) |
| `decision` column | `status` with lifecycle: pending → qa_approved → tailored → applied → rejected |
| `salary_k`, `experience_years`, `score` | Eliminated (no scraper-side parsing) |
| Company parsed at selection time | `company` column populated at crawl time |
| `url` unique per run | `url` globally unique |

### Status lifecycle

```
pending → qa_approved → tailored → applied
    ↘ rejected (at any point)
```

## Project Structure

```
job-scraper/
├── pyproject.toml
├── config.default.yaml
├── scrapy.cfg
└── job_scraper/
    ├── __init__.py          # CLI (typer)
    ├── settings.py          # Scrapy settings
    ├── items.py             # JobItem
    ├── pipelines/
    │   ├── text_extraction.py
    │   ├── dedup.py
    │   ├── hard_filter.py
    │   └── storage.py
    ├── spiders/
    │   ├── ashby.py
    │   ├── greenhouse.py
    │   ├── lever.py
    │   ├── usajobs.py
    │   ├── searxng.py
    │   ├── aggregator.py
    │   └── generic.py
    ├── db.py                # Schema, connection, migrations
    └── config.py            # YAML config loader
```

## Dependencies

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
]
```

Removed: `requests`, `crawl4ai`, undeclared `feedparser`.

## Integration Points

### Dashboard backend
- Imports `job_scraper.db` (replaces `job_scraper.dedup`)
- Queries `jobs` table instead of `results`
- `status` field replaces `decision` field
- Scraping handlers updated to match new schema

### Tailoring selector
- `selector.py` queries `jobs` where `status='qa_approved'`
- `SelectedJob.company` reads directly from column (no `_parse_company()`)
- `SelectedJob` fields map 1:1 to `jobs` columns

### CLI
- Same interface: `scrape`, `stats`, `recent`
- New: `scrape -s <spider>` to run a single spider
- Scrapy's stats collector provides run metrics

## Migration

- Old DB preserved (archival commit already made)
- New schema created on first run via `db.py`
- `seen_urls` table migrated as-is (compatible)
- `results` compatibility view (`CREATE VIEW results AS SELECT *, status AS decision FROM jobs`) ensures dashboard code works during transition
- One-time migration script to copy `results` → `jobs`:
  - Deduplicates by URL (keeps most recent row when same URL appears across runs)
  - Maps `decision` → `status`
  - Preserves `approved_jd_text` if column exists
- `applied_applications`, `applied_snapshots`, `job_state_log`, `tailoring_queue_items` tables and triggers carried over unchanged

## Risks & Mitigations

### scrapy-playwright for Greenhouse/Lever is unvalidated

The same Playwright engine that failed under Crawl4AI may fail under scrapy-playwright. Mitigation:
- Prototype GreenhouseSpider and LeverSpider against 2 target boards each before full implementation
- If they fail, those boards fall back to aggregator-only discovery (SimplyHired, SearXNG) — same as current behavior, no regression
- Document which boards are direct-crawlable vs aggregator-only in config

### Files requiring `results` → `jobs` table name changes

These files contain raw SQL referencing `results`:
- `job-scraper/api/scraping_handlers.py`
- `dashboard/backend/services/tailoring.py`
- `dashboard/backend/services/ops.py`
- `dashboard/backend/routers/tailoring.py`
- `tailoring/tailor/selector.py`

The `results` view provides backward compatibility during migration, but all files should be updated to reference `jobs` directly as part of implementation.

## What's eliminated

- 12 of 15 filter stages
- LLM reviewer in scraper
- Quarantine/promotion system
- Scoring pipeline
- Custom HTMLParser
- Async/sync boundary hacks (Scrapy is natively async)
- File-lock polling for LLM serialization
- Module-level global caches
