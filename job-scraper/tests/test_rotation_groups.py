from job_scraper.tiers import rotation_filter


def test_ashby_roster_partitions_across_groups():
    # Simulate 40-company roster
    companies = [{"url": f"https://jobs.ashbyhq.com/company{i}", "company": f"c{i}"} for i in range(40)]
    key = lambda c: c["url"]
    buckets = [
        rotation_filter(companies, rotation_group=g, total_groups=4, key=key)
        for g in range(4)
    ]
    # All companies covered, no overlap
    flat = [c for b in buckets for c in b]
    assert len(flat) == 40
    assert len({c["url"] for c in flat}) == 40
    # Roughly balanced — wider bounds for N=40 hash variance (ideal=10 per bucket).
    sizes = [len(b) for b in buckets]
    assert all(3 <= s <= 20 for s in sizes), sizes
