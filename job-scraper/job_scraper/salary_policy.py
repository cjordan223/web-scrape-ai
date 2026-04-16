"""Shared salary policy helpers for scraper and QA."""

from __future__ import annotations

from dataclasses import dataclass
import re

_SALARY_PATTERN = re.compile(r"\$\s*([\d,]+)")


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
    matches = _SALARY_PATTERN.findall(text or "")
    if not matches:
        return None
    values: list[int] = []
    for match in matches:
        try:
            value = int(match.replace(",", ""))
        except ValueError:
            continue
        if 20_000 <= value <= 500_000:
            values.append(value // 1000)
    return min(values) if values else None


def evaluate_salary_policy(
    *,
    min_salary_k: int,
    target_salary_k: int,
    salary_text: str = "",
    salary_k: object = None,
) -> SalaryPolicyVerdict:
    parsed_salary_k = _coerce_salary_k(salary_k)
    if parsed_salary_k is None:
        parsed_salary_k = parse_salary_text_k(salary_text)
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
