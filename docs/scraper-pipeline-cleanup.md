# Scraper Pipeline Cleanup — Phase 1 + 2 + 3 + 4

**Date:** 2026-04-25
**Scope:** Remove dead/redundant code without affecting active processes. Prep for upcoming repair work documented in `scraper-pipeline-audit.md`.
**Test result:** 88 passed, 0 failed (was 87 passed + 4 pre-existing failures pre-cleanup; Phase 2 cleared all 4).

## Removed

### Dead config (yaml)
- `filter.fetch_jd: true` in `job-scraper/job_scraper/config.default.yaml`. Flag was read into `HardFilterConfig` model... actually, wasn't even read there. Pydantic never parsed it. No code path consulted the value. Pure documentation rot.
- `llm_review:` block (7 lines) in `config.default.yaml`. Referenced empty `LLMReviewConfig` stub class only. Real LLM gate config lives at `scrape_profile.llm_gate`.

### Dead config classes (`job_scraper/config.py`)
- `USAJobsConfig` (Pydantic model, ~10 lines). Loader populated `ScraperConfig.usajobs` from a `watchers:` block in YAML that doesn't exist. Spider was never registered (see below).
- `FilterConfig` — empty stub for "old filters.py" that no longer exists.
- `QueryTemplate` — empty stub for "old searcher.py" that no longer exists.
- `WatcherConfig` — stub for "old watchers.py / usajobs.py" that no longer exists.
- `LLMReviewConfig` — empty stub for deprecated `llm_review` config.
- `CrawlTarget` — stub for "old crawler.py" that no longer exists.
- Removed corresponding `usajobs_raw` / `usajobs_enabled` parsing block in `load_config()`.
- Removed `usajobs: USAJobsConfig` field from `ScraperConfig`.

### Orphan spider files
- `job-scraper/job_scraper/spiders/usajobs.py` — `USAJobsSpider` class, not in `ALL_SPIDERS` (`__init__.py`), not in `SPIDER_TIERS` (`tiers.py`). Could not be invoked. 292 historical DB rows from when it was wired remain (status `usajobs|usajobs|292`).
- `job-scraper/tests/test_usajobs_spider.py` — tested the removed spider.

### Cosmetic
- `_LOW_SIGNAL_HOST_FRAGMENTS` in `spiders/searxng.py:29` — `"beBee.com".lower()` runtime call replaced with literal `"bebee.com"`.

## Verified live (NOT removed despite earlier audit suspicion)

- `job-scraper/job_scraper/fetcher.py` — `fetch_jd_text()` is **alive**, used by `dashboard/backend/services/jd_fetch.py:67` (manual ingest from URL). The earlier audit claim "fetcher.py is dead code" was wrong. What's dead is the `fetch_jd: true` *config flag* — different artifact. Audit doc updated.

## Phase 2 — completed

Legacy HTML/GraphQL paths in Ashby/Lever/Greenhouse spiders removed per `2026-04-18-scraper-freshness-plan.md:2788` (JSON migrations stable 7+ days, commits `a3c2a0f`/`97bbc2e`/`59f7363`).

