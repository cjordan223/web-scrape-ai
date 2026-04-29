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
    created_at = scrapy.Field()
    discovered_at = scrapy.Field()  # alias accepted by db layer
    status = scrapy.Field()
    rejection_stage = scrapy.Field()
    rejection_reason = scrapy.Field()
    experience_years = scrapy.Field()
    salary_k = scrapy.Field()
    score = scrapy.Field()
    filter_verdicts = scrapy.Field()
    flags = scrapy.Field()
    canonical_url = scrapy.Field()
    ats_provider = scrapy.Field()
    ats_job_id = scrapy.Field()
    company_norm = scrapy.Field()
    title_norm = scrapy.Field()
    location_bucket = scrapy.Field()
    remote_flag = scrapy.Field()
    salary_bucket = scrapy.Field()
    fingerprint = scrapy.Field()
    content_hash = scrapy.Field()
    duplicate_status = scrapy.Field()
    duplicate_of_job_id = scrapy.Field()
