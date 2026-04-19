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
