"""job_scraper — Security job discovery via SearXNG."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from .config import ScraperConfig, load_config
from .dedup import JobStore
from .fetcher import fetch_jd_text
from .filters import apply_filters
from .llm_reviewer import llm_review
from .models import JobResult, ScrapeRun
from .searcher import execute_queries

logger = logging.getLogger(__name__)


def scrape_jobs(
    config_path: Optional[Path] = None,
    config: Optional[ScraperConfig] = None,
    mark_seen: bool = True,
    fetch_jd: bool | None = None,
    crawl: bool = True,
) -> ScrapeRun:
    """Run a full scrape cycle. This is the public API.

    Args:
        config_path: Path to a YAML config override.
        config: Pre-built config (takes precedence over config_path).
        mark_seen: Whether to mark discovered jobs in the dedup store.
        fetch_jd: Override config's fetch_jd setting (None = use config).
    """
    if config is None:
        config = load_config(config_path)

    should_fetch = fetch_jd if fetch_jd is not None else config.filter.fetch_jd
    run_id = uuid.uuid4().hex[:12]

    run = ScrapeRun(run_id=run_id)

    with JobStore() as store:
        store.start_run(run_id)

        try:
            # 1. Execute queries
            logger.info("Executing %d queries...", len(config.queries))
            raw_results = execute_queries(config)
            logger.info("Got %d raw results from SearXNG", len(raw_results))

            # 1b. Crawl job boards
            if crawl and config.crawl.enabled:
                from .crawler import crawl_job_boards

                crawl_results = crawl_job_boards(config)
                logger.info("Got %d results from Crawl4AI", len(crawl_results))
                raw_results = raw_results + crawl_results

            run.raw_count = len(raw_results)
            logger.info("Total raw results: %d", run.raw_count)

            # 2. Dedup
            unseen = []
            for r in raw_results:
                if not store.is_seen(r.url):
                    unseen.append(r)

            run.dedup_count = len(unseen)
            logger.info("%d new (unseen) results after dedup", run.dedup_count)

            # 3. Fetch JD + Filter
            rejected_items = []  # (SearchResult, stage, reason, verdicts)
            for r in unseen:
                jd_text = None
                if should_fetch:
                    jd_text = fetch_jd_text(r.url, max_chars=config.filter.jd_max_chars)

                passed, verdicts, seniority, exp_years, salary = apply_filters(
                    title=r.title,
                    url=r.url,
                    snippet=r.snippet,
                    jd_text=jd_text,
                    config=config.filter,
                )

                if not passed:
                    failing = verdicts[-1]
                    rejected_items.append((r, failing.stage, failing.reason, verdicts))
                    continue

                # LLM common-sense review (after all rule-based stages)
                if config.llm_review.enabled:
                    lv = llm_review(r.title, r.snippet, jd_text, config.llm_review)
                    verdicts.append(lv)
                    if not lv.passed:
                        logger.info("LLM rejected '%s': %s", r.title, lv.reason)
                        rejected_items.append((r, "llm_review", lv.reason, verdicts))
                        continue
                    logger.debug("LLM passed '%s': %s", r.title, lv.reason)

                job = JobResult(
                    title=r.title,
                    url=r.url,
                    board=r.board,
                    seniority=seniority,
                    experience_years=exp_years,
                    salary_k=salary,
                    jd_text=jd_text,
                    snippet=r.snippet,
                    query=r.query,
                    filter_verdicts=verdicts,
                )
                run.jobs.append(job)

            run.filtered_count = len(run.jobs)
            logger.info("%d jobs passed filters, %d rejected", run.filtered_count, len(rejected_items))

            # 4. Mark seen + persist passing results + save rejections
            if mark_seen:
                for r in unseen:
                    store.mark_seen(r.url)
                store.save_results(run.jobs, run_id)
                store.save_rejected_batch(rejected_items, run_id)
                logger.info(
                    "Persisted %d results, %d rejections, marked %d URLs seen",
                    len(run.jobs), len(rejected_items), len(unseen),
                )

            store.finish_run(
                run_id, raw=run.raw_count, dedup=run.dedup_count,
                filtered=run.filtered_count, errors=run.errors,
            )
        except Exception as exc:
            store.fail_run(run_id, str(exc))
            raise

    return run
