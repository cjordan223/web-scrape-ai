"""Tests for the tier-aware scrape scheduler."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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
    assert plan["group"] == 2
    assert "discovery" in plan["tiers"]


def test_alternation_factor_1_always_fires_discovery():
    for i in range(5):
        plan = compute_tick_plan(run_index=i, rotation_groups=4, discovery_every_nth=1)
        assert "discovery" in plan["tiers"]
