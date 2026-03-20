from job_scraper.spiders.usajobs import USAJobsSpider
from job_scraper.items import JobItem

def test_parses_api_response():
    spider = USAJobsSpider()
    api_data = {"SearchResult": {"SearchResultItems": [{"MatchedObjectDescriptor": {"PositionTitle": "IT Specialist", "PositionURI": "https://www.usajobs.gov/job/123", "PositionLocationDisplay": "Remote", "OrganizationName": "NASA", "PositionRemuneration": [{"MinimumRange": "90000", "MaximumRange": "120000"}], "QualificationSummary": "Cybersecurity specialist...", "UserArea": {"Details": {"MajorDuties": ["Perform assessments"]}}}}]}}
    items = list(spider._parse_results(api_data))
    assert len(items) == 1
    assert items[0]["board"] == "usajobs"
    assert items[0]["salary_text"]
