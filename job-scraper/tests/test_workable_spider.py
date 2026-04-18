import json
from pathlib import Path
from scrapy.http import TextResponse, Request
from job_scraper.spiders.workable import WorkableSpider


def _fake_response(url, data):
    return TextResponse(
        url=url,
        request=Request(url=url),
        body=json.dumps(data).encode(),
        encoding="utf-8",
    )


def test_parses_workable_jobs():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "workable_sample.json").read_text())
    spider = WorkableSpider()
    spider._targets = [{"url": "https://apply.workable.com/acmeco/", "company": "acmeco"}]
    response = _fake_response(
        "https://apply.workable.com/api/v3/accounts/acmeco/jobs", fixture,
    )
    response.meta["company"] = "acmeco"
    items = list(spider.parse_board(response))
    assert len(items) == 1
    item = items[0]
    assert item["company"] == "acmeco"
    assert item["board"] == "workable"
    assert item["title"] == "Senior Security Engineer"
    assert "workable" in item["url"]
