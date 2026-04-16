"""Pipeline: hard filters — domain blocklist, title blocklist, salary floor, content blocklist, geo."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from job_scraper.config import HardFilterConfig
from job_scraper.salary_policy import evaluate_salary_policy

logger = logging.getLogger(__name__)

# Non-US location signals (cities, countries, regions)
_NON_US_PATTERN = re.compile(
    r"\b("
    r"london|manchester|bristol|edinburgh|cambridge|oxford|"
    r"berlin|munich|hamburg|frankfurt|"
    r"paris|lyon|toulouse|"
    r"amsterdam|rotterdam|"
    r"dublin|cork|"
    r"barcelona|madrid|"
    r"stockholm|copenhagen|oslo|helsinki|"
    r"zurich|geneva|bern|"
    r"vienna|prague|warsaw|bucharest|athens|lisbon|"
    r"tel aviv|jerusalem|"
    r"singapore|tokyo|osaka|seoul|bangalore|bengaluru|hyderabad|mumbai|pune|"
    r"sydney|melbourne|brisbane|auckland|"
    r"united kingdom|great britain|"
    r"germany|france|netherlands|ireland|spain|italy|sweden|"
    r"denmark|norway|finland|switzerland|austria|poland|czech|romania|greece|portugal|"
    r"ukraine|latvia|lithuania|estonia|croatia|serbia|bulgaria|"
    r"israel|japan|south korea|india|australia|new zealand|"
    r"europe|eu only|emea only|apac only|uk only"
    r")\b", re.I
)

# US location signals — only match against location field, not JD text,
# to avoid false positives from 2-letter state codes in prose.
_US_LOCATION_PATTERN = re.compile(
    r"\b("
    r"usa|united states|u\.s\.a?|"
    r"(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IA|KS|KY|LA|ME|MD|"
    r"MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|"
    r"TN|TX|UT|VT|VA|WA|WV|WI|WY)"
    r")\b|"
    r"\b("
    r"new york|nyc|san francisco|los angeles|seattle|austin|denver|"
    r"chicago|boston|portland|atlanta|dallas|houston|miami|"
    r"washington,?\s*d\.?c\.?|raleigh|phoenix|minneapolis|"
    r"salt lake|san diego|san jose|remote.{0,10}us\b|us.only|usa.only"
    r")\b", re.I
)


def _is_non_us_only(location: str, jd_text: str) -> str | None:
    """Return rejection reason if job is clearly non-US, or None if OK."""
    normalized_location = location.strip()
    if normalized_location:
        # Explicit "international/worldwide/global" location labels are not US-only.
        if re.search(r"\b(international|worldwide)\b", normalized_location, re.I):
            if not _US_LOCATION_PATTERN.search(normalized_location):
                return f"Non-US location: {normalized_location}"
        if re.search(r"\bglobal\b", normalized_location, re.I) and re.search(r"\bremote\b", normalized_location, re.I):
            if not _US_LOCATION_PATTERN.search(normalized_location):
                return f"Non-US location: {normalized_location}"

    # Primary: check location field for non-US signals
    loc_matches = _NON_US_PATTERN.findall(location)
    if loc_matches:
        # Check for US signals in location field
        if _US_LOCATION_PATTERN.search(location):
            return None
        # Bare "remote" without a region qualifier implies US eligibility
        if re.search(r"\bremote\b", location, re.I) and not re.search(
            r"\b(europe|emea|eu\b|apac|uk\b|only)", location, re.I
        ):
            return None
        return f"Non-US location: {', '.join(set(loc_matches[:3]))}"

    # Secondary: if no location field, scan the full JD for strong
    # location-constraint phrases. Offshore restrictions often appear deep in
    # the posting body, so a head-only scan is too weak.
    if not location.strip() and jd_text:
        for located_match in re.finditer(
            r"(?:located?\s+in|based\s+in|position\s+(?:is\s+)?in|office\s+in|"
            r"role\s+is\s+in|work\s+from\s+our|remote\s*[-:]\s*|within\s+the)\s+(.{0,120})",
            jd_text,
            re.I,
        ):
            context = located_match.group(1)
            if _NON_US_PATTERN.search(context) and not _US_LOCATION_PATTERN.search(context):
                non_us = _NON_US_PATTERN.findall(context)
                return f"Non-US location (JD): {', '.join(set(non_us[:3]))}"

    return None
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

        salary_verdict = evaluate_salary_policy(
            min_salary_k=self._config.min_salary_k,
            target_salary_k=self._config.target_salary_k,
            salary_text=item.get("salary_text") or "",
            salary_k=item.get("salary_k"),
        )
        if salary_verdict.hard_reject:
            return self._reject(item, "salary_floor", salary_verdict.reason or "Salary below floor")

        location = item.get("location") or ""
        geo_reason = _is_non_us_only(location, jd_text)
        if geo_reason:
            return self._reject(item, "geo_non_us", geo_reason)

        return item
