# Scraper Freshness & Quality — Design

**Issue:** [#23 — Scraper freshness is unreliable; SearXNG path regresses between duplicate churn and over-filtering](https://github.com/cjordan223/TexTailor/issues/23)
**Date:** 2026-04-18
**Status:** Design approved, pending user review before plan generation.

---

## 1. Problem

Consecutive scrape runs oscillate between two failure modes:

1. **Duplicate churn** — the static ATS board roster is crawled every run; most yielded URLs have been seen before and are dropped by dedup. Runs complete "successfully" with near-zero net-new inventory.
2. **Over-filtering** — when SearXNG quality filters tighten, junk aggregator noise drops but volume collapses with it; fresh leads become sparse.

Tightening one side has repeatedly regressed the other. Operator confidence is low because a run can be technically successful but operationally ineffective.

## 2. Goals

Locked constraints that drive all numbers below:

- **Cadence:** every 6 hours (4 runs/day). Treated as a versioned architectural decision, not a runtime knob — dedup TTL, rotation groups, and per-run budgets all derive from it.
- **Yield target:** 50 net-new stored jobs/day (≈13/run). Headroom of roughly 2× against the realistic source ceiling (~55–110/day).
- **Quality floor:** ≥80% of stored jobs match the operator's persona (security / platform / AI engineering, remote US, ≤5 YOE, ≥$100k) without needing aggressive post-filtering in QA.
- **Reliability:** no empty runs unless every candidate URL is genuinely still within the dedup TTL window.
- **Freshness & quality are tuned independently.** Changes to the discovery path must not regress the workhorse path, and vice versa.

### Non-goals

- A full web UI for scheduling (config-driven cron only).
- LinkedIn Jobs API, YC Work at a Startup, Wellfound ingestion.
- Distributed scheduling or multi-node scraping.
- Catch-up / backfill for missed scheduled runs.

## 3. Architecture

**Source tiers are first-class.** Every spider declares its tier. Pipeline routing, rotation logic, scheduler dispatch, and metrics all branch on tier.

| Tier | Purpose | Spiders | Landing |
|---|---|---|---|
| **workhorse** | Reliable, high-signal, known-good companies | `ashby`, `greenhouse`, `lever`, `workable` (new) | → `pending` (main QA) |
| **discovery** | Breadth, unknown-company detection | `searxng` | LLM gate → `pending` if accepted, else `rejected` |
| **lead** | Low-structure, thin JD, manual browsing | `hn_hiring`, `remoteok` | → `lead` (separate bucket) |

### Module layout

```
job_scraper/
  tiers.py                       # NEW: tier enum, spider→tier registry
  scrape_profile.py              # NEW: loads locked cadence + derived TTL + rotation groups
  pipelines/
    llm_relevance.py             # NEW: LLM gate (discovery-tier only)
    storage.py                   # MODIFIED: tier-aware status routing
    dedup.py                     # TTL now sourced from scrape_profile
  spiders/
    workable.py                  # NEW
    ashby.py, greenhouse.py, lever.py   # MIGRATED to JSON APIs
    searxng.py                   # tier=discovery; reads rotation from scrape_profile
    hn_hiring.py, remoteok.py    # tier=lead (declarative only)

dashboard/backend/services/
  scrape_scheduler.py            # NEW: APScheduler tier-aware dispatch
```

### Config additions (`config.default.yaml`)

```yaml
scrape_profile:
  cadence: "0 */6 * * *"         # versioned — changes are migrations
  rotation_groups: 4             # derived from cadence; roster cycles / 24h
  seen_ttl_days: 45              # must exceed rotation cycle × 2
  discovery_every_nth_run: 2     # SearXNG fires every other run
  target_net_new_per_run: 13     # 50/day ÷ 4 runs
  llm_gate:
    enabled: true
    endpoint: "http://localhost:8080/v1/chat/completions"    # MLX default
    model: "qwen3-4b-instruct-mlx"
    fallback_endpoint: "http://localhost:11434/v1/chat/completions"
    fallback_model: "qwen2.5:3b-instruct"
    accept_threshold: 5
    max_calls_per_run: 150
    timeout_seconds: 10
    fail_open: true
```

**Invariant:** `scrape_profile` is the single source of truth. `dedup.py`, `scheduler.py`, and spider rotation all read from it. Pydantic validators reject TTL days less than `(rotation_cycle_hours × 2) / 24`.

## 4. Cadence & Rotation Math

Derivations from the locked 6h cadence:

| Derived value | Formula | Value |
|---|---|---|
| Runs per day | 24 / 6 | **4** |
| Target net-new per run | 50 / 4 | **~13** |
| Rotation groups | runs per 24h | **4** |
| Full roster cycle | groups × cadence | **24h** |
| Dedup TTL (min safe) | cycle × 2 | ≥ 48h |
| Dedup TTL (chosen) | cycle × ~45 | **45 days** |
| Discovery fires | every 2nd run | **2/day** |

### Rotation strategy per tier

- **workhorse** — roster partitioned into 4 groups via stable hash of `(run_id, company_url)`. Run N hits `group = N mod 4`. A company is crawled once every 24h regardless of roster size; adding a company does not increase per-run time.
- **discovery** — fires every 2nd run (2× per day). On a firing run, `diversified_subset` picks 20 of ~60 queries; every query runs at least once per ~3 days. Time-range rotation (`day`/`week`/`month`) continues as today.
- **lead** — runs every tick; cheap by construction (HN parses cached thread, RemoteOK is one API request).

### Scheduler tick pattern

```
run at 00:00  → workhorse group 0 + discovery + leads
run at 06:00  → workhorse group 1 + leads
run at 12:00  → workhorse group 2 + discovery + leads
run at 18:00  → workhorse group 3 + leads
```

### Failure semantics

Scheduled runs that fail (network, SearXNG down, disk full) are marked failed; the scheduler proceeds at the next tick. **No catch-up runs** — catch-up would defeat rotation and could flood the LLM gate. Operators can manually target a specific group/tier via `/api/scrape/run?tier=workhorse&group=N` if needed.

## 5. LLM Relevance Gate (discovery tier only)

New pipeline stage `LLMRelevancePipeline`, inserted between `hard_filter` and `storage`. Pass-through for non-discovery items.

```
text_extraction → dedup → hard_filter → [llm_relevance]* → storage
                                         *discovery-tier only
```

### Model

- **Default:** Qwen 3 4B Instruct via MLX (non-thinking variant, ~100–300ms/result on Apple Silicon).
- **Fallback:** Ollama `qwen2.5:3b-instruct`.
- **Separation:** deliberately distinct from `TAILOR_LLM_MODEL`. Own endpoint, own file-lock mutex. Gate and tailoring never contend.

### Prompt contract

Inputs per call: title, company, snippet, board, URL host, location (when present), and a cached persona card (~400 tokens) derived from `tailoring/persona/`: target roles, exclusions (staff/manager/clearance), salary band, remote-US requirement.

Output: strict JSON.

```json
{
  "score": 7,
  "verdict": "accept",
  "reason": "Cloud security eng, remote US, series B fintech — strong match",
  "flags": ["remote_us_confirmed", "seniority_ok"]
}
```

### Gating logic

| Verdict | Score | Outcome |
|---|---|---|
| `accept` | any | → `pending` (QA) |
| `uncertain` | ≥ threshold (5) | → `pending` |
| `uncertain` | < threshold | → `rejected`, stage=`llm_relevance` |
| `reject` | any | → `rejected`, stage=`llm_relevance` |

### Cost guardrails

- **Batch cap per run** (`max_calls_per_run`, default 150). Once hit, remaining items get a rules-only decision (accept if title-keyword-match + trusted host else reject) with `flags: ["gate_overflow"]`.
- **Timeout per call**: 10s. Three consecutive timeouts trip a circuit breaker — the stage fails open (accept) for the remainder of the run and writes `runs.gate_mode = 'fail_open'`.
- **Prompt cache**: persona card is the cacheable prefix; result fields are the suffix. Exploits existing KV cache on both MLX and Ollama.

### Failure modes

- LLM endpoint unreachable → fail-open, log + operator alert (matches existing `llm_review.fail_open: true` pattern in QA).
- Malformed JSON → one retry with stricter prompt, then treat as `uncertain` score 5.
- Persona directory missing → startup error; never silently degrade the prompt.

## 6. Source Expansion

### 6a. ATS JSON API migration (existing workhorse spiders)

Replace HTML scraping with public JSON endpoints. Unlocks roster growth to 200+ companies without per-run time blowup and eliminates flaky CSS selectors.

| ATS | Endpoint | Added fields |
|---|---|---|
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true` | compensation tiers, `employmentType`, `workplaceType`, `locationName` |
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true` | departments, offices, full JD content inline |
| Lever | `https://api.lever.co/v0/postings/{company}?mode=json` | `workplaceType`, categories, salary range |

**Migration approach:** one PR per ATS. Keep HTML path behind `legacy_html: true` config flag for one release cycle. Drift test compares JSON-path output against stored HTML-path output before flip. Low-risk rollback by clearing the flag.

### 6b. Workable spider (new source, workhorse tier)

Workable is another major ATS with a public JSON API (`https://apply.workable.com/api/v3/accounts/{company}/jobs`). Same pattern as the migrated three. Opens ~30–50 additional companies — notably security-adjacent and mid-market SaaS not on Ashby/Greenhouse/Lever.

Detection is already present in `_TRUSTED_BOARD_PATTERNS`, so SearXNG currently surfaces Workable postings as discovery leads. A direct workhorse spider upgrades those to full-JD entries.

### Explicitly out of scope

- **LinkedIn Jobs API** — rate-limited, cookie-dependent. SearXNG captures `linkedin.com/jobs/view` via snippets; leave at discovery tier.
- **YC Work at a Startup / Wellfound** — bespoke scraping effort; marginal roster over what's already covered.
- **USAJobs** — persona excludes clearance work; `usajobs.gov` already in `domain_blocklist`.

### Roster growth workflow

Adding a company post-merge: append one entry to `crawl.targets`, redeploy. Rotation auto-includes it in the next group cycle, dedup TTL handles the first crawl, LLM gate is not involved (workhorse bypasses the gate).

## 7. Metrics & Run Visibility

### New table: `run_tier_stats`

One row per `(run_id, tier, source)`. Written incrementally during the run, committed at `close_spider`.

```sql
CREATE TABLE run_tier_stats (
    run_id TEXT NOT NULL,
    tier TEXT NOT NULL,                   -- workhorse | discovery | lead
    source TEXT NOT NULL,                 -- spider name
    raw_hits INTEGER DEFAULT 0,           -- items yielded before any pipeline
    dedup_drops INTEGER DEFAULT 0,        -- dropped by seen_urls TTL (not persisted)
    filter_drops INTEGER DEFAULT 0,       -- persisted with status='rejected' by hard_filter
    llm_rejects INTEGER DEFAULT 0,        -- persisted with status='rejected' by LLM gate
    llm_uncertain_low INTEGER DEFAULT 0,  -- uncertain < threshold → persisted rejected
    llm_overflow INTEGER DEFAULT 0,       -- rules-only fallback path taken
    stored_pending INTEGER DEFAULT 0,
    stored_lead INTEGER DEFAULT 0,
    duration_ms INTEGER,
    PRIMARY KEY (run_id, tier, source)
);
```

### Extensions to existing `runs` table

- `net_new INTEGER` — `stored_pending + stored_lead` across tiers
- `gate_mode TEXT` — `normal` | `overflow` | `fail_open`
- `rotation_group INTEGER` — which workhorse group fired

Filter-drop breakdown is stored in the existing `rejected` table via `rejection_stage`; new stage value `llm_relevance` is added to the existing set (no schema change). `raw_hits = dedup_drops + filter_drops + llm_rejects + llm_uncertain_low + stored_pending + stored_lead` holds as an invariant; `stored_rejected` from the old model is superseded by the stage-specific rejection counters.

**`gate_mode` precedence within a single run:** `fail_open` > `overflow` > `normal`. If the circuit breaker trips at any point during a run, the run is recorded as `fail_open` even if earlier calls also overflowed the batch cap.

### Dashboard surfaces

Extends `/ops/metrics` — no new route.

1. **Per-run card** — net-new / target, `gate_mode` badge, rotation group, tier breakdown bar.
2. **7-day rollup** — daily net-new vs. 50/day target line, stacked by tier.
3. **Source health table** — per source: avg `raw_hits`, drop-rate at each stage, % of runs contributing ≥1 net-new in last 7d.
4. **Gate-overflow alert** — banner if last 3 runs hit `gate_overflow`.

### API addition

`GET /api/scraper/metrics/tier-stats?since=7d` returns the rollup. Single new endpoint; `/api/overview` stays backwards-compatible.

## 8. Scheduler

### Library

**APScheduler 3.x** `AsyncIOScheduler`. Single `CronTrigger` from `scrape_profile.cadence`. Runs inside the FastAPI/uvicorn event loop.

### Startup wiring

```python
# dashboard/backend/server.py
@app.on_event("startup")
async def _init_scheduler():
    if os.getenv("TEXTAILOR_SCRAPE_SCHEDULER", "0") == "1":
        await scrape_scheduler.start()

@app.on_event("shutdown")
async def _stop_scheduler():
    await scrape_scheduler.stop()
```

Feature flag **`TEXTAILOR_SCRAPE_SCHEDULER=1`** — opt-in, matches existing `TEXTAILOR_MANAGE_MLX` pattern. Default off so dev runs don't auto-scrape.

### Tier-aware dispatch

```python
async def _tick():
    run_index = _next_run_index()
    group = run_index % profile.rotation_groups
    fire_discovery = run_index % profile.discovery_every_nth_run == 0
    tiers = ["workhorse", "lead"] + (["discovery"] if fire_discovery else [])
    await dispatch_scrape(tiers=tiers, rotation_group=group)
```

`dispatch_scrape(tiers, rotation_group)` is a new internal helper that both the existing `POST /api/scrape/run` endpoint and the scheduler delegate to. Manual runs accept optional `tiers` and `group` query params; defaults give a scheduled-tick-equivalent run.

### State & concurrency

- **Run-index counter**: derived from `max(rotation_group)` in `runs` — no new table.
- **No catch-up**: missed ticks stay missed; rotation resumes at next tick.
- **Concurrency guard**: if a prior scheduled run is still active when a tick fires, the new tick logs `skipped: concurrency` and does not dispatch. Uses existing `/api/scrape/runner/status` active check.

### Observability

- Log line per tick: `scheduler: tick run_index=12 group=0 tiers=[workhorse,lead,discovery] result=dispatched`.
- `/ops/metrics` adds "Next run at" widget reading APScheduler's next-run-time.
- **No UI to edit cadence.** Architectural per-project decision; edits require config change + restart.

### Local dev

- Flag off by default.
- One-shot CLI: `python -m job_scraper tick --tier workhorse --group 2` runs a single tier-aware tick locally.

## 9. Migration Order

Each step independently mergeable and reversible. Additive schema changes only.

1. **`scrape_profile` + `tiers.py` foundation** — config section, enum, registry. No behavior change.
2. **Metrics schema** — `run_tier_stats` table, `runs` column additions, stats writer in pipelines. No behavior change.
3. **Tier-aware storage routing** — generalize HN lead-routing via `tiers.py`. RemoteOK moves from pending to lead.
4. **Workhorse rotation** — Ashby/Greenhouse/Lever read `rotation_group`, filter targets by hash. TTL → 45 days.
5. **LLM relevance gate** — `llm_relevance.py` inserted; disabled by default via config.
6. **Discovery tier alternation** — `searxng` respects `discovery_every_nth_run` when triggered from tier-dispatch.
7. **Workable spider** — new spider + targets config.
8. **ATS JSON migration** — one PR per ATS (Ashby → Greenhouse → Lever), `legacy_html` flag, drift test before flip.
9. **Scheduler** — `scrape_scheduler.py`, feature-flagged off.
10. **Metrics dashboard surfaces** — `/ops/metrics` updates.

Steps 1–4 form a low-risk refactor tranche. 5–8 deliver quality/breadth. 9–10 light up the continuous experience.

## 10. Testing Strategy

- **Unit tests per new module**: `test_scrape_profile.py` (validator rejects bad TTL), `test_tiers.py` (registry resolution), `test_llm_relevance.py` (verdict parsing, gate-overflow, fail-open), `test_scheduler.py` (tier dispatch for 8 simulated run indexes).
- **Spider integration tests** with recorded HTTP fixtures (existing pattern in `tests/test_searxng_spider.py`). New fixtures for Workable and each ATS JSON endpoint.
- **ATS migration drift test**: HTML fixture + JSON fixture per ATS; assert same URLs emitted and title/company/location parity within tolerance.
- **End-to-end smoke** (`scripts/smoke_scrape.sh`): one cycle against local SearXNG + real (rate-limited) ATS endpoints; asserts ≥1 workhorse and ≥1 discovery stored and run completes <5 min.
- **No load tests for the LLM gate** — cost guardrails (batch cap, timeout, circuit breaker) are the protection; their triggers have unit tests.

## 11. Rollback Posture

- Each migration step is a single commit; schema changes are additive (new tables/columns only), so reverts require no forward migration.
- Feature flags on two steps:
  - `scrape_profile.llm_gate.enabled` (step 5)
  - `TEXTAILOR_SCRAPE_SCHEDULER` env var (step 9)
- `run_tier_stats` left in place after a revert is harmless (write-only from scrape path).

## 12. Success Criteria

Measurable on `/ops/metrics` after one week of continuous scheduling:

1. ≥5 of 7 days produce ≥35 net-new stored_pending + stored_lead (70% of 50/day target; leaves room for quiet periods).
2. SearXNG `raw_hits → stored_pending` ratio ≥ 20% after LLM gate.
3. Workhorse tier contributes ≥40% of net-new (proves rotation works and discovery is not overweight).
4. Zero empty runs unless every candidate URL is legitimately within the dedup TTL window.
5. `gate_overflow` rate < 5% of discovery-firing runs.

## 13. Open Risks

- **Qwen 3 4B may over-accept or over-reject.** Threshold is a tunable config knob (`accept_threshold`). First week will likely need adjustment based on observed stored-pending volume and operator QA rejection rate.
- **ATS JSON endpoints are undocumented.** If an ATS changes their shape without notice, the `legacy_html` flag provides an immediate rollback path per ATS while we adapt.
- **Roster expansion is operator-paced.** The architecture supports 200+ companies, but net-new yield only grows with roster size. Without ongoing roster growth, yield will plateau at ~50/day on the current roster.
- **No catch-up semantics.** If the dashboard process is down at a scheduled tick, that run is lost. Given the 6h cadence and 24h rotation cycle, one missed run means one roster quarter is crawled 12h late, not lost.
