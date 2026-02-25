"""HTML fetch + text extraction for job descriptions."""

from __future__ import annotations

import logging
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_SKIP_TAGS = {"script", "style", "noscript", "svg", "head"}
_META_FALLBACK_PATTERN = re.compile(
    r'<meta[^>]+(?:name|property)\s*=\s*["\']'
    r'(?:description|og:description|twitter:description|keywords|twitter:data1)'
    r'["\'][^>]+content\s*=\s*["\']([^"\']+)["\']',
    re.I,
)


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

        # Detect cross-domain or homepage redirects (e.g. simplyhired.com/job/X → www.simplyhired.com/)
        orig_host = urlparse(url).netloc.lower().replace("www.", "")
        final_host = urlparse(resp.url).netloc.lower().replace("www.", "")
        final_path = urlparse(resp.url).path.rstrip("/")
        if orig_host == final_host and not final_path:
            logger.warning("Redirect to homepage detected for %s → %s", url, resp.url)
            return None

        extractor = _TextExtractor()
        extractor.feed(resp.text)
        text = extractor.get_text()
        if len(text) < 200:
            # JS-heavy boards often keep useful metadata in <meta> tags.
            meta_parts = [unescape(m.group(1)).strip() for m in _META_FALLBACK_PATTERN.finditer(resp.text)]
            if meta_parts:
                text = f"{text} {' '.join(meta_parts)}".strip()

        return text[:max_chars] if text else None
    except Exception as e:
        logger.warning("Failed to fetch JD from %s: %s", url, e)
        return None
