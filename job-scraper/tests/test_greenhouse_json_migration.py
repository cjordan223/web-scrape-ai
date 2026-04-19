import json
from pathlib import Path

from scrapy.http import TextResponse, Request

from job_scraper.spiders.greenhouse import GreenhouseSpider


def test_greenhouse_json_path_yields_item():
    spider = GreenhouseSpider()
    spider._use_json_api = True
    fixture = json.loads((Path(__file__).parent / "fixtures" / "greenhouse_sample.json").read_text())
    url = "https://boards-api.greenhouse.io/v1/boards/acmeco/jobs?content=true"
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
    assert item["board"] == "greenhouse"
    assert item["company"] == "acmeco"
    assert "Remote" in item["location"]
    assert "Join our platform team" in item["jd_html"]
