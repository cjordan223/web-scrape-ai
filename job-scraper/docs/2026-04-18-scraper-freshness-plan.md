# Scraper Freshness & Quality — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the design in `2026-04-18-scraper-freshness-design.md` — tiered sources, 6h cadence with derived rotation, LLM relevance gate on SearXNG, Workable ATS, JSON-API migration for Ashby/Greenhouse/Lever, tier-aware metrics, and an in-app scheduler — so background scraping produces ~50 net-new/day at high quality.

**Architecture:** Add `scrape_profile` + `tiers` as first-class objects read everywhere that rotation, dedup, or metrics decisions happen. Insert a discovery-tier-only LLM pipeline stage. Wire an APScheduler tier-aware dispatcher into the FastAPI app. All schema changes are additive; each task is independently mergeable and revertable.

**Tech Stack:** Python 3.11+, Scrapy 2.x, Pydantic v2, SQLite (WAL), FastAPI, APScheduler 3.x, MLX/Ollama for LLM gate, pytest, React 19 + Vite for dashboard surfaces.

---

## File Structure

**New files:**
- `job-scraper/job_scraper/scrape_profile.py` — locked cadence + derivations
- `job-scraper/job_scraper/tiers.py` — tier enum + spider→tier registry
- `job-scraper/job_scraper/pipelines/llm_relevance.py` — LLM gate stage (discovery-only)
- `job-scraper/job_scraper/pipelines/tier_stats.py` — per-tier counter helper
- `job-scraper/job_scraper/spiders/workable.py` — new ATS spider
- `job-scraper/tests/test_scrape_profile.py`
- `job-scraper/tests/test_tiers.py`
- `job-scraper/tests/test_llm_relevance.py`
- `job-scraper/tests/test_workable_spider.py`
- `job-scraper/tests/test_rotation_groups.py`
- `job-scraper/tests/fixtures/ashby_rippling.json`, `ashby_rippling.html`, similar for Greenhouse/Lever
- `dashboard/backend/services/scrape_scheduler.py` — APScheduler bootstrap + tier-aware dispatch
- `dashboard/backend/tests/test_scrape_scheduler.py`

**Modified files:**
- `job-scraper/job_scraper/config.py` — add `ScrapeProfileConfig`, `LLMGateConfig`; wire into loader
- `job-scraper/job_scraper/config.default.yaml` — add `scrape_profile:` section
- `job-scraper/job_scraper/db.py` — `run_tier_stats` table + `runs` column adds (additive migration)
- `job-scraper/job_scraper/pipelines/dedup.py` — TTL read from profile, stats emission
- `job-scraper/job_scraper/pipelines/hard_filter.py` — stats emission
- `job-scraper/job_scraper/pipelines/storage.py` — tier-aware routing, stats finalization
- `job-scraper/job_scraper/spiders/__init__.py` — add `spider_tier()` and `rotation_filter()` helpers
- `job-scraper/job_scraper/spiders/ashby.py`, `greenhouse.py`, `lever.py` — rotation filter then JSON migration
- `job-scraper/job_scraper/spiders/searxng.py` — discovery alternation check
- `job-scraper/job_scraper/spiders/hn_hiring.py`, `remoteok.py` — tier declaration (hn already, remoteok to lead)
- `job-scraper/job_scraper/settings.py` — register `llm_relevance` in pipeline map
- `job-scraper/job_scraper/__init__.py` — `scrape_all` accepts `tiers` + `rotation_group`
- `dashboard/backend/server.py` — scheduler startup/shutdown hooks
- `dashboard/backend/routers/scraping.py` — tier/group query params, new `/api/scraper/metrics/tier-stats`
- `job-scraper/api/scraping_handlers.py` — thread tier/group into run payload
- `dashboard/web/src/api.ts` — new endpoint method
- `dashboard/web/src/views/domains/ops/MetricsView.tsx` — per-tier card, source-health table, gate-overflow banner

---

## Execution Context

All tasks run from the repo root `/Users/conner/Documents/TexTailor`.

- Python: `source venv/bin/activate` first (see `CLAUDE.md`).
- Frontend: `cd dashboard/web` for npm commands.
- Scraper tests: `cd job-scraper && python -m pytest tests/ -v`
- Backend tests: `python -m pytest dashboard/backend/tests/ -v`

Commit cadence: one commit per task. Use conventional prefixes (`feat`, `fix`, `refactor`, `test`, `docs`). Include `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` when the agent drove the edits.

---

## Task 1: `ScrapeProfile` foundation

Locks the 6h cadence as a config object, derives TTL / rotation_groups / target, and validates the invariant from the spec: `seen_ttl_days × 24 ≥ rotation_cycle_hours × 2`.

**Files:**
- Create: `job-scraper/job_scraper/scrape_profile.py`
- Create: `job-scraper/tests/test_scrape_profile.py`
- Modify: `job-scraper/job_scraper/config.py`
- Modify: `job-scraper/job_scraper/config.default.yaml`

- [ ] **Step 1: Write the failing test**

Create `job-scraper/tests/test_scrape_profile.py`:

```python
import pytest
from pydantic import ValidationError
from job_scraper.scrape_profile import ScrapeProfile, LLMGateConfig


def test_defaults_match_spec():
    p = ScrapeProfile()
    assert p.cadence == "0 */6 * * *"
    assert p.rotation_groups == 4
    assert p.seen_ttl_days == 45
    assert p.discovery_every_nth_run == 2
    assert p.target_net_new_per_run == 13
    assert p.rotation_cycle_hours == 24  # derived: 6 * 4


def test_ttl_validator_rejects_too_short():
    # cycle = 6 * 4 = 24h; min TTL days = (24 * 2) / 24 = 2
    with pytest.raises(ValidationError):
        ScrapeProfile(seen_ttl_days=1)


def test_ttl_validator_accepts_min_safe():
    p = ScrapeProfile(seen_ttl_days=2)
    assert p.seen_ttl_days == 2


def test_llm_gate_default_shape():
    g = LLMGateConfig()
    assert g.enabled is True
    assert g.accept_threshold == 5
    assert g.max_calls_per_run == 150
    assert g.timeout_seconds == 10
    assert g.fail_open is True
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd job-scraper && python -m pytest tests/test_scrape_profile.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_scraper.scrape_profile'`.

- [ ] **Step 3: Implement `ScrapeProfile`**

Create `job-scraper/job_scraper/scrape_profile.py`:

```python
"""Locked cadence + derivations shared across scraper, pipelines, and scheduler.

All runtime decisions about rotation, dedup TTL, and discovery alternation read
from here. Changing `cadence` is an architectural migration — bump TTL and
rotation_groups together.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class LLMGateConfig(BaseModel):
    enabled: bool = True
    endpoint: str = "http://localhost:8080/v1/chat/completions"
    model: str = "qwen3-4b-instruct-mlx"
    fallback_endpoint: str = "http://localhost:11434/v1/chat/completions"
    fallback_model: str = "qwen2.5:3b-instruct"
    accept_threshold: int = Field(default=5, ge=0, le=10)
    max_calls_per_run: int = Field(default=150, ge=1)
    timeout_seconds: int = Field(default=10, ge=1)
    fail_open: bool = True


class ScrapeProfile(BaseModel):
    cadence: str = "0 */6 * * *"               # cron, every 6 hours
    rotation_groups: int = Field(default=4, ge=1)
    seen_ttl_days: int = Field(default=45, ge=1)
    discovery_every_nth_run: int = Field(default=2, ge=1)
    target_net_new_per_run: int = Field(default=13, ge=1)
    llm_gate: LLMGateConfig = Field(default_factory=LLMGateConfig)

    @property
    def rotation_cycle_hours(self) -> int:
        """Hours for one full rotation cycle (cadence × groups)."""
        return self._cadence_hours() * self.rotation_groups

    def _cadence_hours(self) -> int:
        # Parses "0 */N * * *" → N. Reject anything more complex for now.
        parts = self.cadence.split()
        if len(parts) != 5 or not parts[1].startswith("*/"):
            raise ValueError(f"Unsupported cadence format: {self.cadence!r}")
        try:
            return int(parts[1][2:])
        except ValueError as exc:
            raise ValueError(f"Unsupported cadence format: {self.cadence!r}") from exc

    @model_validator(mode="after")
    def _check_ttl_exceeds_cycle(self) -> "ScrapeProfile":
        min_ttl_hours = self.rotation_cycle_hours * 2
        min_ttl_days = max(1, (min_ttl_hours + 23) // 24)
        if self.seen_ttl_days < min_ttl_days:
            raise ValueError(
                f"seen_ttl_days={self.seen_ttl_days} below safe minimum "
                f"{min_ttl_days} (cycle={self.rotation_cycle_hours}h)"
            )
        return self
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd job-scraper && python -m pytest tests/test_scrape_profile.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Wire profile into loader and YAML**

Add to `job-scraper/job_scraper/config.default.yaml` (append as top-level key, after existing sections):

```yaml
scrape_profile:
  cadence: "0 */6 * * *"
  rotation_groups: 4
  seen_ttl_days: 45
  discovery_every_nth_run: 2
  target_net_new_per_run: 13
  llm_gate:
    enabled: true
    endpoint: "http://localhost:8080/v1/chat/completions"
    model: "qwen3-4b-instruct-mlx"
    fallback_endpoint: "http://localhost:11434/v1/chat/completions"
    fallback_model: "qwen2.5:3b-instruct"
    accept_threshold: 5
    max_calls_per_run: 150
    timeout_seconds: 10
    fail_open: true
```

In `job-scraper/job_scraper/config.py`, add the import at the top (after `from pydantic import BaseModel, Field`):

```python
from job_scraper.scrape_profile import ScrapeProfile
```

Then add a field to `ScraperConfig` (place it next to `seen_ttl_days`):

```python
    scrape_profile: ScrapeProfile = Field(default_factory=ScrapeProfile)
```

And in `load_config`, just before the final `return ScraperConfig(...)`, parse it:

```python
    profile_raw = raw.get("scrape_profile") or {}
    scrape_profile = ScrapeProfile(**profile_raw) if profile_raw else ScrapeProfile()
```

Add `scrape_profile=scrape_profile,` to the `ScraperConfig(...)` kwargs in `return`.

- [ ] **Step 6: Smoke-test config load**

```bash
cd job-scraper && python -c "from job_scraper.config import load_config; c = load_config(); print(c.scrape_profile.cadence, c.scrape_profile.rotation_cycle_hours)"
```

Expected output: `0 */6 * * * 24`.

- [ ] **Step 7: Commit**

```bash
git add job-scraper/job_scraper/scrape_profile.py job-scraper/tests/test_scrape_profile.py job-scraper/job_scraper/config.py job-scraper/job_scraper/config.default.yaml
git -c commit.gpgsign=false commit -m "feat(scraper): add ScrapeProfile config with locked 6h cadence

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Tiers registry

Declarative spider→tier map + rotation-group hash helper. No spider is modified yet — just the shared utilities.

**Files:**
- Create: `job-scraper/job_scraper/tiers.py`
- Create: `job-scraper/tests/test_tiers.py`
- Modify: `job-scraper/job_scraper/spiders/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `job-scraper/tests/test_tiers.py`:

```python
import pytest
from job_scraper.tiers import (
    Tier,
    spider_tier,
    rotation_filter,
    SPIDER_TIERS,
)


