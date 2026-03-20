"""Scrapy settings for job_scraper."""

BOT_NAME = "job_scraper"
SPIDER_MODULES = ["job_scraper.spiders"]
NEWSPIDER_MODULE = "job_scraper.spiders"

ROBOTSTXT_OBEY = False

CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1.0

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0

RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

DOWNLOAD_TIMEOUT = 30

ITEM_PIPELINES = {
    "job_scraper.pipelines.text_extraction.TextExtractionPipeline": 100,
    "job_scraper.pipelines.dedup.DeduplicationPipeline": 200,
    "job_scraper.pipelines.hard_filter.HardFilterPipeline": 300,
    "job_scraper.pipelines.storage.SQLitePipeline": 400,
}

DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True}

LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

STATS_CLASS = "scrapy.statscollectors.MemoryStatsCollector"
