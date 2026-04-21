import json
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
    assert len(results) == 1
    assert results[0]["board"] == "ashby"
    assert results[0]["query"] == "security engineer"

def test_queries_are_batched_and_paginated():
    spider = SearXNGSpider()
    spider._searxng_url = "http://localhost:8888/search"
    spider._run_id = "run123"
    spider._queries = [
        SearXNGQuery(title_phrase=f"test engineer {i}", board_site="", suffix="remote")
        for i in range(25)
    ]
    spider._domain_blocklist = set()
    requests = list(spider.start_requests())
    assert len(requests) == 40
    assert all("pageno=" in request.url for request in requests)
    assert all("time_range=" in request.url for request in requests)
    seen_phrases = {request.meta["query_phrase"] for request in requests}
    assert len(seen_phrases) == 20


def test_skips_blocklisted_urls():
    spider = SearXNGSpider()
    spider._domain_blocklist = {"wikipedia.org"}
    data = {"results": [{"url": "https://en.wikipedia.org/wiki/Security", "title": "Security", "content": "..."}]}
    response = _fake_json_response("http://localhost:8888/search?q=test&format=json", data)
    response.meta["query_phrase"] = "test"
    results = list(spider.parse_results(response))
    assert len(results) == 0


def test_skips_low_signal_unknown_hosts():
    spider = SearXNGSpider()
    spider._domain_blocklist = set()
    data = {"results": [{"url": "https://www.indeed.com/q-security-engineer-jobs.html", "title": "Security Engineer Jobs", "content": "..." }]}
    response = _fake_json_response("http://localhost:8888/search?q=test&format=json", data)
    response.meta["query_phrase"] = "security engineer"
    results = list(spider.parse_results(response))
    assert results == []


def test_enforces_query_board_site_match():
    spider = SearXNGSpider()
    spider._domain_blocklist = set()
    data = {"results": [{"url": "https://www.linkedin.com/jobs/view/123", "title": "Security Engineer", "content": "Remote role"}]}
    response = _fake_json_response("http://localhost:8888/search?q=test&format=json", data)
    response.meta["query_phrase"] = "security engineer"
    response.meta["query_board_site"] = "boards.greenhouse.io"
    results = list(spider.parse_results(response))
    assert results == []


def test_accepts_trusted_workday_hosts():
    spider = SearXNGSpider()
    spider._domain_blocklist = set()
    data = {"results": [{"url": "https://example.wd1.myworkdaysite.com/en-US/recruiting/acme/job/123", "title": "Cloud Engineer", "content": "Remote USA role"}]}
    response = _fake_json_response("http://localhost:8888/search?q=test&format=json", data)
    response.meta["query_phrase"] = "cloud engineer"
    results = list(spider.parse_results(response))
    assert len(results) == 1
    assert results[0]["board"] == "workday"