def test_registry_has_all_spiders():
    expected = {
        "ashby", "greenhouse", "lever", "workable",
        "searxng",
        "hn_hiring", "remoteok",
        "aggregator", "generic",
    }
    assert set(SPIDER_TIERS.keys()) == expected


def test_tiers_assigned_correctly():
    assert spider_tier("ashby") is Tier.WORKHORSE
    assert spider_tier("greenhouse") is Tier.WORKHORSE
    assert spider_tier("lever") is Tier.WORKHORSE
    assert spider_tier("workable") is Tier.WORKHORSE
    assert spider_tier("searxng") is Tier.DISCOVERY
    assert spider_tier("hn_hiring") is Tier.LEAD
    assert spider_tier("remoteok") is Tier.LEAD


def test_rotation_filter_partitions_evenly():
    items = [f"https://example.com/{i}" for i in range(100)]
    groups = [rotation_filter(items, rotation_group=g, total_groups=4) for g in range(4)]
    assert sum(len(g) for g in groups) == 100
    # Each item lands in exactly one group
    seen = set()
    for group in groups:
        for item in group:
            assert item not in seen
            seen.add(item)


def test_rotation_filter_is_stable():
    items = [f"https://example.com/{i}" for i in range(50)]
    g0 = rotation_filter(items, rotation_group=0, total_groups=4)
    g0_again = rotation_filter(items, rotation_group=0, total_groups=4)
    assert g0 == g0_again


def test_rotation_filter_passes_through_when_no_group():
    items = ["a", "b", "c"]
    assert rotation_filter(items, rotation_group=None, total_groups=4) == items


def test_unknown_spider_raises():
    with pytest.raises(KeyError):
        spider_tier("not_a_spider")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd job-scraper && python -m pytest tests/test_tiers.py -v
```

Expected: module-not-found error.

- [ ] **Step 3: Implement `tiers.py`**

Create `job-scraper/job_scraper/tiers.py`:

```python
"""Spider tier registry + rotation helper.

Tiers are a first-class concept: each spider declares its tier, and pipeline
routing, scheduling, and metrics all branch on tier. Rotation groups use a
stable hash so the same item lands in the same group across runs.
"""
from __future__ import annotations

import hashlib
from enum import Enum
from typing import Iterable, TypeVar


class Tier(str, Enum):
    WORKHORSE = "workhorse"   # direct ATS, high-signal, known-good companies
    DISCOVERY = "discovery"   # SearXNG — breadth via search engines
    LEAD = "lead"             # thin JD, manual browsing bucket


SPIDER_TIERS: dict[str, Tier] = {
    "ashby": Tier.WORKHORSE,
    "greenhouse": Tier.WORKHORSE,
    "lever": Tier.WORKHORSE,
    "workable": Tier.WORKHORSE,
    "searxng": Tier.DISCOVERY,
    "hn_hiring": Tier.LEAD,
    "remoteok": Tier.LEAD,
    # Legacy/low-signal spiders get a tier too so metrics don't crash.
    "aggregator": Tier.DISCOVERY,
    "generic": Tier.DISCOVERY,
}


def spider_tier(name: str) -> Tier:
    """Return the tier for a spider. KeyError on unknown — forces registration."""
    return SPIDER_TIERS[name]


T = TypeVar("T")


def rotation_filter(
    items: Iterable[T],
    *,
    rotation_group: int | None,
    total_groups: int,
    key: callable | None = None,
) -> list[T]:
    """Return the subset of items that belong to `rotation_group`.

    A None group means 'all groups' — used for ad-hoc/manual runs that ignore
    rotation. Hashing is stable across runs so a given URL always lands in the
    same group regardless of run_id.
    """
    if rotation_group is None:
        return list(items)
    item_key = key or str
    chosen: list[T] = []
    for item in items:
        digest = hashlib.sha256(item_key(item).encode("utf-8")).hexdigest()
        if int(digest[:8], 16) % total_groups == rotation_group:
            chosen.append(item)
    return chosen
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd job-scraper && python -m pytest tests/test_tiers.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/tiers.py job-scraper/tests/test_tiers.py
git -c commit.gpgsign=false commit -m "feat(scraper): add tier registry and rotation_filter helper

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Metrics schema + `TierStatsWriter`

Additive schema (new table `run_tier_stats` + columns on `runs`) plus a helper that pipelines use to increment counters. No spider/pipeline behavior changes yet.

**Files:**
- Modify: `job-scraper/job_scraper/db.py`
- Create: `job-scraper/job_scraper/pipelines/tier_stats.py`
- Create: `job-scraper/tests/test_tier_stats.py`

- [ ] **Step 1: Write the failing test**

Create `job-scraper/tests/test_tier_stats.py`:

```python
import tempfile
from pathlib import Path
from job_scraper.db import JobDB
from job_scraper.pipelines.tier_stats import TierStatsWriter
from job_scraper.tiers import Tier


def _db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return JobDB(Path(tmp.name)), Path(tmp.name)


def test_tier_stats_table_created():
    db, _ = _db()
    assert "run_tier_stats" in db.tables()


def test_runs_has_new_columns():
    db, _ = _db()
    cols = {r[1] for r in db._conn.execute("PRAGMA table_info(runs)")}
    assert "net_new" in cols
    assert "gate_mode" in cols
    assert "rotation_group" in cols


def test_writer_increments_and_persists():
    db, path = _db()
    w = TierStatsWriter(db, run_id="r1")
    w.bump("searxng", Tier.DISCOVERY, "raw_hits", 5)
    w.bump("searxng", Tier.DISCOVERY, "raw_hits", 3)
    w.bump("searxng", Tier.DISCOVERY, "stored_pending", 2)
    w.bump("ashby", Tier.WORKHORSE, "raw_hits", 10)
    w.flush()

    rows = list(db._conn.execute(
        "SELECT source, tier, raw_hits, stored_pending FROM run_tier_stats WHERE run_id = ?",
        ("r1",),
    ))
    by_source = {r["source"]: r for r in rows}
    assert by_source["searxng"]["raw_hits"] == 8
    assert by_source["searxng"]["stored_pending"] == 2
    assert by_source["ashby"]["raw_hits"] == 10


def test_writer_flush_is_idempotent():
    db, _ = _db()
    w = TierStatsWriter(db, run_id="r2")
    w.bump("ashby", Tier.WORKHORSE, "raw_hits", 5)
    w.flush()
    w.flush()  # Second flush must not double-count
    row = db._conn.execute(
        "SELECT raw_hits FROM run_tier_stats WHERE run_id = ? AND source = 'ashby'",
        ("r2",),
    ).fetchone()
    assert row["raw_hits"] == 5
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd job-scraper && python -m pytest tests/test_tier_stats.py -v
```

Expected: `run_tier_stats` not in tables, import error for writer.

- [ ] **Step 3: Extend schema in `db.py`**

In `job-scraper/job_scraper/db.py`, extend the `_SCHEMA` constant by appending before the `CREATE VIEW IF NOT EXISTS results` line:

```sql
CREATE TABLE IF NOT EXISTS run_tier_stats (
    run_id TEXT NOT NULL,
    tier TEXT NOT NULL,
    source TEXT NOT NULL,
    raw_hits INTEGER DEFAULT 0,
    dedup_drops INTEGER DEFAULT 0,
    filter_drops INTEGER DEFAULT 0,
    llm_rejects INTEGER DEFAULT 0,
    llm_uncertain_low INTEGER DEFAULT 0,
    llm_overflow INTEGER DEFAULT 0,
    stored_pending INTEGER DEFAULT 0,
    stored_lead INTEGER DEFAULT 0,
    duration_ms INTEGER,
    PRIMARY KEY (run_id, tier, source)
);
CREATE INDEX IF NOT EXISTS idx_run_tier_stats_run ON run_tier_stats(run_id);
```

In the `_migrate_schema` method, add this block at the end of the runs-migration `try` (right after the existing `for col, defn in [("error_count", ...)]` loop):

```python
                for col, defn in [
                    ("net_new", "INTEGER"),
                    ("gate_mode", "TEXT"),
                    ("rotation_group", "INTEGER"),
                ]:
                    if col not in cols:
                        self._conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {defn}")
                self._conn.commit()
```

- [ ] **Step 4: Implement `TierStatsWriter`**

Create `job-scraper/job_scraper/pipelines/tier_stats.py`:

```python
"""In-memory tier-stat counters, flushed to run_tier_stats on close.

Pipeline stages call .bump(source, tier, field, delta). The writer coalesces
in-memory and upserts at flush(), which close_spider() calls. Flush is
idempotent via ON CONFLICT — second flush re-upserts the same values.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Literal

from job_scraper.db import JobDB
from job_scraper.tiers import Tier


TierStatField = Literal[
    "raw_hits", "dedup_drops", "filter_drops",
    "llm_rejects", "llm_uncertain_low", "llm_overflow",
    "stored_pending", "stored_lead",
    "duration_ms",
]


class TierStatsWriter:
    def __init__(self, db: JobDB, run_id: str):
        self._db = db
        self._run_id = run_id
        # key: (source, tier.value) → {field: int}
        self._counters: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def bump(self, source: str, tier: Tier, field: TierStatField, delta: int = 1) -> None:
        self._counters[(source, tier.value)][field] += delta

    def flush(self) -> None:
        for (source, tier), fields in self._counters.items():
            cols = ["run_id", "tier", "source"] + list(fields.keys())
            placeholders = ",".join("?" for _ in cols)
            update_set = ",".join(f"{k}=excluded.{k}" for k in fields.keys())
            values = [self._run_id, tier, source] + list(fields.values())
            self._db._conn.execute(
                f"INSERT INTO run_tier_stats ({','.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT(run_id, tier, source) DO UPDATE SET {update_set}",
                values,
            )
        self._db._conn.commit()
```

- [ ] **Step 5: Run the test**

```bash
cd job-scraper && python -m pytest tests/test_tier_stats.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add job-scraper/job_scraper/db.py job-scraper/job_scraper/pipelines/tier_stats.py job-scraper/tests/test_tier_stats.py
git -c commit.gpgsign=false commit -m "feat(scraper): add run_tier_stats schema and TierStatsWriter helper

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Wire stats writer into existing pipelines

Pipelines now emit raw/dedup/filter/storage counters. No behavior change; numbers land in `run_tier_stats`.

**Files:**
- Modify: `job-scraper/job_scraper/pipelines/dedup.py`
- Modify: `job-scraper/job_scraper/pipelines/hard_filter.py`
- Modify: `job-scraper/job_scraper/pipelines/storage.py`
- Create: `job-scraper/tests/test_pipeline_stats_integration.py`

- [ ] **Step 1: Write the failing test**

Create `job-scraper/tests/test_pipeline_stats_integration.py`:

```python
import tempfile
from pathlib import Path
from job_scraper.db import JobDB
from job_scraper.pipelines.dedup import DeduplicationPipeline
from job_scraper.pipelines.storage import SQLitePipeline
from job_scraper.pipelines.tier_stats import TierStatsWriter


class _FakeSpider:
    def __init__(self, name="ashby"):
        self.name = name


