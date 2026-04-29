"""Canonical job fingerprint helpers.

The scraper's first dedup layer is still URL TTL, but job postings often move
between URLs. These helpers produce stable enough identifiers for exact ATS
matches and conservative company/title/location duplicate detection.
"""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse


_TRACKING_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {
    "gh_src", "gh_jid", "lever-source", "source", "ref", "referrer",
    "trk", "tracking", "redirectedFrom", "iis", "iisn",
}
_LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
    "co", "company", "plc", "gmbh", "sarl", "sa",
}
_COMPANY_ALIASES = {
    "open ai": "openai",
    "1 password": "1password",
}
_TITLE_ABBREVIATIONS = {
    "sr": "senior",
    "sre": "site reliability engineer",
    "dev sec ops": "devsecops",
    "app sec": "application security",
}
_LOCATION_TAGS = re.compile(
    r"\b(remote|hybrid|onsite|on site|on-site|united states|usa|us|us only|u\.s\.|"
    r"canada|emea|apac|europe|uk|latam|global|worldwide)\b",
    re.I,
)
_REMOTE_RE = re.compile(r"\b(remote|work from home|wfh|distributed|anywhere)\b", re.I)
_HYBRID_RE = re.compile(r"\b(hybrid)\b", re.I)
_ONSITE_RE = re.compile(r"\b(onsite|on-site|on site|in-office|in office)\b", re.I)
_US_RE = re.compile(
    r"\b(usa|united states|u\.s\.|us only|remote\s*[-,]?\s*us|remote,?\s*usa)\b",
    re.I,
)
_NON_US_RE = re.compile(
    r"\b(canada|united kingdom|uk|europe|emea|apac|india|germany|france|"
    r"spain|netherlands|australia|singapore|latam|mexico|brazil)\b",
    re.I,
)
_ATS_URL_RE = re.compile(
    r"https?://[^\s\"'<>)]+(?:ashbyhq\.com|greenhouse\.io|lever\.co|workable\.com)[^\s\"'<>)]+",
    re.I,
)
_ATS_LINK_RE = re.compile(
    r"""(?:href|data-url|data-apply-url|applyUrl|absolute_url|hostedUrl)["'\s:=]+["']([^"']+)""",
    re.I,
)
_HIGH_CONFIDENCE_ATS_PROVIDERS = {"ashby", "greenhouse", "lever", "workable"}


@dataclass(frozen=True)
class FingerprintData:
    canonical_url: str
    ats_provider: str
    ats_job_id: str
    company_norm: str
    title_norm: str
    location_bucket: str
    remote_flag: str
    salary_bucket: str
    fingerprint: str
    content_hash: str

    def as_dict(self) -> dict[str, str]:
        return {
            "canonical_url": self.canonical_url,
            "ats_provider": self.ats_provider,
            "ats_job_id": self.ats_job_id,
            "company_norm": self.company_norm,
            "title_norm": self.title_norm,
            "location_bucket": self.location_bucket,
            "remote_flag": self.remote_flag,
            "salary_bucket": self.salary_bucket,
            "fingerprint": self.fingerprint,
            "content_hash": self.content_hash,
        }


def canonicalize_url(url: str) -> str:
    """Normalize a posting URL without making network calls."""
    if not url:
        return ""
    parsed = urlparse(url.strip())
    if parsed.netloc.endswith("google.com") and parsed.path.startswith("/url"):
        q = parse_qs(parsed.query).get("q") or parse_qs(parsed.query).get("url")
        if q:
            return canonicalize_url(unquote(q[0]))

    scheme = (parsed.scheme or "https").lower()
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/")
    kept = []
    for key, values in parse_qs(parsed.query, keep_blank_values=False).items():
        key_l = key.lower()
        if key_l in _TRACKING_PARAMS or any(key_l.startswith(p) for p in _TRACKING_PREFIXES):
            continue
        for value in values:
            kept.append((key, value))
    query = urlencode(sorted(kept), doseq=True)
    return urlunparse((scheme, host, path, "", query, ""))


def normalize_company(company: str) -> str:
    value = _words(company)
    parts = [p for p in value.split() if p not in _LEGAL_SUFFIXES]
    normalized = " ".join(parts)
    return _COMPANY_ALIASES.get(normalized, normalized).replace(" ", "-")


def normalize_title(title: str) -> str:
    value = _words(_LOCATION_TAGS.sub(" ", title or ""))
    for src, dest in _TITLE_ABBREVIATIONS.items():
        value = re.sub(rf"\b{re.escape(src)}\b", dest, value)
    value = re.sub(r"\b(senior|jr|junior)\s+\1\b", r"\1", value)
    return value.replace(" ", "-")


def location_bucket(location: str, jd_text: str = "") -> str:
    haystack = f"{location or ''} {jd_text or ''}"[:4000]
    loc = location or ""
    if _HYBRID_RE.search(haystack):
        return "hybrid"
    if _ONSITE_RE.search(haystack):
        return "onsite"
    if _REMOTE_RE.search(haystack):
        if _US_RE.search(haystack):
            return "us-remote"
        if _NON_US_RE.search(loc) and not _US_RE.search(loc):
            return "non-us"
        if re.search(r"\b(global|worldwide|anywhere)\b", haystack, re.I):
            return "global-remote"
        return "remote-unclear"
    if _NON_US_RE.search(haystack) and not _US_RE.search(haystack):
        return "non-us"
    return "unclear"


