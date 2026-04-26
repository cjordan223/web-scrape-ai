# Tailor Model Benchmark Guide

This guide is for agents benchmarking candidate LLMs for the TexTailor tailoring
engine. The goal is not to find the fastest chat model. The goal is to find the
best model for producing grounded, valid, high-quality application packages.

## Executive Summary

TexTailor's tailoring workflow is a multi-step generation and repair pipeline:

```text
job description -> analysis -> strategy -> draft -> QA repair -> validator
```

The best tailor model must do five things well:

1. Follow structured-output instructions.
2. Generate valid LaTeX.
3. Stay grounded in the candidate source material.
4. Recover from validation feedback.
5. Finish in a practical amount of time.

Speed matters, but only after the model clears the quality bar. A fast model
that produces invalid, generic, or hallucinated documents is not useful.

## Current Runtime Context

### Local Inference Provider

TexTailor now uses Ollama as the local inference provider.

- Ollama base URL: `http://localhost:11434`
- OpenAI-compatible chat URL: `http://localhost:11434/v1/chat/completions`
- Native Ollama API used by some benchmarks: `http://localhost:11434/api/chat`

### Scraper Gate Model

The scrape relevance gate uses:

```text
qwen2.5:7b
```

This is intentionally a cheaper model. Do not assume it is also the best tailor
model. Tailoring is much harder than scrape relevance scoring.

### Tailoring Model Selection

Relevant files:

- `tailoring/tailor/config.py`
- `tailoring/tailor/ollama.py`
- `dashboard/backend/app.py`
- `dashboard/backend/services/tailoring.py`
- `tailoring/tests/test_model_resolution.py`

Current behavior:

- Direct tailoring expects an explicit model via `TAILOR_LLM_MODEL` or dashboard
  runtime controls.
- `tailoring/tailor/config.py` has `OLLAMA_MODEL` defaulting to `"default"`.
- `tailoring/tailor/ollama.py:get_loaded_model()` treats missing or `"default"`
  as an error for direct calls.
- Dashboard subprocess runtime can resolve `"default"` to the first usable
  loaded Ollama model before launching the child process.

Benchmark agents should record the exact model tag used. Do not rely on
`"default"` during benchmarks.

Use:

```bash
TAILOR_LLM_MODEL=<model-tag> python3 -m tailor run --job-id <job-id>
```

## What The Tailor Actually Needs

The tailor is not just writing prose. It is satisfying a set of hard and soft
constraints.

### Hard Constraints

These are enforced by code and should be treated as pass/fail.

Relevant files:

- `tailoring/QUALITY_BAR.md`
- `tailoring/tailor/config.py`
- `tailoring/tailor/validator.py`
- `tailoring/tailor/compiler.py`

Resume must:

- Compile with `pdflatex`.
- Render to exactly one page.
- Keep canonical section order.
- Match expected work-experience bullet counts.
- Stay within body-length tolerance.
- Avoid Python literal artifacts like `['...']`.
- Avoid escaped newline artifacts like `\n`.
- Preserve immutable facts: employer names, titles, dates.

Cover letter must:

- Compile with `pdflatex`.
- Stay within body-length tolerance.
- Avoid Python literal artifacts.
- Avoid escaped newline artifacts.
- Add narrative value beyond the resume.

### Soft Constraints

These require human or agent judgment.

A strong tailor model should:

- Identify the most important JD requirements.
- Match JD requirements to real candidate evidence.
- Use persona/vignette material naturally.
- Avoid generic corporate filler.
- Avoid unsupported claims, fake metrics, and invented tools.
- Produce specific, credible, role-aligned wording.
- Improve after validator feedback rather than thrashing.

Relevant files:

- `tailoring/tailor/writer.py`
- `tailoring/tailor/analyzer.py`
- `tailoring/tailor/persona.py`
- `tailoring/tailor/grounding.py`
- `tailoring/persona/`
- `tailoring/skills.json`

## Benchmark Philosophy

Use a funnel:

1. Quick synthetic tests reject obviously bad models.
2. Real tailoring runs test actual pipeline performance.
3. A small regression set prevents overfitting to one job.

Do not pick a winner from a single prompt or a single timing number.

## Level 1: Quick Synthetic Benchmark

Use this first to reject models that cannot handle the basic building blocks.

Script:

```bash
cd /Users/conner/Documents/TexTailor/tailoring
python3 benchmark_models.py <model-a> <model-b> <model-c>
```

Relevant file:

- `tailoring/benchmark_models.py`

The script tests:

- JSON analysis output.
- LaTeX document generation.
- Strategy JSON output.
- Time per task.
- Basic output-shape checks.

What to look for:

- All JSON tests parse successfully.
- LaTeX output contains a complete document.
- Strategy includes skills tailoring, experience rewrites, and risk controls.
- Output is not empty or wildly short.
- Runtime is not obviously impractical.

Reject a model immediately if:

- It cannot return valid JSON.
- It wraps everything in markdown despite instructions.
- It omits `\documentclass`, `\begin{document}`, or `\end{document}`.
- It times out repeatedly.
- It emits thinking text, refusals, or unrelated commentary.

Important limitation:

This benchmark is only a smoke test. Passing it does not mean the model is good
enough for production tailoring.

## Level 2: Real Tailoring Run

This is the core benchmark.

Run one real job through the full pipeline:

```bash
cd /Users/conner/Documents/TexTailor/tailoring
TAILOR_LLM_MODEL=<model-tag> python3 -m tailor run --job-id <job-id>
```

Then validate:

```bash
python3 -m tailor validate output/<slug>
```

Collect the generated package:

```text
tailoring/output/<slug>/
```

Inspect:

- `meta.json`
- `analysis.json`
- `resume_strategy.json`
- `cover_strategy.json`
- `Conner_Jordan_Resume.tex`
- `Conner_Jordan_Resume.pdf`
- `Conner_Jordan_Cover_Letter.tex`
- `Conner_Jordan_Cover_Letter.pdf`
- `llm_trace.jsonl`

Record:

- Model tag.
- Job ID.
- Job title/company.
- Total runtime.
- Number of LLM calls.
- Resume attempts.
- Cover attempts.
- Final validation status.
- Failure reasons, if any.
- Whether the final resume is one page.
- Whether the cover letter feels specific and grounded.

## Level 3: Regression Set

Benchmark each serious candidate on multiple jobs.

Use at least 3 jobs. Prefer 5 if time allows.

Suggested set:

1. Security/platform role.
2. Backend/software role.
3. AI/ML infrastructure role.
4. Long or messy JD.
5. A role that previously caused formatting, grounding, or fit problems.

A model is not a default candidate unless it performs consistently across the
set. One great run is not enough.

## Scoring Rubric

Score each model out of 100.

### Reliability: 40 Points

This is the most important category.

Give points for:

- Valid JSON in analysis and strategy.
- Valid, extractable LaTeX.
- Successful `pdflatex` compile.
- Final validator pass.
- Low retry count.
- Stable behavior across multiple jobs.
- No empty responses or timeout loops.

Suggested scoring:

- 40: Passes all runs, usually first or second attempt.
- 30: Passes most runs, occasional retry.
- 20: Passes some runs but needs repeated repair.
- 10: Frequent invalid output or validation failures.
- 0: Cannot complete the pipeline.

### Grounded Intelligence: 25 Points

This measures whether the model understands the job and uses real evidence.

Give points for:

- Correctly identifies the JD's core requirements.
- Maps requirements to real skills and experience.
- Uses persona vignettes when helpful.
- Keeps claims factual.
- Avoids invented tools, metrics, responsibilities, and outcomes.
- Makes good prioritization decisions.

Suggested scoring:

- 25: Specific, grounded, and strategically sharp.
- 18: Mostly grounded, some generic phrasing.
- 12: Understands the JD but weak evidence matching.
- 6: Generic or occasionally unsupported.
- 0: Hallucinates or misrepresents experience.

### Document Quality: 20 Points

This measures the final artifacts.

Give points for:

- Resume reads naturally and fits one page.
- Resume emphasizes the right experience for the JD.
- Bullets are concrete and technically credible.
- Cover letter adds narrative value beyond the resume.
- Voice is confident, direct, and non-generic.
- No markdown fences, raw JSON, Python literals, or escaped newlines.

Suggested scoring:

- 20: Ready to use with minor or no edits.
- 15: Good, needs light editing.
- 10: Structurally valid but bland.
- 5: Awkward, generic, or repetitive.
- 0: Not usable.

### Speed: 10 Points