def test_storage_writes_tier_stat_stored_pending():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = JobDB(Path(tmp.name))
    writer = TierStatsWriter(db, run_id="r-stats")
    pipe = SQLitePipeline(db=db, run_id="r-stats", tier_stats=writer)
    pipe.open_spider(_FakeSpider("ashby"))

    pipe.process_item({
        "url": "https://jobs.ashbyhq.com/acme/1",
        "title": "Platform Engineer",
        "company": "acme",
        "board": "ashby",
        "source": "ashby",
        "created_at": "2026-04-18T00:00:00+00:00",
    }, _FakeSpider("ashby"))
    pipe.close_spider(_FakeSpider("ashby"))

    row = db._conn.execute(
        "SELECT stored_pending FROM run_tier_stats WHERE run_id = 'r-stats' AND source = 'ashby'"
    ).fetchone()
    assert row["stored_pending"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd job-scraper && python -m pytest tests/test_pipeline_stats_integration.py -v
```

Expected: `SQLitePipeline.__init__() got an unexpected keyword argument 'tier_stats'`.

- [ ] **Step 3: Update pipelines to accept and emit stats**

In `job-scraper/job_scraper/pipelines/dedup.py`, replace the class body with:

```python
class DeduplicationPipeline:
    def __init__(self, db: JobDB | None = None, ttl_days: int = 14, tier_stats=None):
        self._db = db
        self._ttl_days = ttl_days
        self._tier_stats = tier_stats

    @classmethod
    def from_crawler(cls, crawler):
        db = _get_shared_db(crawler)
        # Prefer profile TTL; fall back to legacy setting for safety.
        from job_scraper.config import load_config
        cfg = load_config()
        ttl = cfg.scrape_profile.seen_ttl_days
        return cls(db=db, ttl_days=ttl, tier_stats=_get_shared_stats(crawler))

    def process_item(self, item, spider):
        url = item["url"]
        if self._db.is_seen(url, ttl_days=self._ttl_days):
            if self._tier_stats is not None:
                from job_scraper.tiers import spider_tier
                self._tier_stats.bump(spider.name, spider_tier(spider.name), "dedup_drops")
            raise DropItem(f"Already seen: {url}")
        self._db.mark_seen(url)
        if self._tier_stats is not None:
            from job_scraper.tiers import spider_tier
            self._tier_stats.bump(spider.name, spider_tier(spider.name), "raw_hits")
        return item
```

At the top of the same file, add the shared-stats helper next to `_get_shared_db`:

```python
def _get_shared_stats(crawler):
    """Single TierStatsWriter per crawler — all pipelines write to it."""
    if not hasattr(crawler, "_shared_stats"):
        from job_scraper.pipelines.tier_stats import TierStatsWriter
        run_id = crawler.settings.get("SCRAPE_RUN_ID", "")
        db = _get_shared_db(crawler)
        crawler._shared_stats = TierStatsWriter(db, run_id=run_id)
    return crawler._shared_stats
```

In `job-scraper/job_scraper/pipelines/hard_filter.py`, update `__init__` and `_reject`:

```python
class HardFilterPipeline:
    def __init__(self, config: HardFilterConfig | None = None, tier_stats=None):
        self._config = config or HardFilterConfig()
        self._tier_stats = tier_stats
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
        from job_scraper.pipelines.dedup import _get_shared_stats
        cfg = load_config()
        return cls(config=cfg.hard_filters, tier_stats=_get_shared_stats(crawler))

    def _reject(self, item, stage: str, reason: str, spider=None):
        item["status"] = "rejected"
        item["rejection_stage"] = stage
        item["rejection_reason"] = reason
        if self._tier_stats is not None and spider is not None:
            from job_scraper.tiers import spider_tier
            self._tier_stats.bump(spider.name, spider_tier(spider.name), "filter_drops")
        return item
```

Then update every call site in `process_item` from `return self._reject(item, ..., ...)` to `return self._reject(item, ..., ..., spider=spider)`.

In `job-scraper/job_scraper/pipelines/storage.py`, replace the file body with:

```python
from __future__ import annotations

import logging

from job_scraper.db import JobDB
from job_scraper.pipelines.dedup import _get_shared_db, _get_shared_stats
from job_scraper.tiers import Tier, spider_tier

logger = logging.getLogger(__name__)


class SQLitePipeline:
    def __init__(self, db: JobDB | None = None, run_id: str = "", tier_stats=None):
        self._db = db
        self._run_id = run_id
        self._tier_stats = tier_stats

    @classmethod
    def from_crawler(cls, crawler):
        db = _get_shared_db(crawler)
        run_id = crawler.settings.get("SCRAPE_RUN_ID", "")
        return cls(db=db, run_id=run_id, tier_stats=_get_shared_stats(crawler))

    def open_spider(self, spider):
        if not self._run_id:
            import uuid
            self._run_id = str(uuid.uuid4())[:12]

    def process_item(self, item, spider):
        job = dict(item)
        job["run_id"] = self._run_id
        tier = spider_tier(spider.name)
        # Tier-aware status routing (generalizes old hn_hiring-specific rule).
        if tier is Tier.LEAD and job.get("status") != "rejected":
            job["status"] = "lead"
        try:
            self._db.insert_job(job)
            if self._tier_stats is not None:
                status = job.get("status", "pending")
                if status == "lead":
                    self._tier_stats.bump(spider.name, tier, "stored_lead")
                elif status != "rejected":
                    self._tier_stats.bump(spider.name, tier, "stored_pending")
        except Exception:
            logger.exception("Failed to store job: %s", job.get("url"))
        return item

    def close_spider(self, spider):
        if self._db:
            self._db.commit()
        if self._tier_stats is not None:
            self._tier_stats.flush()
```

- [ ] **Step 4: Run the test**

```bash
cd job-scraper && python -m pytest tests/test_pipeline_stats_integration.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Run the full scraper test suite for regressions**

```bash
cd job-scraper && python -m pytest tests/ -v
```

Expected: all prior tests still pass (plus the new one).

- [ ] **Step 6: Commit**

```bash
git add job-scraper/job_scraper/pipelines/dedup.py job-scraper/job_scraper/pipelines/hard_filter.py job-scraper/job_scraper/pipelines/storage.py job-scraper/tests/test_pipeline_stats_integration.py
git -c commit.gpgsign=false commit -m "feat(scraper): emit per-tier run stats from dedup, filter, and storage pipelines

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Propagate `net_new` + `rotation_group` into `runs`

Update `scrape_all` to set the new `runs` columns from the tier-stats writer + incoming rotation group.

**Files:**
- Modify: `job-scraper/job_scraper/db.py`
- Modify: `job-scraper/job_scraper/__init__.py`

- [ ] **Step 1: Extend `JobDB.finish_run` signature**

In `job-scraper/job_scraper/db.py`, replace the `finish_run` method with:

```python
    def finish_run(
        self,
        run_id: str,
        *,
        raw_count: int = 0,
        dedup_count: int = 0,
        filtered_count: int = 0,
        error_count: int = 0,
        errors: str | None = None,
        net_new: int | None = None,
        gate_mode: str | None = None,
        rotation_group: int | None = None,
    ) -> None:
        now = _now()
        started = self._conn.execute(
            "SELECT started_at FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        elapsed = None
        if started:
            start_dt = datetime.fromisoformat(started["started_at"])
            elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()
        self._conn.execute(
            """UPDATE runs SET completed_at = ?, elapsed = ?, raw_count = ?,
               dedup_count = ?, filtered_count = ?, error_count = ?, errors = ?,
               net_new = COALESCE(?, net_new),
               gate_mode = COALESCE(?, gate_mode),
               rotation_group = COALESCE(?, rotation_group),
               status = 'completed'
            WHERE run_id = ?""",
            (now, elapsed, raw_count, dedup_count, filtered_count, error_count,
             errors, net_new, gate_mode, rotation_group, run_id),
        )
        self._conn.commit()
```

- [ ] **Step 2: Update `scrape_all` to accept and emit the new fields**

In `job-scraper/job_scraper/__init__.py`, replace the `scrape_all` signature and epilogue:

```python
def scrape_all(
    *,
    verbose: bool = False,
    spiders: list[str] | None = None,
    tiers: list[str] | None = None,
    rotation_group: int | None = None,
) -> dict:
    """Run spiders via Scrapy CrawlerProcess.

    Args:
        verbose: Enable debug logging.
        spiders: Explicit spider names (overrides tiers).
        tiers: Tier names to include; unspecified spiders in each tier all run.
        rotation_group: Passed to spiders via settings for workhorse rotation.
    """
    from .spiders.ashby import AshbySpider
    from .spiders.greenhouse import GreenhouseSpider
    from .spiders.lever import LeverSpider
    from .spiders.searxng import SearXNGSpider
    from .spiders.aggregator import AggregatorSpider
    from .spiders.generic import GenericSpider
    from .spiders.remoteok import RemoteOKSpider
    from .spiders.hn_hiring import HNHiringSpider
    from .tiers import SPIDER_TIERS, Tier

    ALL_SPIDERS = {
        "ashby": AshbySpider,
        "greenhouse": GreenhouseSpider,
        "lever": LeverSpider,
        "searxng": SearXNGSpider,
        "aggregator": AggregatorSpider,
        "generic": GenericSpider,
        "remoteok": RemoteOKSpider,
        "hn_hiring": HNHiringSpider,
    }

    run_id = uuid.uuid4().hex[:12]

    settings = get_project_settings()
    settings["LOG_LEVEL"] = "DEBUG" if verbose else "INFO"
    settings["SCRAPE_RUN_ID"] = run_id
    if rotation_group is not None:
        settings["SCRAPE_ROTATION_GROUP"] = rotation_group

    db = JobDB()
    db.start_run(run_id, trigger="manual" if spiders else "scheduled")

    if spiders is None and tiers is not None:
        wanted_tiers = {Tier(t) for t in tiers}
        spiders = [name for name, tier in SPIDER_TIERS.items()
                   if tier in wanted_tiers and name in ALL_SPIDERS]

    process = CrawlerProcess(settings)
    crawler_refs = []
    enabled = spiders or list(ALL_SPIDERS.keys())
    for name in enabled:
        spider_cls = ALL_SPIDERS.get(name)
        if spider_cls:
            crawler = process.create_crawler(spider_cls)
            crawler_refs.append(crawler)
            process.crawl(crawler)

    process.start()

    raw_count = 0
    error_count = 0
    for crawler in crawler_refs:
        stats = crawler.stats.get_stats()
        raw_count += stats.get("item_scraped_count", 0) + stats.get("item_dropped_count", 0)
        error_count += stats.get("log_count/ERROR", 0)

    rows = db._conn.execute(
        "SELECT status, COUNT(*) AS n FROM jobs WHERE run_id = ? GROUP BY status",
        (run_id,),
    ).fetchall()
    by_status = {row["status"]: row["n"] for row in rows}
    stored_count = sum(by_status.values())
    filtered_count = by_status.get("rejected", 0)
    net_new = by_status.get("pending", 0) + by_status.get("qa_pending", 0) + by_status.get("lead", 0)

    # gate_mode is set by the LLM gate pipeline via crawler settings side-channel.
    gate_mode = None
    for crawler in crawler_refs:
        mode = crawler.settings.get("LLM_GATE_MODE_OBSERVED")
        if mode and mode != "normal":
            gate_mode = mode  # fail_open wins if any crawler reports it
            if mode == "fail_open":
                break

    db.finish_run(
        run_id,
        raw_count=raw_count,
        dedup_count=stored_count,
        filtered_count=filtered_count,
        error_count=error_count,
        net_new=net_new,
        gate_mode=gate_mode,
        rotation_group=rotation_group,
    )

    stats_out = {
        "run_id": run_id,
        "total_jobs": db.job_count(),
        "pending": db.job_count(status="pending"),
        "rejected": db.job_count(status="rejected"),
        "net_new": net_new,
        "rotation_group": rotation_group,
        "gate_mode": gate_mode or "normal",
    }
    db.close()
    return stats_out
```

- [ ] **Step 3: Smoke-test the new argument surface**

```bash
cd job-scraper && python -c "import inspect; from job_scraper import scrape_all; print(list(inspect.signature(scrape_all).parameters))"
```

Expected: `['verbose', 'spiders', 'tiers', 'rotation_group']`.

- [ ] **Step 4: Run all scraper tests for regressions**

```bash
cd job-scraper && python -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add job-scraper/job_scraper/db.py job-scraper/job_scraper/__init__.py
git -c commit.gpgsign=false commit -m "feat(scraper): accept tiers/rotation_group and persist net_new/gate_mode/group

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Workhorse rotation in Ashby / Greenhouse / Lever

Three spiders read `SCRAPE_ROTATION_GROUP` from settings and filter their target list via `rotation_filter`. TTL was already bumped to 45 via the profile in Task 1, but the first end-to-end behavior shift lives here.

**Files:**
- Modify: `job-scraper/job_scraper/spiders/ashby.py`
- Modify: `job-scraper/job_scraper/spiders/greenhouse.py`
- Modify: `job-scraper/job_scraper/spiders/lever.py`
- Create: `job-scraper/tests/test_rotation_groups.py`

- [ ] **Step 1: Write the failing test**

Create `job-scraper/tests/test_rotation_groups.py`:

```python
from job_scraper.tiers import rotation_filter


def test_ashby_roster_partitions_across_groups():
    # Simulate 40-company roster
    companies = [{"url": f"https://jobs.ashbyhq.com/company{i}", "company": f"c{i}"} for i in range(40)]
    key = lambda c: c["url"]
    buckets = [
        rotation_filter(companies, rotation_group=g, total_groups=4, key=key)
        for g in range(4)
    ]
    # All companies covered, no overlap
    flat = [c for b in buckets for c in b]
    assert len(flat) == 40
    assert len({c["url"] for c in flat}) == 40
    # Roughly balanced (±25% slack for hash variance on small N)
    sizes = [len(b) for b in buckets]
    assert all(5 <= s <= 15 for s in sizes), sizes
```

- [ ] **Step 2: Run the test**

```bash
cd job-scraper && python -m pytest tests/test_rotation_groups.py -v
```

Expected: test passes already (it tests `tiers.rotation_filter` which exists). Good — this is our contract for the spider change.

- [ ] **Step 3: Modify each spider's `start_requests`**

For each of `ashby.py`, `greenhouse.py`, `lever.py`, apply the same change: before iterating targets, apply `rotation_filter`. Example for `ashby.py` — find the existing `start_requests` method, and at the top (before the `for target in self._targets:` loop), add:

```python
    def start_requests(self):
        from job_scraper.tiers import rotation_filter
        rotation_group = self.crawler.settings.get("SCRAPE_ROTATION_GROUP")
        total_groups = self.crawler.settings.getint("SCRAPE_ROTATION_TOTAL", 4)
        targets = rotation_filter(
            self._targets,
            rotation_group=rotation_group,
            total_groups=total_groups,
            key=lambda t: t.get("url", ""),
        )
        logger.info(
            "Ashby: crawling %d/%d targets (group=%s)",
            len(targets), len(self._targets), rotation_group,
        )
        for target in targets:
            # ... existing per-target logic unchanged
```

(Do the same for `greenhouse.py` and `lever.py`, adjusting the log prefix to `"Greenhouse:"` / `"Lever:"`.)

If the spider doesn't have access to `self.crawler.settings` in `start_requests` (spiders that use `from_crawler` to stash settings), read from an attribute set in `from_crawler` instead — pattern:

```python
    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider._rotation_group = crawler.settings.get("SCRAPE_ROTATION_GROUP")
        spider._rotation_total = crawler.settings.getint("SCRAPE_ROTATION_TOTAL", 4)
        return spider
```

Then `start_requests` uses `self._rotation_group` and `self._rotation_total`.

- [ ] **Step 4: Wire `SCRAPE_ROTATION_TOTAL` into `scrape_all`**

In `job-scraper/job_scraper/__init__.py`, in `scrape_all`, after the line setting `SCRAPE_ROTATION_GROUP`, add:

```python
    from .config import load_config
    settings["SCRAPE_ROTATION_TOTAL"] = load_config().scrape_profile.rotation_groups
```

- [ ] **Step 5: Smoke-test rotation**

```bash
cd job-scraper && python -c "
from job_scraper.config import load_config
from job_scraper.tiers import rotation_filter
cfg = load_config()
total = cfg.scrape_profile.rotation_groups
targets = [{'url': b.url} for b in cfg.boards]
for g in range(total):
    sub = rotation_filter(targets, rotation_group=g, total_groups=total, key=lambda t: t['url'])
    print(f'group {g}: {len(sub)} boards')
"
```

Expected: 4 lines, roughly equal counts summing to the full roster.

- [ ] **Step 6: Run all scraper tests**

```bash
cd job-scraper && python -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add job-scraper/job_scraper/spiders/ashby.py job-scraper/job_scraper/spiders/greenhouse.py job-scraper/job_scraper/spiders/lever.py job-scraper/job_scraper/__init__.py job-scraper/tests/test_rotation_groups.py
git -c commit.gpgsign=false commit -m "feat(scraper): apply workhorse rotation groups to ATS spiders

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: LLM relevance gate pipeline

New `LLMRelevancePipeline`. Discovery-tier-only. Off by default via `scrape_profile.llm_gate.enabled`; this task does not flip the default — the next tasks validate it against fixtures before we enable it.

**Files:**
- Create: `job-scraper/job_scraper/pipelines/llm_relevance.py`
- Create: `job-scraper/tests/test_llm_relevance.py`
- Create: `job-scraper/tests/fixtures/llm_gate_responses.json`
- Modify: `job-scraper/job_scraper/settings.py`
- Modify: `job-scraper/job_scraper/config.default.yaml` (add `llm_relevance` to `pipeline_order`)

- [ ] **Step 1: Write the failing test**

Create `job-scraper/tests/fixtures/llm_gate_responses.json`:

```json
{
  "accept": "{\"score\": 8, \"verdict\": \"accept\", \"reason\": \"Security eng remote US\", \"flags\": [\"remote_us_confirmed\"]}",
  "reject": "{\"score\": 1, \"verdict\": \"reject\", \"reason\": \"Staff IC role\", \"flags\": [\"seniority_too_high\"]}",
  "uncertain_low": "{\"score\": 3, \"verdict\": \"uncertain\", \"reason\": \"Unclear remote policy\", \"flags\": []}",
  "uncertain_high": "{\"score\": 6, \"verdict\": \"uncertain\", \"reason\": \"Possibly fits\", \"flags\": []}",
  "malformed": "not even JSON"
}
```

Create `job-scraper/tests/test_llm_relevance.py`:

```python
import json
from pathlib import Path
import pytest
from job_scraper.pipelines.llm_relevance import LLMRelevancePipeline, GateOutcome
from job_scraper.scrape_profile import LLMGateConfig
from job_scraper.tiers import Tier


FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "llm_gate_responses.json").read_text())


