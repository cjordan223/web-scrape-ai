"""CLI for the tailoring engine.

Usage:
    python -m tailor select              # browse recent jobs
    python -m tailor run --job-id 42     # full pipeline
    python -m tailor run --job-id 42 --skip-analysis  # reuse cached analysis
    python -m tailor validate <output_dir>
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import typer

from . import config as cfg
from .selector import list_recent_jobs, select_job
from .metrics import compute_metrics
from .tracing import TraceRecorder, utc_now_iso

app = typer.Typer(help="Job tailoring engine — turn JDs into targeted application materials.")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tailor")


def _allocate_output_dir(base_dir: Path) -> Path:
    """Return a new output directory without clobbering prior runs."""
    if not base_dir.exists():
        base_dir.mkdir(parents=True, exist_ok=False)
        return base_dir

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = base_dir.parent / f"{base_dir.name}-{stamp}"
    n = 1
    while candidate.exists():
        candidate = base_dir.parent / f"{base_dir.name}-{stamp}-{n}"
        n += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _build_validator_retry_feedback(
    result,
    *,
    prior: dict[str, object] | None = None,
) -> dict[str, object]:
    """Preserve readable summaries while passing structured validator diagnostics forward.

    Accumulates `cumulative_banned_phrases` across attempts so a phrase that
    was flagged once stays banned even after a later regen fixes it but
    introduces a different violation.
    """
    banned: list[str] = []
    if prior:
        prior_banned = prior.get("cumulative_banned_phrases") or []
        if isinstance(prior_banned, list):
            for phrase in prior_banned:
                if isinstance(phrase, str) and phrase and phrase not in banned:
                    banned.append(phrase)

    for detail in result.failure_details or []:
        phrase = detail.get("matched_text") if isinstance(detail, dict) else None
        if isinstance(phrase, str) and phrase and phrase not in banned:
            banned.append(phrase)

    return {
        "source": "validator",
        "summary": str(result),
        "failures": list(result.failures),
        "failure_details": list(result.failure_details),
        "cumulative_banned_phrases": banned,
    }


def _build_exception_retry_feedback(
    exc: Exception,
    *,
    prior: dict[str, object] | None = None,
) -> dict[str, object]:
    banned: list[str] = []
    if prior:
        prior_banned = prior.get("cumulative_banned_phrases") or []
        if isinstance(prior_banned, list):
            banned = [p for p in prior_banned if isinstance(p, str) and p]
    return {
        "source": "exception",
        "summary": str(exc),
        "error": str(exc),
        "cumulative_banned_phrases": banned,
    }


@app.command()
def select(limit: int = typer.Option(20, help="Number of recent jobs to show")):
    """Browse recent jobs and pick one to tailor."""
    jobs = list_recent_jobs(limit)
    if not jobs:
        typer.echo("No QA-approved jobs found in database.")
        raise typer.Exit(1)

    typer.echo(f"\n{'ID':>5}  {'Board':<14} {'Seniority':<10} Title")
    typer.echo("─" * 80)
    for j in jobs:
        typer.echo(
            f"{j['id']:>5}  {(j['board'] or '?'):<14} "
            f"{(j['seniority'] or '?'):<10} {j['title'][:50]}"
        )
    typer.echo(f"\nUse: python -m tailor run --job-id <ID>")


@app.command()
def run(
    job_id: int = typer.Option(..., "--job-id", "-j", help="Job ID from the results table"),
    skip_analysis: bool = typer.Option(False, "--skip-analysis", help="Reuse cached analysis.json"),
):
    """Run the full tailoring pipeline for a job."""
    from .analyzer import analyze_job, load_cached_analysis
    from .grounding import clear_grounding_cache
    from .writer import write_resume, write_cover_letter
    from .validator import validate_resume, validate_cover_letter

    clear_grounding_cache()
    cfg.clear_file_cache()

    # Select job
    try:
        job = select_job(job_id)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    typer.echo(f"\nTailoring for: {job.title}")
    typer.echo(f"Company: {job.company}")
    typer.echo(f"URL: {job.url}")

    output_dir = _allocate_output_dir(cfg.OUTPUT_DIR / job.slug)
    typer.echo(f"Output: {output_dir}\n")
    trace_recorder = TraceRecorder(
        output_dir,
        run_context={
            "run_slug": output_dir.name,
            "job_slug": job.slug,
            "job_id": job.id,
            "job_title": job.title,
        },
    )

    # Save job metadata
    run_started_at = utc_now_iso()
    meta = {
        "job_id": job.id, "url": job.url, "title": job.title,
        "company": job.company, "board": job.board,
        "job_slug": job.slug, "run_slug": output_dir.name,
        "run_started_at": run_started_at,
    }
    (output_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # Step 1: Analyze
    trace_recorder.phase_start("analysis")
    if skip_analysis:
        analysis = load_cached_analysis(job, output_dir)
        if analysis is not None:
            typer.echo("→ Using cached analysis")
        else:
            typer.echo("→ Cached analysis missing/stale, regenerating...")
            analysis = analyze_job(job, output_dir, trace_recorder=trace_recorder.record)
    else:
        typer.echo("→ Analyzing JD against skills inventory...")
        analysis = analyze_job(job, output_dir, trace_recorder=trace_recorder.record)
    trace_recorder.phase_end("analysis")
    typer.echo(f"  Mapped {len(analysis.get('requirements', []))} requirements")
    typer.echo(f"  Company: {analysis.get('company_name', '?')}")
    typer.echo(f"  Role: {analysis.get('role_title', '?')}\n")

    # Step 2+3: Write + Validate (with retries)
    def _generate_doc(doc_name, writer_fn, validator_fn):
        """Run the write+validate loop for a single document. Returns (doc_name, passed)."""
        doc_type = "resume" if doc_name == "Resume" else "cover"
        typer.echo(f"→ Generating {doc_name}...")
        trace_recorder.phase_start(doc_type)
        previous_feedback = None
        doc_passed = False
        for attempt in range(1, cfg.MAX_RETRIES + 1):
            try:
                tex_path = writer_fn(
                    job,
                    analysis,
                    output_dir,
                    previous_feedback=previous_feedback,
                    attempt=attempt,
                    trace_recorder=trace_recorder.record,
                )
                typer.echo(f"  Validating {doc_name} (attempt {attempt}/{cfg.MAX_RETRIES})...")
                existing_pdf = tex_path.with_suffix(".pdf")
                result = validator_fn(tex_path, pdf_path=existing_pdf)
                trace_recorder.record(
                    {
                        "event_type": "validation_result",
                        "doc_type": doc_type,
                        "phase": "qa",
                        "attempt": attempt,
                        "passed": result.passed,
                        "failures": result.failures,
                        "failure_details": result.failure_details,
                        "metrics": result.metrics,
                        "timestamp": utc_now_iso(),
                    }
                )
                if result.passed:
                    typer.echo(f"  ✓ {doc_name} passed all gates")
                    doc_passed = True
                    trace_recorder.record(
                        {
                            "event_type": "doc_attempt_result",
                            "doc_type": doc_type,
                            "phase": "qa",
                            "attempt": attempt,
                            "status": "passed",
                            "error": None,
                            "timestamp": utc_now_iso(),
                        }
                    )
                    break
                else:
                    typer.echo(f"  ✗ {doc_name} failed: {result}")
                    previous_feedback = _build_validator_retry_feedback(
                        result, prior=previous_feedback
                    )
                    trace_recorder.record(
                        {
                            "event_type": "doc_attempt_result",
                            "doc_type": doc_type,
                            "phase": "qa",
                            "attempt": attempt,
                            "status": "failed",
                            "error": previous_feedback["summary"],
                            "timestamp": utc_now_iso(),
                        }
                    )
                    if attempt < cfg.MAX_RETRIES:
                        typer.echo(f"  Regenerating {doc_name} with feedback...")
            except Exception as e:
                typer.echo(f"  {doc_name} error: {e}")
                previous_feedback = _build_exception_retry_feedback(
                    e, prior=previous_feedback
                )
                trace_recorder.record(
                    {
                        "event_type": "doc_attempt_result",
                        "doc_type": doc_type,
                        "phase": "qa",
                        "attempt": attempt,
                        "status": "error",
                        "error": previous_feedback["summary"],
                        "timestamp": utc_now_iso(),
                    }
                )
                if attempt == cfg.MAX_RETRIES:
                    typer.echo(f"  ✗ {doc_name} failed after {cfg.MAX_RETRIES} attempts")
        trace_recorder.phase_end(doc_type)
        return doc_name, doc_passed

    docs = [
        ("Resume", write_resume, validate_resume),
        ("Cover Letter", write_cover_letter, validate_cover_letter),
    ]

    # Parallelize resume + cover when file lock is disabled (cloud providers).
    # For local single-GPU providers the lock serializes LLM calls anyway,
    # so sequential execution avoids thread overhead and preserves the
    # resume_strategy.json dependency the cover letter reads.
    from .ollama import _use_file_lock
    use_parallel = not _use_file_lock()

    # Event signals when resume_strategy.json has been written (not when the
    # full resume is done), so the cover letter thread can start its own
    # strategy phase with cross-document consistency data available.
    resume_strategy_ready = threading.Event()

    def _generate_doc_parallel(doc_name, writer_fn, validator_fn):
        """Parallel-aware wrapper: resume signals strategy ready, cover waits for it."""
        if doc_name == "Resume":
            # Inject the callback so the event fires right after strategy is written
            _orig_fn = writer_fn
            def _resume_with_signal(job, analysis, output_dir, **kwargs):
                try:
                    return _orig_fn(job, analysis, output_dir, on_strategy_ready=resume_strategy_ready.set, **kwargs)
                finally:
                    # Ensure cover thread is never blocked if resume fails before strategy
                    resume_strategy_ready.set()
            return _generate_doc(doc_name, _resume_with_signal, validator_fn)
        else:
            # Cover waits for resume strategy to be available before starting
            resume_strategy_ready.wait(timeout=600)
            return _generate_doc(doc_name, writer_fn, validator_fn)

    failed_docs: list[str] = []
    if use_parallel:
        typer.echo("→ Cloud provider detected — generating resume and cover letter in parallel\n")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(_generate_doc_parallel, *doc): doc[0]
                for doc in docs
            }
            for future in as_completed(futures):
                doc_name, passed = future.result()
                if not passed:
                    failed_docs.append(doc_name)
                typer.echo()
    else:
        for doc in docs:
            doc_name, passed = _generate_doc(*doc)
            if not passed:
                failed_docs.append(doc_name)
            typer.echo()

    # Finalize metrics
    meta["run_finished_at"] = utc_now_iso()
    (output_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    try:
        compute_metrics(output_dir)
    except Exception as e:
        logger.warning("Failed to compute metrics: %s", e)

    typer.echo(f"Done. Output at: {output_dir}")
    if failed_docs:
        typer.echo(f"Run failed quality gates for: {', '.join(failed_docs)}")
        raise typer.Exit(1)


@app.command()
def validate(output_path: str = typer.Argument(..., help="Path to output directory")):
    """Validate existing .tex files against quality gates."""
    from .validator import validate_resume, validate_cover_letter

    d = Path(output_path)
    resume = d / "Conner_Jordan_Resume.tex"
    cover = d / "Conner_Jordan_Cover_Letter.tex"

    if resume.exists():
        result = validate_resume(resume)
        typer.echo(f"Resume: {result}")

    if cover.exists():
        result = validate_cover_letter(cover)
        typer.echo(f"Cover Letter: {result}")

    if not resume.exists() and not cover.exists():
        typer.echo(f"No .tex files found in {d}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
