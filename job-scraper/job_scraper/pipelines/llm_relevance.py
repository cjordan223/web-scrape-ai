"""LLM relevance gate — discovery-tier-only pipeline stage."""
from __future__ import annotations

import json
import logging
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
        import requests
        body = {
            "model": self._cfg.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        r = requests.post(self._cfg.endpoint, json=body, timeout=self._cfg.timeout_seconds)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def _load_persona_card() -> str:
    persona_dir = Path(__file__).resolve().parents[3] / "tailoring" / "persona"
    if not persona_dir.exists():
        return ""
    chunks = []
    for name in ("identity.md", "motivation.md", "evidence.md"):
        p = persona_dir / name
        if p.exists():
            chunks.append(p.read_text())
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
        try:
            tier = spider_tier(spider.name)
        except KeyError:
            return item
        if tier is not Tier.DISCOVERY:
            return item
        if not self._cfg.enabled:
            return item

        if self.mode is GateOutcome.FAIL_OPEN:
            return item

        if self._calls_made >= self._cfg.max_calls_per_run:
            self._mark_overflow()
            return self._rules_only(item, spider)

        prompt = self._build_prompt(item)
        try:
            raw = self._client.ask(prompt)
            self._consecutive_timeouts = 0
        except Exception as exc:
            self._consecutive_timeouts += 1
            logger.warning(
                "LLM gate call failed (%d in a row): %s",
                self._consecutive_timeouts, exc,
            )
            if not self._cfg.fail_open:
                self._record_gate_failure(spider, str(exc))
                raise RuntimeError(
                    "LLM relevance gate unavailable and fail_open is disabled"
                ) from exc
            if self._consecutive_timeouts >= 3 and self._cfg.fail_open:
                self.mode = GateOutcome.FAIL_OPEN
                self._record_mode_observed(spider)
                return item
            return self._apply_verdict(
                item, spider,
                verdict="uncertain",
                score=self._cfg.accept_threshold,
            )

        self._calls_made += 1
        parsed = self._parse(raw)
        if parsed is None:
            try:
                raw2 = self._client.ask(prompt + "\n\nReturn ONLY valid JSON.")
                parsed = self._parse(raw2)
                self._calls_made += 1
            except Exception:
                parsed = None
            if parsed is None:
                if not self._cfg.fail_open:
                    self._record_gate_failure(spider, "LLM gate returned invalid JSON")
                    raise RuntimeError("LLM relevance gate returned invalid JSON")
                return self._apply_verdict(
                    item, spider,
                    verdict="uncertain",
                    score=self._cfg.accept_threshold,
                )

        return self._apply_verdict(
            item, spider,
            verdict=parsed.get("verdict", "uncertain"),
            score=int(parsed.get("score", 0)),
            reason=parsed.get("reason"),
            flags=parsed.get("flags") or [],
        )

    def close_spider(self, spider):
        self._record_mode_observed(spider)

    def _build_prompt(self, item: dict[str, Any]) -> str:
        return (
            "You are gating job postings for relevance to this candidate. "
            "HARD REQUIREMENTS (reject if violated): the role must be (a) "
            "based in the United States, and (b) fully remote. EU-only, "
            "UK-only, hybrid, in-office, or unspecified-location postings "
            "are reject. Titles containing '(m/f/d)', '(w/m/d)', '(f/m/d)' "
            "or named EU/APAC cities are reject regardless of snippet.\n\n"
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
            f"Snippet: {(item.get('snippet') or '')[:500]}\n"
        )

    def _parse(self, raw: str) -> dict | None:
        try:
            return json.loads(raw)
        except Exception:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start:end + 1])
                except Exception:
                    return None
            return None

    def _apply_verdict(self, item, spider, *, verdict, score, reason=None, flags=None):
        item["score"] = score
        if flags:
            item["flags"] = flags
        if verdict == "accept" or (
            verdict == "uncertain" and score >= self._cfg.accept_threshold
        ):
            return item
        item["status"] = "rejected"
        item["rejection_stage"] = "llm_relevance"
        item["rejection_reason"] = reason or f"score {score}/10 verdict={verdict}"
        if self._tier_stats is not None:
            tier = spider_tier(spider.name)
            field = "llm_uncertain_low" if verdict == "uncertain" else "llm_rejects"
            self._tier_stats.bump(spider.name, tier, field)
        return item

    def _rules_only(self, item, spider) -> dict:
        title_keywords = [
            "security", "platform", "infrastructure", "devops",
            "sre", "cloud", "backend", "ai", "ml", "site reliability",
        ]
        title_lower = (item.get("title") or "").lower()
        match = any(k in title_lower for k in title_keywords)
        flags = list(item.get("flags") or []) + ["gate_overflow"]
        item["flags"] = flags
        if not match:
            item["status"] = "rejected"
            item["rejection_stage"] = "llm_relevance"
            item["rejection_reason"] = "gate_overflow rules-only reject"
            if self._tier_stats is not None:
                self._tier_stats.bump(
                    spider.name, spider_tier(spider.name), "llm_overflow",
                )
        return item

    def _mark_overflow(self):
        if self.mode is GateOutcome.NORMAL:
            self.mode = GateOutcome.OVERFLOW

    def _record_mode_observed(self, spider):
        try:
            spider.crawler.settings.set(
                "LLM_GATE_MODE_OBSERVED", self.mode.value, priority="cmdline",
            )
        except Exception:
            pass

    def _record_gate_failure(self, spider, reason: str):
        try:
            spider.crawler.settings.set("LLM_GATE_MODE_OBSERVED", "failed", priority="cmdline")
            spider.crawler.settings.set("LLM_GATE_FAILURE", reason, priority="cmdline")
        except Exception:
            pass
