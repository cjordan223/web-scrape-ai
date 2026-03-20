from scrapy.http import HtmlResponse, Request
from job_scraper.spiders.greenhouse import GreenhouseSpider
from job_scraper.items import JobItem

def _fake_response(url, body):
    return HtmlResponse(url=url, request=Request(url=url), body=body, encoding="utf-8")

def test_parses_greenhouse_job_list():
    spider = GreenhouseSpider()
    html = '<html><body><div class="opening"><a href="https://job-boards.greenhouse.io/testco/jobs/12345">Security Engineer</a></div></body></html>'
    response = _fake_response("https://job-boards.greenhouse.io/testco", html)
    response.meta["company"] = "testco"
    results = list(spider.parse_board(response))
    assert len(results) >= 1

def test_parses_greenhouse_job_detail():
    spider = GreenhouseSpider()
    html = '<html><body><h1>Security Engineer</h1><div class="job-post-content"><p>Join our team.</p></div></body></html>'
    response = _fake_response("https://job-boards.greenhouse.io/testco/jobs/12345", html)
    response.meta["company"] = "testco"
    response.meta["board"] = "greenhouse"
    results = list(spider.parse_job(response))
    assert len(results) == 1
    assert results[0]["board"] == "greenhouse"
