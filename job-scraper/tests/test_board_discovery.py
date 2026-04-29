from job_scraper.board_discovery import canonical_board_url


def test_canonical_board_url_for_greenhouse_job():
    assert canonical_board_url(
        "https://job-boards.greenhouse.io/acme/jobs/1234567",
        "greenhouse",
    ) == "https://job-boards.greenhouse.io/acme"


def test_canonical_board_url_for_lever_job():
    assert canonical_board_url(
        "https://jobs.lever.co/acme/abc-123/apply",
        "lever",
    ) == "https://jobs.lever.co/acme"


def test_canonical_board_url_for_ashby_job():
    assert canonical_board_url(
        "https://jobs.ashbyhq.com/acme/abc-123",
        "ashby",
    ) == "https://jobs.ashbyhq.com/acme"


def test_canonical_board_url_for_workday_job():
    assert canonical_board_url(
        "https://example.wd5.myworkdayjobs.com/example/job/US/Engineer_JR123",
        "workday",
    ) == "https://example.wd5.myworkdayjobs.com/example"
