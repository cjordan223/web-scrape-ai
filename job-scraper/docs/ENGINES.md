# SearXNG Engine Configuration

Reference for the engine configuration in `settings.yml`.

## Engine Statistics

| Status | Count |
|--------|-------|
| Total engines defined | 277 |
| Disabled (`disabled: true`) | 172 |
| Inactive (`inactive: true`) | 28 |
| **Enabled by default** | **~77** |

## How Engines Are Configured

Each engine is a YAML entry under the `engines:` list in `settings.yml`. Example:

```yaml
engines:
  - name: google
    engine: google
    shortcut: go
    use_mobile_ui: false

  - name: bing
    engine: bing
    shortcut: bi
    disabled: true    # not used by default

  - name: bitbucket
    engine: xpath     # generic engine type
    paging: true
    search_url: https://bitbucket.org/repo/all/{pageno}?name={query}
    url_xpath: //article[@class="repo-summary"]//a[@class="repo-link"]/@href
    title_xpath: //article[@class="repo-summary"]//a[@class="repo-link"]
    content_xpath: //article[@class="repo-summary"]/p
    categories: [it, repos]
    timeout: 4.0
    shortcut: bb
    disabled: true
```

## Common Engine Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | string | Display name shown in results |
| `engine` | string | Engine module (e.g. `google`, `bing`, `xpath`, `json_engine`) |
| `shortcut` | string | Bang shortcut (e.g. `!go` for Google) |
| `categories` | list | Search categories: `general`, `images`, `news`, `videos`, `music`, `files`, `it`, `science`, `social media`, etc. |
| `disabled` | bool | If `true`, engine is off by default (users can enable in preferences) |
| `inactive` | bool | If `true`, engine is completely hidden (requires API key or setup) |
| `timeout` | float | Request timeout in seconds |
| `paging` | bool | Whether the engine supports pagination |
| `language` | string | Fixed language code for the engine |
| `base_url` | string | Base URL for API requests |
| `tokens` | list | Secret access tokens |
| `proxy` | bool | Whether to route through configured proxy |
| `about` | object | Metadata: `website`, `wikidata_id`, `official_api_documentation`, `use_official_api`, `require_api_key`, `results` |

## Engine Types

### Native Engines
Python modules in the SearXNG codebase with `request()` and `response()` functions. Most major search engines use this type.

Examples: `google`, `bing`, `duckduckgo`, `wikipedia`, `arxiv`, `github`

### XPath Engines
Generic HTML scraping using XPath selectors. Configuration-only — no custom Python code needed.

Additional parameters:
- `search_url` — URL template with `{query}` and `{pageno}` placeholders
- `url_xpath` — XPath to extract result URLs
- `title_xpath` — XPath to extract result titles
- `content_xpath` — XPath to extract result descriptions

### JSON Engines
Generic JSON API scraping. Similar to XPath but uses JSONPath-like selectors.

### Offline Engines
Query local data sources (databases, command-line tools, local indexes).

## Categories

Categories are used by the pipeline to scope searches. The default categories configured as tabs:

| Category | Description |
|----------|-------------|
| `general` | Web search results (used by the job pipeline) |
| `images` | Image search |
| `videos` | Video search |
| `news` | News articles |
| `music` | Music and audio |
| `files` | File/torrent search |
| `it` | Developer/tech resources |
| `science` | Academic papers and data |
| `social media` | Social platforms |

## Key Engines for the Job Scraper

The `job_scraper` package queries `google`, `bing`, and `duckduckgo` with `site:` operators targeting:

- `boards.greenhouse.io`
- `jobs.lever.co`
- `jobs.ashbyhq.com`
- `myworkdayjobs.com`
- `bamboohr.com/careers`
- `icims.com`
- `jobs.smartrecruiters.com`

Plus 3 open-web queries (no `site:` restriction) for junior/entry-level roles.

These engines must be **enabled** (not disabled/inactive) in `settings.yml` for the scraper to function.

## Enabling/Disabling Engines

To enable a disabled engine, remove or set `disabled: false`:

```yaml
# Before (disabled)
  - name: brave
    engine: brave
    shortcut: br
    disabled: true

# After (enabled)
  - name: brave
    engine: brave
    shortcut: br
```

To activate an inactive engine (typically requires API key):

```yaml
  - name: wolframalpha
    engine: wolframalpha_api
    shortcut: wa
    # inactive: true        # remove this line
    api_key: "your-key"     # add required key
```

After changing `settings.yml`, restart the container:

```bash
docker compose restart
```

## Outgoing Request Settings

Configured in the `outgoing:` section of `settings.yml`:

```yaml
outgoing:
  request_timeout: 3.0       # default per-engine timeout
  max_request_timeout: 10.0  # max allowed timeout
  useragent_suffix: ""       # appended to user agent string
  pool_connections: 100
  pool_maxsize: 20
  enable_http2: true          # HTTP/2 support
```

## Suspended Engine Handling

When engines fail, SearXNG suspends them temporarily:

| Error | Suspension Duration |
|-------|-------------------|
| Access denied / HTTP 402-403 | 24 hours |
| CAPTCHA | 24 hours |
| Too many requests / HTTP 429 | 1 hour |
| Cloudflare CAPTCHA | 15 days |
| ReCAPTCHA | 7 days |

These are configured under `search.suspended_times` in `settings.yml`.

## Further Reading

- [SearXNG Engine Overview](https://docs.searxng.org/dev/engines/engine_overview.html)
- [SearXNG Engine Settings](https://docs.searxng.org/admin/settings/settings_engines.html)
- [SearXNG Admin Docs](https://docs.searxng.org/admin/index.html)
