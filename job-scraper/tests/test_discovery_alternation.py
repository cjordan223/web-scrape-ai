from job_scraper.spiders.searxng import SearXNGSpider


def test_searxng_skips_when_discovery_not_firing():
    from job_scraper.config import SearXNGQuery
    spider = SearXNGSpider()
    spider._searxng_url = "http://x/search"
    spider._queries = [SearXNGQuery(title_phrase="eng", board_site="", suffix="")]
    spider._domain_blocklist = set()
    spider._discovery_fire = False
    reqs = list(spider.start_requests())
    assert reqs == []


def test_searxng_fires_when_flag_true():
    from job_scraper.config import SearXNGQuery
    spider = SearXNGSpider()
    spider._searxng_url = "http://x/search"
    spider._queries = [SearXNGQuery(title_phrase="eng", board_site="", suffix="")]
    spider._domain_blocklist = set()
    spider._discovery_fire = True
    reqs = list(spider.start_requests())
    assert len(reqs) >= 1
