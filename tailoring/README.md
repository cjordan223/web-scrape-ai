# Tailoring Engine

Generates targeted application packages (resume + cover letter) from scraper jobs using an OpenAI-compatible LLM endpoint.

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

1. **Analysis** — JD requirement extraction with hash-based caching
2. **Strategy** — structured plan (per doc type) with persona + vignette injection
3. **Draft** — full LaTeX output
4. **QA** — repair pass against structural checks
5. **Validator** — hard gates (section order, bullet counts, grounding claims, PDF fit)

Retries up to `MAX_RETRIES` if validation fails.

## Output Artifacts

Each run creates `output/<slug>/` containing:

- `meta.json`
- `analysis.json`
- `resume_strategy.json`
- `cover_strategy.json`
- `Conner_Jordan_Resume.tex/.pdf`
- `Conner_Jordan_Cover_Letter.tex/.pdf`
- `llm_trace.jsonl`

Runner logs in `output/_runner_logs/`.

## Configuration

Primary settings in `tailor/config.py`.

Common knobs:

- `RESUME_CHAR_TOLERANCE`
- `COVER_CHAR_TOLERANCE`
- `RESUME_BULLET_COUNT`
- `MAX_RETRIES`

Detailed gate behavior: [`QUALITY_BAR.md`](QUALITY_BAR.md)

## LLM Endpoint

Model selection is **explicit** — TexTailor never auto-picks the first loaded model. Tailoring fails with a clear error if no model is configured.

```bash
export TAILOR_LLM_URL=http://localhost:11434/v1/chat/completions
export TAILOR_LLM_MODEL=qwen3:30b     # required
export TAILOR_LLM_PROVIDER=ollama      # default; cloud providers also supported
export TAILOR_LLM_API_KEY=...          # cloud providers only
```

Fallback env vars `TAILOR_OLLAMA_URL` / `TAILOR_OLLAMA_MODEL` still work. Dashboard → Ops → LLM switches providers and models.

## Persona & Vignettes

The tailoring voice and source material live in `persona/`, not `soul.md`. `soul.md` is a fallback mirror for fresh clones.

### Structure

```text
persona/
├── identity.md          # who the candidate is
├── contributions.md     # recurring contribution patterns
├── voice.md             # voice rules + anti-patterns
├── evidence.md          # compact reusable proof anchors
├── interests.md         # motivational framing
├── motivation.md        # cover letter framing
└── vignettes/
    ├── coraline.md
    ├── rag_chatbot.md
    └── ... (one story per file)
```

### Vignette format

Each vignette is one file with YAML frontmatter + one paragraph body:

```markdown
---
tags: [data_correlation, cloud_security, internal_tooling]
company_types: [large_tech, security_focused]
skill_categories: [Security Data Engineering, Cloud Security]
keywords: [correlation, Flask, Docker, ECS, vulnerability]
---
Problem → approach → tradeoffs → outcome, as prose. Reasoning and lessons,
not resume bullets. One paragraph.
```

### Selection scoring (`tailor/persona.py:115`)

The analyzer produces `matched_category` and `matched_skills` per JD requirement. Each vignette is scored:

- `+3` per `skill_categories` match vs `analysis.requirements[].matched_category`
- `+2` if `company_types` matches `analysis.company_context.company_type`
- `+1` per `keywords` match vs `matched_skills`

Sorted by score, then score density, then body length and filename for deterministic packing under a char budget. Keyword scoring tolerates phrase/token variants, and cover letters use `diverse=True` on the primary skill category so one topic cannot anchor the whole letter.

Budgets (strategy / draft, cover / resume): 1500 / 1500 / 1500 / 1500 chars.

Rendered to the LLM with `### Source project: <filename_stem>` headers so the writer does not braid details across vignettes.

### Adding a new vignette

1. Create `persona/vignettes/<slug>.md`.
2. Frontmatter — `skill_categories` **must** match category names in [`skills.json`](skills.json) exactly. Drift breaks scoring.
3. Body: one paragraph, prose, judgment and outcome. No bullets.
4. If the story establishes a new claimable capability → also add to `skills.json`.
5. If it changes broad candidate framing → update `persona/contributions.md`.
6. If it yields a short reusable proof → update `persona/evidence.md`.

Deeper ingestion guidance (routing rules, guardrails, structured intake flow): [`PROFILE_INGESTION.md`](PROFILE_INGESTION.md).

## Key Files

```text
tailoring/
├── Baseline-Dox/            # resume + cover letter LaTeX baselines
├── output/                  # generated packages
├── persona/                 # identity, contributions, voice, vignettes
├── skills.json              # claimable skills + category registry
├── soul.md                  # fallback persona mirror
├── PROFILE_INGESTION.md
├── QUALITY_BAR.md
├── PERFORMANCE_EVALUATION.md
└── tailor/
    ├── __main__.py          # CLI entry
    ├── config.py            # paths, model config, constants
    ├── analyzer.py          # JD requirement extraction
    ├── writer.py            # strategy/draft/QA prompt pipeline
    ├── persona.py           # persona hierarchy + vignette selector
    ├── grounding.py         # structured grounding contract
    ├── validator.py         # hard gates
    ├── semantic_validator.py
    ├── compiler.py          # pdflatex wrapper
    ├── selector.py          # DB job selection
    ├── metrics.py           # run metrics
    ├── ollama.py            # multi-provider LLM client (file-lock mutex)
    └── tracing.py           # per-call trace logging
```
