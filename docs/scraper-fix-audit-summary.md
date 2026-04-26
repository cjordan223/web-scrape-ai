# Scraper Fix — Audit Summary

**Date:** 2026-04-25
**Branch:** `main`
**Commits:** `cb55182` (cleanup), `de4da9e` (fix)

## Original issue

User reported 3 jobs reaching `qa_approved` despite `require_us_location=true` and `require_remote=true`:

- `#7449` Senior Platform Engineer (m/f/d) @ bunch — Berlin (verified via Ashby API)
- `#7448` Senior Security Engineer @ Abound — London, UK (verified via Ashby API)
- `#7439` Senior Security Engineer — Emburse — Barcelona, hybrid (verified via Lever API)

## Root cause

Searxng spider (`spiders/searxng.py`) emits items with empty `location` and a 150-char search-snippet `jd_text`. Original `hard_filter` had four bypasses that silently passed missing data:

1. `_is_non_us_only` line 170: `if require_us and normalized_location` — empty location skipped check entirely.
2. `_check_remote` line 217: `if loc and not _REMOTE_PATTERN.search(loc)` — empty location skipped remote check.
3. No title-level geo gate. EU equality marker `(m/f/d)` and embedded city names like "Berlin" never inspected.
4. Domain blocklist matched host substring only — `lever.co/jobgether/...` slipped past `jobgether.com` rule.

Plus contributing factors: persona card had no geo signal, so LLM gate accepted on title relevance alone. Ashby spider ignored `workplaceType` / `isRemote` / `addressCountry` fields returned by API.

## What was changed

### Cleanup (commit `cb55182`)

20 files, +268/-490 LOC. Tests: 87+4-failing → 88 passing.

- **Phase 1**: removed dead yaml flags (`fetch_jd:`, `llm_review:`); deleted `USAJobsConfig` + 5 backward-compat stub classes (`FilterConfig`, `QueryTemplate`, `WatcherConfig`, `LLMReviewConfig`, `CrawlTarget`); removed unregistered `usajobs.py` spider + its test; fixed `"beBee.com".lower()` typo.
- **Phase 2**: deleted legacy HTML/GraphQL paths in `ashby.py`/`lever.py`/`greenhouse.py` (JSON migrations stable since 2026-04-18 per `2026-04-18-scraper-freshness-plan.md:2788`). Drops Playwright dep for Lever. Removed `ASHBY_LEGACY_HTML`/`GREENHOUSE_LEGACY_HTML`/`LEVER_LEGACY_HTML` env-var pass-throughs from `dashboard/backend/services/scraping.py`. Cleared 4 pre-existing test failures.
- **Phase 3**: removed dead `ScraperConfig.seen_ttl_days` (real ttl is `cfg.scrape_profile.seen_ttl_days`); stripped `llm_review` round-trip in `services/scraper_config.py` + matching TS interface field; consolidated aggregator path-segment tokens into shared `AGGREGATOR_PATH_SEGMENTS` frozenset (used by `hard_filter._BAD_COMPANY_TOKENS` and `searxng._extract_company`); em-dash double-replace dedup.

### Repair (commit `de4da9e`)

5 files, +409/-21 LOC. Tests: 88 → 93 passing.

- `hard_filter.py`:
  - `_check_title_geo()` — new function. Rejects titles with German/EU equality markers `(m/f/d)`, `(w/m/d)`, `(f/m/d)`, `(m/w/d)` or non-US city tokens (Berlin, London, Barcelona, ...). Runs even when location/JD empty.
  - `_is_non_us_only` fail-closes when `require_us=true` AND location empty AND JD has no US signal.
  - `_check_remote` fail-closes when location empty AND JD has no remote signal.
  - Domain blocklist now matches URL path segments (catches aggregators hosted on legit ATS).
  - New `title_geo` stage wired into `process_item` between `title_blocklist` and `content_blocklist`.
- `llm_relevance.py`: prompt now declares hard US/remote requirements at top.
- `ashby.py:parse_board_json`: composes location from `location` + `addressCountry` + `workplaceType` + (if `isRemote=True`) `"Remote"`.
- 5 new tests: `test_eu_marker_in_title_rejected`, `test_eu_city_in_title_rejected`, `test_empty_location_with_no_us_signal_rejected`, `test_empty_location_with_us_jd_signal_passes_geo`, `test_aggregator_path_on_legit_ats_rejected`. 3 existing tests updated to set explicit US location (had passed accidentally on the missing-data short-circuit).

