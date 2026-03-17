"""USAJobs watcher — custom watcher module for the federal jobs API.

Searches data.usajobs.gov with multiple query configs, handles pagination,
and maps results into SearchResult objects for the scraper pipeline.

Env vars:
    USAJOBS_API_KEY   — your API key from developer.usajobs.gov
    USAJOBS_EMAIL     — registered email (sent as User-Agent header)
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

import httpx

from .models import JobBoard, SearchResult

if TYPE_CHECKING:
    from .config import WatcherConfig

logger = logging.getLogger(__name__)

_BASE_URL = "https://data.usajobs.gov/api/search"

# OPM series codes aligned with user interests
_SERIES = {
    "2210": "IT Management",          # cybersecurity, sysadmin, infosec
    "1550": "Computer Science",
    "0854": "Computer Engineering",
    "0861": "Aerospace Engineering",
    "1560": "Data Science",
    "1301": "General Physical Science",
}

# Agencies of interest (subelement codes)
_AGENCIES = {
    "NN": "NASA",
    "CISA": "CISA",          # under DHS
    "EP": "EPA",
    "OC": "NOAA",            # under DOC
    "AF": "Air Force",
    "NS": "NSF",
}

# Clearance keywords to reject (no clearance pathway)
_CLEARANCE_REJECT = re.compile(
    r"\b(top secret|ts/sci|ts-sci|sci clearance|secret clearance|"
    r"polygraph|q clearance|l clearance|active clearance|"
    r"obtain.*clearance|eligible.*clearance|clearance required)\b",
    re.I,
)


def _get_credentials() -> tuple[str, str]:
    key = os.environ.get("USAJOBS_API_KEY", "")
    email = os.environ.get("USAJOBS_EMAIL", "")
    if not key or not email:
        raise RuntimeError(
            "USAJOBS_API_KEY and USAJOBS_EMAIL env vars required. "
            "Get a key at https://developer.usajobs.gov/APIRequest/Index"
        )
    return key, email


def _build_queries(w: WatcherConfig) -> list[dict[str, str]]:
    """Build a list of query param dicts from watcher config.

    The watcher's `params` dict can contain:
        series     — semicolon-separated OPM codes (default: all _SERIES)
        keywords   — semicolon-separated keyword groups, each becomes a query
        agencies   — semicolon-separated org codes (optional, adds agency queries)
        days       — DatePosted window (default 14)
        remote     — "true" to add a remote-only query variant
    """
    series = w.params.get("series", ";".join(_SERIES.keys()))
    keywords = w.params.get("keywords", "cybersecurity;software engineer;platform engineer;cloud security;DevSecOps")
    days = w.params.get("days", "14")
    agencies = w.params.get("agencies", "")
    want_remote = w.params.get("remote", "true").lower() == "true"

    base = {
        "JobCategoryCode": series,
        "SecurityClearanceRequired": "0",
        "HiringPath": "public",
        "DatePosted": days,
        "ResultsPerPage": "500",
        "Fields": "full",
        "SortField": "opendate",
        "SortDirection": "desc",
    }

    queries: list[dict[str, str]] = []

    # Keyword-based queries
    for kw in keywords.split(";"):
        kw = kw.strip()
        if not kw:
            continue
        q = {**base, "Keyword": kw}
        queries.append(q)
        if want_remote:
            queries.append({**q, "RemoteIndicator": "True"})

    # Agency-based queries (broader — all series at that agency)
    for code in (agencies or "").split(";"):
        code = code.strip()
        if not code:
            continue
        q = {**base, "Organization": code}
        queries.append(q)

    return queries


def _fetch_page(client: httpx.Client, headers: dict, params: dict, page: int) -> dict:
    params = {**params, "Page": str(page)}
    resp = client.get(_BASE_URL, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def _extract_results(data: dict, watcher_name: str) -> list[SearchResult]:
    """Parse USAJobs response into SearchResult objects."""
    items = (data.get("SearchResult") or {}).get("SearchResultItems") or []
    results: list[SearchResult] = []

    for item in items:
        obj = item.get("MatchedObjectDescriptor") or {}
        title = obj.get("PositionTitle") or ""
        uri = obj.get("PositionURI") or ""
        if not uri:
            continue

        org = obj.get("OrganizationName") or ""
        dept = obj.get("DepartmentName") or ""

        # Build snippet from qualification summary + location + salary
        qual = obj.get("QualificationSummary") or ""
        locations = [
            loc.get("LocationName", "")
            for loc in (obj.get("PositionLocation") or [])
        ]
        loc_str = "; ".join(filter(None, locations))

        remuneration = (obj.get("PositionRemuneration") or [{}])[0] if obj.get("PositionRemuneration") else {}
        sal_min = remuneration.get("MinimumRange", "")
        sal_max = remuneration.get("MaximumRange", "")
        sal_str = f"${sal_min}-${sal_max}" if sal_min and sal_max else ""

        # Check user area for clearance/telework details
        details = (obj.get("UserArea") or {}).get("Details") or {}
        who_may_apply = (details.get("WhoMayApply") or {}).get("Name") or ""
        major_duties = " ".join(details.get("MajorDuties") or [])

        # Skip if clearance language found in duties or qualifications
        combined_text = f"{qual} {major_duties} {who_may_apply}"
        if _CLEARANCE_REJECT.search(combined_text):
            logger.debug("Skipping %r — clearance language detected", title)
            continue

        snippet_parts = [f"{dept} — {org}" if org != dept else org]
        if loc_str:
            snippet_parts.append(loc_str)
        if sal_str:
            snippet_parts.append(sal_str)
        if qual:
            snippet_parts.append(qual[:300])

        snippet = " • ".join(snippet_parts)

        results.append(SearchResult(
            title=title,
            url=uri,
            snippet=snippet,
            source=f"watcher:{watcher_name}",
            board=JobBoard.usajobs,
            skip_filters=["url_domain", "source_quality", "remote", "location"],
        ))

    return results


def fetch(w: WatcherConfig) -> list[SearchResult]:
    """Entry point called by the custom watcher runner."""
    key, email = _get_credentials()
    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": email,
        "Authorization-Key": key,
    }

    queries = _build_queries(w)
    logger.info("USAJobs: running %d query variants", len(queries))

    all_results: list[SearchResult] = []
    seen_uris: set[str] = set()

    with httpx.Client(timeout=30) as client:
        for qi, params in enumerate(queries, 1):
            kw = params.get("Keyword", params.get("Organization", "?"))
            remote_tag = " [remote]" if params.get("RemoteIndicator") else ""
            try:
                data = _fetch_page(client, headers, params, 1)
                total = (data.get("SearchResult") or {}).get("SearchResultCountAll", 0)
                logger.info(
                    "USAJobs query %d/%d (%s%s): %s total matches",
                    qi, len(queries), kw, remote_tag, total,
                )

                page_results = _extract_results(data, w.name)
                for r in page_results:
                    if r.url not in seen_uris:
                        seen_uris.add(r.url)
                        all_results.append(r)

                # Paginate if needed (cap at 3 pages = 1500 results per query)
                num_pages = min((data.get("SearchResult") or {}).get("NumberOfPages", 1), 3)
                for page in range(2, num_pages + 1):
                    data = _fetch_page(client, headers, params, page)
                    page_results = _extract_results(data, w.name)
                    for r in page_results:
                        if r.url not in seen_uris:
                            seen_uris.add(r.url)
                            all_results.append(r)

            except Exception:
                logger.exception("USAJobs query %d failed (%s%s)", qi, kw, remote_tag)

    logger.info("USAJobs: %d unique results across all queries", len(all_results))
    return all_results
