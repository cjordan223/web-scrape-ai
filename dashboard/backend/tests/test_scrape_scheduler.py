"""Tests for the tier-aware scrape scheduler."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.scrape_scheduler import (
    OllamaHealthError,
    check_ollama_ready,
    compute_tick_plan,
    ollama_base_url_from_chat_endpoint,
)


def test_tick_plan_index_0_fires_discovery():
    plan = compute_tick_plan(run_index=0, rotation_groups=4, discovery_every_nth=2)
    assert plan["group"] == 0
    assert "discovery" in plan["tiers"]
    assert "workhorse" in plan["tiers"]
    assert "lead" not in plan["tiers"]


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


def test_ollama_health_requires_configured_model():
    def fake_fetch(url: str, timeout: int = 3):
        assert url == "http://localhost:11434/api/tags"
        return {"models": [{"name": "qwen2.5:7b"}]}

    check_ollama_ready(model="qwen2.5:7b", fetch_json=fake_fetch)


def test_ollama_health_fails_when_model_missing():
    def fake_fetch(url: str, timeout: int = 3):
        return {"models": [{"name": "llama3.1:8b"}]}

    with pytest.raises(OllamaHealthError, match="qwen2.5:7b"):
        check_ollama_ready(model="qwen2.5:7b", fetch_json=fake_fetch)


def test_ollama_health_fails_when_daemon_unreachable():
    def fake_fetch(url: str, timeout: int = 3):
        raise OSError("connection refused")

    with pytest.raises(OllamaHealthError, match="Ollama unavailable"):
        check_ollama_ready(model="qwen2.5:7b", fetch_json=fake_fetch)


def test_ollama_health_uses_configured_endpoint_base():
    seen: list[str] = []

    def fake_fetch(url: str, timeout: int = 3):
        seen.append(url)
        return {"models": [{"name": "qwen2.5:7b"}]}

    base_url = ollama_base_url_from_chat_endpoint(
        "http://127.0.0.1:11500/v1/chat/completions"
    )
    check_ollama_ready(model="qwen2.5:7b", base_url=base_url, fetch_json=fake_fetch)

    assert seen == ["http://127.0.0.1:11500/api/tags"]
