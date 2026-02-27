# SearXNG Engine Notes

Reference for engine settings used by this workspace.

## Why This Matters

The scraper depends on SearXNG returning stable web results for job-board and open-web queries. If engines are disabled or failing, scraper discovery drops immediately.

## Key Engines for Scraper

Ensure these are active in `settings.yml`:

- `google`
- `bing`
- `duckduckgo`

## Key Query Targets

Scraper templates primarily target:

- `boards.greenhouse.io`
- `jobs.lever.co`
- `jobs.ashbyhq.com`
- `myworkdayjobs.com`
- `bamboohr.com/careers`
- `icims.com`
- `jobs.smartrecruiters.com`

## Engine Status Flags

- `disabled: true` -> off by default
- `inactive: true` -> unavailable until required setup/key is provided

## Common Engine Parameters

- `name`
- `engine`
- `shortcut`
- `categories`
- `timeout`
- `paging`
- `disabled`
- `inactive`

## After Editing settings.yml

Restart SearXNG:

```bash
docker compose restart
```

Quick API check:

```bash
curl "http://localhost:8888/search?q=security+engineer&format=json"
```

## Failure/Suspension Behavior

SearXNG can temporarily suspend engines on repeated failures (403/429/captcha). If scraper volume suddenly drops, inspect SearXNG logs and engine health.

## Upstream Docs

- [SearXNG admin settings](https://docs.searxng.org/admin/settings.html)
- [Engine settings reference](https://docs.searxng.org/admin/settings/settings_engines.html)
