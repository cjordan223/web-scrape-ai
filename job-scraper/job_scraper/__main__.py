"""CLI: python -m job_scraper"""
from __future__ import annotations

import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .db import JobDB

app = typer.Typer(help="Job scraper powered by Scrapy")
console = Console()


@app.command()
def scrape(
    spider: Optional[str] = typer.Option(None, "--spider", "-s", help="Run only this spider (e.g. ashby, greenhouse)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    tiers: Optional[str] = typer.Option(None, "--tiers", help="Comma-separated tiers (workhorse,discovery)"),
    rotation_group: Optional[int] = typer.Option(None, "--rotation-group", help="Which rotation bucket to run this tick"),
    run_index: Optional[int] = typer.Option(None, "--run-index", help="Monotonic run counter (scheduler-supplied)"),
):
    """Run a full scrape cycle using Scrapy spiders."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    from . import scrape_all

    spiders = [spider] if spider else None
    tier_list = [t.strip() for t in tiers.split(",")] if tiers else None
    result = scrape_all(
        verbose=verbose,
        spiders=spiders,
        tiers=tier_list,
        rotation_group=rotation_group,
        run_index=run_index,
    )

    table = Table(title=f"Scrape Run {result['run_id']}")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Total jobs in DB", str(result["total_jobs"]))
    table.add_row("Pending", str(result["pending"]))
    table.add_row("Rejected", str(result["rejected"]))
    console.print(table)
    if result.get("status") == "failed":
        for error in result.get("errors") or ["scrape failed"]:
            console.print(f"[red]{error}[/red]")
        raise typer.Exit(1)


@app.command()
def stats():
    """Show accumulated results and dedup stats."""
    db = JobDB()
    table = Table(title="Job Store")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Total jobs", str(db.job_count()))
    table.add_row("Pending", str(db.job_count(status="pending")))
    table.add_row("Rejected", str(db.job_count(status="rejected")))
    table.add_row("Database", str(db._path))
    console.print(table)
    db.close()


@app.command()
def recent(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of recent results"),
):
    """Show recently discovered jobs."""
    db = JobDB()
    rows = db.recent_jobs(limit=limit)
    db.close()

    if not rows:
        console.print("No results yet.")
        return

    table = Table(title=f"Last {len(rows)} Jobs")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Title")
    table.add_column("Board")
    table.add_column("Status")
    table.add_column("URL", style="cyan")

    for i, row in enumerate(rows, 1):
        table.add_row(
            str(i),
            (row.get("title") or "")[:55],
            row.get("board") or "",
            row.get("status") or "",
            (row.get("url") or "")[:70],
        )
    console.print(table)


@app.command("backfill-fingerprints")
def backfill_fingerprints(
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Maximum jobs to backfill"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Classify without writing fingerprint rows"),
):
    """Backfill canonical fingerprint rows for existing jobs."""
    db = JobDB()
    try:
        result = db.backfill_job_fingerprints(limit=limit, dry_run=dry_run)
    finally:
        db.close()

    table = Table(title="Fingerprint Backfill")
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right")
    for status, count in sorted(result["counts"].items()):
        table.add_row(status, str(count))
    if not result["counts"]:
        table.add_row("(none)", "0")
    console.print(table)
    console.print(f"Processed {result['processed']} job(s){' (dry run)' if dry_run else ''}.")


@app.command("reclassify-fingerprints")
def reclassify_fingerprints(
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Maximum existing fingerprints to scan"),
    dry_run: bool = typer.Option(True, "--dry-run/--write", help="Preview by default; pass --write to update rows"),
):
    """Reclassify historical 'new' fingerprints as similar_posting where safe."""
    db = JobDB()
    try:
        result = db.reclassify_similar_fingerprints(limit=limit, dry_run=dry_run)
    finally:
        db.close()

    table = Table(title="Fingerprint Reclassification")
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right")
    for status, count in sorted(result["counts"].items()):
        table.add_row(status, str(count))
    console.print(table)
    console.print(f"Processed {result['processed']} fingerprint(s){' (dry run)' if dry_run else ''}.")

    samples = result.get("samples") or []
    if samples:
        sample_table = Table(title="Sample Matches")
        sample_table.add_column("Job", justify="right")
        sample_table.add_column("Title")
        sample_table.add_column("Matched Job", justify="right")
        sample_table.add_column("Matched Title")
        for sample in samples[:10]:
            sample_table.add_row(
                str(sample.get("job_id") or ""),
                str(sample.get("title_norm") or "")[:50],
                str(sample.get("duplicate_of_job_id") or ""),
                str(sample.get("matched_title_norm") or "")[:50],
            )
        console.print(sample_table)


@app.command("discover-boards")
def discover_boards(
    limit: int = typer.Option(1000, "--limit", "-n", help="Recent jobs to inspect"),
    include_configured: bool = typer.Option(False, "--include-configured", help="Show boards already in config"),
):
    """Suggest direct ATS boards observed through discovery/search jobs."""
    from .board_discovery import discover_board_candidates

    candidates = discover_board_candidates(limit=limit, include_configured=include_configured)
    table = Table(title="Observed ATS Board Candidates")
    table.add_column("Board")
    table.add_column("Company")
    table.add_column("Observed", justify="right")
    table.add_column("Configured")
    table.add_column("Board URL", style="cyan")
    table.add_column("Latest Seen")
    for candidate in candidates:
        table.add_row(
            candidate.board_type,
            candidate.company,
            str(candidate.observed_jobs),
            "yes" if candidate.already_configured else "no",
            candidate.board_url,
            candidate.latest_seen_at[:19],
        )
    if not candidates:
        table.add_row("(none)", "", "0", "", "", "")
    console.print(table)


if __name__ == "__main__":
    app()
