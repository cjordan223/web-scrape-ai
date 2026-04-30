"""Pipeline: hard filters — domain blocklist, title blocklist, salary floor, content blocklist, geo, remote, experience, company sanity."""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

from job_scraper.config import HardFilterConfig
from job_scraper.salary_policy import evaluate_salary_policy
from job_scraper.spiders import AGGREGATOR_PATH_SEGMENTS

logger = logging.getLogger(__name__)

# Non-US location signals (cities, countries, regions). Comprehensive country
# coverage — if a location explicitly names any non-US country, reject.
_NON_US_PATTERN = re.compile(
    r"\b("
    # Cities commonly appearing without country suffix
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
    r"toronto|vancouver|montreal|ottawa|calgary|"
    r"dubai|abu dhabi|riyadh|doha|kuwait city|manama|muscat|"
    r"mexico city|sao paulo|rio de janeiro|buenos aires|lima|bogota|santiago|caracas|"
    r"cairo|lagos|nairobi|johannesburg|cape town|accra|"
    r"kyiv|kiev|lviv|moscow|st petersburg|minsk|"
    r"istanbul|ankara|"
    r"bangkok|jakarta|manila|kuala lumpur|ho chi minh|hanoi|"
    r"karachi|lahore|dhaka|colombo|"
    r"shanghai|beijing|shenzhen|guangzhou|hong kong|taipei|"
    # Countries / regions
    r"united kingdom|great britain|"
    r"germany|france|netherlands|ireland|spain|italy|sweden|"
    r"denmark|norway|finland|switzerland|austria|poland|czech|romania|greece|portugal|"
    r"ukraine|latvia|lithuania|estonia|croatia|serbia|bulgaria|slovakia|slovenia|hungary|"
    r"belarus|moldova|albania|north macedonia|bosnia|montenegro|kosovo|"
    r"israel|japan|south korea|india|australia|new zealand|"
    # LATAM
    r"argentina|brazil|peru|chile|colombia|mexico|uruguay|venezuela|ecuador|"
    r"bolivia|paraguay|guatemala|costa rica|panama|honduras|nicaragua|"
    r"el salvador|dominican republic|cuba|haiti|jamaica|"
    # Canada
    r"canada|"
    # Africa
    r"nigeria|kenya|egypt|south africa|morocco|tunisia|ghana|ethiopia|"
    r"tanzania|uganda|rwanda|algeria|senegal|cameroon|ivory coast|zimbabwe|"
    # Middle East
    r"saudi arabia|united arab emirates|uae|qatar|kuwait|bahrain|oman|"
    r"jordan|lebanon|iraq|iran|syria|yemen|"
    # Asia
    r"china|taiwan|thailand|vietnam|malaysia|indonesia|philippines|"
    r"pakistan|bangladesh|sri lanka|nepal|myanmar|cambodia|laos|"
    r"mongolia|kazakhstan|uzbekistan|azerbaijan|armenia|georgia|"
    # Europe catch-alls
    r"russia|turkey|turkiye|türkiye|cyprus|malta|iceland|luxembourg|liechtenstein|monaco|andorra|"
    # Oceania / other
    r"fiji|papua new guinea|"
    # Region labels
    r"europe|eu only|emea|emea only|apac|apac only|uk only|latam|lat[\-\s]?am|"
    r"ukraine only|india only|canada only"
    r")\b", re.I
)

# Canada-only tokens — used when allow_canada=true to exempt these from the
# non-US denylist (but still reject other countries).
_CANADA_PATTERN = re.compile(
    r"\b(canada|toronto|vancouver|montreal|ottawa|calgary)\b", re.I
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
    r")\b|"
    r"\bu\.s\.(?:a\.)?", re.I
)

