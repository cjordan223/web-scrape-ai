"""Pipeline: hard filters — domain blocklist, title blocklist, salary floor, content blocklist."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from job_scraper.config import HardFilterConfig

logger = logging.getLogger(__name__)

_SALARY_PATTERN = re.compile(r"\$\s*([\d,]+)")


def _parse_salary_k(text: str) -> int | None:
    matches = _SALARY_PATTERN.findall(text)
    if not matches:
        return None
    values = []
    for m in matches:
        try:
            val = int(m.replace(",", ""))
            if 20_000 <= val <= 500_000:
                values.append(val // 1000)
        except ValueError:
            continue
    return min(values) if values else None


class HardFilterPipeline:
    def __init__(self, config: HardFilterConfig | None = None):
        self._config = config or HardFilterConfig()
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
        cfg = load_config()
        return cls(config=cfg.hard_filters)

    def _reject(self, item, stage: str, reason: str):
        item["status"] = "rejected"
        item["rejection_stage"] = stage
        item["rejection_reason"] = reason
        return item

    def process_item(self, item, spider):
        url = item["url"]
        title = item.get("title", "")

        host = urlparse(url).netloc.lower()
        for domain in self._config.domain_blocklist:
            if domain in host:
                return self._reject(item, "domain_blocklist", f"Blocked domain: {domain}")

        for pattern in self._title_patterns:
            if pattern.search(title):
                return self._reject(item, "title_blocklist", f"Blocked title word: {pattern.pattern}")

        jd_text = item.get("jd_text") or ""
        for pattern in self._content_patterns:
            if pattern.search(jd_text):
                return self._reject(item, "content_blocklist", f"Blocked content: {pattern.pattern}")

        salary_text = item.get("salary_text") or ""
        if salary_text:
            salary_k = _parse_salary_k(salary_text)
            if salary_k is not None and salary_k < self._config.min_salary_k:
                return self._reject(item, "salary_floor", f"Salary ${salary_k}k below ${self._config.min_salary_k}k floor")

        return item
