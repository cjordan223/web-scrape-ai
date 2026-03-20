"""job_scraper — Job discovery pipeline powered by Scrapy."""
from __future__ import annotations

import logging
import uuid

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from .db import JobDB
from .config import load_config

logger = logging.getLogger(__name__)


def scrape_all(*, verbose: bool = False, spiders: list[str] | None = None) -> dict:
    """Run all enabled spiders via Scrapy CrawlerProcess.

    Args:
        verbose: Enable debug logging
        spiders: List of spider names to run (None = all enabled)

    Returns:
        dict with run_id, stats
    """
    from .spiders.ashby import AshbySpider
    from .spiders.greenhouse import GreenhouseSpider
    from .spiders.lever import LeverSpider
    from .spiders.usajobs import USAJobsSpider
    from .spiders.searxng import SearXNGSpider
    from .spiders.aggregator import AggregatorSpider
    from .spiders.generic import GenericSpider

    ALL_SPIDERS = {
        "ashby": AshbySpider,
        "greenhouse": GreenhouseSpider,
        "lever": LeverSpider,
        "usajobs": USAJobsSpider,
        "searxng": SearXNGSpider,
        "aggregator": AggregatorSpider,
        "generic": GenericSpider,
    }

    run_id = uuid.uuid4().hex[:12]

    settings = get_project_settings()
    if verbose:
        settings["LOG_LEVEL"] = "DEBUG"
    else:
        settings["LOG_LEVEL"] = "INFO"

    # Pass run_id to pipelines via settings
    settings["SCRAPE_RUN_ID"] = run_id

    db = JobDB()
    db.start_run(run_id, trigger="manual")

    process = CrawlerProcess(settings)

    enabled = spiders or list(ALL_SPIDERS.keys())
    for name in enabled:
        spider_cls = ALL_SPIDERS.get(name)
        if spider_cls:
            process.crawl(spider_cls)

    process.start()  # blocks until all spiders finish

    # Gather stats from DB
    stats = {
        "run_id": run_id,
        "total_jobs": db.job_count(),
        "pending": db.job_count(status="pending"),
        "rejected": db.job_count(status="rejected"),
    }
    db.close()
    return stats
