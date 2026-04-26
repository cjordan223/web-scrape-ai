# Scraper Phase 5 — Audit-Finding Repairs

**Date:** 2026-04-25
**Scope:** Implement the bug fixes documented in `scraper-pipeline-audit.md`. Stops EU/non-US/non-remote jobs from reaching `qa_approved` via the searxng discovery path.
**Tests:** 93 passed (was 88 + 5 new defensive tests).

## Layer 1 — Defensive hard_filter gates (executed)

Failure mode: `searxng` emits items with empty `location` and search-snippet `jd_text`. Original `hard_filter` short-circuited geo + remote checks on missing data, silently passing.

### Changes in `pipelines/hard_filter.py`

1. **`_EU_EQUALITY_MARKER_PATTERN`** — new regex matching German/EU statutory equality markers `(m/f/d)`, `(w/m/d)`, `(f/m/d)`, `(m/w/d)`, `(d/f/m)` etc.

2. **`_check_title_geo(title, allow_canada)`** — new function. Rejects titles containing:
   - EU equality markers
   - Any token in `_NON_US_PATTERN` (Berlin, London, Barcelona, Tokyo, ...) without a paired US signal
   - Title-only check, runs even when location/JD are empty

3. **`_is_non_us_only`** — fail-closed when `require_us=true` AND location is empty AND JD has no US signal. Previously returned None silently. Now returns `"Empty location and no US signal (enrichment missing)"`.

4. **`_check_remote`** — fail-closed when location is empty AND JD has no remote signal. Previously line 213-215 only fired when location was non-empty. Now also catches the empty-location case.

5. **Domain blocklist URL-path matching** — previously `domain in host` only. Now also checks if the blocked domain's first token (e.g. `jobgether` from `jobgether.com`) appears as a URL path segment. Catches `jobs.lever.co/jobgether/...`.

6. **`process_item`** — wired `title_geo` gate between `title_blocklist` and `content_blocklist`.

### Verified against the three reported EU jobs

| ID | Title | Now rejected at |
|----|-------|----------------|
| 7449 | "Senior Platform Engineer (m/f/d) @ bunch" | `title_geo` (EU marker) |
| 7448 | "Senior Security Engineer @ Abound" | `geo_non_us` (empty loc, no US JD signal) |
| 7439 | "Senior security Engineer - Emburse - Lever" | `geo_non_us` (empty loc, no US JD signal) |

Plus #7438 "Senior DevOps Engineer - Jobgether - Lever" → `domain_blocklist` (jobgether path-segment).

### Tests added (5)

- `test_eu_marker_in_title_rejected`
- `test_eu_city_in_title_rejected`
- `test_empty_location_with_no_us_signal_rejected`
- `test_empty_location_with_us_jd_signal_passes_geo`
- `test_aggregator_path_on_legit_ats_rejected`

Three pre-existing tests updated to set `location="Remote, USA"` (they previously passed by accident on missing-data short-circuit; now require explicit US signal).

## Layer 2 — Ashby spider workplace fields wired (executed)

Ashby JSON API returns `workplaceType` (`"Onsite"`/`"Hybrid"`/`"Remote"`), `isRemote` (boolean), and `address.postalAddress.addressCountry`. Previously ignored.

### Changes in `spiders/ashby.py:parse_board_json`

Composes a richer `location` string from `location` + `addressCountry` + `workplaceType` + (if `isRemote=True`) explicit `"Remote"`. Downstream geo/remote gates now have explicit signal even when the bare `location` field is just a city name.

Existing fixture test still passes (location field already had "Remote - United States").

## Layer 4 — LLM relevance prompt geo signal (executed)

`pipelines/llm_relevance.py:_build_prompt` updated. Persona card had no geo/remote requirement; LLM gate accepted on title relevance alone. Now prompt includes:

> HARD REQUIREMENTS (reject if violated): the role must be (a) based in the United States, and (b) fully remote. EU-only, UK-only, hybrid, in-office, or unspecified-location postings are reject. Titles containing '(m/f/d)', '(w/m/d)', '(f/m/d)' or named EU/APAC cities are reject regardless of snippet.

Treats geo + remote as hard gates orthogonal to persona fit.

## Layer 3 — Searxng ATS-aware enrichment (DEFERRED)

Lower priority now that Layer 1 fail-closes. The architectural fix is bigger:

- searxng spider detects host matches `_TRUSTED_BOARD_PATTERNS` (Lever/Ashby/Greenhouse/Workable)
- yields `scrapy.Request` to the ATS JSON API instead of yielding raw `JobItem`
- callback parses API response, fills location/jd_html/workplaceType, then yields enriched `JobItem`

Recovers items that Layer 1 would now false-reject (legit US-remote roles whose search snippet happens to lack explicit US signal). Without it, expect higher reject volume from the discovery tier.

Implementation hint:
- Lever single-posting endpoint: `https://api.lever.co/v0/postings/{company}/{id}` (alive, returns full JSON for one job)
- Greenhouse single-posting: `https://boards-api.greenhouse.io/v1/boards/{org}/jobs/{id}` (alive)
- Ashby: no per-job posting-api endpoint. Either fetch full board (cache per org) or fall back to GraphQL `ApiJobPosting` query.

## LLM gate fail-open scope (DEFERRED)

`pipelines/llm_relevance.py:109-112` latches `mode=FAIL_OPEN` for the rest of the run after 3 consecutive timeouts. Per-run latch hides degradation. Recommended:
- Per-item retry budget instead of run-wide latch
- Surface mode in `runs.gate_mode` table (already exists; populate)
- Dashboard alert when fail_open fires

Audit found no recent fail-open events, so this is preventative not corrective.

## Operational impact

- **Existing 79 `qa_approved` empty-location jobs** stay until manually reviewed. New filter is forward-only — does not auto-reclassify historical rows. User must manually re-triage these via dashboard.
- **Going forward**, all empty-location items reject at `geo_non_us` or `not_remote`. Visible in dashboard rejected lane.
- **Risk**: legit US-remote searxng items with poor snippets now reject. Layer 3 (deferred) recovers these. Until then, expect ~10-20% drop in net-new accepted items from discovery tier — pure recall hit, all current acceptance was unsafe anyway.

## Files changed

```
job-scraper/job_scraper/pipelines/hard_filter.py    | +60 lines (title_geo, fail-closed, path-segment)
job-scraper/job_scraper/pipelines/llm_relevance.py  | +6 lines  (geo-required prompt)
job-scraper/job_scraper/spiders/ashby.py            | +18 lines (workplace/country/isRemote merge)
job-scraper/tests/test_pipelines.py                 | +85 lines (5 new tests + 3 fixed)
```

## Test results

```
93 passed in 0.37s
```

(was 88 passed pre-Phase-5, +5 new tests.)
