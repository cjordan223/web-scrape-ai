# Tailoring Engine

Turns approved job postings from the scraper into targeted LaTeX application packages (resume + cover letter) using a local LLM.

## Quick Start

```bash
source ../venv/bin/activate

# Browse recent jobs from the scraper DB
python -m tailor select

# Run the full pipeline for a job
python -m tailor run --job-id 69

# Reuse cached JD analysis (skips the first LLM call)
python -m tailor run --job-id 69 --skip-analysis

# Validate existing output without regenerating
python -m tailor validate output/<slug>
```

Requires:
- LM Studio (or any OpenAI-compatible server) running on `localhost:1234`
- pdflatex installed (`brew install --cask mactex` or set `PDFLATEX_BIN`)
- Scraper DB at `~/.local/share/job_scraper/jobs.db` (populated by `job-scraper/`)

## How It Works

Each document goes through a **3-stage LLM pipeline**:

```
 JD + Skills + Baseline Template
          │
    ┌─────▼─────┐
    │  Strategy  │  → JSON writing plan (what to emphasize, risks to avoid)
    └─────┬─────┘
          │
    ┌─────▼─────┐
    │   Draft    │  → Full LaTeX from template + strategy + analysis
    └─────┬─────┘
          │
    ┌─────▼─────┐
    │     QA     │  → Reviews draft against baseline metrics, fixes issues
    └─────┬─────┘
          │
    ┌─────▼─────┐
    │ Validator  │  → Hard gates: compilation, char count, bullet count, etc.
    └─────┬─────┘
          │
      Pass? ──No──→ Retry (up to MAX_RETRIES with error feedback)
          │
        Done → .tex + .pdf in output/<slug>/
```

The QA stage receives **computed structural metrics** (char count ratio vs baseline, bullet count) so it can fix issues before validation runs.

## File Layout

```
tailoring/
├── Baseline-Dox/          # Gold-standard LaTeX templates (do not edit lightly)
│   ├── Conner_Jordan_Software_Engineer/
│   │   └── Conner_Jordan_Resume.tex
│   └── Conner_Jordan_Cover_letter/
│       └── Conner_Jordan_Cover_Letter.tex
├── skills.json            # Structured skills inventory (categories + resume-ready lines)
├── soul.md                # Candidate persona / voice reference for cover letters
├── QUALITY_BAR.md         # Validation gate spec and tuning guide
├── output/                # Generated packages (one dir per job)
│   ├── <slug>/
│   │   ├── meta.json
│   │   ├── analysis.json
│   │   ├── resume_strategy.json
│   │   ├── cover_strategy.json
│   │   ├── Conner_Jordan_Resume.tex / .pdf
│   │   ├── Conner_Jordan_Cover_Letter.tex / .pdf
│   │   └── llm_trace.jsonl
│   └── _runner_logs/      # CLI stdout logs per run
├── tailor/                # Python package
│   ├── __main__.py        # CLI (select, run, validate)
│   ├── config.py          # All paths, thresholds, and LLM settings
│   ├── analyzer.py        # Stage 0: JD → structured requirement mapping
│   ├── writer.py          # Stages 1-3: strategy → draft → QA (prompt definitions here)
│   ├── validator.py       # Hard-gate validation (compilation, char count, bullets, etc.)
│   ├── compiler.py        # pdflatex wrapper
│   ├── selector.py        # Job selection from scraper DB
│   ├── ollama.py          # OpenAI-compatible LLM client with file-lock mutex
│   └── tracing.py         # Per-run LLM call logging (llm_trace.jsonl)
└── tests/
```

## Tuning

**Validation thresholds** (most common adjustment):
Edit `tailor/config.py`. Key knobs:

| Setting | Default | What It Controls |
|---------|---------|-----------------|
| `RESUME_CHAR_TOLERANCE` | 0.15 | How close resume body text must be to baseline (±%) |
| `COVER_CHAR_TOLERANCE` | 0.10 | Same for cover letter |
| `RESUME_BULLET_COUNT` | 14 | Exact bullet count required (6+5+3) |
| `MAX_RETRIES` | 3 | Full pipeline retries per document on validation failure |

Test thresholds on existing output without regenerating:
```bash
python -m tailor validate output/<slug>
```

**LLM prompts** (behavioral changes):
Edit the `_*_SYSTEM` constants in `tailor/writer.py`. Each stage has its own system prompt:
- `_RESUME_STRATEGY_SYSTEM` / `_COVER_STRATEGY_SYSTEM` — writing plan format
- `_RESUME_DRAFT_SYSTEM` / `_COVER_DRAFT_SYSTEM` — LaTeX generation rules
- `_RESUME_QA_SYSTEM` / `_COVER_QA_SYSTEM` — review/repair instructions
- `_STYLE_GUARDRAILS` — shared rules (no dashes, no hallucinations, etc.)

**LLM model/server**:
```bash
# Override via env vars
export TAILOR_LMSTUDIO_URL=http://localhost:1234/v1/chat/completions
export TAILOR_LMSTUDIO_MODEL=qwen/qwen3-coder-next

# Or use "default" to auto-pick first model from /v1/models
```

## Debugging

Every run writes `llm_trace.jsonl` in the output directory. Each line is a JSON object with:
- Full system + user prompts sent to the LLM
- Raw LLM response text
- Timing, model ID, token limits
- Validation results per attempt

Runner logs (CLI stdout) are saved to `output/_runner_logs/`.

## See Also

- `QUALITY_BAR.md` — detailed gate spec and char tolerance tuning rationale
- `tailor/config.py` — single source of truth for all settings