_US_ELIGIBILITY_TEXT_PATTERN = re.compile(
    r"\b("
    r"usa|united states|u\.s\.a?|us[- ]?only|u\.s\.[- ]?only|"
    r"remote(?:\s+eligible)?\s*[-,]?\s*(?:us|usa|u\.s\.|united states)|"
    r"(?:us|usa|u\.s\.|united states)\s*[-,]?\s*remote|"
    r"authorized\s+to\s+work\s+in\s+the\s+(?:us|u\.s\.|united states)|"
    r"candidates?\s+(?:based|located)\s+in\s+the\s+(?:us|u\.s\.|united states)|"
    r"applicants?\s+(?:based|located)\s+in\s+the\s+(?:us|u\.s\.|united states)"
    r")\b|"
    r"\bu\.s\.(?:a\.)?",
    re.I,
)

# Remote / distributed / work-from-home markers.
_REMOTE_PATTERN = re.compile(
    r"\b(remote|work from home|work-from-home|wfh|distributed|"
    r"fully remote|100% remote|remote[- ]?first|anywhere)\b",
    re.I,
)

# Explicit in-office / hybrid markers that disqualify when require_remote is strict.
_ONSITE_PATTERN = re.compile(
    r"\b(onsite|on-site|on site|in[- ]?office|in[- ]?person|"
    r"hybrid|relocation required|must relocate)\b",
    re.I,
)

# German / EU statutory equality marker in titles — strong non-US signal.
_EU_EQUALITY_MARKER_PATTERN = re.compile(
    r"\(\s*[mwfd]\s*/\s*[mwfd]\s*/\s*[mwfd]\s*\)", re.I,
)

_BAD_COMPANY_TOKENS = AGGREGATOR_PATH_SEGMENTS | {"unknown", ""}

# Experience-years regex: captures "7+ years", "8-10 years", "minimum of 10 years", etc.
_EXPERIENCE_PATTERNS = [
    re.compile(r"\b(\d{1,2})\s*\+\s*years?\b", re.I),
    re.compile(r"\bminimum\s+of\s+(\d{1,2})\s+years?\b", re.I),
    re.compile(r"\bat\s+least\s+(\d{1,2})\s+years?\b", re.I),
    re.compile(r"\b(\d{1,2})\s*-\s*\d{1,2}\s+years?\b", re.I),
    re.compile(r"\b(\d{1,2})\s+or\s+more\s+years?\b", re.I),
]


def _extract_experience_years(jd_text: str) -> int | None:
    """Pull the highest experience-year requirement mentioned in the JD body."""
    if not jd_text:
        return None
    candidates: list[int] = []
    for pattern in _EXPERIENCE_PATTERNS:
        for match in pattern.finditer(jd_text):
            try:
                value = int(match.group(1))
            except (ValueError, IndexError):
                continue
            if 0 < value <= 30:
                candidates.append(value)
    if not candidates:
        return None
    # Use the maximum — a posting saying "5-10 years" should count as 10.
    return max(candidates)


def _check_title_geo(title: str, allow_canada: bool = False) -> str | None:
    """Reject titles that explicitly name a non-US city/country or carry an EU
    equality marker like '(m/f/d)'. Returns rejection reason or None."""
    if not title:
        return None
    if _EU_EQUALITY_MARKER_PATTERN.search(title):
        return "EU equality marker in title (m/f/d-style)"
    matches = _NON_US_PATTERN.findall(title)
    if not matches:
        return None
    if _US_LOCATION_PATTERN.search(title):
        return None
    if allow_canada:
        non_canada = [m for m in matches if not _CANADA_PATTERN.search(m)]
        if not non_canada:
            return None
    return f"Non-US token in title: {', '.join(set(matches[:3]))}"


