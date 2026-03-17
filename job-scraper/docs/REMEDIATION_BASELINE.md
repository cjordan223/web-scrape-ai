# Scraper Remediation Baseline

Last updated: 2026-03-15 23:37:00 PDT

## Purpose

Track targeted scraper hardening work, what changed, why it changed, and what we observed after each controlled validation run.

## Active Work Log

### 2026-03-15 23:26:50 PDT

Status: started

Comments:
- Created remediation baseline document.
- Starting initial hardening pass based on controlled LLM scrape review.
- First targets:
  - prevent obvious non-technical roles from depending on LLM review for rejection
  - reduce false negatives from unconditional `clearance` blocklist hits
  - preserve the existing controlled scrape harness for before/after comparison

## Baseline Findings Before Patches

### 2026-03-15 23:26:50 PDT

Status: recorded

Comments:
- Controlled dry-run with LLM enabled produced:
  - raw results: 5
  - deduped: 5
  - accepted: 1
  - rejected: 4
- Search discovery produced 0 hits in the constrained run; crawl produced all 5 candidates.
- An `Account Executive` role reached rule-based acceptance and was only stopped by LLM review.
- A relevant `Infrastructure Engineer` role was rejected because the JD contained the term `clearance`.

## Planned Patches

### 2026-03-15 23:26:50 PDT

Status: queued

Comments:
- Add an explicit rule-based guardrail for obvious non-technical titles.
- Make `clearance` handling more contextual so we reject explicit clearance requirements instead of any incidental mention.
- Re-run the controlled dry-run and compare candidate outcomes.

## Patch Log

### 2026-03-15 23:28:27 PDT

Status: implemented

Comments:
- Added explicit rule-based rejection for obvious non-technical titles such as `account executive`, `customer success`, `business development`, `recruiting`, `marketing`, and `head of growth`.
- Changed `clearance` handling from unconditional substring matching to contextual requirement matching so incidental mentions no longer auto-reject.
- Expanded title cleanup to split concatenated camel-case board artifacts and collapse immediate repeated tokens.
- Validation pending on the same controlled LLM scrape harness used for the baseline run.

### 2026-03-15 23:29:51 PDT

Status: follow-up patch

Comments:
- First rerun showed the non-technical title signal was still only soft because `apply_filters` does not hard-fail on `title_role` misses by default.
- Added an explicit early return when `title_role` identifies an obvious non-technical title.
- Expanded seniority detection to catch `head`, `vice president`, `vp`, and `chief` style management titles earlier.
- Tightened title cleanup to better collapse crawl artifacts like `Engineer Engineering`, with validation still pending on full Ashby-style title metadata.
- Re-running the same controlled scrape after this follow-up patch.

### 2026-03-15 23:34:20 PDT

Status: validation retry discarded

Comments:
- First title-cleanup validation retry accidentally fell back to the default SQLite DB because `JOB_SCRAPER_DB` was not exported across the full shell command.
- That run deduped to `0` unseen jobs and was not used for comparison.
- Removed the accidental no-op `runs` row (`805dd8117907`) from the default DB.

### 2026-03-15 23:37:00 PDT

Status: validated

Comments:
- Re-ran the same controlled dry-run against a fresh throwaway DB after exporting `JOB_SCRAPER_DB` correctly.
- Result stayed stable at `raw=5`, `dedup=5`, `accepted=1`, `rejected=4`, `quarantined=0`.
- Canonical titles are now clean in logs, LLM prompts, and output tables:
  - `Software Engineer`
  - `Infrastructure Engineer`
- Preserved dropped title metadata as filter and LLM context, so `Remote` and `United States` still contribute to remote/location scoring without polluting the stored title.
- Confirmed rule-based rejection now stops obvious non-technical titles before LLM review:
  - `Account Executive - Commercial Growth`
  - `Account Executive - Federal Growth`
  - `Head of Growth`
- `Infrastructure Engineer` is still rejected for `blocked: clearance requirement`, which remains an open tuning item rather than a regression from this patch set.
- Search discovery is still underperforming in the constrained harness:
  - SearXNG queries: `0`
  - Ashby crawl links: `5`
  - Greenhouse crawl links: `0`
