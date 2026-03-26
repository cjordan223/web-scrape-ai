"""Tests for config loader."""

import os
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


def test_title_keywords_loaded():
    cfg = load_config()
    assert len(cfg.hard_filters.title_keywords) > 0
    assert "security" in cfg.hard_filters.title_keywords


def test_remoteok_config_loaded():
    cfg = load_config()
    assert cfg.remoteok is not None
    assert cfg.remoteok.enabled is True
    assert len(cfg.remoteok.tag_filter) > 0


def test_hn_hiring_config_loaded():
    cfg = load_config()
    assert cfg.hn_hiring is not None
    assert cfg.hn_hiring.enabled is True
    assert cfg.hn_hiring.max_comments > 0


def test_linkedin_queries_present():
    cfg = load_config()
    linkedin_queries = [q for q in cfg.queries if "linkedin.com" in q.board_site]
    assert len(linkedin_queries) >= 10


def test_dotenv_loads_env_file(tmp_path, monkeypatch):
    """settings.py should load .env via python-dotenv."""
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_DOTENV_VAR=hello_from_dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TEST_DOTENV_VAR", raising=False)
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_file)
    assert os.environ.get("TEST_DOTENV_VAR") == "hello_from_dotenv"
