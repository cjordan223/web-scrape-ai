import json
from pathlib import Path

from job_scraper.items import JobItem
from job_scraper.pipelines.llm_relevance import _HTTPGateClient, LLMRelevancePipeline, GateOutcome
from job_scraper.scrape_profile import LLMGateConfig


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


class _FakeSettings:
    def __init__(self):
        self.values = {}

    def set(self, key, value, priority=None):
        self.values[key] = value


class _FakeCrawler:
    def __init__(self):
        self.settings = _FakeSettings()


class _FakeCrawlerSpider:
    name = "searxng"

    def __init__(self):
        self.crawler = _FakeCrawler()


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

    class AshbySpider:
        name = "ashby"

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


def test_malformed_retry_then_raises_when_fail_open_disabled():
    client = _StubClient([FIXTURES["malformed"], FIXTURES["malformed"]])
    pipe = _make_pipe(client)
    item = {"url": "https://x", "title": "Eng", "company": "acme",
            "snippet": "", "source": "searxng", "status": "pending"}
    try:
        pipe.process_item(item, _FakeSpider())
    except RuntimeError as exc:
        assert "valid JSON" in str(exc)
    else:
        raise AssertionError("expected malformed LLM output to fail closed")
    assert client.calls == 2


def test_malformed_retry_then_uncertain_when_fail_open_enabled():
    client = _StubClient([FIXTURES["malformed"], FIXTURES["malformed"]])
    pipe = _make_pipe(client, cfg=LLMGateConfig(fail_open=True))
    item = {"url": "https://x", "title": "Eng", "company": "acme",
            "snippet": "", "source": "searxng", "status": "pending"}
    out = pipe.process_item(item, _FakeSpider())
    assert out["status"] == "pending"
    assert client.calls == 2


def test_batch_cap_falls_back_to_rules_only():
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


def test_jobitem_with_flags_survives_gate():
    """Regression: the LLM gate must not crash when the model returns non-empty flags.

    Prior to the fix, `_apply_verdict` called `item["flags"] = flags` on a JobItem
    that didn't declare a `flags` field, which raised KeyError. Scrapy silently
    dropped the item, so counters never bumped and the item vanished between the
    filter stage and storage (observed as raw=107, filter=10, llm=0, stored=0 for
    searxng on 2026-04-19).
    """
    pipe = _make_pipe(_StubClient([FIXTURES["accept"]]))
    item = JobItem(
        url="https://x", title="Security Eng", company="acme",
        snippet="remote us", source="searxng", status="pending",
    )
    out = pipe.process_item(item, _FakeSpider())
    assert out["score"] == 8
    assert out["flags"] == ["remote_us_confirmed"]
    assert out["status"] == "pending"


def test_jobitem_reject_with_flags_survives_gate():
    pipe = _make_pipe(_StubClient([FIXTURES["reject"]]))
    item = JobItem(
        url="https://x", title="Staff Eng", company="acme",
        snippet="", source="searxng", status="pending",
    )
    out = pipe.process_item(item, _FakeSpider())
    assert out["status"] == "rejected"
    assert out["flags"] == ["seniority_too_high"]


def test_fail_open_on_circuit_break():
    class BrokenClient:
        def ask(self, prompt):
            raise TimeoutError("no response")
    pipe = _make_pipe(BrokenClient(), cfg=LLMGateConfig(fail_open=True))
    for _ in range(3):
        item = {"url": f"https://x/{_}", "title": "Eng", "company": "c",
                "snippet": "", "source": "searxng", "status": "pending"}
        pipe.process_item(item, _FakeSpider())
    item = {"url": "https://x/final", "title": "Eng", "company": "c",
            "snippet": "", "source": "searxng", "status": "pending"}
    out = pipe.process_item(item, _FakeSpider())
    assert out["status"] == "pending"
    assert pipe.mode == GateOutcome.FAIL_OPEN


def test_gate_failure_raises_when_fail_open_disabled():
    class BrokenClient:
        def ask(self, prompt):
            raise TimeoutError("no response")

    pipe = _make_pipe(BrokenClient(), cfg=LLMGateConfig(fail_open=False))
    item = {"url": "https://x/fail", "title": "Eng", "company": "c",
            "snippet": "", "source": "searxng", "status": "pending"}

    try:
        pipe.process_item(item, _FakeSpider())
    except RuntimeError as exc:
        assert "fail_open is disabled" in str(exc)
    else:
        raise AssertionError("expected fail-closed LLM gate to raise")


def test_gate_failure_marks_crawler_settings():
    class BrokenClient:
        def ask(self, prompt):
            raise TimeoutError("no response")

    spider = _FakeCrawlerSpider()
    pipe = _make_pipe(BrokenClient(), cfg=LLMGateConfig(fail_open=False))
    item = {"url": "https://x/fail", "title": "Eng", "company": "c",
            "snippet": "", "source": "searxng", "status": "pending"}

    try:
        pipe.process_item(item, spider)
    except RuntimeError:
        pass

    assert spider.crawler.settings.values["LLM_GATE_MODE_OBSERVED"] == "failed"
    assert "no response" in spider.crawler.settings.values["LLM_GATE_FAILURE"]


def test_http_gate_client_does_not_silently_fallback(monkeypatch):
    calls: list[str] = []

    def broken_post(url, **kwargs):
        calls.append(url)
        raise TimeoutError("ollama unavailable")

    monkeypatch.setattr("requests.post", broken_post)
    cfg = LLMGateConfig(
        endpoint="http://localhost:11434/v1/chat/completions",
        model="qwen2.5:7b",
    )
    client = _HTTPGateClient(cfg)

    try:
        client.ask("score this job")
    except TimeoutError:
        pass
    else:
        raise AssertionError("expected unavailable Ollama call to raise")

    assert calls == ["http://localhost:11434/v1/chat/completions"]