class _StubClient:
    def __init__(self, canned: list[str]):
        self.canned = list(canned)
        self.calls = 0

    def ask(self, prompt: str) -> str:
        self.calls += 1
        return self.canned.pop(0)


class _FakeSpider:
    name = "searxng"


def _make_pipe(client, cfg: LLMGateConfig | None = None, stats=None):
    cfg = cfg or LLMGateConfig()
    return LLMRelevancePipeline(
        config=cfg,
        client=client,
        persona_card="PERSONA",
        tier_stats=stats,
    )


def test_workhorse_item_passes_through_untouched():
    pipe = _make_pipe(_StubClient([]))
    item = {
        "url": "https://x", "title": "Platform Engineer", "company": "acme",
        "snippet": "", "source": "ashby", "status": "pending",
    }
    class AshbySpider: name = "ashby"
    out = pipe.process_item(item, AshbySpider())
    assert out is item
    assert out["status"] == "pending"


def test_accept_routes_to_pending():
    client = _StubClient([FIXTURES["accept"]])
    pipe = _make_pipe(client)
    item = {"url": "https://x", "title": "Security Eng", "company": "acme",
            "snippet": "remote us", "source": "searxng", "status": "pending"}
    out = pipe.process_item(item, _FakeSpider())
    assert out["status"] == "pending"
    assert out.get("score") == 8


def test_reject_routes_to_rejected():
    pipe = _make_pipe(_StubClient([FIXTURES["reject"]]))
    item = {"url": "https://x", "title": "Staff Eng", "company": "acme",
            "snippet": "", "source": "searxng", "status": "pending"}
    out = pipe.process_item(item, _FakeSpider())
    assert out["status"] == "rejected"
    assert out["rejection_stage"] == "llm_relevance"


def test_uncertain_below_threshold_rejected():
    pipe = _make_pipe(_StubClient([FIXTURES["uncertain_low"]]))
    item = {"url": "https://x", "title": "Eng", "company": "acme",
            "snippet": "", "source": "searxng", "status": "pending"}
    out = pipe.process_item(item, _FakeSpider())
    assert out["status"] == "rejected"


def test_uncertain_above_threshold_accepted():
    pipe = _make_pipe(_StubClient([FIXTURES["uncertain_high"]]))
    item = {"url": "https://x", "title": "Eng", "company": "acme",
            "snippet": "", "source": "searxng", "status": "pending"}
    out = pipe.process_item(item, _FakeSpider())
    assert out["status"] == "pending"


def test_malformed_retry_then_uncertain_fallback():
    client = _StubClient([FIXTURES["malformed"], FIXTURES["malformed"]])
    pipe = _make_pipe(client)
    item = {"url": "https://x", "title": "Eng", "company": "acme",
            "snippet": "", "source": "searxng", "status": "pending"}
    pipe.process_item(item, _FakeSpider())
    assert client.calls == 2  # one retry


def test_batch_cap_falls_back_to_rules_only():
    # Configure cap of 1; second discovery item must use rules-only.
    cfg = LLMGateConfig(max_calls_per_run=1)
    pipe = _make_pipe(_StubClient([FIXTURES["accept"]]), cfg=cfg)
    item1 = {"url": "https://a", "title": "Security Eng", "company": "c1",
             "snippet": "remote us", "source": "searxng", "status": "pending",
             "board": "ashby"}
    item2 = {"url": "https://b", "title": "Security Eng", "company": "c2",
             "snippet": "remote us", "source": "searxng", "status": "pending",
             "board": "ashby"}
    pipe.process_item(item1, _FakeSpider())
    out = pipe.process_item(item2, _FakeSpider())
    assert "gate_overflow" in (out.get("flags") or [])


