import json

from scrapy.http import Request, TextResponse

from job_scraper.spiders.remotive import RemotiveSpider


def test_remotive_json_yields_items():
    spider = RemotiveSpider()
    payload = {
        "jobs": [
            {
                "id": 123,
                "url": "https://remotive.com/remote-jobs/software-dev/cloud-security-engineer-123",
                "title": "Cloud Security Engineer",
                "company_name": "Acme",
                "category": "Software Development",
                "tags": ["security", "cloud", "python"],
                "candidate_required_location": "USA",
                "salary": "$140k - $170k",
                "description": "<p>Remote cloud security engineering role.</p>",
            }
        ]
    }
    response = TextResponse(
        url="https://remotive.com/api/remote-jobs",
        request=Request(url="https://remotive.com/api/remote-jobs"),
        body=json.dumps(payload).encode(),
        encoding="utf-8",
    )
    items = list(spider.parse_jobs(response))
    assert len(items) == 1
    item = items[0]
    assert item["source"] == "remotive"
    assert item["board"] == "remotive"
    assert item["company"] == "Acme"
    assert "security" in item["snippet"]
    assert item["salary_text"] == "$140k - $170k"
