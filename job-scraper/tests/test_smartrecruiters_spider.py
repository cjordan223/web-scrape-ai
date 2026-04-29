import json
from pathlib import Path

from scrapy.http import Request, TextResponse

from job_scraper.spiders.smartrecruiters import SmartRecruitersSpider


def _response(url, data):
    return TextResponse(
        url=url,
        request=Request(url=url),
        body=json.dumps(data).encode(),
        encoding="utf-8",
    )


def test_board_json_schedules_detail_requests():
    spider = SmartRecruitersSpider()
    response = _response(
        "https://api.smartrecruiters.com/v1/companies/Nexthink/postings?limit=50",
        {
            "content": [
                {
                    "id": "744000123755755",
                    "name": "Senior Security Engineer",
                    "ref": "https://api.smartrecruiters.com/v1/companies/Nexthink/postings/744000123755755",
                }
            ]
        },
    )
    response.meta["company"] = "Nexthink"
    response.meta["company_identifier"] = "Nexthink"
    requests = list(spider.parse_board_json(response))
    assert len(requests) == 1
    assert requests[0].url.endswith("/postings/744000123755755")
    assert requests[0].meta["summary"]["name"] == "Senior Security Engineer"


def test_detail_json_yields_job_item():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "smartrecruiters_detail.json").read_text())
    spider = SmartRecruitersSpider()
    response = _response(
        "https://api.smartrecruiters.com/v1/companies/Nexthink/postings/744000123755755",
        fixture,
    )
    response.meta["company"] = "Nexthink"
    response.meta["company_identifier"] = "Nexthink"
    item = list(spider.parse_job_detail(response))[0]
    assert item["board"] == "smartrecruiters"
    assert item["ats_provider"] == "smartrecruiters"
    assert item["ats_job_id"] == "744000123755755"
    assert item["title"] == "Senior Security Engineer"
    assert "Remote" in item["location"]
    assert item["salary_text"] == "109000 - 169000"
    assert item["salary_k"] == 169.0
    assert "automate detection workflows" in item["jd_html"]
