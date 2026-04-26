# Scraper Pipeline Audit — Empty-Location Job Slippage

**Date:** 2026-04-25
**Trigger:** Three EU jobs (#7449 Berlin, #7448 London, #7439 Barcelona) reached `qa_approved`.
**Scope:** `job-scraper/` end-to-end, focus on searxng-discovery path.

## TL;DR

Three slipping jobs are tip of an iceberg. **1089 searxng-source jobs (100%) and 71 lever-source jobs (100%) have empty `location`.** Every downstream gate (hard_filter, llm_relevance, auto_qa_review) silently passes rows with empty location, so the pipeline reports green while shipping European jobs to a US-remote-only candidate.

Root cause is structural: **searxng spider emits unenriched search snippets as if they were full job items**, and every gate downstream noops on missing data instead of failing closed.

## Evidence

| Source | Total | Empty location | Avg JD chars | Real JDs? |
|--------|-------|----------------|--------------|-----------|
| ashby (direct API) | 1941 | 17% | 5669 | yes |
| lever (direct API) | 71 | **100%** | 3166 | partial |
| searxng (discovery) | 1089 | **100%** | 2350 | snippets only |

Verified via Lever/Ashby JSON APIs (`api.lever.co/v0/postings/...`, `api.ashbyhq.com/posting-api/job-board/...`):
- #7439 Emburse → Barcelona, hybrid
- #7448 Abound → London, UK, remote
- #7449 bunch → Berlin, Germany, onsite

DB row `filter_verdicts` for #7449 shows every gate `pass: true`.

## Failure chain (per searxng item)

1. **searxng spider** (`spiders/searxng.py:154`) — emits `JobItem` with `jd_text=snippet`, `jd_html=snippet`, `location` unset. Detects host as Ashby/Lever via `_TRUSTED_BOARD_PATTERNS` (line 32) but **never dispatches to ATS API**.

2. **text_extraction pipeline** (`pipelines/text_extraction.py:22`) — `if len(existing) >= 30: return item`. Snippet (~150 chars) clears 30, short-circuits. Never falls through to fetch.

3. **`fetch_jd: true` config flag is dead.** Pydantic never parsed it; no code path consults it. Removed in Phase 1 cleanup. Note: `fetcher.py:fetch_jd_text()` itself is **alive** — used by `dashboard/backend/services/jd_fetch.py:67` for manual URL ingest. Earlier audit claim "fetcher.py dead" was wrong; corrected here. The function is just not wired into the scraper pipeline.

4. **hard_filter empty-location bypasses:**
   - Line 170 `_is_non_us_only`: `if require_us and normalized_location` — empty location skips US-signal check, returns None (pass).
   - Line 217 `_check_remote`: `if loc and not _REMOTE_PATTERN.search(loc)` — empty loc skips remote-required check.
   - JD-prose path (line 179-189) needs phrases like "located in"/"based in" — search snippets don't contain those.

5. **Title-pattern gap** — no regex against title for German/EU markers `(m/f/d)`, `(w/m/d)`, `(f/m/d)`, `(m/w/d)`, nor for embedded city names (Berlin/London/Barcelona). Title is the **only** signal that survives empty enrichment, and it's barely used.

6. **Domain blocklist is host-substring only** — `jobgether.com` blocked, but `jobs.lever.co/jobgether/...` (jobgether-as-Lever-tenant) slips through. See #7438.

7. **llm_relevance gate** (`pipelines/llm_relevance.py:146`) — prompt fed Title + Company + URL + Location (empty) + 500-char snippet. With location absent, gate reasons from title alone. Plus `fail_open: true`, 10s timeout, 3 consecutive timeouts → `mode=FAIL_OPEN` latches for **rest of run** silently (line 109-112).

8. **auto_qa_review** (`services/auto_qa_review.py`) — funnels `qa_pending` into same manual-LLM-review pathway. Same blind row data. Same approval verdicts. Recent feature (commit `4eadd1f`) compounds blindness by promoting faster.

9. **salary_floor passes empty** — `salary_policy.py` does not `hard_reject` when both `salary_text` and `salary_k` are absent. Default for searxng items.

## Why prior fix did not catch this

Commit `4177c25` "tighten hard_filter to catch non-remote/non-US/aggregator slippers" added `not_remote`, `experience_years`, `company_sanity` gates. **Every new gate depends on populated location/JD.** Empty input → every gate passes. Patch added breadth, not depth on missing-data case.

## Architectural verdict

Scraper has two ingest modes:
- **Direct ATS API** (`crawl.targets`, ~60 companies): full enrichment, location populated.
- **Searxng discovery** (anything else): no enrichment, snippet-only.

Pipeline contract is implicitly "items have location+jd_text". Searxng violates contract. No upstream validation enforces it.

Net effect: every gate is a no-op on the worst data, and gates that nominally protect (geo, remote, salary, experience) silently fail-open.

## Numbers worth tracking

- 51 searxng items reached `qa_approved` (visible to user).
- 754 searxng items reached `qa_rejected` — but on what basis? Title alone (LLM with no location/JD).
- Lever direct spider 71/71 empty location: secondary bug, same family.
- ~60 companies in crawl targets vs full universe → most discovery items go through broken path.

## Suggested fix shape (do not implement yet)

- searxng spider: when `_TRUSTED_BOARD_PATTERNS` matches, dispatch ATS API call (Ashby/Lever/Greenhouse/Workable JSON endpoints), merge `location`/`jd_text`/`workplaceType` before yielding.
- New enrichment-contract check: empty `location` after enrichment attempt → reject with stage `enrichment_failed`, surface in dashboard. Fail-loud, not fail-silent.
- Fix lever spider location extraction (`spiders/lever.py:124`).
- Title-pattern gate runs independent of location data (catches `(m/f/d)`, embedded city names).
- Domain blocklist matches URL path segments, not just host.
- LLM-gate fail-open should expire per-item or surface in dashboard, not silently latch for run.
- Decide on `fetch_jd` flag: wire properly or delete. **Update: deleted in Phase 1 cleanup.**

## Validated against DB (2026-04-25)

Empty-location distribution by source × date confirms the failure profiles differ:

- **searxng = persistent ongoing.** 100-200 empty-loc rows daily, every run, since 2026-04-18.
- **ashby = single-incident.** 323 rows in a 2-minute window on **2026-04-20** (notion 146, cohere 103, supabase 37, semgrep 31, wraithwatch 4, elastic 2). Rows on 2026-04-21/24/25 have populated location ("San Francisco, California", "Tokyo, Japan"). Spider code is fine; one bad run captured null `location` field. Cause unconfirmed.
- **lever = pre-migration legacy.** 71 empty-loc rows from 2026-04-14 to 2026-04-16, before commit `97bbc2e` migrated to JSON API. Current code (`spiders/lever.py:99` `categories.get("location")`) populates correctly — verified against live `api.lever.co/v0/postings/spotify?mode=json` (returns "Toronto", "London", etc.).
- **remoteok = decommissioned.** Spider deleted in current branch.

Live ATS API verification:
- Ashby: 17 fields per job, including `location` (string), `address.postalAddress`, `isRemote`, `workplaceType`, `secondaryLocations`. Spider only consumes `location`. **Workplace/remote flag not used.**
- Lever: `categories.location`, `salaryRange`. Spider only consumes location and salary.

## Persistence trap (new finding)

`seen_urls` table has 3939 rows with TTL **45 days** (`scrape_profile.seen_ttl_days`). Once a URL is captured with empty location, dedup blocks re-emission for 45 days even if the underlying ATS now returns proper location. Confirmed: 146 Notion rows seen 2026-04-20 with empty `location` are now `qa_rejected` and locked out until **2026-06-04**.

This means the 2026-04-20 ashby incident has compounding cost — those rows can't be self-healed by re-crawl. Need explicit backfill or `seen_urls` invalidation for empty-location URLs.

## Filter telemetry (works when input is enriched)

Rejection-stage histogram (cumulative):
- `title_blocklist`: 806 (top filter — seniority works)
- `geo_non_us`: 275 — sub-reasons "London 56", "Tokyo 18", "Sydney 17", "Dublin 16", "Singapore 15", "Europe 14", "Munich 10". Gate fires correctly when location is populated.
- `content_blocklist`: 93 (clearance terms)
- `salary_floor`: 88
- `not_remote`: 87
- `company_sanity`: 27 (post-`4177c25`)
- `llm_relevance`: 20 (very low — gate runs but rarely rejects)
- `experience_years`: 10
- `domain_blocklist`: 10

`llm_relevance: 20` is suspiciously low given 1089+ underspecified searxng items. Either gate is fail-opening or items are passing on title.

## Refuted from prior analysis

- "Lever spider broken" — only legacy HTML rows are bad; current JSON code is correct.
- "Ashby spider has 17% empty-loc systemic bug" — really one-day incident, not systemic.

## Confirmed and unchanged

- searxng spider does no enrichment; `fetch_jd: true` flag was dead config (now removed). `fetcher.py:fetch_jd_text` exists and works but is only wired into dashboard manual ingest, not the scraper.
- hard_filter empty-location bypass (lines 170, 217) is real and is the single biggest leak.
- Title-pattern gate gap, jobgether-on-Lever bypass, salary policy passing empty.

## LLM gate is not the safety net it appears

- Recent runs `runs.gate_mode`: all `normal`, `skipped_by_cadence`, or `no_discovery_items` — no `fail_open` latches in last 10 runs. Gate is functioning, not silently dead. **Refutes prior hypothesis.**
- But cumulative `llm_relevance` rejects = **20** total, vs ~1089 searxng items. **1.8% reject rate.**
- Score distribution among scored searxng items: 240 at score=8, 133 at 6, 79 at 7. Bulk pile up at "accept". Only 20 fall below `accept_threshold=5`.
- Why so permissive? **Persona card has no geo/remote requirement** — `tailoring/persona/identity.md` and `motivation.md` describe interests, working style, frustrations; not a single mention of "US-only" or "remote-only". LLM has no signal to penalize EU jobs.
- Gate evaluates "would this candidate be interested?" not "does this job meet hard requirements?" — orthogonal to hard_filter. Gate accepts on title match. Hard filter passes on empty data. **Two checks, both miss geo.**

## Open questions (still researching)

- Why did 2026-04-20 ashby run capture null `location`? Possible API regression that day or temporary `_use_json_api=False`. Run logs would clarify.
- Workplace flag in Ashby API (`workplaceType: "Onsite"|"Hybrid"|"Remote"`, `isRemote` boolean) is completely ignored by spider. Even with location "San Francisco", a hybrid SF role passes `not_remote` if "remote" appears anywhere in JD. Should be wired through.
- Backfill plan: 51 searxng + 323 ashby + 71 lever empty-loc rows need re-enrichment OR explicit reject-with-`enrichment_failed`. Plus `seen_urls` invalidation so re-crawl can self-heal. Cannot just delete jobs rows — `seen_urls` traps URLs for 45 days.
- Should LLM gate prompt explicitly include "REQUIRED: US-based, fully remote" so it acts as a real safety net? Or keep it as persona-only and lean on enrichment + hard_filter for hard requirements?
