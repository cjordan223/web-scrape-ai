# Tailoring Engine — Performance Evaluation

**Date:** 2026-04-08  
**Scope:** Full tailoring run pipeline (`tailor/__main__.py` → analysis → resume → cover → validation)

---

## Executive Summary

A typical tailoring run takes **7–10 minutes** (happy path) and up to **22 minutes** on retry-heavy runs. The pipeline is **entirely sequential** — every LLM call, every `pdflatex` invocation, every file read waits for the previous step. The two largest time sinks are:

1. **LLM inference** — 7–9 sequential calls per attempt, 30–120s each
2. **`pdflatex` compilation** — 2 runs per compile × up to 4 compile cycles = 8 subprocess invocations

Below are the specific opportunities ranked by estimated time savings.

---

## 1. Parallelize Resume and Cover Letter Generation

| Metric | Current | Potential |
|--------|---------|-----------|
| Wall time | Resume + Cover sequential | Resume ∥ Cover |
| Savings | — | ~3–4 min per run |

**What:** `__main__.py:147` iterates `[("Resume", ...), ("Cover Letter", ...)]` sequentially. Resume and cover share the analysis output but are otherwise independent — separate strategies, separate LLM calls, separate compilations.

**Why it's safe:** The cover letter reads `resume_strategy.json` for cross-document consistency (`writer.py:1569`), but this is optional (guarded by `if resume_strat_path.exists()`). If resume runs in parallel, the cover can either skip this read or the resume strategy step can be extracted and run before forking.

**Constraint:** The file lock in `ollama.py` serializes LLM access for local providers (single GPU). This optimization only yields wall-time gains when using **cloud providers** (`use_lock=False`) or a multi-GPU setup. For single-GPU Ollama, the lock would serialize the calls anyway.

**Verdict:** High impact for cloud LLM providers. No impact for single-GPU local inference.

---

## 2. Reduce `pdflatex` Double-Compilation

| Metric | Current | Potential |
|--------|---------|-----------|
| Compiles per fit check | 2 (for LaTeX references) | 1 |
| Total compiles (worst case) | 8 | 4 |
| Savings per run | — | ~40–120s |

**What:** `compiler.py:53` runs `pdflatex` twice per `compile_tex()` call ("for references"). The resume template has **no cross-references, no bibliography, no table of contents** — it's a single-page document with static content.

**Why it matters:** Each `pdflatex` invocation takes 10–30s. The fit-to-page loop (`writer.py:1260–1355`) calls `_inspect_resume_candidate()` up to 4 times (initial + condense + compact + prune), each triggering a full double-compile. That's 4–8 unnecessary second passes.

**Risk:** None for the current template. If cross-references were ever added, the second pass would be needed again.

---

## 3. Cache Baseline File Reads Within a Run

| Metric | Current | Potential |
|--------|---------|-----------|
| `RESUME_TEX` reads | ~4 per run | 1 |
| `SKILLS_JSON` reads | ~3 per run | 1 |
| `COVER_TEX` reads | ~2 per run | 1 |
| Savings | — | Negligible (~50ms) |

**What:** `cfg.RESUME_TEX.read_text()` is called in `analyze_job()`, `write_resume()` (line 1367), `write_cover_letter()` (QA baseline comparison), and `build_grounding_context()`. Similarly, `cfg.SKILLS_JSON.read_text()` + `json.loads()` is repeated in each phase.

**Why it matters:** The I/O itself is fast (~10ms per read), but the JSON parsing of `skills.json` and the regex parsing in `_extract_resume_companies()` are repeated unnecessarily. A run-scoped cache (dict passed through or a simple module-level cache invalidated per run) would eliminate redundant work.

**Risk:** None — these files don't change mid-run.

---

## 4. Cache Grounding Context Across Phases

| Metric | Current | Potential |
|--------|---------|-----------|
| `build_grounding_context()` calls | 3 (analysis, resume, cover) | 1 |
| Savings | — | ~100–150ms + prompt consistency |

**What:** `build_grounding_context()` is called separately in `analyzer.py`, `write_resume()` (line 1375), and `write_cover_letter()` (line 1566). Each call re-reads baseline files, re-runs regex extraction, reloads persona texts, and rebuilds the full grounding dict.

**Why it matters:** Beyond the redundant computation, rebuilding grounding independently risks subtle differences if the extraction logic is non-deterministic (regex match ordering, etc.). Building once and passing through would be both faster and more consistent.

**Risk:** The cover letter variant calls `build_grounding_context(skills_data=skills_data)` without `baseline_tex`, so the grounding output differs slightly. The cache would need to handle both variants, or the full context could be built once and subset per phase.

---

## 5. Skip Fit-to-Page When Draft Is Provably Short

| Metric | Current | Potential |
|--------|---------|-----------|
| Fit loop invocations | Always runs initial compile + inspect | Skip if char ratio < 0.95 |
| Savings | — | ~20–60s when draft is already short |

**What:** `_fit_resume_to_one_page()` always compiles and inspects the resume PDF even when the QA stage already reported the draft is within or under the baseline character count. If `char_ratio < 0.95` (draft shorter than baseline), it's extremely unlikely the PDF overflows to page 2.

**Why it matters:** The initial `_inspect_resume_candidate()` at line 1260 triggers a full compile + `pdfinfo` + `pdftotext` just to check page count. If the text metrics already indicate the content is shorter than baseline (which is known to fit on one page), this compile cycle is wasted.

