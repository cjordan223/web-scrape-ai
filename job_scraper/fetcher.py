"""HTML fetch + text extraction for job descriptions."""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

import requests

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_SKIP_TAGS = {"script", "style", "noscript", "svg", "head"}


class _TextExtractor(HTMLParser):
    """Simple HTML → plain text extractor."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str):
        if tag.lower() in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str):
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = " ".join(self._parts)
        return re.sub(r"\s+", " ", raw).strip()


def fetch_jd_text(
    url: str, max_chars: int = 15000, timeout: int = 15
) -> str | None:
    """Fetch a job description URL and return plain text, or None on failure."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
        )
        resp.raise_for_status()

        extractor = _TextExtractor()
        extractor.feed(resp.text)
        text = extractor.get_text()

        return text[:max_chars] if text else None
    except Exception as e:
        logger.warning("Failed to fetch JD from %s: %s", url, e)
        return None
