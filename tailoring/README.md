# Tailoring Engine

Generates targeted application packages (resume + cover letter) from scraper jobs using a local OpenAI-compatible LLM endpoint.

## Quick Start

```bash
cd /Users/conner/Documents/TexTailor/tailoring
source ../venv/bin/activate

python -m tailor select
python -m tailor run --job-id 69
python -m tailor run --job-id 69 --skip-analysis
python -m tailor validate output/<slug>
```

## Requirements

- Scraper DB populated (`~/.local/share/job_scraper/jobs.db`)
- Ollama running on `localhost:11434` (or any OpenAI-compatible endpoint via env var)
- `pdflatex` available (`PDFLATEX_BIN` override supported)

## Pipeline

Each document uses:

1. **Strategy** (structured plan)
2. **Draft** (full LaTeX)
3. **QA** (repair against structural checks)
4. **Validator** (hard gates)

Retries up to configured max if validation fails.

## Output Artifacts

Each run creates `output/<slug>/` containing:

- `meta.json`
- `analysis.json`
- `resume_strategy.json`
- `cover_strategy.json`
- `Conner_Jordan_Resume.tex/.pdf`
- `Conner_Jordan_Cover_Letter.tex/.pdf`
- `llm_trace.jsonl`

Runner logs are in `output/_runner_logs/`.

## Configuration

Primary settings are in `tailor/config.py`.

Common tuning knobs:

- `RESUME_CHAR_TOLERANCE`
- `COVER_CHAR_TOLERANCE`
- `RESUME_BULLET_COUNT`
- `MAX_RETRIES`

Detailed gate behavior: [`QUALITY_BAR.md`](QUALITY_BAR.md)

## LLM Endpoint

The engine auto-discovers the first loaded model from `/v1/models` at runtime. To pin a specific model:

```bash
export TAILOR_LLM_URL=http://localhost:11434/v1/chat/completions
export TAILOR_LLM_MODEL=qwen3.5:27b   # omit to auto-discover
```

The dashboard Ops > LLM view allows switching providers and models.

## Key Files

```text
tailoring/
├── Baseline-Dox/
├── output/
├── persona/
├── PROFILE_INGESTION.md
├── skills.json
├── soul.md
├── QUALITY_BAR.md
└── tailor/
    ├── __main__.py
    ├── config.py
    ├── analyzer.py
    ├── writer.py
    ├── validator.py
    ├── compiler.py
    ├── selector.py
    ├── ollama.py
    └── tracing.py
```
