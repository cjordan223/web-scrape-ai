import json
from unittest.mock import patch
from scrapy.http import TextResponse, Request
from job_scraper.spiders.searxng import SearXNGSpider
from job_scraper.config import SearXNGQuery

def _fake_json_response(url, data):
    return TextResponse(url=url, request=Request(url=url), body=json.dumps(data).encode(), encoding="utf-8")

def test_parses_searxng_results():
    spider = SearXNGSpider()
    spider._domain_blocklist = set()
    data = {"results": [{"url": "https://jobs.ashbyhq.com/testco/abc123", "title": "Security Engineer", "content": "Great role..."}]}
    response = _fake_json_response("http://localhost:8888/search?q=test&format=json", data)
    response.meta["query_phrase"] = "security engineer"
    results = list(spider.parse_results(response))
    assert len(results) >= 1  # Should yield follow-up requests

def test_time_range_rotates_by_hour():
    spider = SearXNGSpider()
    spider._searxng_url = "http://localhost:8888/search"
    spider._queries = [SearXNGQuery(title_phrase="test engineer", board_site="", suffix="remote")]
    spider._domain_blocklist = set()

    # Even hour -> "day"
    with patch("job_scraper.spiders.searxng.datetime") as mock_dt:
        mock_now = mock_dt.now.return_value
        mock_now.hour = 10
        mock_now.isoformat.return_value = "2026-03-25T10:00:00"
        mock_dt.now.return_value = mock_now
        requests = list(spider.start_requests())
        assert len(requests) == 1
        assert "time_range=day" in requests[0].url

    # Odd hour -> "week"
    with patch("job_scraper.spiders.searxng.datetime") as mock_dt:
        mock_now = mock_dt.now.return_value
        mock_now.hour = 11
        mock_now.isoformat.return_value = "2026-03-25T11:00:00"
        mock_dt.now.return_value = mock_now
        requests = list(spider.start_requests())
        assert "time_range=week" in requests[0].url


def test_skips_blocklisted_urls():
    spider = SearXNGSpider()
    spider._domain_blocklist = {"wikipedia.org"}
    data = {"results": [{"url": "https://en.wikipedia.org/wiki/Security", "title": "Security", "content": "..."}]}
    response = _fake_json_response("http://localhost:8888/search?q=test&format=json", data)
    response.meta["query_phrase"] = "test"
    results = list(spider.parse_results(response))
    assert len(results) == 0