Speed is important, but it is not the first filter.

Measure full package runtime, not just one chat call.

Suggested scoring:

- 10: Under 5 minutes.
- 8: 5-10 minutes.
- 5: 10-20 minutes.
- 2: 20-40 minutes.
- 0: Over 40 minutes or frequent timeouts.

Adjust if the model is exceptionally high quality. A slower model can still win
if it avoids retries and produces much better artifacts.

### Operational Fit: 5 Points

Give points for:

- Runs reliably in Ollama.
- Fits local memory without severe system slowdown.
- Works with the file-lock concurrency model.
- Has sufficient context length.
- Does not require fragile custom runtime setup.

Suggested scoring:

- 5: Easy, stable, repeatable.
- 3: Works but heavy.
- 1: Fragile or very resource intensive.
- 0: Not practical locally.

## Minimum Bar For Default Tailor Model

A model can become the default tailor model only if:

- It scores at least 85 overall.
- It passes every hard validator gate in the regression set.
- It has no hallucination or unsupported-claim failures.
- It completes most packages in under 10 minutes.
- It works from an explicit Ollama model tag.

If no model meets this bar, do not set a default yet. Keep explicit selection
and document the best current candidate as experimental.

## Model Comparison Template

Use this format for each model:

```markdown
## Model: <model-tag>

### Summary
- Overall score:
- Recommendation: default candidate / fallback / reject
- Best use:
- Main concern:

### Environment
- Ollama tag:
- Machine:
- Date:
- Runtime notes:

### Quick Benchmark
- JSON analysis:
- LaTeX generation:
- Strategy JSON:
- Notable failures:

### Real Tailor Runs
- Job IDs:
- Total runtime per job:
- Resume attempts:
- Cover attempts:
- Validator result:
- Failure reasons:

### Quality Notes
- JD understanding:
- Evidence grounding:
- Resume quality:
- Cover letter quality:
- Formatting/artifacts:

### Decision
- Keep testing / promote / reject:
- Why:
```

## Result Table Template

```markdown
| Model | Reliability /40 | Intelligence /25 | Quality /20 | Speed /10 | Ops /5 | Total | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| <model> |  |  |  |  |  |  |  |
```

## How To Interpret Common Outcomes

### Fast But Fails Validation

Reject for default use. It may be useful for low-risk drafts, but not for the
main tailor pipeline.

### Slow But First-Try Passes

Consider seriously. A slow first-pass model may be faster overall than a quick
model that needs three retries.

### Good Resume, Weak Cover Letter

Do not promote yet. The cover letter is a first-class artifact and should use
persona/vignette material, not just restate the resume.

### Good Output, Occasional Unsupported Claims

Treat as a major risk. Unsupported claims are worse than bland writing because
they can create false application material.

### Great Smoke Test, Bad Real Run

Reject or demote. The real pipeline is the source of truth.

## Current Candidate Notes

Known benchmark script defaults:

```text
qwen3:30b
gemma4:31b-it-q8_0
```

Suggested starting candidates:

1. `qwen3:30b`
2. Strongest available 30B-ish Gemma/Qwen/Mistral model in Ollama
3. `qwen2.5:7b` as a speed baseline only

Do not assume `qwen2.5:7b` is strong enough for final tailoring. It is currently
appropriate for scrape relevance, not necessarily for resume and cover-letter
generation.

## Hardware-Specific Shortlist

Current machine:

```text
Mac mini
Apple M4 Pro
14 CPU cores
20 GPU cores
64 GB unified memory
```

This is a strong local inference box for 24B-35B class models. Because tailoring
is an offline/high-value workflow, benchmark agents may use most of the machine.
Prioritize quality over interactivity, but reject models that make a full package
feel impractical.

### Practical Model Class

Best target class:

```text
24B-35B models, preferably Q4/Q5/Q6 or efficient MoE variants
```

Why:

- 64 GB unified memory leaves enough room for 20-35 GB model weights plus KV
  cache, Python, Ollama, LaTeX, and dashboard processes.
- Tailoring prompts can be long because they include baseline LaTeX, job text,
  persona, vignettes, strategy, draft, QA feedback, and validator failures.
- 70B-class models may fit at 4-bit, but on this M4 Pro/20-core GPU they are
  likely to be slow enough that retry-heavy tailoring becomes painful.

