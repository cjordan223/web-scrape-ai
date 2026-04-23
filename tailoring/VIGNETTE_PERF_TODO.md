# Vignette System — Performance Tuning TODO

Session handoff. Earlier work added observability so remaining tuning can be evidence-driven.

## Done

- **5. Per-run selection logging** — `tailor/writer.py:_log_vignette_selection` emits `vignette_selection` trace event at all 4 stages (strategy/draft × resume/cover). Metadata: budget, diverse flag, candidates scored, selected with scores, skipped with reason, budget usage.
- **6. Coverage audit** — `python -m tailor coverage [--json]`. Lists category coverage, flags missing / overrepresented (≥3) / orphan categories.
- **11. Deleted stale `VIGNETTE_INTERVIEW.md`** — all 5 "gap" categories already had vignettes. Preserved accurate info in `README.md` (new Persona & Vignettes section).
- **12. Rebalanced overrepresented categories** — tightened broad frontmatter tags without deleting stories. Current coverage has no missing, overrepresented, or orphan categories.
- **13. Gap audit follow-up** — re-ran `python -m tailor coverage --json`; all 19 categories still have at least one vignette.
- **1-4. Selector scoring tune** — added phrase/token keyword matching, deterministic tie-breaks, score-density tie-breaks, and primary-category-only diversity.
- **7. Budget saturation metric** — `python -m tailor vignette-saturation [--json]` aggregates `budget_used / budget_chars` from trace logs.
- **8-10. Integrity guards** — added `tests/test_persona_vignettes.py` for category registry validity, keyword/category overlap, deterministic phrase matching, and diverse selection behavior.
- **14-15. Prompt-layer cleanup** — cover prompt now treats selected source blocks as authority and includes a negative example against braiding details across `### Source project:` blocks.
- **16. Memoized selection** — `PersonaStore` caches selection metadata by `(analysis, budget, diverse)`.

## Files touched

- `tailor/persona.py` — added `_stage_budget`, `_select_with_meta`, `explain_selection`. `for_strategy`/`for_draft` now share budget table.
- `tailor/writer.py` — added `_log_vignette_selection`, hooked 4 callsites.
- `tailor/__main__.py` — added `coverage` CLI subcommand.
- `tailoring/README.md` — rewrote. Now documents vignette system, fixed stale auto-discovery claim.

## Live findings (from first trace + coverage run)

- **No missing categories.** 18 vignettes cover all 19 declared skills.json categories.
- **Overrepresented:** none after retagging.
- **Real budget bug fixed:** cover strategy budget is now 1500 chars, matching the other stages, so `identity_access.md` can fit.

## Remaining TODOs (priority order)

### Follow-up data collection

- [ ] Run 10-20 real tailoring jobs across varied JDs and inspect `python -m tailor vignette-saturation --json` plus `vignette_selection` trace events. The code-level tuning is complete, but the empirical sample is still small.
- [ ] Consider adding a second story for one-vignette categories after observing real misses. Current coverage is complete, but robustness is uneven by design.

## How to pick up

1. Run `python -m tailor coverage` to re-check category state.
2. Run `python -m tailor run --job-id <id>` on a recent JD, inspect `output/<slug>/llm_trace.jsonl` for `event_type: vignette_selection`. Confirm trace output is useful.
3. Start with item 12 (rebalance) — biggest observable lever with current data.
4. Items 1–4 (scoring) benefit from trace samples across 10–20 JDs — collect before tuning.

## Reference

- Budgets: `tailor/persona.py:_STAGE_BUDGETS` — all strategy/draft cover/resume vignette budgets are 1500 chars.
- Scoring weights: category +3, company_type +2, keyword +1.
- Render format: each vignette wrapped in `### Source project: <stem>` header to prevent braiding.
