# Quality Bar

Validation gates that every generated document must pass before the pipeline succeeds.
Gates are enforced by `tailor/validator.py`; thresholds live in `tailor/config.py`.

## Resume Gates

| # | Gate | Config Key | Default | Notes |
|---|------|-----------|---------|-------|
| 1 | LaTeX compilation | — | — | pdflatex must exit 0 |
| 2 | Bullet count | `RESUME_BULLET_COUNT` | 14 | 6 (UCOP) + 5 (GWR) + 3 (Simple.biz). Must match baseline exactly. |
| 3 | Body char count | `RESUME_CHAR_TOLERANCE` | ±15% | Ratio of generated body text to baseline body text. See "Tuning char tolerance" below. |
| 4 | No Python literals | — | — | Rejects `['` or `"]` in .tex |
| 5 | No literal `\n` | — | — | Catches raw `\n` tokens (not LaTeX commands like `\newcommand`) |
| 6 | Section order | `RESUME_SECTIONS` | 5 sections | Must appear in canonical order: Summary, Skills, Experience, Education, Certs |

## Cover Letter Gates

| # | Gate | Config Key | Default | Notes |
|---|------|-----------|---------|-------|
| 1 | LaTeX compilation | — | — | pdflatex must exit 0 |
| 2 | Body char count | `COVER_CHAR_TOLERANCE` | ±10% | Same ratio logic as resume |
| 3 | No Python literals | — | — | Same as resume |
| 4 | No literal `\n` | — | — | Same as resume |

## Retry Behavior

- `MAX_RETRIES` (default 3): each retry reruns the full 3-stage pipeline (strategy, draft, QA)
- Validation failure messages are passed back to the next attempt via `previous_errors`
- Error messages include concrete char counts and targets so the LLM can self-correct

## Tuning Char Tolerance

The char tolerance is the most common failure point. It controls how close the generated
document's body text must be to the baseline template's body text length.

**How body text is measured:** `validator._extract_body_text()` strips LaTeX commands and
preamble, keeping only visible content. This is an approximation — it includes header text
(name, contact info) which doesn't change between runs.

**Why ±15% for resumes:** Local models (tested with Qwen3-coder) consistently produce
resumes 8-15% shorter than baseline. At ±8%, every run failed. At ±15%, first-attempt
pass rate is ~100%. If you switch to a stronger model (GPT-4, Claude), you can safely
tighten to ±8-10%.

**To tune:** Edit `RESUME_CHAR_TOLERANCE` or `COVER_CHAR_TOLERANCE` in `tailor/config.py`.
Run `python -m tailor validate <output_dir>` on existing outputs to test new thresholds
without regenerating.

## QA Stage Length Awareness

The QA (third LLM call) receives computed structural metrics in its prompt:
- Exact char count of draft vs baseline, with ratio
- Bullet count check (pass/fail with counts)
- If the draft is too short, the QA prompt explicitly instructs the model to expand content

This is built in `writer.py` — search for `STRUCTURAL CHECKS` to see the injection point.
