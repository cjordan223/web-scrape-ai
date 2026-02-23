"""CLI: python -m job_scraper"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import scrape_jobs
from .dedup import JobStore

app = typer.Typer(help="Security job scraper powered by SearXNG")
console = Console()


@app.command()
def scrape(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to YAML config override"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write JSON output to file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Don't mark jobs as seen or persist results"),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="Skip JD fetching (faster, title filters only)"),
    no_crawl: bool = typer.Option(False, "--no-crawl", help="Skip Crawl4AI board crawling (SearXNG only)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
):
    """Run a full scrape cycle."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    run = scrape_jobs(
        config_path=config,
        mark_seen=not dry_run,
        fetch_jd=False if no_fetch else None,
        crawl=not no_crawl,
    )

    # Summary table (include accumulated totals)
    with JobStore() as store:
        total_results = store.result_count()
        total_seen = store.seen_count()

    table = Table(title=f"Scrape Run {run.run_id}")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Raw results", str(run.raw_count))
    table.add_row("After dedup", str(run.dedup_count))
    table.add_row("Passed filters", str(run.filtered_count))
    table.add_row("───────────────", "─────")
    table.add_row("Total accumulated", str(total_results))
    table.add_row("Total URLs seen", str(total_seen))
    if run.errors:
        table.add_row("Errors", str(len(run.errors)))
    console.print(table)

    # Job list
    if run.jobs:
        jobs_table = Table(title="Matching Jobs")
        jobs_table.add_column("#", justify="right", style="dim")
        jobs_table.add_column("Title")
        jobs_table.add_column("Board")
        jobs_table.add_column("Seniority")
        jobs_table.add_column("URL", style="cyan")

        for i, job in enumerate(run.jobs, 1):
            jobs_table.add_row(
                str(i),
                job.title[:60],
                job.board.value,
                job.seniority.value,
                job.url[:80],
            )
        console.print(jobs_table)

    # Output JSON
    if output:
        json_str = run.model_dump_json(indent=2)
        output.write_text(json_str)
        console.print(f"\nJSON written to [bold]{output}[/bold]")


@app.command()
def stats():
    """Show accumulated results and dedup stats."""
    with JobStore() as store:
        total_results = store.result_count()
        total_seen = store.seen_count()
        db_path = store.db_path

    table = Table(title="Job Store")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Passing jobs stored", str(total_results))
    table.add_row("Total URLs seen", str(total_seen))
    table.add_row("Database", str(db_path))
    console.print(table)


@app.command()
def recent(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of recent results to show"),
):
    """Show recently discovered jobs."""
    with JobStore() as store:
        rows = store.recent_results(limit)

    if not rows:
        console.print("No results yet.")
        return

    table = Table(title=f"Last {len(rows)} Jobs")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Title")
    table.add_column("Board")
    table.add_column("Seniority")
    table.add_column("Run")
    table.add_column("URL", style="cyan")

    for i, row in enumerate(rows, 1):
        table.add_row(
            str(i),
            (row["title"] or "")[:55],
            row["board"] or "",
            row["seniority"] or "",
            row["run_id"] or "",
            (row["url"] or "")[:70],
        )
    console.print(table)


if __name__ == "__main__":
    app()
