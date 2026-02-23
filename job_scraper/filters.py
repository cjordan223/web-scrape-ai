"""Filtering pipeline: url_domain → title_relevance → title_role → seniority → experience → blocklist → remote."""

from __future__ import annotations

import re

from .config import FilterConfig
from .models import FilterVerdict, Seniority

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

# Matches patterns like "3+ years", "3-5 years", "3 years"
_EXPERIENCE_PATTERN = re.compile(r"(\d{1,2})\s*[\-\+]?\s*(?:\d{1,2}\s*)?years?\b", re.I)

# Matches salary figures: $120k, $120K, $120,000 ($ required for bare numbers; k/K suffix alone is ok)
_SALARY_PATTERN = re.compile(
    r"\$\s*(?P<d_amt>\d{1,3}(?:,\d{3})*|\d+)\s*(?P<d_k>[kK])?"  # $120,000 or $120k
    r"|(?P<k_amt>\d{1,3}(?:,\d{3})*|\d+)\s*(?P<k_sfx>[kK])\b"    # 120k (k required without $)
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
    for m in _SALARY_PATTERN.finditer(text):
        if m.group("d_amt"):
            raw = m.group("d_amt").replace(",", "")
            has_k = bool(m.group("d_k"))
        else:
            raw = m.group("k_amt").replace(",", "")
            has_k = True
        try:
            value = int(raw) * (1000 if has_k else 1)
        except ValueError:
            continue
        # Filter to plausible annual salary range ($30K–$900K)
        if 30_000 <= value <= 900_000:
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


def _build_keyword_patterns(keywords: list[str]) -> list[tuple[str, re.Pattern]]:
    """Build word-boundary regex patterns from keyword list."""
    patterns = []
    for kw in keywords:
        # Multi-word phrases use literal match with boundaries; single words use \b
        escaped = re.escape(kw)
        patterns.append((kw, re.compile(rf"\b{escaped}\b", re.I)))
    return patterns


def _check_title_relevance(title: str, keywords: list[str]) -> FilterVerdict:
    patterns = _build_keyword_patterns(keywords)
    for kw, pattern in patterns:
        if pattern.search(title):
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
    patterns = _build_keyword_patterns(role_words)
    for word, pattern in patterns:
        if pattern.search(title):
            return FilterVerdict(stage="title_role", passed=True, reason=f"role: '{word}'")
    return FilterVerdict(stage="title_role", passed=False, reason="no job role word in title")


def _check_seniority(title: str, exclude: list[str]) -> tuple[FilterVerdict, Seniority]:
    seniority = detect_seniority(title)
    if seniority.value in exclude:
        return (
            FilterVerdict(stage="seniority", passed=False, reason=f"excluded: {seniority.value}"),
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
            FilterVerdict(stage="experience", passed=False, reason=f"{years}yr > {max_years}yr max"),
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
        return FilterVerdict(stage="salary", passed=False, reason="no JD text to parse salary from"), None
    salary = parse_salary_max(jd_text)
    if salary is None:
        return FilterVerdict(stage="salary", passed=False, reason="no salary found in JD"), None
    threshold = min_salary_k * 1000
    if salary < threshold:
        return (
            FilterVerdict(stage="salary", passed=False, reason=f"max salary ${salary:,} < ${min_salary_k}K threshold"),
            salary,
        )
    return FilterVerdict(stage="salary", passed=True, reason=f"salary ${salary:,} meets ${min_salary_k}K threshold"), salary


def _check_remote(title: str, snippet: str, jd_text: str | None) -> FilterVerdict:
    combined = f"{title} {snippet} {jd_text or ''}"
    if _REMOTE_PATTERN.search(combined):
        return FilterVerdict(stage="remote", passed=True, reason="remote keyword found")
    return FilterVerdict(stage="remote", passed=False, reason="no remote keyword")


def apply_filters(
    title: str,
    url: str,
    snippet: str,
    jd_text: str | None,
    config: FilterConfig,
) -> tuple[bool, list[FilterVerdict], Seniority, int | None, int | None]:
    """Run all filter stages. Returns (passed, verdicts, seniority, experience_years, salary_dollars)."""
    verdicts: list[FilterVerdict] = []

    # 1. URL domain blocklist
    v = _check_url_domain(url, config.url_domain_blocklist)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, Seniority.unknown, None, None

    # 2. Title relevance
    v = _check_title_relevance(title, config.title_keywords)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, Seniority.unknown, None, None

    # 3. Title role word
    v = _check_title_role(title, config.title_role_words)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, Seniority.unknown, None, None

    # 4. Seniority
    v, seniority = _check_seniority(title, config.seniority_exclude)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, seniority, None, None

    # 5. Experience
    v, years = _check_experience(jd_text, config.max_experience_years)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, seniority, years, None

    # 6. Content blocklist (checks title + snippet + JD)
    v = _check_blocklist(title, snippet, jd_text, config.content_blocklist)
    verdicts.append(v)
    if not v.passed:
        return False, verdicts, seniority, years, None

    # 7. Remote (only if required)
    if config.require_remote:
        v = _check_remote(title, snippet, jd_text)
        verdicts.append(v)
        if not v.passed:
            return False, verdicts, seniority, years, None

    # 8. Salary minimum
    salary = None
    if config.min_salary_k > 0:
        v, salary = _check_salary(jd_text, config.min_salary_k)
        verdicts.append(v)
        if not v.passed:
            return False, verdicts, seniority, years, salary

    return True, verdicts, seniority, years, salary
