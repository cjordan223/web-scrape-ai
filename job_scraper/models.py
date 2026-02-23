"""Data models for job scraper."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Seniority(str, Enum):
    junior = "junior"
    mid = "mid"
    senior = "senior"
    staff = "staff"
    principal = "principal"
    lead = "lead"
    manager = "manager"
    director = "director"
    unknown = "unknown"


class JobBoard(str, Enum):
    greenhouse = "greenhouse"
    lever = "lever"
    ashby = "ashby"
    workday = "workday"
    bamboohr = "bamboohr"
    icims = "icims"
    smartrecruiters = "smartrecruiters"
    jobvite = "jobvite"
    unknown = "unknown"


class SearchResult(BaseModel):
    """Raw result from a SearXNG query."""

    title: str
    url: str
    snippet: str = ""
    query: str = ""
    board: JobBoard = JobBoard.unknown


class FilterVerdict(BaseModel):
    """Auditable pass/fail for a single filter stage."""

    stage: str
    passed: bool
    reason: str = ""


class JobResult(BaseModel):
    """A validated job posting that passed all filters."""

    title: str
    url: str
    board: JobBoard = JobBoard.unknown
    seniority: Seniority = Seniority.unknown
    experience_years: Optional[int] = None
    jd_text: Optional[str] = None
    snippet: str = ""
    query: str = ""
    filter_verdicts: list[FilterVerdict] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScrapeRun(BaseModel):
    """Top-level output of a scrape cycle."""

    run_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_count: int = 0
    dedup_count: int = 0
    filtered_count: int = 0
    jobs: list[JobResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
