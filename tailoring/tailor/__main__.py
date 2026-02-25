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
from pathlib import Path

import typer

from . import config as cfg
from .selector import list_recent_jobs, select_job
from .tracing import TraceRecorder, utc_now_iso

app = typer.Typer(help="Job tailoring engine — turn JDs into targeted application materials.")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tailor")


@app.command()
def select(limit: int = typer.Option(20, help="Number of recent jobs to show")):
    """Browse recent jobs and pick one to tailor."""
    jobs = list_recent_jobs(limit)
    if not jobs:
        typer.echo("No jobs found in database.")
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
    from .writer import write_resume, write_cover_letter
    from .validator import validate_resume, validate_cover_letter

    # Select job
    job = select_job(job_id)
    typer.echo(f"\nTailoring for: {job.title}")
    typer.echo(f"Company: {job.company}")
    typer.echo(f"URL: {job.url}")

    output_dir = cfg.OUTPUT_DIR / job.slug
    output_dir.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Output: {output_dir}\n")
    trace_recorder = TraceRecorder(
        output_dir,
        run_context={
            "run_slug": job.slug,
            "job_id": job.id,
            "job_title": job.title,
        },
    )

    # Save job metadata
    meta = {
        "job_id": job.id, "url": job.url, "title": job.title,
        "company": job.company, "board": job.board,
    }
    (output_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # Step 1: Analyze
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
    typer.echo(f"  Mapped {len(analysis.get('requirements', []))} requirements")
    typer.echo(f"  Company: {analysis.get('company_name', '?')}")
    typer.echo(f"  Role: {analysis.get('role_title', '?')}\n")

    # Step 2+3: Write + Validate (with retries)
    failed_docs: list[str] = []
    for doc_name, writer_fn, validator_fn in [
        ("Resume", write_resume, validate_resume),
        ("Cover Letter", write_cover_letter, validate_cover_letter),
    ]:
        doc_type = "resume" if doc_name == "Resume" else "cover"
        typer.echo(f"→ Generating {doc_name}...")
        previous_errors = None
        doc_passed = False
        for attempt in range(1, cfg.MAX_RETRIES + 1):
            try:
                tex_path = writer_fn(
                    job,
                    analysis,
                    output_dir,
                    previous_errors=previous_errors,
                    attempt=attempt,
                    trace_recorder=trace_recorder.record,
                )
                typer.echo(f"  Validating (attempt {attempt}/{cfg.MAX_RETRIES})...")
                result = validator_fn(tex_path)
                trace_recorder.record(
                    {
                        "event_type": "validation_result",
                        "doc_type": doc_type,
                        "phase": "qa",
                        "attempt": attempt,
                        "passed": result.passed,
                        "failures": result.failures,
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
                    previous_errors = str(result)
                    trace_recorder.record(
                        {
                            "event_type": "doc_attempt_result",
                            "doc_type": doc_type,
                            "phase": "qa",
                            "attempt": attempt,
                            "status": "failed",
                            "error": previous_errors,
                            "timestamp": utc_now_iso(),
                        }
                    )
                    if attempt < cfg.MAX_RETRIES:
                        typer.echo(f"  Regenerating with feedback...")
            except Exception as e:
                typer.echo(f"  Error: {e}")
                previous_errors = str(e)
                trace_recorder.record(
                    {
                        "event_type": "doc_attempt_result",
                        "doc_type": doc_type,
                        "phase": "qa",
                        "attempt": attempt,
                        "status": "error",
                        "error": previous_errors,
                        "timestamp": utc_now_iso(),
                    }
                )
                if attempt == cfg.MAX_RETRIES:
                    typer.echo(f"  ✗ {doc_name} failed after {cfg.MAX_RETRIES} attempts")
        if not doc_passed:
            failed_docs.append(doc_name)
        typer.echo()

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
