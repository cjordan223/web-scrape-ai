import json
from pathlib import Path

from scrapy.http import TextResponse, Request

from job_scraper.spiders.ashby import AshbySpider


def test_ashby_json_path_yields_item():
    spider = AshbySpider()
    fixture = json.loads((Path(__file__).parent / "fixtures" / "ashby_sample.json").read_text())
    url = "https://api.ashbyhq.com/posting-api/job-board/acmeco?includeCompensation=true"
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
    assert item["board"] == "ashby"
    assert item["company"] == "acmeco"
    assert item["title"] == "Security Engineer"
    assert "Remote" in item["location"]
    assert item["salary_k"] is not None
    assert "$160,000" in item["salary_text"]
