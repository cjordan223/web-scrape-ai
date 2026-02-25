"""URL normalization helpers for stable deduplication."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "refid",
    "trackingid",
    "trk",
    "position",
    "pagenum",
    "originalsubdomain",
    "lipi",
}

_HOST_ALIASES = {
    # Greenhouse exposes equivalent links on both hosts.
    "job-boards.greenhouse.io": "boards.greenhouse.io",
}


def canonicalize_job_url(url: str) -> str:
    """Normalize job URLs so dedup keys are stable across runs."""
    if not url:
        return url

    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    host = _HOST_ALIASES.get(host, host)

    path = parsed.path or "/"

    if "jobs.lever.co" in host and path.lower().endswith("/apply"):
        path = path[:-6] or "/"
    if "myworkdayjobs.com" in host:
        # Normalize apply/autofill endpoints back to the canonical posting path.
        path = re.sub(r"/apply(?:/[^/?#]+)*$", "", path, flags=re.I)
    if "icims.com" in host:
        # Keep canonical posting path and drop login/apply variants.
        path = re.sub(r"/job/(?:login|apply(?:/.*)?)$", "/job", path, flags=re.I)

    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # These boards encode the job identity in the path; query params are tracking noise.
    if (
        "linkedin.com" in host
        or "jobs.lever.co" in host
        or "boards.greenhouse.io" in host
        or "simplyhired.com" in host
        or "ashbyhq.com" in host
    ):
        query = ""
    else:
        pairs = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            lk = key.lower()
            if lk in _TRACKING_PARAMS or lk.startswith("utm_"):
                continue
            pairs.append((key, value))
        query = urlencode(pairs, doseq=True)

    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=host,
        path=path,
        params="",
        query=query,
        fragment="",
    )
    return urlunparse(normalized)
