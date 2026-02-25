# SearXNG + Job Scraper

Self-hosted [SearXNG](https://github.com/searxng/searxng) metasearch engine paired with:
- a policy-driven job scraper (`job-scraper/`)
- a JD-to-doc tailoring engine (`tailoring/`)

## Layout

```
SearXNG/
├── docker-compose.yml      # SearXNG container config
├── settings.yml            # SearXNG engine settings
├── job-scraper/            # Job scraper project (see job-scraper/README.md)
│   ├── job_scraper/        # Python package
│   ├── dashboard/          # FastAPI + Alpine.js SPA (:8899)
│   └── pyproject.toml
├── tailoring/              # Tailoring engine (see plan.md)
│   ├── tailor/             # CLI package: select/run/validate
│   ├── Baseline-Dox/       # Baseline LaTeX templates
│   └── output/             # Generated per-job artifacts
├── docs/
│   └── ENGINES.md          # SearXNG engine reference
└── venv/                   # Python 3.14 virtualenv (shared)
```

## SearXNG

```bash
docker compose up -d                                    # start
docker compose down                                     # stop
docker compose logs -f searxng                          # logs
docker compose pull && docker compose up -d             # update
curl "http://localhost:8888/search?q=test&format=json"  # test
```

- **Port:** `8888` (host) → `8080` (container)
- **Settings:** `./settings.yml` mounted into container
- **Limiter:** disabled (private instance)
- **JSON API:** enabled (`search.formats: [html, json]`)

### MCP Server

```bash
source venv/bin/activate
python -m searXNG --instance-url http://localhost:8888
```

## Job Scraper

See [`job-scraper/README.md`](job-scraper/README.md) for full documentation.

```bash
source venv/bin/activate
pip install -e ./job-scraper/
cd job-scraper && python -m job_scraper scrape -v
```

Current defaults are strict:
- remote-only policy (`require_remote: true`)
- reject internship/new-grad postings
- reject known LinkedIn shell/login pages
- canonical URL dedup (tracking params stripped for major boards)

## Tailoring Engine

See [`plan.md`](plan.md) for implementation details.

```bash
source venv/bin/activate
cd tailoring
python -m tailor select
python -m tailor run --job-id <ID>
python -m tailor validate output/<job-slug>/
```

Tailoring runs now include full LLM transparency traces at:

- `tailoring/output/<job-slug>/llm_trace.jsonl`

The dashboard (`job-scraper/dashboard`) includes a **Tailoring** tab to inspect:

- analyzer + resume/cover strategy/draft/QA prompt payloads
- raw model responses
- attempt-level validation/failure events

## Port Map

| Service | Port | Notes |
|---|---|---|
| SearXNG | 8888 | Docker, host-mapped from container :8080 |
| Dashboard | 8899 | Native Python, FastAPI + uvicorn |
| LLM server (LM Studio API) | 1234 | OpenAI-compatible local endpoint |
