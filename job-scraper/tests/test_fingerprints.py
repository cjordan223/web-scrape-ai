from job_scraper.fingerprints import (
    build_fingerprint_data,
    canonicalize_url,
    extract_ats_identity,
    extract_embedded_ats_identity,
    normalize_company,
    normalize_title,
)


def test_canonicalize_url_strips_tracking_and_normalizes_host():
    url = "HTTPS://WWW.Example.com/jobs/123/?utm_source=x&ref=abc&keep=1#section"
    assert canonicalize_url(url) == "https://example.com/jobs/123?keep=1"


def test_normalizes_company_suffixes_and_title_location_tags():
    assert normalize_company("Acme Security, Inc.") == "acme-security"
    assert normalize_title("Sr. Cloud Security Engineer - Remote US") == "senior-cloud-security-engineer"


def test_build_fingerprint_data_uses_composite_fields():
    fp = build_fingerprint_data({
        "url": "https://jobs.lever.co/acme/abc-123?utm_medium=x",
        "board": "lever",
        "title": "Senior Cloud Security Engineer (Remote US)",
        "company": "Acme Security LLC",
        "location": "Remote, United States",
        "salary_k": 180,
        "jd_text": "Remote role for candidates in the United States.",
    })
    assert fp.canonical_url == "https://jobs.lever.co/acme/abc-123"
    assert fp.ats_provider == "lever"
    assert fp.ats_job_id == "abc-123"
    assert fp.fingerprint == "acme-security|senior-cloud-security-engineer|us-remote|true|160k-200k"
    assert fp.content_hash


def test_extract_ats_identity_uses_greenhouse_query_id_before_stripping_tracking():
    provider, job_id = extract_ats_identity(
        "https://boards.greenhouse.io/acme/jobs/engineering?gh_jid=1234567&utm_source=search",
        "greenhouse",
    )
    assert provider == "greenhouse"
    assert job_id == "1234567"


def test_extract_embedded_ats_identity_from_aggregator_html():
    url, provider, job_id = extract_embedded_ats_identity(
        '<a data-apply-url="https://jobs.lever.co/acme/abc-123?lever-source=mirror">Apply</a>'
    )
    assert url == "https://jobs.lever.co/acme/abc-123"
    assert provider == "lever"
    assert job_id == "abc-123"


def test_build_fingerprint_prefers_embedded_ats_identity_for_mirror_page():
    fp = build_fingerprint_data({
        "url": "https://example-aggregator.test/jobs/acme-security-engineer",
        "board": "simplyhired",
        "title": "Senior Cloud Security Engineer",
        "company": "Acme Security",
        "location": "Remote, United States",
        "jd_text": "Remote role for candidates in the United States.",
        "jd_html": '<a href="https://job-boards.greenhouse.io/acme/jobs/7654321?gh_src=abc">Apply</a>',
    })
    assert fp.canonical_url == "https://job-boards.greenhouse.io/acme/jobs/7654321"
    assert fp.ats_provider == "greenhouse"
    assert fp.ats_job_id == "7654321"