def test_fail_open_on_circuit_break():
    class BrokenClient:
        def ask(self, prompt):
            raise TimeoutError("no response")
    pipe = _make_pipe(BrokenClient())
    for _ in range(3):
        item = {"url": f"https://x/{_}", "title": "Eng", "company": "c",
                "snippet": "", "source": "searxng", "status": "pending"}
        pipe.process_item(item, _FakeSpider())
    # After circuit-break, the next item accepts (fail_open=True default)
    item = {"url": "https://x/final", "title": "Eng", "company": "c",
            "snippet": "", "source": "searxng", "status": "pending"}
    out = pipe.process_item(item, _FakeSpider())
    assert out["status"] == "pending"
    assert pipe.mode == GateOutcome.FAIL_OPEN
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd job-scraper && python -m pytest tests/test_llm_relevance.py -v
```

Expected: module-not-found error.

- [ ] **Step 3: Implement the pipeline**

Create `job-scraper/job_scraper/pipelines/llm_relevance.py`:

```python
"""LLM relevance gate — discovery-tier-only pipeline stage.

Accepts/rejects SearXNG items via a cheap local model against a persona card.
Works with any OpenAI-compatible chat endpoint (MLX, Ollama). Has two
guardrails: a per-run batch cap (`max_calls_per_run`) and a 3-consecutive-
timeout circuit breaker that flips the stage to fail-open for the rest of the
run.
"""
from __future__ import annotations

import json
import logging
import time
from enum import Enum
from pathlib import Path
from typing import Any

from job_scraper.scrape_profile import LLMGateConfig
from job_scraper.tiers import Tier, spider_tier

logger = logging.getLogger(__name__)


class GateOutcome(str, Enum):
    NORMAL = "normal"
    OVERFLOW = "overflow"
    FAIL_OPEN = "fail_open"


