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
