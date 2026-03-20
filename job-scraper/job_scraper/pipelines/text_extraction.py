"""Pipeline: extract clean text from JD HTML using Trafilatura."""

from __future__ import annotations

import logging

import trafilatura

logger = logging.getLogger(__name__)


class TextExtractionPipeline:
    def process_item(self, item, spider):
        html = item.get("jd_html")
        if html:
            text = trafilatura.extract(html, include_comments=False, include_tables=True)
            if text:
                item["jd_text"] = text
                return item
        snippet = item.get("snippet")
        if snippet:
            item["jd_text"] = snippet
        else:
            item["jd_text"] = None
        return item
