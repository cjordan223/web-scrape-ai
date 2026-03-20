import json
from scrapy.http import HtmlResponse, Request
from job_scraper.spiders.ashby import AshbySpider
from job_scraper.items import JobItem

def _fake_response(url, body):
    return HtmlResponse(url=url, request=Request(url=url), body=body, encoding="utf-8")

def test_parses_ashby_job_detail():
    spider = AshbySpider()
    html = '<html><body><div class="ashby-job-posting-description"><p>Great opportunity.</p></div></body></html>'
    response = _fake_response("https://jobs.ashbyhq.com/testco/abc-123", html)
    response.meta["company"] = "testco"
    response.meta["board"] = "ashby"
    results = list(spider.parse_job(response))
    assert len(results) == 1
    assert isinstance(results[0], JobItem)
    assert results[0]["company"] == "testco"
