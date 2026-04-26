import json
from pathlib import Path

from scrapy.http import TextResponse, Request

from job_scraper.spiders.lever import LeverSpider


def test_lever_json_path_yields_item():
    spider = LeverSpider()
    fixture = json.loads((Path(__file__).parent / "fixtures" / "lever_sample.json").read_text())
    url = "https://api.lever.co/v0/postings/acmeco?mode=json"
    response = TextResponse(
        url=url,
        request=Request(url=url),
        body=json.dumps(fixture).encode(),
        encoding="utf-8",
    )
    response.meta["company"] = "acmeco"
    items = list(spider.parse_board_json(response))
    assert len(items) == 1
    item = items[0]
    assert item["board"] == "lever"
    assert item["company"] == "acmeco"
    assert "Remote" in item["location"]
    assert item["salary_k"] == 150.0
