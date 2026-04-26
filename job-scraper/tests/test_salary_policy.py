"""Unit tests for shared salary policy helpers."""

from __future__ import annotations

import pytest

from job_scraper.salary_policy import evaluate_salary_policy, parse_salary_text_k


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$60K – $70K", 70),
        ("$97K – $145K", 145),
        ("$90.1K – $181.5K", 181),
        ("CA$90K – CA$100K", 100),
        ("$25 – $40 per hour", 83),
        ("$36 per hour", 74),
        ("$11.7K per month", 140),
        ("$8K per month", 96),
        ("£42K – £60K", 60),
        ("$150 – $250,000", 250),
        ("$95K", 95),
        ("$86.4K – $228K", 228),
        ("", None),
        ("no money here", None),
    ],
)
def test_parse_salary_text_k(text, expected):
    assert parse_salary_text_k(text) == expected


def test_evaluate_uses_text_ceiling_over_stored_min():
    # Old data has stored salary_k = bottom-of-range (90); text reveals
    # ceiling of 145; verdict should accept on the ceiling.
    verdict = evaluate_salary_policy(
        min_salary_k=100,
        target_salary_k=150,
        salary_text="$90K – $145K",
        salary_k=90,
    )
    assert verdict.parsed_salary_k == 145
    assert verdict.hard_reject is False


def test_evaluate_rejects_when_ceiling_below_floor():
    verdict = evaluate_salary_policy(
        min_salary_k=100,
        target_salary_k=150,
        salary_text="$60K – $70K",
        salary_k=60,
    )
    assert verdict.hard_reject is True
    assert "below" in (verdict.reason or "")


def test_evaluate_no_signal_returns_soft_pass():
    verdict = evaluate_salary_policy(
        min_salary_k=100,
        target_salary_k=150,
        salary_text="",
        salary_k=None,
    )
    assert verdict.parsed_salary_k is None
    assert verdict.hard_reject is False
    assert verdict.meets_target is False
