"""Discover candidate direct ATS boards from recently observed job URLs."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from job_scraper.config import load_config
from job_scraper.db import JobDB
from job_scraper.spiders import AGGREGATOR_PATH_SEGMENTS


@dataclass(frozen=True)
class BoardCandidate:
    board_type: str
    company: str
    board_url: str
    observed_jobs: int
    latest_seen_at: str
    already_configured: bool


def discover_board_candidates(limit: int = 1000, include_configured: bool = False) -> list[BoardCandidate]:
    db = JobDB()
    try:
        rows = db._conn.execute(
            """SELECT url, board, company, created_at
               FROM jobs
               WHERE url IS NOT NULL AND url != ''
               ORDER BY created_at DESC, id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    finally:
        db.close()

    configured = _configured_board_urls()
    aggregate: dict[tuple[str, str], dict] = {}
    for row in rows:
        board_url = canonical_board_url(row["url"], row["board"] or "")
        if not board_url:
            continue
        board_type = board_type_from_url(board_url)
        if not board_type:
            continue
        key = (board_type, board_url)
        entry = aggregate.setdefault(
            key,
            {
                "board_type": board_type,
                "company": company_from_board_url(board_url, board_type) or row["company"] or "unknown",
                "board_url": board_url,
                "observed_jobs": 0,
                "latest_seen_at": row["created_at"] or "",
                "already_configured": board_url in configured,
            },
        )
        entry["observed_jobs"] += 1
        if (row["created_at"] or "") > (entry["latest_seen_at"] or ""):
            entry["latest_seen_at"] = row["created_at"] or ""

    candidates = [BoardCandidate(**entry) for entry in aggregate.values()]
    if not include_configured:
        candidates = [candidate for candidate in candidates if not candidate.already_configured]
    return sorted(candidates, key=lambda c: (-c.observed_jobs, c.board_type, c.company))


def _configured_board_urls() -> set[str]:
    cfg = load_config()
    urls = set()
    for board in cfg.boards:
        canonical = canonical_board_url(board.url, board.board_type)
        if canonical:
            urls.add(canonical)
    return urls


def board_type_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "ashbyhq.com" in host:
        return "ashby"
    if "greenhouse.io" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "smartrecruiters.com" in host:
        return "smartrecruiters"
    if "myworkdayjobs.com" in host or "myworkdaysite.com" in host:
        return "workday"
    if "icims.com" in host:
        return "icims"
    if "bamboohr.com" in host:
        return "bamboohr"
    if "jobvite.com" in host:
        return "jobvite"
    return ""


def canonical_board_url(url: str, board: str = "") -> str:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    board_type = board if board in {
        "ashby", "greenhouse", "lever", "smartrecruiters", "workday",
        "icims", "bamboohr", "jobvite",
    } else board_type_from_url(url)
    company = company_from_parts(board_type, host, parts)
    if not company:
        return ""
    if board_type == "ashby":
        return f"https://jobs.ashbyhq.com/{company}"
    if board_type == "greenhouse":
        return f"https://job-boards.greenhouse.io/{company}"
    if board_type == "lever":
        return f"https://jobs.lever.co/{company}"
    if board_type == "smartrecruiters":
        return f"https://jobs.smartrecruiters.com/{company}"
    if board_type in {"workday", "icims", "bamboohr", "jobvite"}:
        return f"https://{host}/{company}" if company in parts else f"https://{host}"
    return ""


def company_from_board_url(url: str, board_type: str) -> str:
    parsed = urlparse(url or "")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    return company_from_parts(board_type, parsed.netloc.lower(), parts)


def company_from_parts(board_type: str, host: str, parts: list[str]) -> str:
    first = _first_valid_segment(parts)
    if board_type in {"ashby", "greenhouse", "lever", "smartrecruiters", "jobvite"}:
        return first or ""
    if board_type == "workday":
        return first or host.split(".")[0]
    if board_type in {"icims", "bamboohr"}:
        return host.split(".")[0].replace("careers-", "")
    return ""


def _first_valid_segment(parts: list[str]) -> str:
    for part in parts:
        normalized = part.strip().lower()
        if normalized and normalized not in AGGREGATOR_PATH_SEGMENTS and not normalized.isdigit():
            return part
    return ""
