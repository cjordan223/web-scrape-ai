from job_scraper.spiders import title_matches


def test_matches_security_engineer():
    assert title_matches("Security Engineer") is True


def test_matches_cloud_in_title():
    assert title_matches("Cloud Infrastructure Lead") is True


def test_matches_platform_engineer():
    assert title_matches("Platform Engineer - Remote") is True


def test_rejects_sales_title():
    assert title_matches("Account Executive") is False


def test_rejects_marketing_title():
    assert title_matches("Marketing Manager") is False


def test_rejects_hr_title():
    assert title_matches("People Operations Coordinator") is False


def test_case_insensitive():
    assert title_matches("SECURITY ENGINEER") is True
    assert title_matches("devops engineer") is True


def test_matches_sre():
    assert title_matches("Site Reliability Engineer") is True


def test_matches_ai_engineer():
    assert title_matches("AI Engineer") is True