def _is_non_us_only(location: str, jd_text: str, require_us: bool = True, allow_canada: bool = False) -> str | None:
    """Return rejection reason if job is clearly non-US, or None if OK.

    Empty location with require_us=True fails closed when JD has no US signal —
    missing data should not silently pass a hard requirement.
    """
    normalized_location = location.strip()
    jd_has_us_eligibility = bool(jd_text and _US_ELIGIBILITY_TEXT_PATTERN.search(jd_text[:4000]))
    if normalized_location:
        if re.search(r"\b(international|worldwide)\b", normalized_location, re.I):
            if not _US_LOCATION_PATTERN.search(normalized_location):
                return f"Non-US location: {normalized_location}"
        if re.search(r"\bglobal\b", normalized_location, re.I) and re.search(r"\bremote\b", normalized_location, re.I):
            if not _US_LOCATION_PATTERN.search(normalized_location):
                return f"Non-US location: {normalized_location}"

    loc_matches = _NON_US_PATTERN.findall(location)
    if loc_matches:
        if _US_LOCATION_PATTERN.search(location):
            # Has US signal — location pairs US with another region (e.g. "US | Canada"). Accept.
            return None
        # allow_canada=true and every matched token is Canadian → accept.
        if allow_canada:
            non_canada_matches = [m for m in loc_matches if not _CANADA_PATTERN.search(m)]
            if not non_canada_matches:
                return None
        return f"Non-US location: {', '.join(set(loc_matches[:3]))}"

    if require_us and normalized_location:
        if _US_LOCATION_PATTERN.search(normalized_location):
            return None
        if jd_has_us_eligibility:
            return None
        if _REMOTE_PATTERN.search(normalized_location):
            return f"Remote location lacks explicit US eligibility: {normalized_location}"
        return f"Non-US location (no US signal): {normalized_location}"

    if not location.strip():
        if jd_text:
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
        if require_us:
            if not jd_has_us_eligibility:
                return "Empty location and no US signal (enrichment missing)"

    return None


def _check_remote(location: str, jd_text: str, require_explicit: bool) -> str | None:
    """Return rejection reason if the posting is clearly non-remote, or None if OK."""
    loc = location or ""
    jd = jd_text or ""

    if _REMOTE_PATTERN.search(loc):
        # Explicit remote in the location field — accept even if JD mentions hybrid elsewhere.
        return None

    if _ONSITE_PATTERN.search(loc):
        match = _ONSITE_PATTERN.search(loc)
        return f"Non-remote location: {match.group(0)}"

    jd_has_remote = bool(_REMOTE_PATTERN.search(jd))
    jd_has_onsite_strict = bool(re.search(r"\b(in[- ]?office [1-5] days?|must be on[- ]?site|no remote|onsite only|on-site only|in-office only)\b", jd, re.I))

    if jd_has_onsite_strict:
        return "Non-remote (JD asserts in-office / onsite)"

    if require_explicit:
        if not jd_has_remote and not _REMOTE_PATTERN.search(loc):
            return "Remote not explicitly stated"

    if loc and not _REMOTE_PATTERN.search(loc) and not jd_has_remote:
        # Location set to a specific city with no remote mention anywhere.
        return f"No remote signal (location: {loc[:80]})"

    if not loc and not jd_has_remote:
        # Empty location and no remote signal in JD — fail closed instead of
        # silently passing on missing data.
        return "No remote signal (location empty, JD silent)"

    return None


