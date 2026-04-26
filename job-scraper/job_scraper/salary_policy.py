"""Shared salary policy helpers for scraper and QA."""

from __future__ import annotations

from dataclasses import dataclass
import re

_SALARY_TOKEN = re.compile(
    r"(?:US|CA|AU|NZ|GB|EU)?\s*[\$£€¥]\s*([\d,]+(?:\.\d+)?)\s*([KkMm]?)"
)
_HOURLY_HINTS = ("per hour", "/hr", "hourly", " an hour")
_MONTHLY_HINTS = ("per month", "/mo", "monthly", " a month")
_ANNUAL_HOURS = 2080
_ANNUAL_MONTHS = 12


@dataclass(frozen=True)
class SalaryPolicyVerdict:
    parsed_salary_k: int | None
    floor_k: int
    target_k: int
    hard_reject: bool
    meets_target: bool
    reason: str | None


def _coerce_salary_k(value: object) -> int | None:
    if value in (None, "", "null"):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    # Manual ingest stores thousands (e.g. 150). Some sources may store raw dollars.
    if numeric >= 20_000:
        return int(numeric // 1000)
    return int(numeric)


def parse_salary_text_k(text: str) -> int | None:
    """Return the top of a salary range expressed in annual thousands.

    Handles K/M suffixes, common currency symbols, and hourly/monthly rates
    (converted to annual at 2080 hrs/yr or 12 mo/yr). Returns the maximum
    value in the text so wide ranges with a qualifying ceiling are not
    rejected on their low end.
    """
    if not text:
        return None
    low = text.lower()
    if any(h in low for h in _HOURLY_HINTS):
        multiplier = _ANNUAL_HOURS
    elif any(h in low for h in _MONTHLY_HINTS):
        multiplier = _ANNUAL_MONTHS
    else:
        multiplier = 1
    candidates: list[float] = []
    for match in _SALARY_TOKEN.finditer(text):
        try:
            num = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        suffix = match.group(2)
        if suffix in ("K", "k"):
            dollars = num * 1_000
        elif suffix in ("M", "m"):
            dollars = num * 1_000_000
        else:
            dollars = num
        annual_k = (dollars * multiplier) / 1000
        if 20 <= annual_k <= 600:
            candidates.append(annual_k)
    if not candidates:
        return None
    return int(max(candidates))


def evaluate_salary_policy(
    *,
    min_salary_k: int,
    target_salary_k: int,
    salary_text: str = "",
    salary_k: object = None,
) -> SalaryPolicyVerdict:
    # Take the higher of stored salary_k and re-parsed salary_text. Stored
    # salary_k can be the bottom of a range when an upstream spider captured
    # the min; re-parsing the text recovers the true ceiling.
    coerced = _coerce_salary_k(salary_k)
    parsed_text = parse_salary_text_k(salary_text)
    candidates = [v for v in (coerced, parsed_text) if v is not None]
    parsed_salary_k = max(candidates) if candidates else None
    if parsed_salary_k is None:
        return SalaryPolicyVerdict(
            parsed_salary_k=None,
            floor_k=min_salary_k,
            target_k=target_salary_k,
            hard_reject=False,
            meets_target=False,
            reason=None,
        )
    if parsed_salary_k < min_salary_k:
        return SalaryPolicyVerdict(
            parsed_salary_k=parsed_salary_k,
            floor_k=min_salary_k,
            target_k=target_salary_k,
            hard_reject=True,
            meets_target=False,
            reason=f"Salary ${parsed_salary_k}k below ${min_salary_k}k floor",
        )
    return SalaryPolicyVerdict(
        parsed_salary_k=parsed_salary_k,
        floor_k=min_salary_k,
        target_k=target_salary_k,
        hard_reject=False,
        meets_target=parsed_salary_k >= target_salary_k,
        reason=None,
    )
