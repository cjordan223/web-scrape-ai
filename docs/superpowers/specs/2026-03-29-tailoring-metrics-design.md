# Tailoring Metrics — Design Spec

## Goal

Capture per-run metrics from the tailoring pipeline to establish performance baselines. Metrics are stored per-run and aggregated in the database, surfaced in the ops UI.

## Data Capture

### Instrumentation points (additive only)

1. **`meta.json`** — add `run_started_at` and `run_finished_at` ISO timestamps
2. **`tracing.py`** — add `phase_start` and `phase_end` event types for: `analysis`, `resume`, `cover`, `compile_resume`, `compile_cover`
3. **`metrics.py`** (new) — post-processes `llm_trace.jsonl` + `meta.json` into `metrics.json` at run completion

### Phase boundary placement

| Location | Event |
|---|---|
| `__main__.py` before `analyze()` | `phase_start(analysis)` |
| `__main__.py` after `analyze()` | `phase_end(analysis)` |
| `writer.py` before resume generation loop | `phase_start(resume)` |
| `writer.py` after resume generation loop | `phase_end(resume)` |
| `writer.py` before cover generation loop | `phase_start(cover)` |
| `writer.py` after cover generation loop | `phase_end(cover)` |
| `compiler.py` before pdflatex (resume) | `phase_start(compile_resume)` |
| `compiler.py` after pdflatex (resume) | `phase_end(compile_resume)` |
| `compiler.py` before pdflatex (cover) | `phase_start(compile_cover)` |
| `compiler.py` after pdflatex (cover) | `phase_end(compile_cover)` |

### `run_started_at` / `run_finished_at`

Set in `__main__.py`:
- `run_started_at` = ISO timestamp captured before any work begins (after arg parsing, before analysis)
- `run_finished_at` = ISO timestamp captured after all documents generated and compiled
- Both written to `meta.json`

## Per-Run `metrics.json`

Written to `tailoring/output/<slug>/metrics.json` by a new `tailoring/tailor/metrics.py` module. Computed from `llm_trace.jsonl` + `meta.json` at the end of the run.

```json
{
  "run_slug": "string",
  "job_id": 123,
  "model": "qwen3:30b",
  "timestamp": "ISO",

  "total_wall_time_s": 480.0,
  "queue_wait_s": null,

  "analysis_time_s": 45.0,
  "analysis_llm_time_s": 40.0,
  "analysis_llm_calls": 1,

  "resume_time_s": 180.0,
  "resume_llm_time_s": 160.0,
  "resume_llm_calls": 3,
  "resume_attempts": 1,

  "cover_time_s": 220.0,
  "cover_llm_time_s": 200.0,
  "cover_llm_calls": 4,
  "cover_attempts": 2,

  "compile_resume_s": 2.5,
  "compile_cover_s": 2.3,

  "total_llm_calls": 8,
  "total_llm_time_s": 400.0
}
```

`queue_wait_s` is `null` in the per-run file (the subprocess doesn't know queue timing). The backend fills it in when writing the DB row.

## Database Table

```sql
CREATE TABLE IF NOT EXISTS tailoring_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_slug TEXT NOT NULL UNIQUE,
    job_id INTEGER NOT NULL,
    model TEXT,
    timestamp TEXT NOT NULL,

    total_wall_time_s REAL,
    queue_wait_s REAL,

    analysis_time_s REAL,
    analysis_llm_time_s REAL,
    analysis_llm_calls INTEGER,

    resume_time_s REAL,
    resume_llm_time_s REAL,
    resume_llm_calls INTEGER,
    resume_attempts INTEGER,

    cover_time_s REAL,
    cover_llm_time_s REAL,
    cover_llm_calls INTEGER,
    cover_attempts INTEGER,

    compile_resume_s REAL,
    compile_cover_s REAL,

    total_llm_calls INTEGER,
    total_llm_time_s REAL
);
```

## Backend Integration

In `_tailoring_runner_snapshot()` (app.py), when a run completes successfully:

1. Read `metrics.json` from the run's output directory
2. Compute `queue_wait_s` from the queue item's `created_at` and `started_at`
3. INSERT into `tailoring_metrics` table (UPSERT on `run_slug`)

New API endpoint:
- `GET /api/ops/tailoring/metrics` — returns all rows from `tailoring_metrics`, most recent first, plus a `baselines` object with averages across all runs

## Ops UI

New "Metrics" section in the ops area. Simple sortable table:

| Column | Content |
|---|---|
| Run | `run_slug` (links to run detail) |
| Job | job title |
| Model | model name |
| Wall Time | `total_wall_time_s` formatted |
| Queue Wait | `queue_wait_s` |
| Analysis | `analysis_time_s` |
| Resume | `resume_time_s` (attempts) |
| Cover | `cover_time_s` (attempts) |
| Compile | sum of compile times |
| LLM Time | `total_llm_time_s` |
| LLM Calls | `total_llm_calls` |
| Date | timestamp |

Top row: computed baselines (averages) with label "Baseline (avg)".

## Files Changed

### Tailoring package (subprocess side)
- `tailoring/tailor/tracing.py` — add `phase_start`/`phase_end` convenience methods
- `tailoring/tailor/__main__.py` — add `run_started_at`/`run_finished_at` to meta, phase boundary calls, metrics generation at end
- `tailoring/tailor/writer.py` — phase boundary calls for resume/cover
- `tailoring/tailor/compiler.py` — phase boundary calls for compilation
- `tailoring/tailor/metrics.py` — **new**, post-processes trace + meta into `metrics.json`

### Dashboard backend
- `dashboard/backend/app.py` — create `tailoring_metrics` table, ingest metrics on run completion
- `dashboard/backend/routers/ops.py` — add `GET /api/ops/tailoring/metrics` endpoint
- `dashboard/backend/services/ops.py` — metrics query function

### Dashboard frontend
- `dashboard/web/src/views/domains/ops/MetricsView.tsx` — **new**, metrics table view
- `dashboard/web/src/App.tsx` — add route
- `dashboard/web/src/components/layout/AppShell.tsx` — add nav link
- `dashboard/web/src/api.ts` — add fetch function

## Not in scope
- Real-time streaming metrics during a run
- Historical trend charts (future enhancement)
- Alerts/thresholds
- Changes to existing trace format (additive only)
