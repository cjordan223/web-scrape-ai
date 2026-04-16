# Quality Bar

Validation gates enforced by `tailor/validator.py`.
Threshold values live in `tailor/config.py`.

## Resume Gates

| Gate | Config | Default | Requirement |
|---|---|---:|---|
| LaTeX compiles | — | — | `pdflatex` exit code must be `0` |
| Rendered pages | `RESUME_TARGET_PAGES` | 1 | Compiled PDF must render to exactly one page |
| Bullet counts | `RESUME_COMPANY_BULLET_TARGETS` | 6 / 5 / 3 | Normal mode must match per-company targets exactly |
| Pruned-mode floors | `RESUME_COMPANY_BULLET_FLOORS` | 4 / 4 / 3 | Last-resort prune mode may reduce UCOP/GWR only, never Simple.biz |
| Body char ratio | `RESUME_CHAR_TOLERANCE` | ±20% | Generated/body text must stay within tolerance |
| No Python literals | — | — | Rejects `['` / `"]` artifacts |
| No literal `\\n` | — | — | Rejects escaped newline tokens |
| Section order | `RESUME_SECTIONS` | canonical | Required section order must match |

## Cover Letter Gates

| Gate | Config | Default | Requirement |
|---|---|---:|---|
| LaTeX compiles | — | — | `pdflatex` exit code must be `0` |
| Body char ratio | `COVER_CHAR_TOLERANCE` | ±10% | Generated/body text within tolerance |
| No Python literals | — | — | Same as resume |
| No literal `\\n` | — | — | Same as resume |

## Retry Behavior

- `MAX_RETRIES` controls attempts per document.
- Validation failures are fed back to subsequent attempts.
- Error feedback includes concrete counts/targets to help recovery.
- Resume generation now includes fit-stage recovery: condense → last-resort prune.

## Tuning Guidance

Most common tuning is char tolerance.

- If local models produce too-short drafts, increase tolerance slightly.
- If content quality degrades due to over-expansion, decrease tolerance.
- Validate existing outputs without regenerating:

```bash
python -m tailor validate output/<slug>
```

## Resume Fit Awareness

Resume QA prompts include structural checks, and resume generation now inspects rendered PDFs using `pdfinfo` and `pdftotext -bbox-layout` so overflow can be repaired before final validation.

Inspect prompt logic in `tailor/writer.py` (`STRUCTURAL CHECKS` section).
