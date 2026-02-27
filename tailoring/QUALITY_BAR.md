# Quality Bar

Validation gates enforced by `tailor/validator.py`.
Threshold values live in `tailor/config.py`.

## Resume Gates

| Gate | Config | Default | Requirement |
|---|---|---:|---|
| LaTeX compiles | — | — | `pdflatex` exit code must be `0` |
| Bullet count | `RESUME_BULLET_COUNT` | 14 | Must match baseline count exactly |
| Body char ratio | `RESUME_CHAR_TOLERANCE` | ±15% | Generated/body text must stay within tolerance |
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

## Tuning Guidance

Most common tuning is char tolerance.

- If local models produce too-short drafts, increase tolerance slightly.
- If content quality degrades due to over-expansion, decrease tolerance.
- Validate existing outputs without regenerating:

```bash
python -m tailor validate output/<slug>
```

## QA Structural Awareness

QA prompts include structural checks (char ratios, bullet counts) so repair can happen before final validation.

Inspect prompt logic in `tailor/writer.py` (`STRUCTURAL CHECKS` section).
