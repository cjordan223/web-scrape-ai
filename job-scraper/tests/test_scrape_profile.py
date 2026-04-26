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
    assert g.endpoint == "http://localhost:11434/v1/chat/completions"
    assert g.model == "qwen2.5:7b"
    assert not hasattr(g, "fallback_endpoint")
    assert not hasattr(g, "fallback_model")
    assert g.accept_threshold == 5
    assert g.max_calls_per_run == 150
    assert g.timeout_seconds == 10
    assert g.fail_open is False
