import json
from scrapy.http import TextResponse, Request
from job_scraper.spiders.hn_hiring import HNHiringSpider, parse_hn_comment
from job_scraper.items import JobItem


def _fake_json_response(url, data):
    return TextResponse(url=url, request=Request(url=url), body=json.dumps(data).encode(), encoding="utf-8")


def test_parse_hn_comment_pipe_format():
    text = "Acme Corp | Security Engineer | Remote (US) | $150k-$200k | https://acme.com/jobs/123"
    result = parse_hn_comment(text)
    assert result["company"] == "Acme Corp"
    assert result["title"] == "Security Engineer"
    assert result["location"] == "Remote (US)"
    assert result["url"] == "https://acme.com/jobs/123"


def test_parse_hn_comment_no_url():
    text = "BigCo | Platform Engineer | San Francisco | $180k"
    result = parse_hn_comment(text)
    assert result["company"] == "BigCo"
    assert result["title"] == "Platform Engineer"
    assert result["url"] is None


def test_parse_hn_comment_minimal():
    text = "We're hiring engineers at StartupXYZ. Check out https://startupxyz.com/careers"
    result = parse_hn_comment(text)
    assert result["url"] == "https://startupxyz.com/careers"


def test_parses_thread_kids():
    spider = HNHiringSpider(max_comments=500)
    thread_data = {
        "id": 47219668,
        "kids": [100, 200, 300],
        "title": "Ask HN: Who is hiring? (March 2026)",
    }
    response = _fake_json_response("https://hacker-news.firebaseio.com/v0/item/47219668.json", thread_data)
    requests = list(spider.parse_thread(response))
    assert len(requests) == 3
    assert "item/100.json" in requests[0].url


def test_parses_comment_into_job_item():
    spider = HNHiringSpider(max_comments=500)
    comment_data = {
        "id": 100,
        "text": "Acme Corp | Cloud Security Engineer | Remote | $160k-$200k | https://acme.com/apply",
        "by": "acme_recruiter",
    }
    response = _fake_json_response("https://hacker-news.firebaseio.com/v0/item/100.json", comment_data)
    results = list(spider.parse_comment(response))
    assert len(results) >= 1


def test_skips_deleted_comment():
    spider = HNHiringSpider(max_comments=500)
    comment_data = {"id": 100, "deleted": True}
    response = _fake_json_response("https://hacker-news.firebaseio.com/v0/item/100.json", comment_data)
    results = list(spider.parse_comment(response))
    assert len(results) == 0
