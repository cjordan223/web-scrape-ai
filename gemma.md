# Tailoring Run Performance Evaluation

Based on a thorough review of the `tailoring/` engine codebase, here is an evaluation of the performance bottlenecks and actionable optimizations that can comprehensively speed up the tailoring run without compromising generating accuracy.

## 1. Document-Level Parallelization (Primary Bottleneck)
**Current State:** 
In `tailor/__main__.py`, the generation of the Resume and the Cover Letter operates sequentially inside a `for` loop:
```python
for doc_name, writer_fn, validator_fn in [
    ("Resume", write_resume, validate_resume),
    ("Cover Letter", write_cover_letter, validate_cover_letter),
]:
```
**Optimization:**
Both documents depend exclusively on the same shared `analysis` dictionary, and both output to completely separate final `.tex`/`.pdf` paths. These pipelines are structurally isolated.
Moving the generation pipelines to run concurrently (using `asyncio.gather` or a `concurrent.futures.ThreadPoolExecutor`) will effectively halve the time taken for the document generation and QA phases.

**Accuracy Impact:** Zero. The generation paths do not share state.

## 2. LLM I/O Concurrency
**Current State:**
In `tailor/writer.py`, each document steps through a 3-stage LLM pipeline (`Strategy` &rarr; `Draft` &rarr; `QA`). The API interaction layer (`tailor/ollama.py`) relies on standard, synchronous `requests` (e.g., `chat_expect_json`).

**Optimization:**
While a single document must flow sequentially through its 3 stages, generating *multiple* documents in parallel requires an asynchronous HTTP implementation (like `httpx.AsyncClient`) to prevent the GIL/thread from blocking during LLM inference stalls. 

**Accuracy Impact:** Zero, provided that the underlying Ollama daemon is configured to handle multiple continuous requests without queuing them up sequentially (set `OLLAMA_NUM_PARALLEL > 1` on the host side).

## 3. Compiler Execution Parallelization
**Current State:**
The `compiler.py` module runs `subprocess.run(["pdflatex", ...])` twice synchronously per document.

**Optimization:**
Like LLM request generation, LaTeX compilation is an independent step for each document (`Conner_Jordan_Resume.tex` vs `Conner_Jordan_Cover_Letter.tex`). Dispatching the `pdflatex` compilation step concurrently via background threads or `asyncio.create_subprocess_exec` will shave additional seconds of I/O latency off the tail end of the pipeline.

**Accuracy Impact:** Zero. `compiler.py` already provisions independent temporary directories for each compilation attempt via `tempfile.TemporaryDirectory()`, ensuring the build artifacts cannot collide. 

## 4. Hash-Based Smart Caching for Analysis Pipeline
**Current State:**
The system caches `analysis.json` and supports `--skip-analysis` as a manual bypass. By default, `analyze_job` performs a cache check (found in `analyzer.py`) that strictly checks keys, `job_id`, and `job_url`, relying on the user to assert the `--skip-analysis` flag.

**Optimization:**
Implement deterministic hashing (e.g., `SHA-256`) representing the exact inputs passed into the prompt (`jd_text` payload, `skills_inventory`, and `baseline_tex` content). 
By natively enforcing this hash check before the `analyze_job` LLM call, we can proactively skip the heaviest LLM stage safely if a user re-runs a job that has structurally identical inputs.

**Accuracy Impact:** Zero. Because LLMs are non-deterministic, running the same prompts twice could theoretically generate new data. However, reusing an identical prompt's output cache is widely accepted, reduces monetary/compute costs, and avoids pipeline jitter.

## 5. Token Limiting by Stage
**Current State:**
Functions like `analyze_job` permit up to `max_tokens=4096` directly sent to the inference payload.

**Optimization:**
Tailoring the exact limits per pipeline phase can vastly improve inference speeds:
- `Strategy` JSON output rarely generates beyond `~1000-1500` tokens.
- Restricting `max_tokens` enforces brevity upon local models, reducing the probability of model hallucination bloat and slightly improving "time-to-first-token".

**Accuracy Impact:** Minimal. If appropriately scaled to account for standard response sizes, accuracy will be unaffected while performance overhead is decreased. 
