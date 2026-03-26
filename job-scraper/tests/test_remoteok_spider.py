import json
from scrapy.http import TextResponse, Request
from job_scraper.spiders.remoteok import RemoteOKSpider
from job_scraper.items import JobItem


def _fake_json_response(url, data):
    return TextResponse(url=url, request=Request(url=url), body=json.dumps(data).encode(), encoding="utf-8")


def test_parses_remoteok_api():
    spider = RemoteOKSpider(tag_filter=["security", "engineer"])
    data = [
        {"legal": "RemoteOK API"},
        {
            "id": "12345",
            "position": "Security Engineer",
            "company": "Acme Corp",
            "description": "<p>We are looking for a security engineer to join our team.</p>",
            "tags": ["security", "engineer"],
            "url": "https://remoteok.com/remote-jobs/12345",
            "salary_min": 120000,
            "salary_max": 180000,
            "location": "Remote",
        },
    ]
    response = _fake_json_response("https://remoteok.com/api", data)
    items = list(spider.parse_api(response))
    assert len(items) == 1
    assert isinstance(items[0], JobItem)
    assert items[0]["board"] == "remoteok"
    assert items[0]["title"] == "Security Engineer"
    assert items[0]["company"] == "Acme Corp"
    assert "120000" in items[0]["salary_text"]


def test_filters_by_tags():
    spider = RemoteOKSpider(tag_filter=["security"])
    data = [
        {"legal": "metadata"},
        {
            "id": "111",
            "position": "Marketing Manager",
            "company": "Foo",
            "description": "<p>Marketing role</p>",
            "tags": ["marketing", "manager"],
            "url": "https://remoteok.com/remote-jobs/111",
            "location": "Remote",
        },
        {
            "id": "222",
            "position": "Security Analyst",
            "company": "Bar",
            "description": "<p>Security role</p>",
            "tags": ["security", "analyst"],
            "url": "https://remoteok.com/remote-jobs/222",
            "location": "Remote",
        },
    ]
    response = _fake_json_response("https://remoteok.com/api", data)
    items = list(spider.parse_api(response))
    assert len(items) == 1
    assert items[0]["title"] == "Security Analyst"


def test_handles_empty_api_response():
    spider = RemoteOKSpider(tag_filter=["security"])
    data = [{"legal": "metadata"}]
    response = _fake_json_response("https://remoteok.com/api", data)
    items = list(spider.parse_api(response))
    assert len(items) == 0
