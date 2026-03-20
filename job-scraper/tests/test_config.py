"""Tests for config loader."""

from pathlib import Path
from job_scraper.config import load_config, ScraperConfig


def test_load_default_config():
    cfg = load_config()
    assert isinstance(cfg, ScraperConfig)
    assert len(cfg.boards) > 0


def test_boards_have_required_fields():
    cfg = load_config()
    for board in cfg.boards:
        assert board.url
        assert board.board_type
        assert board.company


def test_hard_filters_loaded():
    cfg = load_config()
    assert len(cfg.hard_filters.domain_blocklist) > 0
    assert len(cfg.hard_filters.title_blocklist) > 0
    assert cfg.hard_filters.min_salary_k > 0


def test_searxng_optional():
    cfg = load_config()
    assert cfg.searxng is not None
