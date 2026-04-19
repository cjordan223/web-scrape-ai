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
    tiers: Optional[str] = typer.Option(None, "--tiers", help="Comma-separated tiers (workhorse,discovery,lead)"),
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


if __name__ == "__main__":
    app()
