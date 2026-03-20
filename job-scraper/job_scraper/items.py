"""Scrapy Item definition for scraped jobs."""

from __future__ import annotations

import scrapy


class JobItem(scrapy.Item):
    url = scrapy.Field()
    title = scrapy.Field()
    company = scrapy.Field()
    board = scrapy.Field()
    location = scrapy.Field()
    seniority = scrapy.Field()
    salary_text = scrapy.Field()
    jd_html = scrapy.Field()
    jd_text = scrapy.Field()
    snippet = scrapy.Field()
    query = scrapy.Field()
    source = scrapy.Field()
    discovered_at = scrapy.Field()
    status = scrapy.Field()
    rejection_stage = scrapy.Field()
    rejection_reason = scrapy.Field()
