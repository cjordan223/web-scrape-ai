# Pipeline Editor — Frontend API Reference

The Pipeline Editor (`/pipeline/editor`) is a React Flow graph that visualizes the scraper → filter → QA → tailoring pipeline. It polls three live-status endpoints and reads/writes the scraper config.

Route: `http://localhost:8899/pipeline/editor`
Source: `src/views/domains/ops/diagnostics/PipelineEditorView.tsx`

---

## Endpoints

### Config

#### `GET /api/scraper/config`

Load the full scraper configuration (boards, queries, filters, pipeline order).

```ts
api.getScraperConfig(): Promise<ScraperConfig>
```

**Response:**

```jsonc
{
  "boards": [
    { "url": "https://ramp.com/careers", "board_type": "ashby", "company": "ramp", "enabled": true }
  ],
  "queries": [
    { "title_phrase": "security engineer", "board_site": "greenhouse", "board": "nansen", "suffix": "remote" }
  ],
  "searxng": {
    "enabled": true, "url": "http://localhost:8888/search",
    "timeout": 15, "engines": "google,startpage",
    "time_range": "week", "request_delay": 1.0
  },
  "usajobs": {
    "enabled": false, "keywords": [], "series": [],
    "agencies": [], "days": 14, "remote": true
  },
  "hard_filters": {
    "domain_blocklist": ["linkedin.com"],
    "title_blocklist": ["staff", "principal"],
    "content_blocklist": [],
    "min_salary_k": 70
  },
  "filter": {
    "title_keywords": ["engineer", "security"],
    "title_role_words": ["engineer", "architect"],
    "require_remote": true, "require_us_location": true,
    "min_jd_chars": 50, "max_experience_years": 5,
    "score_accept_threshold": 0, "score_reject_threshold": -3
  },
  "seen_ttl_days": 14,
  "target_max_results": 50,
  "pipeline_order": ["text_extraction", "dedup", "hard_filter", "storage"],
  "llm_review": {},
  "crawl": {
    "enabled": true, "request_delay": 2.0, "max_results_per_target": 50
  }
}
```

Backend: `services/scraper_config.py → scraper_config_get()`
Reads: `job-scraper/job_scraper/config.default.yaml`

---

#### `POST /api/scraper/config`

Save partial config changes. Merges with existing YAML, validates, writes back.

```ts
api.saveScraperConfig(config: Partial<ScraperConfig>): Promise<{ ok: boolean; config: ScraperConfig }>
```

**Request body:** Any subset of the `ScraperConfig` shape above.

Backend: `services/scraper_config.py → scraper_config_save()`
Writes: `job-scraper/job_scraper/config.default.yaml`

---

#### `GET /api/scraper/pipeline/stats`

Per-stage counts from the latest completed run + current inventory breakdown.

```ts
api.getScraperPipelineStats(): Promise<PipelineStats>
```

**Response:**

```jsonc
{
  "run_id": "abc123def456",
  "started_at": "2026-03-22T10:30:00Z",
  "raw_count": 1500,
  "dedup_dropped": 450,
  "filter_rejected": 1000,
  "stored": 50,
  "error_count": 0,
  "per_source": { "ashby_ramp": 120, "greenhouse_nansen": 85, "google": 650 },
  "per_rejection": { "url_domain": 250, "seniority": 180, "salary": 120 },
  "inventory": {
    "total": 50,
    "qa_pending": 12, "qa_approved": 23,
    "qa_rejected": 5, "rejected": 10
  }
}
```

Backend: `services/scraper_config.py → scraper_pipeline_stats()`

---

### Live Status (polled every 4s)

All three are polled in a single `setInterval` with `.catch(() => null)` for resilience.

#### `GET /api/scrape/runner/status`

```ts
api.getScrapeRunnerStatus(): Promise<ScrapeRunnerStatus>
```

**Response:**

```jsonc
{
  "running": true,
  "started_at": "2026-03-22T10:45:00Z",
  "ended_at": null,
  "exit_code": null,
  "log_tail": "2026-03-22 10:46:15 Deduplication complete...",
  "options": { "spider": null }
}
```

Backend: `job-scraper/api/scraping_handlers.py → scrape_runner_status()`
Query param: `lines` (int, default 80) — number of log lines to tail.