def remote_flag(location: str, jd_text: str = "") -> str:
    haystack = f"{location or ''} {jd_text or ''}"[:4000]
    if _REMOTE_RE.search(haystack):
        return "true"
    if _HYBRID_RE.search(haystack) or _ONSITE_RE.search(haystack):
        return "false"
    return "unclear"


def salary_bucket(salary_k: object = None, salary_text: str = "") -> str:
    value = _salary_value_k(salary_k, salary_text)
    if value is None:
        return "unknown"
    if value < 100:
        return "below-floor"
    if value < 120:
        return "100k-120k"
    if value < 160:
        return "120k-160k"
    if value < 200:
        return "160k-200k"
    return "200k+"


def content_hash(text: str) -> str:
    normalized = _words(text or "")
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_ats_identity(url: str, board: str = "", explicit_id: str = "") -> tuple[str, str]:
    raw_parsed = urlparse((url or "").strip())
    raw_query = parse_qs(raw_parsed.query)
    canonical = canonicalize_url(url)
    parsed = urlparse(canonical)
    host = parsed.netloc.lower()
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    provider = (board or "").lower().strip()
    if not provider:
        if "ashbyhq.com" in host:
            provider = "ashby"
        elif "greenhouse.io" in host:
            provider = "greenhouse"
        elif "lever.co" in host:
            provider = "lever"
        elif "workable.com" in host:
            provider = "workable"

    if explicit_id:
        return provider, str(explicit_id).strip()

    if provider == "greenhouse":
        for key in ("gh_jid", "gh_jid[]"):
            value = raw_query.get(key)
            if value and re.fullmatch(r"\d{5,}", value[0]):
                return provider, value[0]

    if provider == "greenhouse":
        for part in reversed(path_parts):
            if re.fullmatch(r"\d{5,}", part):
                return provider, part
    if provider == "lever" and path_parts:
        return provider, path_parts[-1]
    if provider == "ashby" and path_parts:
        return provider, path_parts[-1]
    if provider == "workable":
        for idx, part in enumerate(path_parts):
            if part.lower() == "j" and idx + 1 < len(path_parts):
                return provider, path_parts[idx + 1].lower()
        if path_parts:
            return provider, path_parts[-1].lower()
    return provider, ""


def extract_embedded_ats_identity(text: str) -> tuple[str, str, str]:
    """Find a high-confidence ATS URL and identity inside fetched page content."""
    candidates = _ats_url_candidates(text)
    for candidate in candidates:
        provider, job_id = extract_ats_identity(candidate)
        if provider in _HIGH_CONFIDENCE_ATS_PROVIDERS and job_id:
            return canonicalize_url(candidate), provider, job_id
    return "", "", ""


def build_fingerprint_data(item: dict) -> FingerprintData:
    canonical = canonicalize_url(str(item.get("canonical_url") or item.get("url") or ""))
    ats_provider, ats_job_id = extract_ats_identity(
        canonical,
        str(item.get("ats_provider") or item.get("board") or ""),
        str(item.get("ats_job_id") or ""),
    )
    html_text = str(item.get("jd_html") or "")
    jd = str(item.get("jd_text") or item.get("snippet") or "")
    if not ats_job_id:
        embedded_url, embedded_provider, embedded_job_id = extract_embedded_ats_identity(
            "\n".join([html_text, jd, str(item.get("snippet") or "")])
        )
        if embedded_job_id:
            canonical = embedded_url
            ats_provider = embedded_provider
            ats_job_id = embedded_job_id
    company = normalize_company(str(item.get("company") or ""))
    title = normalize_title(str(item.get("title") or ""))
    loc_bucket = location_bucket(str(item.get("location") or ""), jd)
    remote = remote_flag(str(item.get("location") or ""), jd)
    salary = salary_bucket(item.get("salary_k"), str(item.get("salary_text") or ""))
    fingerprint = "|".join([company, title, loc_bucket, remote, salary])
    return FingerprintData(
        canonical_url=canonical,
        ats_provider=ats_provider,
        ats_job_id=ats_job_id,
        company_norm=company,
        title_norm=title,
        location_bucket=loc_bucket,
        remote_flag=remote,
        salary_bucket=salary,
        fingerprint=fingerprint,
        content_hash=content_hash(jd),
    )


def _ats_url_candidates(text: str) -> list[str]:
    if not text:
        return []
    decoded = html.unescape(str(text))
    candidates: list[str] = []
    for pattern in (_ATS_URL_RE, _ATS_LINK_RE):
        for match in pattern.finditer(decoded):
            candidate = match.group(1) if pattern is _ATS_LINK_RE else match.group(0)
            candidate = candidate.strip().rstrip(".,;")
            if candidate.startswith("//"):
                candidate = f"https:{candidate}"
            if not candidate.startswith(("http://", "https://")):
                continue
            if any(host in candidate.lower() for host in ("ashbyhq.com", "greenhouse.io", "lever.co", "workable.com")):
                if candidate not in candidates:
                    candidates.append(candidate)
    return candidates


def _words(value: str) -> str:
    value = (value or "").lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _salary_value_k(salary_k: object, salary_text: str) -> float | None:
    try:
        if salary_k is not None and str(salary_k).strip() != "":
            return float(salary_k)
    except (TypeError, ValueError):
        pass
    nums = []
    for match in re.finditer(r"\$?\s*(\d{2,3})(?:,\d{3})?\s*k?", salary_text or "", re.I):
        raw = match.group(1)
        try:
            value = float(raw)
        except ValueError:
            continue
        if value >= 1000:
            value = value / 1000.0
        nums.append(value)
    return max(nums) if nums else None
