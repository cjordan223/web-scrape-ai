"""Spider tier registry + rotation helper.

Tiers are a first-class concept: each spider declares its tier, and pipeline
routing, scheduling, and metrics all branch on tier. Rotation groups use a
stable hash so the same item lands in the same group across runs.
"""
from __future__ import annotations

import hashlib
from enum import Enum
from typing import Callable, Iterable, TypeVar


class Tier(str, Enum):
    WORKHORSE = "workhorse"   # direct ATS, high-signal, known-good companies
    DISCOVERY = "discovery"   # SearXNG — breadth via search engines


SPIDER_TIERS: dict[str, Tier] = {
    "ashby": Tier.WORKHORSE,
    "greenhouse": Tier.WORKHORSE,
    "lever": Tier.WORKHORSE,
    "workable": Tier.WORKHORSE,
    "searxng": Tier.DISCOVERY,
    "remotive": Tier.DISCOVERY,
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
    key: Callable[[T], str] | None = None,
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
