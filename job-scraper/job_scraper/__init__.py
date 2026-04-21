"""job_scraper — Job discovery pipeline powered by Scrapy."""
from __future__ import annotations

import logging
import uuid

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from .db import JobDB
from .config import load_config

logger = logging.getLogger(__name__)


def scrape_all(
    *,
    verbose: bool = False,
    spiders: list[str] | None = None,
    tiers: list[str] | None = None,
    rotation_group: int | None = None,
    run_index: int | None = None,
) -> dict:
    """Run spiders via Scrapy CrawlerProcess.

    Args:
        verbose: Enable debug logging.
        spiders: Explicit spider names (overrides tiers).
        tiers: Tier names to include; unspecified spiders in each tier all run.
        rotation_group: Passed to spiders via settings for workhorse rotation.
        run_index: Scheduler run counter; gates SearXNG discovery firing per
            `scrape_profile.discovery_every_nth_run`. When None, discovery fires.
    """
    from .spiders.ashby import AshbySpider
    from .spiders.greenhouse import GreenhouseSpider
    from .spiders.lever import LeverSpider
    from .spiders.workable import WorkableSpider
    from .spiders.searxng import SearXNGSpider
    from .spiders.aggregator import AggregatorSpider
    from .spiders.generic import GenericSpider
    from .spiders.remoteok import RemoteOKSpider
    from .spiders.hn_hiring import HNHiringSpider
    from .tiers import SPIDER_TIERS, Tier

    ALL_SPIDERS = {
        "ashby": AshbySpider,
        "greenhouse": GreenhouseSpider,
        "lever": LeverSpider,
        "workable": WorkableSpider,
        "searxng": SearXNGSpider,
        "aggregator": AggregatorSpider,
        "generic": GenericSpider,
        "remoteok": RemoteOKSpider,
        "hn_hiring": HNHiringSpider,
    }

    run_id = uuid.uuid4().hex[:12]

    settings = get_project_settings()
    settings["LOG_LEVEL"] = "DEBUG" if verbose else "INFO"
    settings["SCRAPE_RUN_ID"] = run_id
    if rotation_group is not None:
        settings["SCRAPE_ROTATION_GROUP"] = rotation_group
    cfg = load_config()
    settings["SCRAPE_ROTATION_TOTAL"] = cfg.scrape_profile.rotation_groups
    if run_index is not None:
        every_n = cfg.scrape_profile.discovery_every_nth_run
        settings["SCRAPE_DISCOVERY_FIRE"] = (run_index % every_n) == 0

    db = JobDB()
    db.start_run(run_id, trigger="manual" if spiders else "scheduled")

    if spiders is None and tiers is not None:
        wanted_tiers = {Tier(t) for t in tiers}
        spiders = [name for name, tier in SPIDER_TIERS.items()
                   if tier in wanted_tiers and name in ALL_SPIDERS]

    process = CrawlerProcess(settings)
    crawler_refs: list = []
    crawler_names: dict = {}  # crawler -> spider name
    enabled = spiders or list(ALL_SPIDERS.keys())
    for name in enabled:
        spider_cls = ALL_SPIDERS.get(name)
        if spider_cls:
            crawler = process.create_crawler(spider_cls)
            crawler_refs.append(crawler)
            crawler_names[crawler] = name
            process.crawl(crawler)

    rotation_members = list(crawler_names.values())
    # Seed zero rows so scheduled-but-silent spiders are visible in run_tier_stats.
    db.seed_tier_stats(
        run_id,
        [(name, SPIDER_TIERS[name].value) for name in rotation_members if name in SPIDER_TIERS],
    )

    process.start()  # blocks until all spiders finish

    raw_count = 0
    error_count = 0
    discovery_raw_hits = 0
    for crawler in crawler_refs:
        stats = crawler.stats.get_stats()
        hits = stats.get("item_scraped_count", 0) + stats.get("item_dropped_count", 0)
        raw_count += hits
        error_count += stats.get("log_count/ERROR", 0)
        name = crawler_names.get(crawler)
        if name and SPIDER_TIERS.get(name) is Tier.DISCOVERY:
            discovery_raw_hits += hits

    rows = db._conn.execute(
        "SELECT status, COUNT(*) AS n FROM jobs WHERE run_id = ? GROUP BY status",
        (run_id,),
    ).fetchall()
    by_status = {row["status"]: row["n"] for row in rows}
    stored_count = sum(by_status.values())
    filtered_count = by_status.get("rejected", 0)
    net_new = by_status.get("pending", 0) + by_status.get("qa_pending", 0) + by_status.get("lead", 0)

    # Semantic gate_mode — never null for a completed run.
    discovery_members = [n for n in rotation_members if SPIDER_TIERS.get(n) is Tier.DISCOVERY]
    if not discovery_members:
        gate_mode = "skipped_by_cadence"
    elif discovery_raw_hits == 0:
        gate_mode = "no_discovery_items"
    else:
        gate_mode = "normal"
        for crawler in crawler_refs:
            if SPIDER_TIERS.get(crawler_names.get(crawler, "")) is not Tier.DISCOVERY:
                continue
            mode = crawler.settings.get("LLM_GATE_MODE_OBSERVED")
            if mode == "fail_open":
                gate_mode = "fail_open"
                break
            if mode == "overflow":
                gate_mode = "overflow"

    db.finish_run(
        run_id,
        raw_count=raw_count,
        dedup_count=stored_count,
        filtered_count=filtered_count,
        error_count=error_count,
        net_new=net_new,
        gate_mode=gate_mode,
        rotation_group=rotation_group,
        rotation_members=rotation_members,
    )

    stats_out = {
        "run_id": run_id,
        "total_jobs": db.job_count(),
        "pending": db.job_count(status="pending"),
        "rejected": db.job_count(status="rejected"),
        "net_new": net_new,
        "rotation_group": rotation_group,
        "rotation_members": rotation_members,
        "gate_mode": gate_mode,
    }
    db.close()
    return stats_out
