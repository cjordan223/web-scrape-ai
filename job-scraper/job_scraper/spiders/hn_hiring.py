"""Spider for Hacker News 'Who is Hiring?' monthly threads."""
from __future__ import annotations

import html as html_mod
import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

import scrapy
from job_scraper.items import JobItem

logger = logging.getLogger(__name__)

_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
_FIREBASE_URL = "https://hacker-news.firebaseio.com/v0/item"
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")

_LOCATION_WORDS = re.compile(
    r"\b(remote|onsite|on-site|hybrid|nyc|sf|usa|london|berlin|eu|"
    r"europe|canada|worldwide|global|los angeles|new york|seattle|"
    r"austin|denver|chicago|boston|san francisco|portland|toronto|"
    r"vancouver|uk|germany|france|india|singapore|australia|japan|"
    r"amsterdam|paris|munich|stockholm|barcelona|tokyo)\b",
    re.I,
)
_ROLE_WORDS = re.compile(
    r"\b(engineer|developer|designer|scientist|manager|architect|"
    r"analyst|lead|senior|staff|principal|director|sre|devops|"
    r"security|backend|frontend|full.?stack|platform|infra|data|"
    r"ml|ai|ios|android|product|qa|test|cloud|devsecops|swe|"
    r"founding|cto|ciso|researcher|consultant)\b",
    re.I,
)
_EMPLOYMENT_WORDS = re.compile(
    r"^(full[- ]?time|part[- ]?time|contract|freelance|intern|internship|consulting|contractor)$",
    re.I,
)
_JUNK_TITLE = re.compile(
    r"^(YC\s*[SWFA]?\d{2,4}|Y\s*Combinator|Series\s*[A-Z]|seed|multiple\s*(roles|positions)|various)$",
    re.I,
)
_URL_ONLY = re.compile(r"^https?://\S+$")


def _clean(s: str) -> str:
    """Decode HTML entities and strip tags."""
    s = re.sub(r"<[^>]+>", "", s)
    return html_mod.unescape(s).strip()


def _classify_part(part: str) -> str:
    """Guess whether a pipe segment is a location, role, or company."""
    loc_hits = len(_LOCATION_WORDS.findall(part))
    role_hits = len(_ROLE_WORDS.findall(part))
    if loc_hits > role_hits and loc_hits > 0:
        return "location"
    if role_hits > 0:
        return "title"
    return "unknown"


def parse_hn_comment(text: str) -> dict:
    """Parse a Who's Hiring comment into structured fields.

    Convention: Company | Role | Location | Salary | URL
    But many comments don't follow this exactly — use heuristics.
    """
    result = {"company": "", "title": "", "location": "", "url": None}

    # Extract first URL from text
    url_match = _URL_PATTERN.search(text)
    if url_match:
        result["url"] = html_mod.unescape(url_match.group(0).rstrip(".,;)"))

    # Work with first line only, cleaned
    first_line = text.split("<p>")[0].split("\n")[0].strip()
    first_line = _clean(first_line)
    parts = [p.strip() for p in first_line.split("|")]

    if len(parts) >= 2:
        # Classify all parts first, then assign intelligently
        classified = []
        for part in parts:
            if len(part) > 200:
                classified.append(("skip", part))
                continue
            clean_part = re.sub(r"\s*https?://\S+", "", part).strip()
            clean_part = re.sub(r"\s*\([^)]*https?://[^)]*\)", "", clean_part).strip()
            if _URL_ONLY.match(part.strip()):
                classified.append(("url", part))
            elif _EMPLOYMENT_WORDS.match(clean_part):
                classified.append(("employment", part))
            else:
                classified.append((_classify_part(part), part))

        # First part: company unless it looks like a role (and a later part doesn't)
        first_kind, first_val = classified[0]
        rest = classified[1:]

        # Detect misclassified first part: if first part has role words but no
        # later parts do, the first part is actually a role not a company
        if first_kind == "title":
            has_later_title = any(k == "title" for k, _ in rest)
            if has_later_title:
                # First part is the company (has some role words but there's a better title later)
                result["company"] = first_val[:120]
            else:
                # First part looks like a role — check if it could be company
                # HN convention: first part is company. Only override if it's
                # clearly a role with no company-like content
                loc_hits = len(_LOCATION_WORDS.findall(first_val))
                role_hits = len(_ROLE_WORDS.findall(first_val))
                if role_hits >= 2 and loc_hits == 0:
                    # Strong role signal — this IS the title, company unknown
                    result["title"] = first_val[:120]
                else:
                    result["company"] = first_val[:120]
        else:
            result["company"] = first_val[:120]

        # Assign remaining parts
        for kind, part in rest:
            if kind == "skip" or kind == "url":
                continue
            if kind == "title" and not result["title"]:
                result["title"] = part[:120]
            elif kind == "location" and not result["location"]:
                result["location"] = part[:120]
            elif kind == "employment":
                # Don't use employment type as title — store in location if
                # we have nothing better, but prefer to skip
                continue
            elif kind == "unknown":
                if not result["title"]:
                    result["title"] = part[:120]
                elif not result["location"]:
                    result["location"] = part[:120]

    elif len(parts) == 1 and len(first_line) < 200:
        # No pipes — use the whole first line as company
        result["company"] = first_line[:120]

    # Strip URLs and clean up fields
    for field in ("company", "title", "location"):
        result[field] = re.sub(r"\s*https?://\S+", "", result[field]).strip()
        # Remove parenthesized URLs
        result[field] = re.sub(r"\s*\([^)]*https?://[^)]*\)", "", result[field]).strip()
        # Remove trailing/leading punctuation junk (but preserve balanced parens)
        result[field] = result[field].strip(" \t-–—")
        # Only strip unbalanced parens
        val = result[field]
        if val.startswith("(") and ")" not in val:
            val = val.lstrip("(").strip()
        if val.endswith(")") and "(" not in val:
            val = val.rstrip(")").strip()
        result[field] = val

    # Post-processing: reject bad titles
    clean_title = result["title"].strip()
    if clean_title and (
        _EMPLOYMENT_WORDS.match(clean_title)
        or _JUNK_TITLE.match(clean_title)
        or _URL_ONLY.match(clean_title)
    ):
        result["title"] = ""

    return result