### Spiders rewritten (JSON-only)
- `spiders/ashby.py` — removed `LIST_QUERY`, `DETAIL_QUERY`, `ASHBY_GQL_URL`, `_use_json_api`, legacy `parse_board()`+`parse_job()` GraphQL paths. Unused `title_matches` import dropped (JSON path doesn't pre-filter titles; hard_filter handles it). 204 → 95 lines.
- `spiders/lever.py` — removed Playwright `custom_settings`, `_use_json_api`, legacy `parse_board()`+`parse_job()` HTML paths, `title_matches` import. 126 → 95 lines. **Frees Playwright dependency for Lever flow.**
- `spiders/greenhouse.py` — removed `_use_json_api`, legacy two-step `parse_board()`+`parse_job()` paths, `title_matches` + `json` imports. 154 → 84 lines.

### Tests updated
- `tests/test_ashby_spider.py` — DELETED (tested removed GraphQL path).
- `tests/test_greenhouse_spider.py` — DELETED (tested removed two-step path).
- `tests/test_ashby_json_migration.py` — dropped `spider._use_json_api = True` line (attribute no longer exists).
- `tests/test_lever_json_migration.py` — dropped `spider._use_json_api = True` line.
- `tests/test_greenhouse_json_migration.py` — dropped `spider._use_json_api = True` line.
- `tests/test_db.py::test_insert_job` — fixed pre-existing assertion. Code path inserts `qa_pending` (db.py:248) but test expected schema-default `pending`. Updated test to match active behavior.

### Dashboard
- `dashboard/backend/services/scraping.py:65-67` — removed `ASHBY_LEGACY_HTML`, `GREENHOUSE_LEGACY_HTML`, `LEVER_LEGACY_HTML` from `_FLAG_KEYS`. Only consumed by status reporting; legacy code paths gone.

## Phase 3 — completed

### Dead config field
- `ScraperConfig.seen_ttl_days` (`config.py:81`) + load_config use — unused. Real ttl is `cfg.scrape_profile.seen_ttl_days = 45` consumed by `pipelines/dedup.py:44`. Removed.

### Dead API exposure
- `dashboard/backend/services/scraper_config.py:102` — `"llm_review": raw.get("llm_review", {})` exposed deleted yaml block to frontend. Removed.
- `dashboard/backend/services/scraper_config.py:172-173` — `_json_to_yaml` round-tripped `llm_review` back to yaml. Removed.
- `dashboard/web/src/views/domains/ops/diagnostics/PipelineEditorView.tsx:44` — TypeScript interface field `llm_review: Record<string, any>` matched removed backend field. Removed.

### Token-set consolidation
- New shared constant `AGGREGATOR_PATH_SEGMENTS` in `spiders/__init__.py` (frozenset of 14 segments).
- `hard_filter.py:_BAD_COMPANY_TOKENS` now derives `AGGREGATOR_PATH_SEGMENTS | {"unknown", ""}`.
- `searxng.py:_extract_company` now imports `AGGREGATOR_PATH_SEGMENTS` directly. Removed inlined `_aggregator_segments` set.

### Cosmetic
- `spiders/aggregator.py:80` — `.replace('—','').replace('—','')` (same codepoint twice) collapsed to single call.

### Verified alive (NOT removed despite earlier suspicion)

- `JobItem.seniority` (`items.py:14`) — alive: DB column `db.py:25`, inserted via `db.py:228`, exposed/filtered by `api/scraping_handlers.py` (lines 68, 106, 118, 130-132, 170, 377, 791) and `dashboard/backend/app.py:1414`. No spider currently *sets* it (used by manual ingest), but field plumbing is required.
- `JobItem.discovered_at` (`items.py:22`) — alive: `db.py:117-121` performs migration `discovered_at` → `created_at`; `db.py:256` accepts as alias on insert.
- `watchers: []` in `config.default.yaml:303` — kept. `dashboard/backend/services/scraper_config.py:141` defensively strips stale `usajobs` watcher entries on save. Empty list is intentional defensive guard, not orphan.

## Phase 3 candidates (still deferred)

### Idle but registered spiders
- `spiders/aggregator.py` (SimplyHired) — registered in `ALL_SPIDERS`, no `simplyhired` entries in `crawl.targets`, plus `simplyhired.com` in `_LOW_SIGNAL_HOST_FRAGMENTS` so searxng filters it out. Unreachable. Leave in case SimplyHired targets get re-added.
- `spiders/generic.py` (RSS / generic HTML) — registered, no `board_type==generic` config rows. Idle.

### Configuration-shape inconsistency (Phase 5 territory)
- Yaml has both `filter.seen_ttl_days: 14` (line 122) and `scrape_profile.seen_ttl_days: 45` (line 554). Only the latter is read by code now. Dashboard config UI still binds to the former. Consolidating means resolving the dashboard binding too.

### Logic duplication
- `config.py:_company_from_board_url` vs `spiders/searxng.py:_extract_company` — both derive company from URL with different rules. Consolidate or document divergence.

## Phase 4 — completed

DB backed up first: `~/.local/share/job_scraper/jobs.db.pre-phase4-backup-20260425-172224` (131 MB snapshot). All mutations done in single transaction.

### Orphan-spider rejected rows purged (426 jobs)
Deleted from `jobs` table where `source IN ('usajobs','remoteok','hn_hiring')` AND `status IN ('rejected','qa_rejected','permanently_rejected')` AND not referenced by `applied_applications`. Cascade-deleted dependents:
- `qa_llm_review_items`: 41 rows
- `tailoring_queue_items`: 9 rows
- `job_state_log`: 19 rows
- `seen_urls`: 424 dangling entries (only where `permanently_rejected=0`)

### Kept (intentional)
- `hn_hiring|lead`: 194 rows (leads partition per `2026-03-26-hn-leads-partitioning` design — user assets)
- `remoteok|lead`: 19 rows (leads)
- 1 `remoteok|permanently_rejected` row referenced by `applied_applications` (excluded from delete)

### Legacy backup tables dropped
- `results_v1_backup` (52 rows, V1 schema artifact)
- `rejected_v1_backup` (1364 rows, V1 schema artifact)
- Triggers `protect_applied_results_before_update`, `protect_applied_results_before_delete` auto-dropped (were on `results_v1_backup`).

### VACUUM run
DB shrank 131 MB → 127 MB (indexes dominate; modest reclaim).

### State after Phase 4
| Metric | Before | After |
|--------|--------|-------|
| jobs total | ~3750 | 3324 |
| orphan-spider rows | 640 | 214 (leads + 1 applied) |
| seen_urls | 3939 | 3515 |
| empty-location rows | 1534 | 1511 |
| Tables | 16 | 14 |

### Phase 4 candidates NOT executed (require data-aware decisions)

- **1511 empty-location rows** still in DB. 79 are `qa_approved` — user must manually review (audit-finding territory). Re-enrichment via ATS API is Phase 5 work; deletion would lose history.
- **1525 → 1101 dangling seen_urls** for empty-location URLs (after Phase 4 reduced 424). Blocks re-scrape for 45 days. Invalidation needs paired re-enrichment to be useful.
- **`quarantine` table** — schema present, not investigated. May contain orphan data.

## Audit-doc correction

`docs/scraper-pipeline-audit.md` originally claimed `fetcher.py` was dead. Wrong. The dead artifact was the `fetch_jd: true` config flag. Audit doc updated.

## Test results

Phase 1 + 2 + 3 + 4 final:
```
88 passed in 0.37s
```

Pre-cleanup baseline was 87 passed + 4 pre-existing failures. Phase 1 net-zero on tests. Phase 2 cleared the 4 pre-existing failures. Phase 3 net-zero. Phase 4 (DB-only) net-zero.

Same 4 failures as pre-cleanup baseline (`test_ashby_spider.py::test_parses_ashby_job_detail`, `test_db.py::test_insert_job`, `test_greenhouse_spider.py::test_parses_greenhouse_job_list`, `test_greenhouse_spider.py::test_parses_greenhouse_job_detail`). All 4 are tests of removed legacy paths — will be addressed in Phase 2.

## Diff summary

```
Phase 1:
job-scraper/job_scraper/config.default.yaml      | -8 lines (fetch_jd, llm_review)
job-scraper/job_scraper/config.py                | -55 lines (USAJobsConfig + 5 stubs + loader)
job-scraper/job_scraper/spiders/usajobs.py       | DELETED
job-scraper/tests/test_usajobs_spider.py         | DELETED
job-scraper/job_scraper/spiders/searxng.py       | 1 line typo

Phase 2:
job-scraper/job_scraper/spiders/ashby.py         | rewritten 204 → 95 lines (JSON-only)
job-scraper/job_scraper/spiders/lever.py         | rewritten 126 → 95 lines (JSON-only, no Playwright)
job-scraper/job_scraper/spiders/greenhouse.py    | rewritten 154 → 84 lines (JSON-only)
job-scraper/tests/test_ashby_spider.py           | DELETED
job-scraper/tests/test_greenhouse_spider.py      | DELETED
job-scraper/tests/test_ashby_json_migration.py   | -1 line (_use_json_api)
job-scraper/tests/test_lever_json_migration.py   | -1 line (_use_json_api)
job-scraper/tests/test_greenhouse_json_migration.py | -1 line (_use_json_api)
job-scraper/tests/test_db.py                     | fix stale assertion
dashboard/backend/services/scraping.py           | -3 lines (_FLAG_KEYS legacy entries)

Phase 3:
job-scraper/job_scraper/config.py                | -2 lines (seen_ttl_days field + loader use)
job-scraper/job_scraper/spiders/__init__.py      | +9 lines (AGGREGATOR_PATH_SEGMENTS shared)
job-scraper/job_scraper/spiders/searxng.py       | -7 lines (inlined set removed, import added)
job-scraper/job_scraper/pipelines/hard_filter.py | -5 lines (set derives from shared, import added)
job-scraper/job_scraper/spiders/aggregator.py    | -1 line (em-dash dedup)
dashboard/backend/services/scraper_config.py    | -3 lines (llm_review exposure + round-trip)
dashboard/web/src/views/domains/ops/diagnostics/PipelineEditorView.tsx | -1 line (llm_review interface field)

Docs:
docs/scraper-pipeline-audit.md                   | fetcher.py correction
docs/scraper-pipeline-cleanup.md                 | NEW
```

Net code reduction: ~280 lines deleted, 4 pre-existing test failures cleared, 0 regressions.

Phase 4 (DB):
- 426 orphan-spider rejected jobs deleted
- 69 dependent rows cascaded (qa_llm_review_items + tailoring_queue_items + job_state_log)
- 424 dangling seen_urls cleaned
- 2 legacy V1 backup tables dropped (1416 rows)
- 4.85 MB reclaimed via VACUUM
- Backup file at `~/.local/share/job_scraper/jobs.db.pre-phase4-backup-20260425-172224` (131 MB snapshot for rollback)
