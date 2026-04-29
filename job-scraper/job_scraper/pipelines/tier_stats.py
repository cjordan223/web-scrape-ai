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
    "raw_hits", "dedup_drops",
    "duplicate_url", "duplicate_ats_id", "duplicate_fingerprint",
    "duplicate_similar", "duplicate_content", "reposts", "changed_postings",
    "filter_drops",
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