class HardFilterPipeline:
    def __init__(self, config: HardFilterConfig | None = None, tier_stats=None):
        self._config = config or HardFilterConfig()
        self._tier_stats = tier_stats
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
        from job_scraper.pipelines.dedup import _get_shared_stats
        cfg = load_config()
        return cls(config=cfg.hard_filters, tier_stats=_get_shared_stats(crawler))

    def _persist_verdicts(self, item, verdicts: list[dict]) -> None:
        existing = item.get("filter_verdicts")
        if isinstance(existing, str) and existing:
            try:
                prior = json.loads(existing)
                if isinstance(prior, list):
                    verdicts = prior + verdicts
            except (ValueError, TypeError):
                pass
        item["filter_verdicts"] = json.dumps(verdicts, ensure_ascii=False)

    def _reject(self, item, stage: str, reason: str, spider=None, verdicts: list[dict] | None = None):
        item["status"] = "rejected"
        item["rejection_stage"] = stage
        item["rejection_reason"] = reason
        if verdicts is not None:
            verdicts.append({"rule": stage, "pass": False, "reason": reason})
            self._persist_verdicts(item, verdicts)
        if self._tier_stats is not None and spider is not None:
            from job_scraper.tiers import spider_tier
            self._tier_stats.bump(spider.name, spider_tier(spider.name), "filter_drops")
        return item

    def process_item(self, item, spider):
        url = item["url"]
        title = item.get("title", "")
        verdicts: list[dict] = []

        parsed_url = urlparse(url)
        host = parsed_url.netloc.lower()
        path_segments = {seg.lower() for seg in parsed_url.path.split("/") if seg}
        for domain in self._config.domain_blocklist:
            domain_lc = domain.lower()
            if domain_lc in host:
                return self._reject(item, "domain_blocklist", f"Blocked domain: {domain}", spider=spider, verdicts=verdicts)
            # Also block aggregator hosting on legitimate ATS — e.g.
            # `jobs.lever.co/jobgether/...` should be caught by `jobgether.com`.
            blocked_token = domain_lc.split(".")[0]
            if blocked_token and blocked_token in path_segments:
                return self._reject(item, "domain_blocklist", f"Blocked aggregator in path: {domain}", spider=spider, verdicts=verdicts)
        verdicts.append({"rule": "domain_blocklist", "pass": True})

        # Company sanity — reject URL-path-leak company names.
        company_value = (item.get("company") or "").strip().lower()
        if company_value in _BAD_COMPANY_TOKENS:
            return self._reject(item, "company_sanity", f"Bad company value: {company_value or '(empty)'}", spider=spider, verdicts=verdicts)
        verdicts.append({"rule": "company_sanity", "pass": True})

        for pattern in self._title_patterns:
            if pattern.search(title):
                return self._reject(item, "title_blocklist", f"Blocked title word: {pattern.pattern}", spider=spider, verdicts=verdicts)
        verdicts.append({"rule": "title_blocklist", "pass": True})

        title_geo_reason = _check_title_geo(title, allow_canada=self._config.allow_canada)
        if title_geo_reason:
            return self._reject(item, "title_geo", title_geo_reason, spider=spider, verdicts=verdicts)
        verdicts.append({"rule": "title_geo", "pass": True})

        jd_text = item.get("jd_text") or ""
        for pattern in self._content_patterns:
            if pattern.search(jd_text):
                return self._reject(item, "content_blocklist", f"Blocked content: {pattern.pattern}", spider=spider, verdicts=verdicts)
        verdicts.append({"rule": "content_blocklist", "pass": True})

        salary_verdict = evaluate_salary_policy(
            min_salary_k=self._config.min_salary_k,
            target_salary_k=self._config.target_salary_k,
            salary_text=item.get("salary_text") or "",
            salary_k=item.get("salary_k"),
        )
        if salary_verdict.hard_reject:
            return self._reject(item, "salary_floor", salary_verdict.reason or "Salary below floor", spider=spider, verdicts=verdicts)
        verdicts.append({"rule": "salary_floor", "pass": True})

        location = item.get("location") or ""
        geo_reason = _is_non_us_only(
            location, f"{title}\n{jd_text}",
            require_us=self._config.require_us_location,
            allow_canada=self._config.allow_canada,
        )
        if geo_reason:
            return self._reject(item, "geo_non_us", geo_reason, spider=spider, verdicts=verdicts)
        verdicts.append({"rule": "geo_non_us", "pass": True})

        if self._config.require_remote:
            remote_reason = _check_remote(location, jd_text, self._config.require_explicit_remote)
            if remote_reason:
                return self._reject(item, "not_remote", remote_reason, spider=spider, verdicts=verdicts)
            verdicts.append({"rule": "not_remote", "pass": True})

        experience_years = item.get("experience_years")
        if experience_years is None:
            experience_years = _extract_experience_years(jd_text)
            if experience_years is not None:
                item["experience_years"] = experience_years
        if experience_years is not None and self._config.max_experience_years > 0:
            if experience_years > self._config.max_experience_years:
                return self._reject(
                    item, "experience_years",
                    f"Requires {experience_years}+ years (max {self._config.max_experience_years})",
                    spider=spider, verdicts=verdicts,
                )
        verdicts.append({"rule": "experience_years", "pass": True, "value": experience_years})

        self._persist_verdicts(item, verdicts)
        return item
