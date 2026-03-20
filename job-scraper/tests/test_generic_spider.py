from scrapy.http import HtmlResponse, TextResponse, Request
from job_scraper.spiders.generic import GenericSpider
from job_scraper.items import JobItem

def _fake_response(url, body, cls=HtmlResponse):
    return cls(url=url, request=Request(url=url), body=body, encoding="utf-8")

def test_parses_rss_feed():
    spider = GenericSpider()
    rss = '<?xml version="1.0"?><rss version="2.0"><channel><title>Jobs</title><item><title>Security Engineer</title><link>https://example.com/job/1</link><description>Great role</description></item></channel></rss>'
    response = _fake_response("https://example.com/jobs.rss", rss.encode(), cls=TextResponse)
    response.meta["company"] = "example"
    results = list(spider.parse_rss(response))
    assert len(results) == 1
    assert results[0]["title"] == "Security Engineer"
