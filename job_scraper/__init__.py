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
from .models import JobResult, ScrapeRun
from .searcher import execute_queries

logger = logging.getLogger(__name__)


def scrape_jobs(
    config_path: Optional[Path] = None,
    config: Optional[ScraperConfig] = None,
    mark_seen: bool = True,
    fetch_jd: bool | None = None,
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
            run.raw_count = len(raw_results)
            logger.info("Got %d raw results", run.raw_count)

            # 2. Dedup
            unseen = []
            for r in raw_results:
                if not store.is_seen(r.url):
                    unseen.append(r)

            run.dedup_count = len(unseen)
            logger.info("%d new (unseen) results after dedup", run.dedup_count)

            # 3. Fetch JD + Filter
            for r in unseen:
                jd_text = None
                if should_fetch:
                    jd_text = fetch_jd_text(r.url, max_chars=config.filter.jd_max_chars)

                passed, verdicts, seniority, exp_years = apply_filters(
                    title=r.title,
                    url=r.url,
                    snippet=r.snippet,
                    jd_text=jd_text,
                    config=config.filter,
                )

                if passed:
                    job = JobResult(
                        title=r.title,
                        url=r.url,
                        board=r.board,
                        seniority=seniority,
                        experience_years=exp_years,
                        jd_text=jd_text,
                        snippet=r.snippet,
                        query=r.query,
                        filter_verdicts=verdicts,
                    )
                    run.jobs.append(job)

            run.filtered_count = len(run.jobs)
            logger.info("%d jobs passed filters", run.filtered_count)

            # 4. Mark seen + persist passing results
            if mark_seen:
                for r in unseen:
                    store.mark_seen(r.url)
                store.save_results(run.jobs, run_id)
                logger.info("Persisted %d results, marked %d URLs seen", len(run.jobs), len(unseen))

            store.finish_run(
                run_id, raw=run.raw_count, dedup=run.dedup_count,
                filtered=run.filtered_count, errors=run.errors,
            )
        except Exception as exc:
            store.fail_run(run_id, str(exc))
            raise

    return run
