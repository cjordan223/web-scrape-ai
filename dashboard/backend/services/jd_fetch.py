"""Domain-specific job description fetchers."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urlparse

import requests

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_linkedin(url: str) -> str | None:
    """Extract JD from LinkedIn by rewriting to /jobs/view/ and parsing the HTML."""
    m = re.search(r"currentJobId=(\d+)", url) or re.search(r"/jobs/view/[^/]*?(\d+)", url)
    if not m:
        return None
    view_url = f"https://www.linkedin.com/jobs/view/{m.group(1)}"
    resp = requests.get(view_url, headers={"User-Agent": _UA}, timeout=20)
    resp.raise_for_status()
    show = re.search(r'class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
    if show:
        txt = re.sub(r"<[^>]+>", " ", unescape(show.group(1)))
        txt = re.sub(r"\s+", " ", txt).strip()
        if len(txt) > 50:
            return txt
    return None


def fetch_ashby(url: str) -> str | None:
    """Extract JD from Ashby pages via embedded descriptionHtml."""
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
    resp.raise_for_status()
    m = re.search(r'"descriptionHtml"\s*:\s*"(.*?)"(?:,|})', resp.text)
    if m:
        desc = m.group(1).encode().decode("unicode_escape")
        desc = re.sub(r"<[^>]+>", " ", desc)
        desc = re.sub(r"\s+", " ", desc).strip()
        if len(desc) > 50:
            return desc
    return None


def fetch_jd(url: str) -> tuple[str | None, str]:
    """Fetch job description text from a URL. Returns (text, method_used).

    Tries domain-specific extractors first, then falls back to generic HTML fetch.
    """
    host = urlparse(url).netloc.lower()
    text = None
    method = "generic"

    if "linkedin.com" in host:
        text = fetch_linkedin(url)
        method = "linkedin"
    elif "ashbyhq.com" in host:
        text = fetch_ashby(url)
        method = "ashby"

    if not text:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "job-scraper"))
        from job_scraper.fetcher import fetch_jd_text
        text = fetch_jd_text(url, max_chars=15000, timeout=20)
        if method != "generic":
            method += "+generic"

    return text, method
