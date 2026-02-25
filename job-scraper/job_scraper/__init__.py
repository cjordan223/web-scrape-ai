"""job_scraper — Security job discovery via SearXNG."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .config import ScraperConfig, load_config
from .dedup import JobStore
from .fetcher import fetch_jd_text
from .filters import apply_filters
from .llm_reviewer import llm_review
from .models import JobResult, ScrapeRun
from .runtime_controls import load_runtime_controls
from .searcher import execute_queries
from .urlnorm import canonicalize_job_url

logger = logging.getLogger(__name__)


def _normalize_title_for_key(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _company_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]

    if "jobs.lever.co" in host and path_parts:
        return path_parts[0].lower()
    if ("boards.greenhouse.io" in host or "job-boards.greenhouse.io" in host) and path_parts:
        return path_parts[0].lower()
    if "jobs.ashbyhq.com" in host and path_parts:
        return path_parts[0].lower()
    if "jobs.smartrecruiters.com" in host and path_parts:
        return path_parts[0].lower()
    if "myworkdayjobs.com" in host:
        # e.g. nvidia.wd5.myworkdayjobs.com -> nvidia
        return host.split(".")[0]
    if "icims.com" in host:
        # e.g. careers-foo.icims.com -> foo
        first = host.split(".")[0]
        return first.replace("careers-", "")
    return host


def _semantic_job_key(job: JobResult) -> str:
    company = _company_from_url(job.url)
    title = _normalize_title_for_key(job.title)
    return f"{job.board.value}|{company}|{title}"


def _job_quality_score(job: JobResult) -> tuple[int, int]:
    # Prefer richer records when collapsing duplicates.
    return (len(job.jd_text or ""), int(job.score or 0))


def _dedupe_semantic_jobs(jobs: list[JobResult]) -> tuple[list[JobResult], list[JobResult]]:
    by_key: dict[str, JobResult] = {}
    key_order: list[str] = []
    dropped: list[JobResult] = []

    for job in jobs:
        key = _semantic_job_key(job)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = job
            key_order.append(key)
            continue

        if _job_quality_score(job) > _job_quality_score(existing):
            by_key[key] = job
            dropped.append(existing)
        else:
            dropped.append(job)

    return [by_key[k] for k in key_order], dropped


def _dedupe_canonical_jobs(jobs: list[JobResult]) -> tuple[list[JobResult], list[JobResult]]:
    by_key: dict[str, JobResult] = {}
    key_order: list[str] = []
    dropped: list[JobResult] = []

    for job in jobs:
        key = canonicalize_job_url(job.url)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = job
            key_order.append(key)
            continue

        if _job_quality_score(job) > _job_quality_score(existing):
            by_key[key] = job
            dropped.append(existing)
        else:
            dropped.append(job)

    return [by_key[k] for k in key_order], dropped


def _clean_job_title(title: str) -> str:
    t = " ".join(title.split())
    # Ashby pages sometimes concatenate role + department labels.
    t = re.sub(r"\b([A-Za-z]+Engineer)Engineering\b", r"\1", t)
    t = re.sub(r"\b([A-Za-z]+Engineer)Security\b", r"\1", t)
    t = re.sub(r"(?<=[A-Za-z0-9\)])Engineering(?=\s*•)", "", t)
    t = re.sub(r"(?<=[A-Za-z0-9\)])Security(?=\s*•)", "", t)
    t = re.sub(r"(?<=\w)\$(?=\d)", " $", t)
    if "•" in t:
        parts = [p.strip() for p in t.split("•")]
        head, tail = parts[0], parts[1:]
        deduped_tail: list[str] = []
        seen: set[str] = set()
        for p in tail:
            key = p.lower()
            if p and key not in seen:
                deduped_tail.append(p)
                seen.add(key)
        t = " • ".join([head, *deduped_tail]) if deduped_tail else head
    return t.strip()


def _result_rank_key(job: JobResult) -> tuple[int, int]:
    return (int(job.score or -999), len(job.jd_text or ""))


def _verdict_stage_map(verdicts: list) -> dict[str, object]:
    return {getattr(v, "stage", ""): v for v in verdicts}


def _promotion_candidate_ok(verdicts: list) -> bool:
    stages = _verdict_stage_map(verdicts)
    # Require core relevance gates to have passed before promotion.
    for stage in ("title_relevance", "title_role", "jd_quality", "jd_presence", "remote", "location"):
        v = stages.get(stage)
        if v is not None and not getattr(v, "passed", False):
            return False
    remote_v = stages.get("remote")
    if remote_v and "mixed remote/onsite" in (getattr(remote_v, "reason", "") or "").lower():
        return False
    location_v = stages.get("location")
    if location_v and "mixed us/non-us" in (getattr(location_v, "reason", "") or "").lower():
        return False
    return True


def scrape_jobs(
    config_path: Optional[Path] = None,
    config: Optional[ScraperConfig] = None,
    mark_seen: bool = True,
    fetch_jd: bool | None = None,
    crawl: bool = True,
    respect_runtime_controls: bool = True,
    llm_enabled_override: bool | None = None,
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

    if respect_runtime_controls:
        controls = load_runtime_controls()
        if not controls.get("scrape_enabled", True):
            logger.info("Scrape skipped: disabled by runtime controls")
            return ScrapeRun(run_id=f"disabled-{uuid.uuid4().hex[:12]}")

        if config.llm_review.enabled and not controls.get("llm_enabled", True):
            logger.info("LLM review disabled by runtime controls")
            config = config.model_copy(deep=True)
            config.llm_review.enabled = False

    if llm_enabled_override is not None:
        logger.info("LLM review override applied: %s", llm_enabled_override)
        config = config.model_copy(deep=True)
        config.llm_review.enabled = bool(llm_enabled_override)

    should_fetch = fetch_jd if fetch_jd is not None else config.filter.fetch_jd
    logger.info(
        "Scrape config: fetch_jd=%s crawl=%s require_remote=%s require_us_location=%s target=%d-%d",
        should_fetch,
        crawl and config.crawl.enabled,
        config.filter.require_remote,
        config.filter.require_us_location,
        config.filter.target_min_results,
        config.filter.target_max_results,
    )
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
            in_run_urls: set[str] = set()
            for r in raw_results:
                canonical = canonicalize_job_url(r.url)
                if canonical in in_run_urls:
                    continue
                in_run_urls.add(canonical)
                if not store.is_seen(canonical):
                    unseen.append(r)

            run.dedup_count = len(unseen)
            logger.info("%d new (unseen) results after dedup", run.dedup_count)

            # 3. Fetch JD + Filter
            rejected_items = []  # (SearchResult, stage, reason, verdicts)
            quarantine_items = []
            # (SearchResult, score, decision, signals, verdicts, seniority, exp_years, salary, jd_text, cleaned_title)
            for r in unseen:
                jd_text = None
                if should_fetch:
                    jd_text = fetch_jd_text(r.url, max_chars=config.filter.jd_max_chars)

                cleaned_title = _clean_job_title(r.title)
                passed, verdicts, seniority, exp_years, salary, score, decision, signals = apply_filters(
                    title=cleaned_title,
                    url=r.url,
                    snippet=r.snippet,
                    jd_text=jd_text,
                    board=r.board,
                    config=config.filter,
                )

                if not passed:
                    failing = verdicts[-1]
                    if decision == "review":
                        quarantine_items.append(
                            (
                                r,
                                score,
                                decision,
                                signals,
                                verdicts,
                                seniority,
                                exp_years,
                                salary,
                                jd_text,
                                cleaned_title,
                            )
                        )
                    else:
                        rejected_items.append((r, failing.stage, failing.reason, verdicts))
                    continue

                # LLM common-sense review (after all rule-based stages)
                if config.llm_review.enabled:
                    lv = llm_review(cleaned_title, r.snippet, jd_text, config.llm_review)
                    verdicts.append(lv)
                    if not lv.passed:
                        logger.info("LLM rejected '%s': %s", r.title, lv.reason)
                        rejected_items.append((r, "llm_review", lv.reason, verdicts))
                        continue
                    logger.debug("LLM passed '%s': %s", r.title, lv.reason)

                job = JobResult(
                    title=cleaned_title,
                    url=r.url,
                    board=r.board,
                    seniority=seniority,
                    experience_years=exp_years,
                    salary_k=salary,
                    score=score,
                    decision=decision,
                    jd_text=jd_text,
                    snippet=r.snippet,
                    query=r.query,
                    filter_verdicts=verdicts,
                )
                run.jobs.append(job)

            # 3b. Promotion pass: when strict gates under-fill, promote top review candidates
            # through an LLM check to keep quality while meeting target output volume.
            promoted_count = 0
            if len(run.jobs) < config.filter.target_min_results and quarantine_items:
                needed = config.filter.target_min_results - len(run.jobs)
                kept_quarantine = []
                ordered = sorted(quarantine_items, key=lambda item: int(item[1]), reverse=True)
                for item in ordered:
                    (
                        r,
                        score,
                        decision,
                        signals,
                        verdicts,
                        seniority,
                        exp_years,
                        salary,
                        jd_text,
                        cleaned_title,
                    ) = item

                    if promoted_count >= needed or len(run.jobs) >= config.filter.target_max_results:
                        kept_quarantine.append(item)
                        continue
                    if score < config.filter.promotion_min_score:
                        kept_quarantine.append(item)
                        continue
                    if not _promotion_candidate_ok(verdicts):
                        kept_quarantine.append(item)
                        continue

                    promotion_verdicts = list(verdicts)
                    if config.llm_review.enabled:
                        lv = llm_review(cleaned_title, r.snippet, jd_text, config.llm_review)
                        promotion_verdicts.append(lv)
                        if not lv.passed:
                            rejected_items.append((r, "llm_review_promotion", lv.reason, promotion_verdicts))
                            continue

                    run.jobs.append(
                        JobResult(
                            title=cleaned_title,
                            url=r.url,
                            board=r.board,
                            seniority=seniority,
                            experience_years=exp_years,
                            salary_k=salary,
                            score=score,
                            decision=decision,
                            jd_text=jd_text,
                            snippet=r.snippet,
                            query=r.query,
                            filter_verdicts=promotion_verdicts,
                        )
                    )
                    promoted_count += 1

                quarantine_items = kept_quarantine
                if promoted_count:
                    logger.info(
                        "Promoted %d review candidates to meet minimum target (%d)",
                        promoted_count,
                        config.filter.target_min_results,
                    )

            run.jobs, semantic_deduped_out = _dedupe_semantic_jobs(run.jobs)
            run.jobs, canonical_deduped_out = _dedupe_canonical_jobs(run.jobs)
            deduped_out = semantic_deduped_out + canonical_deduped_out
            overflow_dropped: list[JobResult] = []
            if len(run.jobs) > config.filter.target_max_results:
                run.jobs = sorted(run.jobs, key=_result_rank_key, reverse=True)
                overflow_dropped = run.jobs[config.filter.target_max_results:]
                run.jobs = run.jobs[: config.filter.target_max_results]
                deduped_out += overflow_dropped
                logger.info(
                    "Trimmed %d accepted jobs to target_max=%d",
                    len(overflow_dropped),
                    config.filter.target_max_results,
                )
            run.filtered_count = len(run.jobs)
            if semantic_deduped_out:
                logger.info(
                    "Collapsed %d semantic duplicate jobs before final output",
                    len(semantic_deduped_out),
                )
            if canonical_deduped_out:
                logger.info(
                    "Collapsed %d canonical URL duplicate jobs before final output",
                    len(canonical_deduped_out),
                )
            logger.info(
                "%d jobs passed filters, %d rejected, %d quarantined(review)",
                run.filtered_count, len(rejected_items), len(quarantine_items)
            )

            # 4. Mark ALL discovered URLs as seen (not just passing ones)
            #    This prevents re-processing rejected URLs every run.
            if mark_seen:
                seen_marked = 0
                for r in unseen:
                    store.mark_seen(r.url)
                    seen_marked += 1
                inserted = store.save_results(run.jobs, run_id)
                store.save_rejected_batch(rejected_items, run_id)
                quarantine_for_store = [
                    (r, score, decision, signals, verdicts)
                    for (
                        r,
                        score,
                        decision,
                        signals,
                        verdicts,
                        _seniority,
                        _exp_years,
                        _salary,
                        _jd_text,
                        _cleaned_title,
                    ) in quarantine_items
                ]
                store.save_quarantine_batch(quarantine_for_store, run_id)
                logger.info(
                    "Persisted %d/%d results, %d rejections, %d quarantine rows, marked %d URLs seen",
                    inserted, len(run.jobs), len(rejected_items), len(quarantine_for_store), seen_marked,
                )
                if inserted != len(run.jobs):
                    logger.warning(
                        "Result persistence discrepancy resolved by dedup: %d accepted in memory, %d inserted",
                        len(run.jobs), inserted,
                    )

            store.finish_run(
                run_id, raw=run.raw_count, dedup=run.dedup_count,
                filtered=run.filtered_count, errors=run.errors,
            )
        except Exception as exc:
            store.fail_run(run_id, str(exc))
            raise

    return run
