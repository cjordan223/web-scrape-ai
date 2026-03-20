from scrapy.http import HtmlResponse, Request
from job_scraper.spiders.aggregator import AggregatorSpider

def _fake_response(url, body):
    return HtmlResponse(url=url, request=Request(url=url), body=body, encoding="utf-8")

def test_parses_simplyhired_results():
    spider = AggregatorSpider()
    html = '<html><body><article class="SerpJob"><a class="SerpJob-link card-link" href="/job/abc123"><h2 class="jobposting-title">Security Engineer</h2></a><span class="jobposting-company">Acme Corp</span></article></body></html>'
    response = _fake_response("https://www.simplyhired.com/search?q=security+engineer", html)
    results = list(spider.parse_board(response))
    assert len(results) >= 1