### Installed Models To Benchmark First

The local Ollama inventory already includes several serious candidates.

Benchmark in this order:

1. `qwen3.6:35b-a3b-coding-nvfp4`
   - Best first candidate.
   - 21 GB installed size.
   - MoE-style 35B/A3B shape should give strong capability without dense-35B
     latency.
   - Likely best balance for structured reasoning, coding-like LaTeX repair,
     and pipeline reliability.

2. `gemma4:31b-it-q8_0`
   - 33 GB installed size.
   - Use as the high-quality/heavy comparison.
   - Q8 should preserve quality well, but may be slower and leave less context
     headroom.
   - Good candidate if it produces noticeably better writing and fewer retries.

3. `gemma4:31b`
   - 19 GB installed size.
   - Compare against the Q8 variant to see whether smaller quantization is good
     enough.
   - If quality is close to Q8 and speed is better, this may be preferable.

4. `gemma4:26b`
   - 17 GB installed size.
   - Strong practical candidate if 31B models are too slow.
   - May offer better memory headroom for long context.

5. `qwen3:30b`
   - 18 GB installed size.
   - Good general reasoning baseline.
   - Should be compared directly against the newer `qwen3.6:35b-a3b...` model.

6. `qwen3-coder:30b`
   - 18 GB installed size.
   - Benchmark because tailoring has code-like demands: JSON, LaTeX, repair,
     format discipline.
   - Watch for overly code-focused prose or weaker cover-letter voice.

7. `gpt-oss:latest`
   - 13 GB installed size.
   - Useful as a fast reasoning/agent baseline.
   - Promote only if it stays grounded and follows schema/LaTeX instructions.

8. `gemma3:12b-it-qat`
   - 8.9 GB installed size.
   - Fast fallback candidate.
   - Not expected to beat 30B-class models on final quality, but useful for
     speed comparison.

9. `qwen2.5:7b`
   - 4.7 GB installed size.
   - Scrape-gate baseline only.
   - Include in benchmarks to quantify the quality gap, not as a likely default.

### Models Worth Pulling If Available

If benchmark agents are allowed to install more Ollama models, consider:

1. `qwen3.5:35b` or closest available Qwen 35B-A3B tag
   - Research indicates this class is strong on Apple Silicon and practical in
     32-64 GB unified memory.
   - Good fit for agentic/coding-adjacent tasks.

2. `qwen3.5:27b` or closest available Qwen 27B tag
   - Potential sweet spot if 35B variants are too slow.
   - Useful comparison against `gemma4:26b`.

3. `llama3.3:70b`
   - Only test if agents have time and can tolerate slow runs.
   - Treat as an upper-bound quality experiment, not the likely default on this
     M4 Pro.

Do not spend time on tiny models unless establishing a speed floor.

### Expected Winner Profile

Most likely default candidates:

1. `qwen3.6:35b-a3b-coding-nvfp4`
2. `gemma4:31b` or `gemma4:31b-it-q8_0`
3. `qwen3:30b`

Most likely fast fallback:

```text
gemma4:26b or gpt-oss:latest
```

Most likely scrape-only model:

```text
qwen2.5:7b
```

### Hardware Decision Rules

Promote a heavy model only if it materially reduces retries or improves final
artifact quality. A 33 GB model is worth it if it passes first try and writes a
better cover letter. It is not worth it if a 17-21 GB model produces the same
quality with less latency.

For this machine, prefer:

- A 20-22 GB excellent model over a 33 GB model with only marginal quality gain.
- A first-try 30B model over a faster 12B model that needs repair loops.
- A slower grounded model over a faster hallucination-prone model.

Reject:

- Any model that regularly fails JSON or LaTeX.
- Any model that invents claims.
- Any model that pushes full package runtime beyond practical use without a
  clear quality advantage.

## Final Recommendation Format

At the end of the benchmark work, report:

```markdown
# Tailor Model Benchmark Results

## Recommendation
Default tailor model: `<model-tag>` or "no default yet"

Why:
- ...

## Ranking
1. `<model>` - score, reason
2. `<model>` - score, reason
3. `<model>` - score, reason

## Hard Failures
- ...

## Follow-Up Work
- ...
```

The final recommendation should clearly separate:

- Best model for scrape relevance.
- Best model for full tailoring.
- Fast fallback model.
- Models rejected and why.