---

#### `GET /api/tailoring/runner/status`

```ts
api.getTailoringRunnerStatus(): Promise<TailoringRunnerStatus>
```

**Response:**

```jsonc
{
  "running": true,
  "job": {
    "id": 42, "title": "Senior Security Engineer",
    "url": "https://...", "board": "ashby_ramp"
  },
  "started_at": "2026-03-22T11:00:00Z",
  "ended_at": null,
  "log_tail": "Analyzing job requirements...\nExtracting key skills...",
  "queue": [
    { "id": 2, "job_id": 43, "status": "queued", "run_slug": null }
  ],
  "active_item": {
    "id": 1, "job_id": 42, "status": "running", "run_slug": "job-42-20260322"
  }
}
```

Backend: `services/tailoring.py → tailoring_runner_status()`
Query param: `lines` (int, default 80).

---

#### `GET /api/tailoring/qa/llm-review`

QA LLM review batch progress — drives the live review feed in the QA node sidebar.

```ts
api.getQALlmReviewStatus(): Promise<QALlmReviewStatus>
```

**Response:**

```jsonc
{
  "running": true,
  "batch_id": 5,
  "started_at": "2026-03-22T11:10:00Z",
  "ended_at": null,
  "resolved_model": "llama2-70b",
  "active_job": {
    "job_id": 42, "title": "Senior Security Engineer",
    "status": "reviewing"
  },
  "items": [
    {
      "job_id": 40, "title": "Junior Dev",
      "status": "pass",               // "pass" | "fail" | "skipped" | "error"
      "reason": "Good fit",
      "confidence": 0.88,
      "top_matches": ["bash", "security"],
      "gaps": ["Go", "Rust"]
    }
  ],
  "summary": {
    "total": 10, "queued": 3, "reviewing": 1, "completed": 6,
    "passed": 4, "failed": 1, "skipped": 1, "errors": 0
  }
}
```

Backend: `services/tailoring.py → tailoring_qa_llm_review_status()`

---

### Runtime Controls

#### `GET /api/runtime-controls`

```ts
api.getRunsControls(): Promise<RuntimeControls>
```

**Response:**

```jsonc
{
  "scrape_enabled": true,
  "llm_enabled": true,
  "llm_provider": "lmstudio",
  "llm_base_url": "http://localhost:1234",
  "llm_model": "default",
  "schedule_interval_minutes": null,
  "schedule_started_at": null,
  "updated_at": "2026-03-22T09:15:00Z"
}
```

Backend: `services/ops.py → get_runtime_controls()`
Reads: `~/.local/share/job_scraper/runtime_controls.json`

---

## Architecture Notes

- **No WebSockets.** Everything is HTTP polling.
- **Poll interval:** 4 seconds, single `setInterval` fires all three status calls in parallel.
- **Config save flow:** frontend POSTs partial config → backend merges with YAML on disk → returns full merged config.
- **Scrape runs are UI-initiated only.** No auto-scheduling. The old `_set_scrape_schedule` / launchd mechanisms have been removed.
- **Items with no JD text are dropped** at the `TextExtractionPipeline` stage (< 30 chars → `DropItem`). They never reach `qa_pending`.

## File Map

| Layer | File | Role |
|-------|------|------|
| Frontend view | `src/views/domains/ops/diagnostics/PipelineEditorView.tsx` | React Flow graph + sidebar panels |
| Frontend styles | `src/styles/pipeline-editor.css` | Node/edge/sidebar CSS |
| API client | `src/api.ts` | Axios wrapper, all `api.*` methods |
| Config service | `backend/services/scraper_config.py` | Read/write `config.default.yaml` |
| Ops service | `backend/services/ops.py` | Runtime controls, scrape runner |
| Tailoring service | `backend/services/tailoring.py` | QA review, tailoring runner |
| Scraping handlers | `job-scraper/api/scraping_handlers.py` | Scrape runner status |
| Route registration | `backend/routers/ops.py` | Maps paths → handler names |
| Route registration | `backend/routers/scraping.py` | Maps paths → handler names |
| Route registration | `backend/routers/tailoring.py` | Maps paths → handler names |