class _HTTPGateClient:
    def __init__(self, cfg: LLMGateConfig):
        self._cfg = cfg

    def ask(self, prompt: str) -> str:
        import requests  # local import keeps non-LLM runs light
        body = {
            "model": self._cfg.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        try:
            r = requests.post(self._cfg.endpoint, json=body, timeout=self._cfg.timeout_seconds)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception:
            # fall back once
            body["model"] = self._cfg.fallback_model
            r = requests.post(
                self._cfg.fallback_endpoint, json=body, timeout=self._cfg.timeout_seconds
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]


def _load_persona_card() -> str:
    persona_dir = Path(__file__).resolve().parents[3] / "tailoring" / "persona"
    if not persona_dir.exists():
        raise FileNotFoundError(f"persona dir missing: {persona_dir}")
    chunks = []
    for name in ("identity.md", "motivation.md", "evidence.md"):
        p = persona_dir / name
        if p.exists():
            chunks.append(p.read_text())
    # Truncate to ~400 tokens worth (~1600 chars).
    card = "\n\n".join(chunks)
    return card[:1600]


class LLMRelevancePipeline:
    def __init__(
        self,
        config: LLMGateConfig | None = None,
        client=None,
        persona_card: str | None = None,
        tier_stats=None,
    ):
        self._cfg = config or LLMGateConfig()
        self._client = client or _HTTPGateClient(self._cfg)
        self._persona = persona_card if persona_card is not None else _load_persona_card()
        self._tier_stats = tier_stats
        self._calls_made = 0
        self._consecutive_timeouts = 0
        self.mode: GateOutcome = GateOutcome.NORMAL

    @classmethod
    def from_crawler(cls, crawler):
        from job_scraper.config import load_config
        from job_scraper.pipelines.dedup import _get_shared_stats
        cfg = load_config().scrape_profile.llm_gate
        return cls(config=cfg, tier_stats=_get_shared_stats(crawler))

    def process_item(self, item, spider):
        # Short-circuit for non-discovery items.
        try:
            tier = spider_tier(spider.name)
        except KeyError:
            return item
        if tier is not Tier.DISCOVERY:
            return item
        if not self._cfg.enabled:
            return item

        # Circuit breaker already tripped — fail-open.
        if self.mode is GateOutcome.FAIL_OPEN:
            return item

        # Batch cap — rules-only fallback.
        if self._calls_made >= self._cfg.max_calls_per_run:
            self._mark_overflow()
            return self._rules_only(item, spider)

        prompt = self._build_prompt(item)
        try:
            raw = self._client.ask(prompt)
            self._consecutive_timeouts = 0
        except Exception as exc:
            self._consecutive_timeouts += 1
            logger.warning("LLM gate call failed (%d in a row): %s", self._consecutive_timeouts, exc)
            if self._consecutive_timeouts >= 3 and self._cfg.fail_open:
                self.mode = GateOutcome.FAIL_OPEN
                self._record_mode_observed(spider)
                return item
            # Single-call failure — treat as uncertain at threshold.
            return self._apply_verdict(item, spider, verdict="uncertain", score=self._cfg.accept_threshold)

        self._calls_made += 1
        parsed = self._parse(raw)
        if parsed is None:
            # Retry once with a stricter prompt; then treat as uncertain.
            try:
                raw2 = self._client.ask(prompt + "\n\nReturn ONLY valid JSON.")
                parsed = self._parse(raw2)
                self._calls_made += 1
            except Exception:
                parsed = None
            if parsed is None:
                return self._apply_verdict(item, spider, verdict="uncertain", score=self._cfg.accept_threshold)

        return self._apply_verdict(
            item, spider,
            verdict=parsed.get("verdict", "uncertain"),
            score=int(parsed.get("score", 0)),
            reason=parsed.get("reason"),
            flags=parsed.get("flags") or [],
        )

    def close_spider(self, spider):
        self._record_mode_observed(spider)

    # --- helpers ---

    def _build_prompt(self, item: dict[str, Any]) -> str:
        return (
            "You are gating job postings for relevance to this candidate. "
            "Respond with ONLY a JSON object: "
            '{"score": 0-10, "verdict": "accept"|"reject"|"uncertain", '
            '"reason": "short", "flags": ["..."]}.\n\n'
            f"CANDIDATE PROFILE:\n{self._persona}\n\n"
            f"JOB:\n"
            f"Title: {item.get('title')}\n"
            f"Company: {item.get('company')}\n"
            f"Board: {item.get('board')}\n"
            f"URL: {item.get('url')}\n"
            f"Location: {item.get('location', '')}\n"
            f"Snippet: {item.get('snippet', '')[:500]}\n"
        )

    def _parse(self, raw: str) -> dict | None:
        try:
            return json.loads(raw)
        except Exception:
            # Try extracting a {…} block
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except Exception:
                    return None
            return None

    def _apply_verdict(self, item, spider, *, verdict, score, reason=None, flags=None):
        item["score"] = score
        if flags:
            item["flags"] = flags
        if verdict == "accept" or (verdict == "uncertain" and score >= self._cfg.accept_threshold):
            return item
        # reject path
        item["status"] = "rejected"
        item["rejection_stage"] = "llm_relevance"
        item["rejection_reason"] = reason or f"score {score}/10 verdict={verdict}"
        if self._tier_stats is not None:
            tier = spider_tier(spider.name)
            field = "llm_uncertain_low" if verdict == "uncertain" else "llm_rejects"
            self._tier_stats.bump(spider.name, tier, field)
        return item

    def _rules_only(self, item, spider) -> dict:
        title_keywords = ["security", "platform", "infrastructure", "devops",
                          "sre", "cloud", "backend", "ai", "ml", "site reliability"]
        title_lower = (item.get("title") or "").lower()
        match = any(k in title_lower for k in title_keywords)
        flags = list(item.get("flags") or []) + ["gate_overflow"]
        item["flags"] = flags
        if not match:
            item["status"] = "rejected"
            item["rejection_stage"] = "llm_relevance"
            item["rejection_reason"] = "gate_overflow rules-only reject"
            if self._tier_stats is not None:
                self._tier_stats.bump(spider.name, spider_tier(spider.name), "llm_overflow")
        return item

    def _mark_overflow(self):
        if self.mode is GateOutcome.NORMAL:
            self.mode = GateOutcome.OVERFLOW

    def _record_mode_observed(self, spider):
        # Side-channel: stash observed mode on crawler settings so scrape_all can read it.
        try:
            spider.crawler.settings.set("LLM_GATE_MODE_OBSERVED", self.mode.value, priority="cmdline")
        except Exception:
            pass
```

- [ ] **Step 4: Register the pipeline slot**

In `job-scraper/job_scraper/settings.py`, extend `_PIPELINE_MAP`:

```python
_PIPELINE_MAP = {
    "text_extraction": "job_scraper.pipelines.text_extraction.TextExtractionPipeline",
    "dedup": "job_scraper.pipelines.dedup.DeduplicationPipeline",
    "hard_filter": "job_scraper.pipelines.hard_filter.HardFilterPipeline",
    "llm_relevance": "job_scraper.pipelines.llm_relevance.LLMRelevancePipeline",
    "storage": "job_scraper.pipelines.storage.SQLitePipeline",
}
```

In `job-scraper/job_scraper/config.default.yaml`, update `pipeline_order`:

```yaml
pipeline_order:
- text_extraction
- dedup
- hard_filter
- llm_relevance
- storage
```

- [ ] **Step 5: Run the tests**

```bash
cd job-scraper && python -m pytest tests/test_llm_relevance.py -v
```

Expected: 8 passed.

- [ ] **Step 6: Run the full suite**

```bash
cd job-scraper && python -m pytest tests/ -v
```

Expected: all pass. Note: the pipeline is enabled by default in config but is a no-op for non-discovery items, and the MLX/Ollama endpoint isn't contacted in any test (they use stubs or non-discovery spiders).

- [ ] **Step 7: Commit**

```bash
git add job-scraper/job_scraper/pipelines/llm_relevance.py job-scraper/tests/test_llm_relevance.py job-scraper/tests/fixtures/llm_gate_responses.json job-scraper/job_scraper/settings.py job-scraper/job_scraper/config.default.yaml
git -c commit.gpgsign=false commit -m "feat(scraper): add LLM relevance gate pipeline for discovery tier

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Discovery tier alternation

`searxng` spider reads a new setting `SCRAPE_DISCOVERY_FIRE` and no-ops when false.

**Files:**
- Modify: `job-scraper/job_scraper/spiders/searxng.py`
- Modify: `job-scraper/job_scraper/__init__.py`
- Create: `job-scraper/tests/test_discovery_alternation.py`

- [ ] **Step 1: Write the failing test**

Create `job-scraper/tests/test_discovery_alternation.py`:

```python
from scrapy.utils.test import get_crawler
from job_scraper.spiders.searxng import SearXNGSpider


def test_searxng_skips_when_discovery_not_firing():
    spider = SearXNGSpider()
    spider._searxng_url = "http://x/search"
    spider._queries = []
    spider._domain_blocklist = set()
    spider._discovery_fire = False
    reqs = list(spider.start_requests())
    assert reqs == []


def test_searxng_fires_when_flag_true():
    from job_scraper.config import SearXNGQuery
    spider = SearXNGSpider()
    spider._searxng_url = "http://x/search"
    spider._queries = [SearXNGQuery(title_phrase="eng", board_site="", suffix="")]
    spider._domain_blocklist = set()
    spider._discovery_fire = True
    reqs = list(spider.start_requests())
    assert len(reqs) >= 1
```

- [ ] **Step 2: Run — verify it fails**

```bash
cd job-scraper && python -m pytest tests/test_discovery_alternation.py -v
```

Expected: failure — `_discovery_fire` attribute not consulted.

- [ ] **Step 3: Thread the flag through**

In `job-scraper/job_scraper/spiders/searxng.py`, add to `__init__`:

```python
        self._discovery_fire = True
```

Update `from_crawler`:

```python
    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider._searxng_url = cfg.searxng.url
        spider._queries = cfg.queries
        spider._domain_blocklist = set(cfg.hard_filters.domain_blocklist)
        spider._run_id = crawler.settings.get("SCRAPE_RUN_ID", "")
        spider._discovery_fire = crawler.settings.getbool("SCRAPE_DISCOVERY_FIRE", True)
        return spider
```

At the top of `start_requests`, short-circuit:

```python
    def start_requests(self):
        if not self._discovery_fire:
            logger.info("SearXNG: discovery alternation says skip this run")
            return
        # ... existing body unchanged
```

- [ ] **Step 4: Thread `discovery_fire` through `scrape_all`**

In `job-scraper/job_scraper/__init__.py`, add a parameter `run_index: int | None = None` to `scrape_all`, and after `settings["SCRAPE_ROTATION_GROUP"] = rotation_group`:

```python
    if run_index is not None:
        every_n = load_config().scrape_profile.discovery_every_nth_run
        settings["SCRAPE_DISCOVERY_FIRE"] = (run_index % every_n) == 0
```

(If `run_index is None` we default to firing; manual runs don't skip discovery unless explicitly told to.)

- [ ] **Step 5: Run the tests**

```bash
cd job-scraper && python -m pytest tests/test_discovery_alternation.py tests/test_searxng_spider.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add job-scraper/job_scraper/spiders/searxng.py job-scraper/job_scraper/__init__.py job-scraper/tests/test_discovery_alternation.py
git -c commit.gpgsign=false commit -m "feat(scraper): alternate SearXNG discovery firing via scheduler run index

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Workable spider (new workhorse source)

New spider hitting Workable's public JSON API. Registered in `ALL_SPIDERS` and `SPIDER_TIERS`, config-driven target list.

**Files:**
- Create: `job-scraper/job_scraper/spiders/workable.py`
- Create: `job-scraper/tests/fixtures/workable_sample.json`
- Create: `job-scraper/tests/test_workable_spider.py`
- Modify: `job-scraper/job_scraper/__init__.py`
- Modify: `job-scraper/job_scraper/config.default.yaml`

- [ ] **Step 1: Pin a fixture**

Create `job-scraper/tests/fixtures/workable_sample.json` (minimal representative shape):

```json
{
  "results": [
    {
      "id": "abc123",
      "title": "Senior Security Engineer",
      "shortcode": "SEC-001",
      "department": "Engineering",
      "location": {"city": "Remote", "country": "United States"},
      "employment_type": "Full-time",
      "url": "https://apply.workable.com/acmeco/j/ABC123/",
      "application_url": "https://apply.workable.com/acmeco/j/ABC123/apply",
      "description": "<p>We're looking for a Senior Security Engineer to help us...</p>",
      "created_at": "2026-04-10T12:00:00Z"
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

Create `job-scraper/tests/test_workable_spider.py`:

```python
import json
from pathlib import Path
from scrapy.http import TextResponse, Request
from job_scraper.spiders.workable import WorkableSpider


def _fake_response(url, data):
    return TextResponse(url=url, request=Request(url=url), body=json.dumps(data).encode(), encoding="utf-8")


def test_parses_workable_jobs():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "workable_sample.json").read_text())
    spider = WorkableSpider()
    spider._targets = [{"url": "https://apply.workable.com/acmeco/", "company": "acmeco"}]
    response = _fake_response("https://apply.workable.com/api/v3/accounts/acmeco/jobs", fixture)
    response.meta["company"] = "acmeco"
    items = list(spider.parse_board(response))
    assert len(items) == 1
    item = items[0]
    assert item["company"] == "acmeco"
    assert item["board"] == "workable"
    assert item["title"] == "Senior Security Engineer"
    assert "workable" in item["url"]
```

- [ ] **Step 3: Run — verify failure**

```bash
cd job-scraper && python -m pytest tests/test_workable_spider.py -v
```

Expected: module-not-found.

- [ ] **Step 4: Implement the spider**

Create `job-scraper/job_scraper/spiders/workable.py`:

```python
"""Workable JSON API spider.

Workhorse-tier spider using Workable's public jobs endpoint. Same pattern as
Ashby/Greenhouse/Lever: configured company roster, rotation-group filter,
minimal HTML parsing (JD is in `description` field as HTML).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import scrapy

from job_scraper.items import JobItem

logger = logging.getLogger(__name__)


class WorkableSpider(scrapy.Spider):
    name = "workable"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._targets: list[dict] = []
        self._rotation_group: int | None = None
        self._rotation_total: int = 4

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider._targets = [
            {"url": b.url, "company": b.company}
            for b in cfg.boards if b.board_type == "workable" and b.enabled
        ]
        spider._rotation_group = crawler.settings.get("SCRAPE_ROTATION_GROUP")
        spider._rotation_total = crawler.settings.getint("SCRAPE_ROTATION_TOTAL", 4)
        return spider

    def start_requests(self):
        from job_scraper.tiers import rotation_filter
        targets = rotation_filter(
            self._targets,
            rotation_group=self._rotation_group,
            total_groups=self._rotation_total,
            key=lambda t: t["url"],
        )
        logger.info("Workable: crawling %d/%d targets (group=%s)",
                    len(targets), len(self._targets), self._rotation_group)
        for target in targets:
            slug = self._slug_from_url(target["url"])
            yield scrapy.Request(
                url=f"https://apply.workable.com/api/v3/accounts/{slug}/jobs",
                callback=self.parse_board,
                meta={"company": target["company"]},
                dont_filter=True,
            )

    def parse_board(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Workable returned non-JSON: %s", response.url)
            return
        company = response.meta.get("company", "unknown")
        for job in data.get("results", []):
            loc = job.get("location") or {}
            location_str = ", ".join(
                x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x
            )
            yield JobItem(
                url=job.get("url") or job.get("application_url", ""),
                title=job.get("title", "Unknown"),
                company=company,
                board="workable",
                location=location_str,
                jd_html=job.get("description") or "",
                jd_text="",  # text_extraction pipeline strips HTML
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )

    @staticmethod
    def _slug_from_url(url: str) -> str:
        # https://apply.workable.com/acmeco/ → acmeco
        path = urlparse(url).path.strip("/")
        return path.split("/")[0] if path else ""
```

- [ ] **Step 5: Register in `scrape_all`**

In `job-scraper/job_scraper/__init__.py`:

```python
    from .spiders.workable import WorkableSpider
```

Add to `ALL_SPIDERS`:

```python
        "workable": WorkableSpider,
```

- [ ] **Step 6: Seed a small initial roster**

Append to `config.default.yaml` under `crawl.targets` (keep under the existing list):

```yaml
  - url: https://apply.workable.com/remote/
    board: workable
    company: remote
  - url: https://apply.workable.com/deel/
    board: workable
    company: deel
  - url: https://apply.workable.com/tryhackme/
    board: workable
    company: tryhackme
```

- [ ] **Step 7: Run the tests**

```bash
cd job-scraper && python -m pytest tests/test_workable_spider.py tests/test_rotation_groups.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add job-scraper/job_scraper/spiders/workable.py job-scraper/tests/test_workable_spider.py job-scraper/tests/fixtures/workable_sample.json job-scraper/job_scraper/__init__.py job-scraper/job_scraper/config.default.yaml
git -c commit.gpgsign=false commit -m "feat(scraper): add Workable ATS spider (workhorse tier)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: Migrate Ashby spider to JSON API

Add a JSON path behind `legacy_html` flag; keep the old HTML path as fallback for one release. Drift test confirms parity before flip.

**Files:**
- Modify: `job-scraper/job_scraper/spiders/ashby.py`
- Create: `job-scraper/tests/fixtures/ashby_sample.json`
- Create: `job-scraper/tests/test_ashby_json_migration.py`

- [ ] **Step 1: Capture a representative JSON fixture**

Create `job-scraper/tests/fixtures/ashby_sample.json`:

```json
{
  "apiVersion": "2",
  "jobs": [
    {
      "id": "11111111-aaaa-bbbb-cccc-222222222222",
      "title": "Security Engineer",
      "departmentName": "Engineering",
      "teamName": "Security",
      "locationName": "Remote - United States",
      "employmentType": "FullTime",
      "publishedDate": "2026-04-10T00:00:00.000Z",
      "jobUrl": "https://jobs.ashbyhq.com/acmeco/job-posting/11111111-aaaa-bbbb-cccc-222222222222",
      "descriptionHtml": "<p>About the role…</p>",
      "compensation": {
        "summaryComponents": [
          {"label": "Base Salary", "currencyCode": "USD", "minValue": 160000, "maxValue": 200000}
        ]
      }
    }
  ]
}
```

- [ ] **Step 2: Write the migration test**

Create `job-scraper/tests/test_ashby_json_migration.py`:

```python
import json
from pathlib import Path
from scrapy.http import TextResponse, Request
from job_scraper.spiders.ashby import AshbySpider


def test_ashby_json_path_yields_item():
    spider = AshbySpider()
    spider._use_json_api = True
    fixture = json.loads((Path(__file__).parent / "fixtures" / "ashby_sample.json").read_text())
    url = "https://api.ashbyhq.com/posting-api/job-board/acmeco?includeCompensation=true"
    response = TextResponse(url=url, request=Request(url=url),
                            body=json.dumps(fixture).encode(), encoding="utf-8")
    response.meta["company"] = "acmeco"
    items = list(spider.parse_board_json(response))
    assert len(items) == 1
    item = items[0]
    assert item["board"] == "ashby"
    assert item["company"] == "acmeco"
    assert item["title"] == "Security Engineer"
    assert "Remote" in item["location"]
    assert item["salary_k"] is not None  # parsed compensation
```

- [ ] **Step 3: Run — expect failure**

```bash
cd job-scraper && python -m pytest tests/test_ashby_json_migration.py -v
```

Expected: `AttributeError: 'AshbySpider' has no attribute 'parse_board_json'`.

- [ ] **Step 4: Add the JSON path**

In `job-scraper/job_scraper/spiders/ashby.py`, add a flag read in `from_crawler`:

```python
        spider._use_json_api = not crawler.settings.getbool("ASHBY_LEGACY_HTML", False)
```

In `start_requests`, branch on the flag:

```python
        for target in targets:
            if self._use_json_api:
                slug = self._slug_from_url(target["url"])
                yield scrapy.Request(
                    url=f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
                    callback=self.parse_board_json,
                    meta={"company": target["company"]},
                    dont_filter=True,
                )
            else:
                yield scrapy.Request(
                    # ... existing HTML request unchanged
                )
```

Add `parse_board_json`:

```python
    def parse_board_json(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Ashby JSON endpoint returned non-JSON: %s", response.url)
            return
        company = response.meta.get("company", "unknown")
        for job in data.get("jobs", []):
            salary_k = None
            comp = (job.get("compensation") or {}).get("summaryComponents") or []
            if comp:
                values = [c.get("minValue") for c in comp if c.get("minValue")]
                if values:
                    salary_k = min(values) / 1000.0
            yield JobItem(
                url=job.get("jobUrl", ""),
                title=job.get("title", "Unknown"),
                company=company,
                board="ashby",
                location=job.get("locationName", ""),
                salary_k=salary_k,
                jd_html=job.get("descriptionHtml", ""),
                jd_text="",
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )

    @staticmethod
    def _slug_from_url(url: str) -> str:
        from urllib.parse import urlparse
        path = urlparse(url).path.strip("/")
        return path.split("/")[0] if path else ""
```

(Top of file: ensure `from job_scraper.items import JobItem` and `from datetime import datetime, timezone` are imported.)

- [ ] **Step 5: Run the tests**

```bash
cd job-scraper && python -m pytest tests/test_ashby_json_migration.py -v
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add job-scraper/job_scraper/spiders/ashby.py job-scraper/tests/test_ashby_json_migration.py job-scraper/tests/fixtures/ashby_sample.json
git -c commit.gpgsign=false commit -m "feat(scraper): migrate Ashby spider to posting-api JSON (legacy flag retained)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: Migrate Greenhouse spider to JSON API

Same pattern as Task 10. Endpoint: `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`. Response shape: `{"jobs": [{"id", "title", "absolute_url", "location": {"name"}, "departments": [...], "content": "<html>..."}]}`.

**Files:**
- Modify: `job-scraper/job_scraper/spiders/greenhouse.py`
- Create: `job-scraper/tests/fixtures/greenhouse_sample.json`
- Create: `job-scraper/tests/test_greenhouse_json_migration.py`

- [ ] **Step 1: Capture fixture**

Create `job-scraper/tests/fixtures/greenhouse_sample.json`:

```json
{
  "jobs": [
    {
      "id": 4000000001,
      "title": "Platform Engineer",
      "absolute_url": "https://job-boards.greenhouse.io/acmeco/jobs/4000000001",
      "location": {"name": "Remote - US"},
      "departments": [{"id": 1, "name": "Engineering"}],
      "offices": [{"name": "Remote"}],
      "content": "\u003Cp\u003EJoin our platform team...\u003C/p\u003E",
      "updated_at": "2026-04-10T12:00:00-04:00"
    }
  ]
}
```

- [ ] **Step 2: Write the test**

Create `job-scraper/tests/test_greenhouse_json_migration.py`:

```python
import json
from pathlib import Path
from scrapy.http import TextResponse, Request
from job_scraper.spiders.greenhouse import GreenhouseSpider


def test_greenhouse_json_path_yields_item():
    spider = GreenhouseSpider()
    spider._use_json_api = True
    fixture = json.loads((Path(__file__).parent / "fixtures" / "greenhouse_sample.json").read_text())
    url = "https://boards-api.greenhouse.io/v1/boards/acmeco/jobs?content=true"
    response = TextResponse(url=url, request=Request(url=url),
                            body=json.dumps(fixture).encode(), encoding="utf-8")
    response.meta["company"] = "acmeco"
    items = list(spider.parse_board_json(response))
    assert len(items) == 1
    item = items[0]
    assert item["board"] == "greenhouse"
    assert item["company"] == "acmeco"
    assert "Remote" in item["location"]
    assert "Join our platform team" in item["jd_html"]
```

- [ ] **Step 3: Run — verify failure**

```bash
cd job-scraper && python -m pytest tests/test_greenhouse_json_migration.py -v
```

Expected: attribute error.

- [ ] **Step 4: Implement `parse_board_json` + flag**

In `job-scraper/job_scraper/spiders/greenhouse.py`, mirror Task 10's structure:

Add `_use_json_api` in `from_crawler` (using `GREENHOUSE_LEGACY_HTML` setting). In `start_requests`, branch on the flag. The JSON callback:

```python
    def parse_board_json(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Greenhouse JSON endpoint returned non-JSON: %s", response.url)
            return
        company = response.meta.get("company", "unknown")
        for job in data.get("jobs", []):
            loc = (job.get("location") or {}).get("name") or ""
            yield JobItem(
                url=job.get("absolute_url", ""),
                title=job.get("title", "Unknown"),
                company=company,
                board="greenhouse",
                location=loc,
                jd_html=job.get("content") or "",
                jd_text="",
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )

    @staticmethod
    def _slug_from_url(url: str) -> str:
        from urllib.parse import urlparse
        path = urlparse(url).path.strip("/")
        return path.split("/")[0] if path else ""
```

For the request side in `start_requests` when `_use_json_api`:

```python
                slug = self._slug_from_url(target["url"])
                yield scrapy.Request(
                    url=f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
                    callback=self.parse_board_json,
                    meta={"company": target["company"]},
                    dont_filter=True,
                )
```

- [ ] **Step 5: Run the test**

```bash
cd job-scraper && python -m pytest tests/test_greenhouse_json_migration.py -v
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add job-scraper/job_scraper/spiders/greenhouse.py job-scraper/tests/test_greenhouse_json_migration.py job-scraper/tests/fixtures/greenhouse_sample.json
git -c commit.gpgsign=false commit -m "feat(scraper): migrate Greenhouse spider to boards-api JSON

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 12: Migrate Lever spider to JSON API

Endpoint: `https://api.lever.co/v0/postings/{slug}?mode=json`. Response shape: array of posting objects with `id, text, categories: {location, team}, hostedUrl, descriptionPlain, descriptionHtml, salaryRange`.

**Files:**
- Modify: `job-scraper/job_scraper/spiders/lever.py`
- Create: `job-scraper/tests/fixtures/lever_sample.json`
- Create: `job-scraper/tests/test_lever_json_migration.py`

- [ ] **Step 1: Capture fixture**

Create `job-scraper/tests/fixtures/lever_sample.json`:

```json
[
  {
    "id": "aaaa-bbbb-cccc",
    "text": "DevSecOps Engineer",
    "categories": {
      "location": "Remote (United States)",
      "team": "Security",
      "commitment": "Full-time"
    },
    "hostedUrl": "https://jobs.lever.co/acmeco/aaaa-bbbb-cccc",
    "descriptionHtml": "<p>You'll own our build-time security pipeline.</p>",
    "salaryRange": {"currency": "USD", "interval": "per-year-salary", "min": 150000, "max": 180000},
    "createdAt": 1712764800000
  }
]
```

- [ ] **Step 2: Write the test**

Create `job-scraper/tests/test_lever_json_migration.py`:

```python
import json
from pathlib import Path
from scrapy.http import TextResponse, Request
from job_scraper.spiders.lever import LeverSpider


def test_lever_json_path_yields_item():
    spider = LeverSpider()
    spider._use_json_api = True
    fixture = json.loads((Path(__file__).parent / "fixtures" / "lever_sample.json").read_text())
    url = "https://api.lever.co/v0/postings/acmeco?mode=json"
    response = TextResponse(url=url, request=Request(url=url),
                            body=json.dumps(fixture).encode(), encoding="utf-8")
    response.meta["company"] = "acmeco"
    items = list(spider.parse_board_json(response))
    assert len(items) == 1
    item = items[0]
    assert item["board"] == "lever"
    assert item["company"] == "acmeco"
    assert "Remote" in item["location"]
    assert item["salary_k"] == 150.0
```

- [ ] **Step 3: Run — verify failure**

```bash
cd job-scraper && python -m pytest tests/test_lever_json_migration.py -v
```

- [ ] **Step 4: Implement**

In `job-scraper/job_scraper/spiders/lever.py`, mirror the pattern:

```python
    def parse_board_json(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Lever JSON endpoint returned non-JSON: %s", response.url)
            return
        company = response.meta.get("company", "unknown")
        for job in data:
            categories = job.get("categories") or {}
            salary_k = None
            sr = job.get("salaryRange") or {}
            if sr.get("min"):
                salary_k = sr["min"] / 1000.0
            yield JobItem(
                url=job.get("hostedUrl", ""),
                title=job.get("text", "Unknown"),
                company=company,
                board="lever",
                location=categories.get("location", ""),
                salary_k=salary_k,
                jd_html=job.get("descriptionHtml") or "",
                jd_text="",
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
```

Plus the `_slug_from_url` helper and `_use_json_api` flag (setting name `LEVER_LEGACY_HTML`), and request-side branch in `start_requests`:

```python
                slug = self._slug_from_url(target["url"])
                yield scrapy.Request(
                    url=f"https://api.lever.co/v0/postings/{slug}?mode=json",
                    callback=self.parse_board_json,
                    meta={"company": target["company"]},
                    dont_filter=True,
                )
```

- [ ] **Step 5: Run the test**

```bash
cd job-scraper && python -m pytest tests/test_lever_json_migration.py -v
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add job-scraper/job_scraper/spiders/lever.py job-scraper/tests/test_lever_json_migration.py job-scraper/tests/fixtures/lever_sample.json
git -c commit.gpgsign=false commit -m "feat(scraper): migrate Lever spider to postings-api JSON

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 13: Scheduler service (APScheduler, feature-flagged)

Background APScheduler in FastAPI startup, dispatches tier-aware scrape runs via the existing run-dispatch path. Off by default.

**Files:**
- Create: `dashboard/backend/services/scrape_scheduler.py`
- Create: `dashboard/backend/tests/test_scrape_scheduler.py`
- Modify: `dashboard/backend/server.py`
- Modify: `dashboard/backend/routers/scraping.py`
- Modify: `job-scraper/api/scraping_handlers.py`

- [ ] **Step 1: Confirm APScheduler is installed**

```bash
python -c "import apscheduler; print(apscheduler.__version__)"
```

If missing: `pip install APScheduler==3.10.4` and add to `requirements.txt`.

- [ ] **Step 2: Write the failing test**

Create `dashboard/backend/tests/test_scrape_scheduler.py`:

```python
from services.scrape_scheduler import compute_tick_plan


def test_tick_plan_index_0_fires_discovery():
    plan = compute_tick_plan(run_index=0, rotation_groups=4, discovery_every_nth=2)
    assert plan["group"] == 0
    assert "discovery" in plan["tiers"]
    assert "workhorse" in plan["tiers"]
    assert "lead" in plan["tiers"]


def test_tick_plan_index_1_skips_discovery():
    plan = compute_tick_plan(run_index=1, rotation_groups=4, discovery_every_nth=2)
    assert plan["group"] == 1
    assert "discovery" not in plan["tiers"]


def test_tick_plan_index_6_wraps_group():
    plan = compute_tick_plan(run_index=6, rotation_groups=4, discovery_every_nth=2)
    assert plan["group"] == 2  # 6 mod 4
    assert "discovery" in plan["tiers"]  # 6 mod 2 == 0


def test_alternation_factor_1_always_fires_discovery():
    for i in range(5):
        plan = compute_tick_plan(run_index=i, rotation_groups=4, discovery_every_nth=1)
        assert "discovery" in plan["tiers"]
```

- [ ] **Step 3: Run — verify failure**

```bash
python -m pytest dashboard/backend/tests/test_scrape_scheduler.py -v
```

Expected: module not found.

- [ ] **Step 4: Implement the scheduler**

Create `dashboard/backend/services/scrape_scheduler.py`:

```python
"""APScheduler-driven tier-aware scrape dispatcher.

Feature-flagged by TEXTAILOR_SCRAPE_SCHEDULER=1. Reads cron/group/alternation
from scrape_profile in the scraper config. No UI knobs — cadence changes are
config + restart (architectural, not runtime).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def compute_tick_plan(
    *,
    run_index: int,
    rotation_groups: int,
    discovery_every_nth: int,
) -> dict[str, Any]:
    group = run_index % rotation_groups
    fire_discovery = (run_index % discovery_every_nth) == 0
    tiers = ["workhorse", "lead"]
    if fire_discovery:
        tiers.append("discovery")
    return {"run_index": run_index, "group": group, "tiers": tiers}


def _next_run_index(db_path) -> int:
    """Max(rotation_group) + 1 over the last week of runs. None-safe."""
    import sqlite3
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE rotation_group IS NOT NULL"
        ).fetchone()
    return int(row[0] if row else 0)


async def _tick():
    from job_scraper.config import load_config, DB_PATH
    cfg = load_config()
    profile = cfg.scrape_profile
    run_index = _next_run_index(DB_PATH)
    plan = compute_tick_plan(
        run_index=run_index,
        rotation_groups=profile.rotation_groups,
        discovery_every_nth=profile.discovery_every_nth_run,
    )
    logger.info(
        "scheduler: tick run_index=%s group=%s tiers=%s",
        plan["run_index"], plan["group"], plan["tiers"],
    )
    # Concurrency guard: skip if a prior run is still active.
    from services.scraping import handlers as scraping_handlers
    status = scraping_handlers.scrape_runner_status(lines=0)
    if status.get("active"):
        logger.warning("scheduler: skipping tick — run still active")
        return
    scraping_handlers.run_scrape({
        "tiers": plan["tiers"],
        "rotation_group": plan["group"],
        "run_index": plan["run_index"],
    })


async def start():
    global _scheduler
    from job_scraper.config import load_config
    profile = load_config().scrape_profile
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_tick, CronTrigger.from_crontab(profile.cadence), id="scrape_tick")
    _scheduler.start()
    logger.info("scheduler started: cadence=%s", profile.cadence)


async def stop():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler stopped")


def enabled() -> bool:
    return os.getenv("TEXTAILOR_SCRAPE_SCHEDULER", "0") == "1"


def next_run_time() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job("scrape_tick")
    if not job or not job.next_run_time:
        return None
    return job.next_run_time.isoformat()
```

- [ ] **Step 5: Extend `run_scrape` handler to accept tiers/group**

In `job-scraper/api/scraping_handlers.py`, update the `run_scrape` body:

```python
def run_scrape(payload: dict = Body(default={})):
    _sync_app_state()
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid payload"}, 400)
    spider = payload.get("spider")
    tiers = payload.get("tiers")
    rotation_group = payload.get("rotation_group")
    run_index = payload.get("run_index")
    ok, result = _start_scrape_run(
        spider=spider,
        tiers=tiers,
        rotation_group=rotation_group,
        run_index=run_index,
    )
    if not ok:
        return JSONResponse(result, 409)
    return result
```

Thread the new kwargs into `_start_scrape_run` (inspect file to find its signature; it already invokes `scrape_all` — forward the kwargs).

- [ ] **Step 6: Wire startup/shutdown hooks**

In `dashboard/backend/server.py`, find the FastAPI `app = FastAPI(...)` declaration and add (near other event handlers):

```python
from services import scrape_scheduler

@app.on_event("startup")
async def _scrape_scheduler_startup():
    if scrape_scheduler.enabled():
        await scrape_scheduler.start()

@app.on_event("shutdown")
async def _scrape_scheduler_shutdown():
    if scrape_scheduler.enabled():
        await scrape_scheduler.stop()
```

- [ ] **Step 7: Run the scheduler tests**

```bash
python -m pytest dashboard/backend/tests/test_scrape_scheduler.py -v
```

Expected: 4 passed.

- [ ] **Step 8: Run backend suite for regressions**

```bash
python -m pytest dashboard/backend/tests/ -v
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add dashboard/backend/services/scrape_scheduler.py dashboard/backend/tests/test_scrape_scheduler.py dashboard/backend/server.py job-scraper/api/scraping_handlers.py
git -c commit.gpgsign=false commit -m "feat(dashboard): tier-aware scrape scheduler (feature-flagged)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 14: Metrics dashboard surfaces

Backend endpoint + frontend widgets for per-tier, 7-day rollups, source-health, and gate-overflow banner.

**Files:**
- Modify: `dashboard/backend/routers/scraping.py`
- Modify: `job-scraper/api/scraping_handlers.py` (add `tier_stats_rollup` handler)
- Modify: `dashboard/web/src/api.ts`
- Modify: `dashboard/web/src/views/domains/ops/MetricsView.tsx`
- Create: `dashboard/backend/tests/test_tier_stats_api.py`

- [ ] **Step 1: Write the failing backend test**

Create `dashboard/backend/tests/test_tier_stats_api.py`:

```python
def test_tier_stats_endpoint_returns_schema(client):
    resp = client.get("/api/scraper/metrics/tier-stats?since=7d")
    assert resp.status_code == 200
    data = resp.json()
    assert "per_run" in data
    assert "by_source" in data
    assert "daily_net_new" in data
```

(Assuming the existing test fixture provides a `client` — check existing `conftest.py`; if a fixture doesn't exist, use `TestClient(app)` inline.)

- [ ] **Step 2: Run — verify failure**

```bash
python -m pytest dashboard/backend/tests/test_tier_stats_api.py -v
```

Expected: 404 / endpoint not found.

- [ ] **Step 3: Implement the handler**

In `job-scraper/api/scraping_handlers.py`, add:

```python
def tier_stats_rollup(since: str = "7d"):
    import re
    from datetime import datetime, timedelta, timezone
    m = re.fullmatch(r"(\d+)d", since)
    days = int(m.group(1)) if m else 7
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_db()
    try:
        per_run = [dict(r) for r in conn.execute(
            """SELECT run_id, started_at, net_new, gate_mode, rotation_group
               FROM runs WHERE started_at >= ? ORDER BY started_at DESC LIMIT 60""",
            (cutoff,),
        ).fetchall()]
        by_source = [dict(r) for r in conn.execute(
            """SELECT source, tier,
                      SUM(raw_hits) AS raw_hits,
                      SUM(dedup_drops) AS dedup_drops,
                      SUM(filter_drops) AS filter_drops,
                      SUM(llm_rejects + llm_uncertain_low) AS llm_rejects,
                      SUM(stored_pending) AS stored_pending,
                      SUM(stored_lead) AS stored_lead,
                      COUNT(DISTINCT run_id) AS runs
               FROM run_tier_stats
               WHERE run_id IN (SELECT run_id FROM runs WHERE started_at >= ?)
               GROUP BY source, tier""",
            (cutoff,),
        ).fetchall()]
        daily_net_new = [dict(r) for r in conn.execute(
            """SELECT substr(started_at, 1, 10) AS day, SUM(net_new) AS net_new
               FROM runs WHERE started_at >= ?
               GROUP BY substr(started_at, 1, 10) ORDER BY day""",
            (cutoff,),
        ).fetchall()]
        return {"per_run": per_run, "by_source": by_source, "daily_net_new": daily_net_new}
    finally:
        conn.close()
```

- [ ] **Step 4: Register the route**

In `dashboard/backend/routers/scraping.py`, add to the route list:

```python
    ("GET", "/api/scraper/metrics/tier-stats", "tier_stats_rollup"),
```

- [ ] **Step 5: Run the backend test**

```bash
python -m pytest dashboard/backend/tests/test_tier_stats_api.py -v
```

Expected: pass.

- [ ] **Step 6: Frontend — add API method**

In `dashboard/web/src/api.ts`, add:

```typescript
export async function getTierStatsRollup(since = "7d") {
  return fetchJson(`/api/scraper/metrics/tier-stats?since=${encodeURIComponent(since)}`);
}
```

- [ ] **Step 7: Frontend — extend `MetricsView.tsx`**

In `dashboard/web/src/views/domains/ops/MetricsView.tsx`, add a new section (keep it beneath the existing metrics). Minimal React for the three widgets:

```tsx
import { getTierStatsRollup } from "../../../api";
import { useEffect, useState } from "react";

function TierStatsPanel() {
  const [data, setData] = useState<any>(null);
  useEffect(() => {
    getTierStatsRollup("7d").then(setData);
  }, []);
  if (!data) return <div>Loading tier stats…</div>;

  const overflowRuns = (data.per_run || []).slice(0, 3)
    .filter((r: any) => r.gate_mode === "overflow");

  return (
    <section>
      <h2>Scraper tier stats (7d)</h2>

      {overflowRuns.length === 3 && (
        <div style={{ background: "#fff4e5", border: "1px solid #f0a030", padding: "8px", marginBottom: "12px" }}>
          Gate overflow on last 3 runs — SearXNG volume or LLM endpoint may need attention.
        </div>
      )}

      <div>
        <h3>Daily net-new vs 50/day target</h3>
        <ul>
          {(data.daily_net_new || []).map((d: any) => (
            <li key={d.day}>
              {d.day}: <strong>{d.net_new}</strong>
              {d.net_new < 35 && <span style={{ color: "#b34" }}> (below 70% target)</span>}
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h3>Source health</h3>
        <table>
          <thead>
            <tr>
              <th>Tier</th><th>Source</th><th>Raw</th><th>Dedup-drop</th>
              <th>Filter-drop</th><th>LLM-reject</th><th>Pending</th><th>Lead</th><th>Runs</th>
            </tr>
          </thead>
          <tbody>
            {(data.by_source || []).map((r: any) => (
              <tr key={`${r.tier}-${r.source}`}>
                <td>{r.tier}</td><td>{r.source}</td>
                <td>{r.raw_hits}</td><td>{r.dedup_drops}</td>
                <td>{r.filter_drops}</td><td>{r.llm_rejects}</td>
                <td>{r.stored_pending}</td><td>{r.stored_lead}</td>
                <td>{r.runs}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
```

Render `<TierStatsPanel />` inside the existing `MetricsView` component return.

- [ ] **Step 8: Build and smoke-test frontend**

```bash
cd dashboard/web && npm run build
```

Expected: no TypeScript errors.

- [ ] **Step 9: Commit**

```bash
git add dashboard/backend/routers/scraping.py job-scraper/api/scraping_handlers.py dashboard/backend/tests/test_tier_stats_api.py dashboard/web/src/api.ts dashboard/web/src/views/domains/ops/MetricsView.tsx
git -c commit.gpgsign=false commit -m "feat(dashboard): expose tier-stats rollup API and metrics panel

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Post-merge Validation (not a task — operator action)

Once all tasks are on `main`:

1. Enable the scheduler in your environment: `export TEXTAILOR_SCRAPE_SCHEDULER=1`, restart the dashboard.
2. Let it run for 7 days. Check `/ops/metrics` against the success criteria in the spec §12:
   - ≥5 of 7 days produce ≥35 net-new
   - SearXNG raw→stored ratio ≥20%
   - Workhorse ≥40% of net-new
   - Zero empty runs unless all URLs are within TTL
   - `gate_overflow` rate <5% of discovery-firing runs
3. If the LLM gate is over-rejecting, raise `scrape_profile.llm_gate.accept_threshold` to 4 (or lower) and rerun.
4. If workhorse volume is the bottleneck, add companies to `crawl.targets` — rotation automatically absorbs them.
5. After one release cycle of stability, delete the legacy HTML paths by searching for `ASHBY_LEGACY_HTML` / `GREENHOUSE_LEGACY_HTML` / `LEVER_LEGACY_HTML` and removing the branches.