**Risk:** Low — character count is a strong proxy for page fit. Edge case: a draft with many long LaTeX commands or unusual spacing could still overflow despite low char count, but this is rare with the current template.

---

## 6. Avoid Redundant Validation Compile

| Metric | Current | Potential |
|--------|---------|-----------|
| Resume compiles for validation | 1 (separate from fit loop) | 0 (reuse fit loop PDF) |
| Savings | — | ~20–60s |

**What:** `validate_resume()` in `validator.py` calls `compile_tex()` independently to check PDF pagination. But `_fit_resume_to_one_page()` already compiled the final `.tex` and produced a PDF. The validator recompiles the same `.tex` from scratch.

**Why it matters:** The PDF produced by the fit loop is identical to what the validator would produce. Passing the existing PDF path to the validator (or having the validator check for an existing PDF before recompiling) would save one full compile cycle.

**Risk:** None — same input `.tex`, same output PDF.

---

## 7. Reduce Thinking Model Token Overhead

| Metric | Current | Potential |
|--------|---------|-----------|
| `num_predict` multiplier | 4× `max_tokens` | Configurable per phase |
| Wasted tokens (thinking models) | Up to 12K per call | Reduced by ~50% on QA/humanize |

**What:** `ollama.py:202` applies a blanket `thinking_headroom = max_tokens * 4` for all calls when using Ollama. This accommodates Qwen3's chain-of-thought leakage but is applied uniformly — even for low-complexity phases like QA review and humanize, which don't need 16K token budgets.

**Why it matters:** Thinking models (Qwen3) generate CoT tokens that consume `num_predict` budget. For the strategy and draft phases (complex reasoning), the 4× headroom is justified. For QA (reviewing existing text) and humanize (stylistic polish), the actual reasoning overhead is much smaller. Reducing `num_predict` on these phases would reduce inference time proportionally.

**Risk:** Setting `num_predict` too low could cause truncated output. The safe approach is a per-phase multiplier (e.g., 4× for strategy/draft, 2× for QA/humanize) rather than a flat cap.

---

## 8. Eliminate `json_mode` Fallback Retry in `chat_expect_json()`

| Metric | Current | Potential |
|--------|---------|-----------|
| LLM calls on JSON parse failure | 2 (original + regen) | 1 (better prompt engineering) |
| Frequency | Occasional | — |

**What:** `ollama.py:437–459` — when the initial `json_mode=True` response can't be parsed, a second full LLM call is made with a "strict JSON generator" system prompt. This doubles the cost of that phase.

**Why it matters:** The regeneration prompt truncates the original system prompt to 3000 chars and the user prompt to 12000 chars, losing context. A better approach: (a) improve the initial prompt to reduce parse failures, (b) use `extract_json()` repair logic more aggressively before falling back to a full regen call, or (c) for cloud providers, use structured output / tool-use mode which guarantees valid JSON.

**Risk:** Removing the fallback entirely would cause hard failures. The optimization is to reduce how often it triggers, not to remove it.

---

## 9. Pre-resolve `pdflatex` Binary Path Once

| Metric | Current | Potential |
|--------|---------|-----------|
| `_resolve_pdflatex()` calls | 1 per `compile_tex()` call (up to 8/run) | 1 per run |
| Savings | — | Negligible (~5ms) |

**What:** `compiler.py:15–28` resolves the `pdflatex` binary path by checking env vars, `shutil.which()`, and multiple filesystem paths on every compile call.

**Risk:** None — the binary doesn't move mid-run.

---

## 10. Use Streaming for Lock-Holding Duration

| Metric | Current | Potential |
|--------|---------|-----------|
| Lock held during | Full request + response | Only during request dispatch |

**What:** The file lock in `ollama.py:183` is held for the entire duration of the LLM call — including waiting for the full response. For local inference on a single GPU, this is correct (concurrent requests would queue server-side anyway). But for cloud providers with `use_lock=False`, this is already a no-op, so no change needed there.

**Potential refinement for local:** If the Ollama server supports request queuing properly, the lock could be released after the request is dispatched rather than after the response returns. However, Ollama's behavior with concurrent requests is undefined, so this is risky.

**Verdict:** Not recommended for local providers. Already optimized for cloud.

---

## Summary: Prioritized Recommendations

| # | Optimization | Est. Savings | Risk | Complexity |
|---|-------------|-------------|------|------------|
| **2** | Single `pdflatex` pass (no double-compile) | 40–120s | None | Low |
| **6** | Reuse fit-loop PDF in validation | 20–60s | None | Low |
| **5** | Skip fit compile when char ratio < 0.95 | 20–60s | Low | Low |
| **7** | Per-phase `num_predict` multiplier | 30–90s | Low | Low |
| **1** | Parallel resume + cover (cloud only) | 3–4 min | None | Medium |
| **4** | Cache grounding context across phases | ~150ms | Low | Medium |
| **8** | Reduce JSON regen fallback triggers | 30–120s (when triggered) | Low | Medium |
| **3** | Cache baseline file reads | ~50ms | None | Low |
| **9** | Pre-resolve pdflatex path | ~5ms | None | Trivial |

**Quick wins (items 2, 5, 6):** Eliminating the unnecessary second `pdflatex` pass and reusing compiled PDFs could shave **1–3 minutes** off every run with zero risk to output quality.

**Largest single gain (item 1):** Parallelizing resume and cover generation saves **3–4 minutes** but only when using cloud LLM providers that don't require the file lock.

**Token efficiency (item 7):** Reducing `num_predict` headroom on low-complexity phases (QA, humanize) directly reduces inference time on thinking models.
