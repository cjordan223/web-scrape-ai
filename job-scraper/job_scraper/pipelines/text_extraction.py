"""Pipeline: extract clean text from JD HTML using Trafilatura."""

from __future__ import annotations

import logging

import trafilatura
from scrapy.exceptions import DropItem

logger = logging.getLogger(__name__)

# Suppress trafilatura's noisy ERROR logs (empty HTML trees are expected, not errors)
logging.getLogger("trafilatura").setLevel(logging.CRITICAL)

_MIN_JD_CHARS = 30


class TextExtractionPipeline:
    def process_item(self, item, spider):
        html = item.get("jd_html")
        if html:
            text = trafilatura.extract(html, include_comments=False, include_tables=True)
            if text and len(text.strip()) >= _MIN_JD_CHARS:
                item["jd_text"] = text
                return item

        # Fall back to snippet
        snippet = item.get("snippet") or ""
        if len(snippet.strip()) >= _MIN_JD_CHARS:
            item["jd_text"] = snippet
            return item

        raise DropItem(f"No usable JD text for {item.get('url', '?')}")