class HNHiringSpider(scrapy.Spider):
    name = "hn_hiring"

    def __init__(self, max_comments=500, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._max_comments = max_comments

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        from job_scraper.config import load_config
        cfg = load_config()
        if not cfg.hn_hiring.enabled:
            kwargs["max_comments"] = 0
        else:
            kwargs["max_comments"] = cfg.hn_hiring.max_comments
        return super().from_crawler(crawler, *args, **kwargs)

    def start_requests(self):
        if self._max_comments <= 0:
            logger.info("HN Hiring spider disabled")
            return
        now = datetime.now()
        month_year = now.strftime("%B %Y")  # e.g. "March 2026"
        query = quote(f'"Who is hiring" "{month_year}"')
        url = f"{_ALGOLIA_URL}?query={query}&tags=ask_hn&hitsPerPage=1"
        yield scrapy.Request(url=url, callback=self.parse_search, dont_filter=True)

    def parse_search(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Failed to parse Algolia response")
            return

        hits = data.get("hits", [])
        if not hits:
            logger.warning("No 'Who is hiring' thread found")
            return

        thread_id = hits[0].get("objectID")
        if not thread_id:
            return

        logger.info("Found HN hiring thread: %s (id=%s)", hits[0].get("title", "?"), thread_id)
        yield scrapy.Request(
            url=f"{_FIREBASE_URL}/{thread_id}.json",
            callback=self.parse_thread,
            dont_filter=True,
        )

    def parse_thread(self, response):
        try:
            data = response.json()
        except Exception:
            logger.warning("Failed to parse HN thread response")
            return

        kids = data.get("kids", [])
        logger.info("HN thread has %d top-level comments (limit %d)", len(kids), self._max_comments)

        for kid_id in kids[: self._max_comments]:
            yield scrapy.Request(
                url=f"{_FIREBASE_URL}/{kid_id}.json",
                callback=self.parse_comment,
                dont_filter=True,
                priority=-1,
            )

    def parse_comment(self, response):
        try:
            data = response.json()
        except Exception:
            return

        if not data or data.get("deleted") or data.get("dead"):
            return

        comment_id = data.get("id", "")
        text = data.get("text", "")
        if not text:
            return

        parsed = parse_hn_comment(text)
        hn_url = f"https://news.ycombinator.com/item?id={comment_id}"
        job_url = parsed.get("url")
        clean_text = _clean(re.sub(r"<p>", "\n\n", text))

        if job_url:
            yield scrapy.Request(
                url=job_url,
                callback=self.parse_job_page,
                meta={
                    "hn_url": hn_url,
                    "hn_company": parsed.get("company", ""),
                    "hn_title": parsed.get("title", ""),
                    "hn_location": parsed.get("location", ""),
                    "hn_text": clean_text,
                },
                errback=self.errback_job_page,
                dont_filter=True,
                priority=-2,
            )
        else:
            if parsed.get("title"):
                yield JobItem(
                    url=hn_url,
                    title=parsed["title"],
                    company=parsed.get("company", "Unknown"),
                    board="hn_hiring",
                    location=parsed.get("location", ""),
                    jd_text=clean_text,
                    source=self.name,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )

    def parse_job_page(self, response):
        meta = response.meta
        title = meta.get("hn_title") or "Unknown"
        company = meta.get("hn_company") or "Unknown"
        location = meta.get("hn_location") or ""

        yield JobItem(
            url=response.url,
            title=title.strip(),
            company=company.strip(),
            board="hn_hiring",
            location=location,
            jd_html=response.text,
            source=self.name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def errback_job_page(self, failure):
        request = failure.request
        meta = request.meta
        hn_url = meta.get("hn_url", "")
        title = meta.get("hn_title", "Unknown")
        company = meta.get("hn_company", "Unknown")
        text = meta.get("hn_text", "")

        if title and title != "Unknown":
            yield JobItem(
                url=hn_url,
                title=title,
                company=company,
                board="hn_hiring",
                location=meta.get("hn_location", ""),
                jd_text=text,
                source=self.name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
