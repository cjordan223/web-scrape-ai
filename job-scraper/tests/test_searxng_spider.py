import json
from scrapy.http import TextResponse, Request
from job_scraper.spiders.searxng import SearXNGSpider

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

def test_skips_blocklisted_urls():
    spider = SearXNGSpider()
    spider._domain_blocklist = {"wikipedia.org"}
    data = {"results": [{"url": "https://en.wikipedia.org/wiki/Security", "title": "Security", "content": "..."}]}
    response = _fake_json_response("http://localhost:8888/search?q=test&format=json", data)
    response.meta["query_phrase"] = "test"
    results = list(spider.parse_results(response))
    assert len(results) == 0
