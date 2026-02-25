"""Filtering pipeline with policy gates for role fit, JD quality, remote-only, and salary."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .config import FilterConfig
from .models import FilterVerdict, JobBoard, Seniority

# Seniority detection patterns (order matters — first match wins)
_SENIORITY_PATTERNS: list[tuple[re.Pattern, Seniority]] = [
    (re.compile(r"\b(?:junior|jr\.?|entry[\s-]?level|associate)\b", re.I), Seniority.junior),
    (re.compile(r"\b(?:staff)\b", re.I), Seniority.staff),
    (re.compile(r"\b(?:principal)\b", re.I), Seniority.principal),
    (re.compile(r"\b(?:director)\b", re.I), Seniority.director),
    (re.compile(r"\b(?:manager|management)\b", re.I), Seniority.manager),
    (re.compile(r"\b(?:lead|team\s+lead)\b", re.I), Seniority.lead),
    (re.compile(r"\b(?:senior|sr\.?)\b", re.I), Seniority.senior),
]

_REMOTE_PATTERN = re.compile(r"\b(?:remote|work[\s-]?from[\s-]?home|distributed|anywhere)\b", re.I)
_ONSITE_PATTERN = re.compile(r"\b(?:on[\s-]?site|onsite|in[\s-]?office|office[-\s]?based)\b", re.I)
_HYBRID_PATTERN = re.compile(r"\bhybrid\b", re.I)
_EARLY_CAREER_PATTERN = re.compile(
    r"\b(?:intern|internship|new[\s-]?grad(?:uate)?|co[\s-]?op|apprentice|fellowship)\b", re.I
)
_NON_REMOTE_PATTERN = re.compile(r"\b(?:not\s+remote|non[\s-]?remote|must\s+be\s+on[\s-]?site)\b", re.I)
_US_LOCATION_PATTERN = re.compile(
    r"\b(?:united states|u\.s\.a?\.?|us-based|u\.s\.-based|remote us|usa|within the us|continental us|"
    r"north america|us[\s-]?eligible|us[\s-]?remote|remote[\s,\-]+us|remote[\s,\-]+united states)\b",
    re.I,
)
_US_STATE_PATTERN = re.compile(
    r"\b(?:alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|"
    r"hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|"
    r"michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|"
    r"new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|"
    r"south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|"
    r"wisconsin|wyoming|district of columbia)\b|,\s*(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|"
    r"KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|"
    r"WI|WY|DC)\b",
    re.I,
)
_NON_US_LOCATION_PATTERN = re.compile(
    r"\b(?:germany|berlin|munich|budapest|hungary|slovakia|czech(?:ia)?|united kingdom|uk\b|london|"
    r"europe|european union|eu\b|emea|apac|asia|india|canada|latam|australia|singapore|japan|france|"
    r"spain|italy|netherlands|poland|ireland|israel)\b",
    re.I,
)
_LINKEDIN_SHELL_PATTERN = re.compile(
    r"(skip to main content linkedin|agree & join linkedin|sign in to view|"
    r"this button displays the currently selected search type)",
    re.I,
)
_SECURITY_TITLE_PATTERN = re.compile(
    r"\b(?:security|cyber|infosec|appsec|devsecops|soc|secops|threat|vulnerability)\b", re.I
)
_REQUIRE_JD_HOSTS = (
    "simplyhired.com",
    "linkedin.com",
    "indeed.com",
    "ziprecruiter.com",
    "glassdoor.com",
)
_LISTING_TITLE_PATTERN = re.compile(
    r"\b(?:jobs?,\s*employment|jobs?\s+in\s+|work\s+from\s+home.+jobs|search results?|open positions?|careers?)\b",
    re.I,
)
_APPLY_SHELL_TITLE_PATTERN = re.compile(r"^(?:apply(?:\s+now)?|job application|submit\s+application)$", re.I)
_CLOSED_POSTING_PATTERN = re.compile(
    r"\b(?:job(?:\s+posting)?\s+(?:is\s+)?(?:no longer available|closed|expired)|"
    r"position\s+(?:has been filled|is no longer available|closed)|"
    r"no longer accepting applications|posting is no longer active|404|page not found)\b",
    re.I,
)

# Matches patterns like "3+ years", "3-5 years", "3 years"
_EXPERIENCE_PATTERN = re.compile(r"(\d{1,2})\s*[\-\+]?\s*(?:\d{1,2}\s*)?years?\b", re.I)

# Matches salary figures like $120,000 / $120k and plain 120k.
_DOLLAR_SALARY_PATTERN = re.compile(r"\$\s*(\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?\s*([kK])?")
_K_SALARY_PATTERN = re.compile(r"\b(\d{2,3})\s*([kK])\b")
_COMPENSATION_CONTEXT_PATTERN = re.compile(
    r"\b(?:salary|compensation|base\s+pay|base\s+salary|pay\s+range|salary\s+range|"
    r"total\s+comp(?:ensation)?|annual(?:ly)?|per\s+year|yearly|ote|on-target)\b",
    re.I,
)


def detect_seniority(title: str) -> Seniority:
    """Detect seniority level from a job title."""
    for pattern, level in _SENIORITY_PATTERNS:
        if pattern.search(title):
            return level
    return Seniority.unknown


def parse_salary_max(text: str) -> int | None:
    """Parse the maximum salary figure from text. Returns dollars (e.g. 130000) or None."""
    candidates = []
    for m in _DOLLAR_SALARY_PATTERN.finditer(text):
        raw = m.group(1).replace(",", "")
        has_k = bool(m.group(2))
        start = m.start()
        end = m.end()
        try:
            value = int(raw) * (1000 if has_k else 1)
        except ValueError:
            continue
        window = text[max(0, start - 80): min(len(text), end + 80)]
        if not _COMPENSATION_CONTEXT_PATTERN.search(window):
            continue
        # Filter to plausible annual salary range ($30K–$450K)
        if 30_000 <= value <= 450_000:
            candidates.append(value)

    for m in _K_SALARY_PATTERN.finditer(text):
        raw = m.group(1)
        token = m.group(0).lower().replace(" ", "")
        if token == "401k":
            continue
        start = m.start()
        end = m.end()
        window = text[max(0, start - 80): min(len(text), end + 80)]
        if not _COMPENSATION_CONTEXT_PATTERN.search(window):
            continue
        try:
            value = int(raw) * 1000
        except ValueError:
            continue
        if 30_000 <= value <= 450_000:
            candidates.append(value)
    return max(candidates) if candidates else None


def parse_experience_years(text: str) -> int | None:
    """Parse the minimum years of experience from JD text.

    E.g. "3-5 years of experience" → 3, "5+ years" → 5.
    Returns the maximum of all minimums found, or None.
    """
    matches = _EXPERIENCE_PATTERN.findall(text)
    if not matches:
        return None
    return max(int(m) for m in matches)


def _clean_title(raw: str) -> str:
    """Normalize concatenated Ashby titles like 'SecurityEngineering' → 'Security Engineering'."""
    cleaned = re.sub(r'([a-z])([A-Z])', r'\1 \2', raw)
    cleaned = cleaned.split('•')[0].strip()
    return cleaned


def _build_keyword_patterns(keywords: list[str]) -> list[tuple[str, re.Pattern]]:
    """Build word-boundary regex patterns from keyword list."""
    patterns = []
    for kw in keywords:
        # Multi-word phrases use literal match with boundaries; single words use \b
        escaped = re.escape(kw)
        patterns.append((kw, re.compile(rf"\b{escaped}\b", re.I)))
    return patterns


def _check_title_relevance(title: str, keywords: list[str]) -> FilterVerdict:
    cleaned = _clean_title(title)
    patterns = _build_keyword_patterns(keywords)
    for kw, pattern in patterns:
        if pattern.search(cleaned):
            return FilterVerdict(stage="title_relevance", passed=True, reason=f"matched '{kw}'")
    return FilterVerdict(stage="title_relevance", passed=False, reason="no title keyword match")


def _check_url_domain(url: str, blocklist: list[str]) -> FilterVerdict:
    """Reject URLs from non-job domains."""
    url_lower = url.lower()
    for domain in blocklist:
        if domain.lower() in url_lower:
            return FilterVerdict(stage="url_domain", passed=False, reason=f"blocked domain: {domain}")
    return FilterVerdict(stage="url_domain", passed=True, reason="domain ok")


def _check_title_role(title: str, role_words: list[str]) -> FilterVerdict:
    """Require at least one job-role word in the title."""
    cleaned = _clean_title(title)
    patterns = _build_keyword_patterns(role_words)
    for word, pattern in patterns:
        if pattern.search(cleaned):
            return FilterVerdict(stage="title_role", passed=True, reason=f"role: '{word}'")
    return FilterVerdict(stage="title_role", passed=False, reason="no job role word in title")


def _check_seniority(title: str, exclude: list[str]) -> tuple[FilterVerdict, Seniority]:
    seniority = detect_seniority(title)
    # Keep hard blocks for clearly over-senior or management-style roles.
    if seniority in {
        Seniority.staff,
        Seniority.principal,
        Seniority.manager,
        Seniority.director,
    }:
        return FilterVerdict(stage="seniority", passed=False, reason=f"excluded: {seniority.value}"), seniority
    if seniority.value in exclude:
        return (
            FilterVerdict(stage="seniority", passed=True, reason=f"soft-excluded: {seniority.value}"),
            seniority,
        )
    return FilterVerdict(stage="seniority", passed=True, reason=f"level: {seniority.value}"), seniority


def _check_experience(jd_text: str | None, max_years: int) -> tuple[FilterVerdict, int | None]:
    if not jd_text:
        return FilterVerdict(stage="experience", passed=True, reason="no JD text"), None
    years = parse_experience_years(jd_text)
    if years is None:
        return FilterVerdict(stage="experience", passed=True, reason="no years found"), None
    if years > max_years:
        return (
            FilterVerdict(
                stage="experience",
                passed=True,
                reason=f"{years}yr > {max_years}yr max (soft signal)",
            ),
            years,
        )
    return FilterVerdict(stage="experience", passed=True, reason=f"{years}yr <= {max_years}yr max"), years


def _check_blocklist(title: str, snippet: str, jd_text: str | None, blocklist: list[str]) -> FilterVerdict:
    combined = f"{title} {snippet} {jd_text or ''}"
    combined_lower = combined.lower()
    for term in blocklist:
        if term.lower() in combined_lower:
            return FilterVerdict(stage="content_blocklist", passed=False, reason=f"blocked: '{term}'")
    return FilterVerdict(stage="content_blocklist", passed=True, reason="clean")


def _check_salary(jd_text: str | None, min_salary_k: int) -> tuple[FilterVerdict, int | None]:
    if not jd_text:
        return FilterVerdict(stage="salary", passed=True, reason="no JD text — pass by default"), None
    salary = parse_salary_max(jd_text)
    if salary is None:
        return FilterVerdict(stage="salary", passed=True, reason="no salary found — pass by default"), None
    threshold = min_salary_k * 1000
    if salary < threshold:
        return FilterVerdict(stage="salary", passed=False, reason=f"${salary:,} < ${min_salary_k}K"), salary
    return FilterVerdict(stage="salary", passed=True, reason=f"salary ${salary:,} meets ${min_salary_k}K threshold"), salary


def _check_board_quality(board: JobBoard, title: str, url: str, require_known_board: bool) -> FilterVerdict:
    """Reject unknown/listing-like sources that are usually not canonical postings."""
    if require_known_board and board == JobBoard.unknown:
        return FilterVerdict(stage="source_quality", passed=False, reason="unknown board")
    path = urlparse(url).path.lower()
    if path.endswith("/apply"):
        return FilterVerdict(stage="source_quality", passed=False, reason="apply endpoint")
    cleaned_title = _clean_title(title)
    if cleaned_title.startswith("http://") or cleaned_title.startswith("https://"):
        return FilterVerdict(stage="source_quality", passed=False, reason="url-like title")
    if _APPLY_SHELL_TITLE_PATTERN.match(cleaned_title):
        return FilterVerdict(stage="source_quality", passed=False, reason="apply-shell title")
    if _LISTING_TITLE_PATTERN.search(cleaned_title):
        return FilterVerdict(stage="source_quality", passed=False, reason="listing/search page")
    return FilterVerdict(stage="source_quality", passed=True, reason="source ok")


def _check_jd_presence(jd_text: str | None, min_chars: int) -> FilterVerdict:
    if not jd_text:
        return FilterVerdict(stage="jd_presence", passed=False, reason="missing JD text")
    if len(jd_text.strip()) < min_chars:
        return FilterVerdict(stage="jd_presence", passed=False, reason=f"JD too short (<{min_chars} chars)")
    return FilterVerdict(stage="jd_presence", passed=True, reason="JD present")


def _check_location_scope(
    title: str, snippet: str, jd_text: str | None, url: str, require_us_location: bool
) -> FilterVerdict:
    # Limit to location-bearing sections to avoid false positives from long corp overviews.
    combined = f"{title} {snippet} {(jd_text or '')[:1500]} {url}"
    lower = combined.lower()
    has_us = bool(_US_LOCATION_PATTERN.search(combined) or _US_STATE_PATTERN.search(combined))
    has_non_us = bool(_NON_US_LOCATION_PATTERN.search(combined))

    if "addresscountry" in lower and "united states" not in lower and not has_us:
        return FilterVerdict(stage="location", passed=False, reason="non-US country metadata")
    if has_non_us and has_us:
        # Global companies mention multiple offices — US signal is sufficient
        return FilterVerdict(stage="location", passed=True, reason="US signal present (non-US also mentioned)")
    if has_non_us and not has_us:
        return FilterVerdict(stage="location", passed=False, reason="non-US location signal found")
    if ("€" in combined or "£" in combined) and not has_us:
        return FilterVerdict(stage="location", passed=False, reason="non-US currency/location signal")
    if require_us_location and not has_us:
        # If the job just says "Remote" with no country qualifier, let it through
        has_remote = bool(_REMOTE_PATTERN.search(combined))
        if has_remote:
            return FilterVerdict(stage="location", passed=True, reason="remote with no non-US signal")
        return FilterVerdict(stage="location", passed=False, reason="missing US location signal")
    return FilterVerdict(stage="location", passed=True, reason="location scope ok")


def _check_jd_quality(url: str, jd_text: str | None) -> FilterVerdict:
    """Reject known shell/login pages that do not contain real JD content."""
    host = urlparse(url).netloc.lower()
    if not jd_text:
        if any(domain in host for domain in _REQUIRE_JD_HOSTS):
            return FilterVerdict(
                stage="jd_quality",
                passed=False,
                reason=f"missing JD text on aggregator domain: {host or 'unknown'}",
            )
        return FilterVerdict(stage="jd_quality", passed=True, reason="no JD text")
    if "linkedin.com/jobs/view/" in url.lower() and _LINKEDIN_SHELL_PATTERN.search(jd_text):
        return FilterVerdict(stage="jd_quality", passed=False, reason="shell-like jd text")
    if _CLOSED_POSTING_PATTERN.search(jd_text):
        return FilterVerdict(stage="jd_quality", passed=False, reason="closed/expired posting")
    return FilterVerdict(stage="jd_quality", passed=True, reason="jd quality ok")


def _check_early_career(title: str, snippet: str, jd_text: str | None) -> FilterVerdict:
    """Reject internship/new-grad/apprentice postings."""
    combined = f"{title} {snippet} {jd_text or ''}"
    m = _EARLY_CAREER_PATTERN.search(combined)
    if m:
        return FilterVerdict(stage="early_career", passed=False, reason=f"excluded early-career term: '{m.group(0)}'")
    return FilterVerdict(stage="early_career", passed=True, reason="not internship/new-grad")


def _check_remote(title: str, snippet: str, jd_text: str | None, require_explicit_remote: bool) -> FilterVerdict:
    # Title/snippet are the strongest signal for remote status.
    # JD body often mentions "on-site" in company descriptions even for remote roles.
    title_snippet = f"{title} {snippet}"
    title_remote = bool(_REMOTE_PATTERN.search(title_snippet))
    title_onsite = bool(_ONSITE_PATTERN.search(title_snippet))

    # If title explicitly says remote, trust it regardless of JD body content
    if title_remote and not title_onsite:
        return FilterVerdict(stage="remote", passed=True, reason="remote in title/snippet")

    combined = f"{title} {snippet} {jd_text or ''}"
    has_remote = bool(_REMOTE_PATTERN.search(combined))
    has_onsite = bool(_ONSITE_PATTERN.search(combined))
    has_hybrid = bool(_HYBRID_PATTERN.search(combined))
    has_non_remote = bool(_NON_REMOTE_PATTERN.search(combined))

    if title_onsite:
        return FilterVerdict(stage="remote", passed=False, reason="onsite in title")
    if has_non_remote:
        return FilterVerdict(stage="remote", passed=False, reason="explicit non-remote signal found")
    if has_remote and not has_onsite:
        return FilterVerdict(stage="remote", passed=True, reason="remote keyword found")
    if has_remote and has_onsite:
        # Mixed signals in JD body only — pass with note (title didn't say onsite)
        return FilterVerdict(stage="remote", passed=True, reason="remote found (onsite in JD body only)")
    if has_onsite and not has_remote:
        return FilterVerdict(stage="remote", passed=False, reason="onsite signal found")
    if has_hybrid:
        return FilterVerdict(stage="remote", passed=True, reason="hybrid (may allow remote)")
    if require_explicit_remote:
        return FilterVerdict(stage="remote", passed=False, reason="missing explicit remote signal")
    return FilterVerdict(stage="remote", passed=True, reason="no explicit onsite signal")


def _score_job(
    title: str,
    snippet: str,
    jd_text: str | None,
    seniority: Seniority,
    years: int | None,
    title_relevance_ok: bool,
    title_role_ok: bool,
    config: FilterConfig,
) -> tuple[int, str, list[str]]:
    combined = f"{title} {snippet} {jd_text or ''}"
    score = 0
    signals: list[str] = []

    if _REMOTE_PATTERN.search(combined):
        score += 2
        signals.append("remote:+2")

    if _ONSITE_PATTERN.search(combined) or _NON_REMOTE_PATTERN.search(combined):
        score -= 3
        signals.append("onsite:-3")

    if _HYBRID_PATTERN.search(combined) and not _REMOTE_PATTERN.search(combined):
        score -= 1
        signals.append("hybrid_only:-1")

    if _EARLY_CAREER_PATTERN.search(combined):
        score -= 4
        signals.append("intern:-4")

    if seniority.value in config.seniority_exclude:
        score -= 2
        signals.append(f"seniority_mismatch({seniority.value}):-2")

    if years is not None and years > config.max_experience_years:
        over = years - config.max_experience_years
        penalty = 2 if over <= 2 else 3
        score -= penalty
        signals.append(f"experience_over({years}>{config.max_experience_years}):-{penalty}")

    if not title_relevance_ok:
        score -= 2
        signals.append("title_relevance_miss:-2")

    if not title_role_ok:
        score -= 1
        signals.append("title_role_miss:-1")

    if _SECURITY_TITLE_PATTERN.search(title):
        score += 2
        signals.append("security_title:+2")

    if jd_text and not _LINKEDIN_SHELL_PATTERN.search(jd_text):
        score += 1
        signals.append("jd_quality:+1")

    # Safety rail: never auto-accept when title has no obvious job-role word.
    # This keeps "security news/article" pages out while still allowing review.
    if not title_role_ok and score >= config.score_accept_threshold:
        signals.append("accept_downgrade:no_role_word")
        return score, "review", signals

    if score >= config.score_accept_threshold:
        return score, "accept", signals
    if score <= config.score_reject_threshold:
        return score, "reject", signals
    return score, "review", signals


def apply_filters(
    title: str,
    url: str,
    snippet: str,
    jd_text: str | None,
    board: JobBoard,
    config: FilterConfig,
) -> tuple[bool, list[FilterVerdict], Seniority, int | None, int | None, int, str, list[str]]:
    """Run all filter stages.

    Returns:
        (passed, verdicts, seniority, experience_years, salary_dollars, score, decision, signals)
    """
    verdicts: list[FilterVerdict] = []

    # 1. URL domain blocklist
    v = _check_url_domain(url, config.url_domain_blocklist)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, Seniority.unknown, None, None, -999, "reject", []

    # 1b. Board/source quality
    v = _check_board_quality(board, title, url, config.require_known_board)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, Seniority.unknown, None, None, -999, "reject", []

    # 2. Title relevance (soft signal)
    v = _check_title_relevance(title, config.title_keywords)
    verdicts.append(v)
    title_relevance_ok = v.passed

    # 3. Title role word (soft signal)
    v = _check_title_role(title, config.title_role_words)
    verdicts.append(v)
    title_role_ok = v.passed

    # 4. Seniority
    v, seniority = _check_seniority(title, config.seniority_exclude)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, seniority, None, None, -999, "reject", []
    # 5. Internship/new-grad exclusion (hard block)
    v = _check_early_career(title, snippet, jd_text)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, seniority, None, None, -999, "reject", []

    # 6. JD quality signal
    v = _check_jd_quality(url, jd_text)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, seniority, None, None, -999, "reject", []

    # 6b. JD presence (soft signal — don't hard-reject, let scoring decide)
    v = _check_jd_presence(jd_text, config.min_jd_chars)
    verdicts.append(v)

    # 7. Experience
    v, years = _check_experience(jd_text, config.max_experience_years)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, seniority, years, None, -999, "reject", []

    # 8. Content blocklist (checks title + snippet + JD)
    v = _check_blocklist(title, snippet, jd_text, config.content_blocklist)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, seniority, years, None, -999, "reject", []

    # 9. Remote (only if required)
    if config.require_remote:
        v = _check_remote(title, snippet, jd_text, config.require_explicit_remote)
        verdicts.append(v)
        if not v.passed:
            return False, verdicts, seniority, years, None, -999, "reject", []

    # 9b. US location guardrail
    v = _check_location_scope(title, snippet, jd_text, url, config.require_us_location)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, seniority, years, None, -999, "reject", []

    # 10. Salary minimum
    salary = None
    if config.min_salary_k > 0:
        v, salary = _check_salary(jd_text, config.min_salary_k)
        verdicts.append(v)
        if not v.passed:
            return False, verdicts, seniority, years, salary, -999, "reject", []
    score, decision, signals = _score_job(
        title, snippet, jd_text, seniority, years, title_relevance_ok, title_role_ok, config
    )
    scoring_pass = decision == "accept"
    verdicts.append(
        FilterVerdict(
            stage="scoring",
            passed=scoring_pass,
            reason=f"decision={decision} score={score} signals={', '.join(signals)}",
        )
    )
    return scoring_pass, verdicts, seniority, years, salary, score, decision, signals