## DB hygiene

DB backed up before each mutation step:
- `jobs.db.pre-phase4-backup-20260425-172224` (131 MB) — orphan-spider purge
- `jobs.db.pre-backfill-20260425-182708` (127 MB) — backfill rejection

### Phase 4 (transactional)

- 426 orphan-spider rejected rows deleted (`source IN ('usajobs','remoteok','hn_hiring')` AND `status IN ('rejected','qa_rejected','permanently_rejected')`, excluding 1 row referenced by `applied_applications`).
- Cascade: 41 `qa_llm_review_items`, 9 `tailoring_queue_items`, 19 `job_state_log` rows.
- 424 dangling `seen_urls` cleaned (only `permanently_rejected=0`).
- Dropped V1 backup tables: `results_v1_backup` (52 rows), `rejected_v1_backup` (1364 rows).
- VACUUM: 131 MB → 127 MB.

### Backfill against new filter

Ran `HardFilterPipeline` from `de4da9e` against existing 138 `qa_approved` rows. 47 reclassified to `rejected`:

| Stage | Count |
|-------|------:|
| `geo_non_us` | 20 |
| `not_remote` | 18 |
| `domain_blocklist` | 6 |
| `title_geo` | 3 |

Reported jobs all caught:
- `#7449` → `title_geo` ("EU equality marker in title (m/f/d-style)")
- `#7448` → `geo_non_us` ("Empty location and no US signal (enrichment missing)")
- `#7439` → `geo_non_us` (same)
- `#7438` → `domain_blocklist` ("Blocked aggregator in path: jobgether.com")

Final dashboard state: 91 `qa_approved`. 32 still have empty `location` but passed legitimately because JD body contained US/remote signals; Layer 3 enrichment (deferred) would surface any hidden EU jobs there.

## Deployment

Ran `./scripts/restart-dashboard.sh`:
- SearXNG Docker container restarted
- Frontend rebuilt (Vite, ~33 chunks)
- Backend restarted (port 8899)
- SearXNG ready (port 8888)
- Scrape scheduler env enabled (`TEXTAILOR_SCRAPE_SCHEDULER=1`)

## Verification commands

```bash
# Tests
cd job-scraper && python -m pytest tests/ -q  # 93 passed

# Confirm reported jobs flipped
sqlite3 ~/.local/share/job_scraper/jobs.db \
  "SELECT id, status, rejection_stage, rejection_reason FROM jobs WHERE id IN (7449,7448,7439,7438);"

# Active-status counts
sqlite3 ~/.local/share/job_scraper/jobs.db \
  "SELECT status, COUNT(*) FROM jobs WHERE status IN ('qa_approved','qa_pending','pending') GROUP BY status;"

# Inspect commits
git log --oneline -2  # cb55182 cleanup, de4da9e fix
```

## Deferred work (not done; documented in `scraper-pipeline-cleanup.md` + `scraper-phase5-repairs.md`)

1. **Layer 3 — searxng ATS-aware enrichment**. When searxng detects a Lever/Ashby/Greenhouse URL, dispatch a JSON API call before yielding `JobItem`. Recovers legit US-remote items the new fail-closed gates may falsely reject. Architectural addition.
2. **LLM gate fail-open scope**. Currently latches `mode=FAIL_OPEN` for rest of run after 3 consecutive timeouts. Should be per-item retry budget and surface in dashboard.
3. **Idle aggregator/generic spiders** registered but no config targets — kept for re-enable.
4. **`filter.seen_ttl_days: 14` (yaml) vs `scrape_profile.seen_ttl_days: 45`** — dashboard config UI still binds former.
5. **`config.py:_company_from_board_url` vs `searxng.py:_extract_company`** — duplicated company-from-URL logic.
6. **1101 dangling seen_urls for empty-location URLs** — not invalidated. Useful only paired with Layer 3 enrichment.
7. **Live-scrape verification** — repairs unit-tested but no end-to-end run yet.

## Files of record

- `docs/scraper-pipeline-audit.md` — diagnosis (140 lines)
- `docs/scraper-pipeline-cleanup.md` — Phase 1-4 record (188 lines)
- `docs/scraper-phase5-repairs.md` — Phase 5 record (111 lines)
- `docs/scraper-fix-audit-summary.md` — this file
