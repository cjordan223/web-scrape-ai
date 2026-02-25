"""Generate tailored LaTeX documents using a 3-stage LLM pipeline.

Each document (resume, cover letter) goes through:
  1. Strategy  — LLM produces a JSON writing plan (what to emphasize, what to avoid)
  2. Draft     — LLM generates full LaTeX from baseline template + strategy + analysis
  3. QA        — LLM reviews the draft for style, factual grounding, and structural compliance

The QA stage receives computed metrics (char count ratio, bullet count) so it can
fix structural issues before the hard-gate validator runs. See QUALITY_BAR.md for gates.

System prompts are defined as module-level constants (_RESUME_DRAFT_SYSTEM, etc.).
To tune LLM behavior, edit the prompt strings directly. To tune validation thresholds,
edit config.py.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from . import config as cfg
from .ollama import chat, chat_expect_json, extract_latex
from .selector import SelectedJob
from .validator import _extract_body_text, _count_resume_bullets

logger = logging.getLogger(__name__)

_STYLE_GUARDRAILS = """\
STYLE GUARDRAILS (HARD):
- No em dash or en dash characters anywhere. Use commas, periods, or parentheses instead.
- No hallucinations: do not invent projects, tools, scope, timelines, outcomes, or responsibilities.
- No fake metrics: only keep quantitative claims if they are directly supported by provided source material.
- If a number is uncertain, remove the number and keep a factual qualitative claim instead.
- Avoid empty corporate language. Prefer concrete technical actions and outcomes."""

_RESUME_STRATEGY_SYSTEM = f"""\
You are a resume tailoring strategist. Build a precise writing plan for a LaTeX generator.

{_STYLE_GUARDRAILS}

Return ONLY JSON:
{{
  "summary_strategy": "one sentence describing summary angle and tone",
  "skills_strategy": "how to emphasize relevant skills categories and line format",
  "experience_focus": [
    {{
      "company": "University of California|Great Wolf Resorts|Simple.biz",
      "must_highlight": ["key relevance theme 1", "key relevance theme 2"],
      "safe_metrics_to_keep": ["specific numeric claims known to be grounded in source"],
      "claims_to_avoid": ["specific risky claim patterns to avoid"]
    }}
  ],
  "risk_controls": [
    "specific anti-hallucination and anti-corporate-speak reminders for final draft"
  ]
}}"""

_RESUME_DRAFT_SYSTEM = f"""\
You are a LaTeX resume tailoring expert.

{_STYLE_GUARDRAILS}

Output requirements:
- Return ONLY the complete .tex file content. No explanations, no markdown fences.
- Preserve the EXACT LaTeX preamble, commands, and document structure from the template.
- Preserve ALL \\newcommand definitions exactly as they appear.
- Keep section order: Professional Summary, Technical Skills, Work Experience, Education, Certifications.
- Professional Summary must be exactly one sentence.
- Bullet distribution is fixed:
  - University of California: exactly 6 \\resumeItem bullets
  - Great Wolf Resorts: exactly 5 \\resumeItem bullets
  - Simple.biz: exactly 3 \\resumeItem bullets
  - Total: exactly 14 bullets
- LENGTH IS CRITICAL: Your output must match the baseline template's body length within ±8%.
  Each bullet should be roughly the same length as the corresponding baseline bullet.
  Do NOT shorten bullets. If you tailor content, keep bullet length comparable by adding relevant detail.
  Shorter output WILL fail validation. When in doubt, write longer rather than shorter.
- Escape LaTeX special characters (for example '&' as '\\&', '_' as '\\_').
- Do not output literal \\n tokens.
- Do not output Python list syntax.
- Keep content factual and grounded in provided source content only."""

_RESUME_QA_SYSTEM = f"""\
You are a strict final quality reviewer for LaTeX resumes.

{_STYLE_GUARDRAILS}

Task:
- Review draft LaTeX for factual grounding, style violations, and LaTeX safety.
- Repair issues directly and return corrected LaTeX only.
- Preserve the exact structure and fixed bullet counts (exactly 14 \\resumeItem: 6 + 5 + 3).
- Remove or rewrite risky claims rather than inventing evidence.
- CRITICAL LENGTH CHECK: Compare the draft against the baseline template provided.
  The output body text must be within ±8% of the baseline's character count.
  If the draft is shorter than the baseline, expand bullets with additional grounded technical detail
  until the length matches. Do NOT trim or shorten content. Every bullet should be a substantial
  sentence comparable in length to its baseline counterpart."""

_COVER_STRATEGY_SYSTEM = f"""\
You are a cover-letter strategist creating a concise writing plan.

{_STYLE_GUARDRAILS}

Return ONLY JSON:
{{
  "opening_angle": "how to connect role/company and candidate fit",
  "paragraph_focus": [
    "paragraph 1 focus",
    "paragraph 2 focus",
    "paragraph 3 focus",
    "paragraph 4 focus"
  ],
  "voice_controls": [
    "specific wording/tone controls to avoid fluff and keep concrete"
  ],
  "claims_to_avoid": [
    "specific risky claims or inflated phrasing to avoid"
  ]
}}"""

_COVER_DRAFT_SYSTEM = f"""\
You are a LaTeX cover letter tailoring expert.

{_STYLE_GUARDRAILS}

Output requirements:
- Return ONLY complete .tex content. No markdown fences.
- Preserve exact LaTeX preamble and document structure from template.
- Replace [COMPANY_NAME] in \\companyname.
- Replace [DATE] with today's date.
- Keep a 4-paragraph structure: opening, current role, prior experience, closing.
- Keep tone grounded, direct, and technically credible.
- Do not use literal \\n tokens or Python list syntax.
- Keep content factual and grounded in provided source text only."""

_COVER_QA_SYSTEM = f"""\
You are a strict final quality reviewer for LaTeX cover letters.

{_STYLE_GUARDRAILS}

Task:
- Review draft LaTeX for factual grounding, style violations, and LaTeX safety.
- Repair issues directly and return corrected LaTeX only.
- Preserve template structure and 4-paragraph flow.
- Remove or rewrite risky claims rather than inventing evidence."""


def _strip_disallowed_dashes(text: str) -> str:
    """Normalize Unicode dash variants to ASCII fallback punctuation."""
    return text.replace("\u2014", ", ").replace("\u2013", ", ")


def _resume_strategy(
    job: SelectedJob,
    analysis: dict,
    baseline: str,
    skills_data: dict,
    attempt: int,
    trace_recorder: Callable[[dict], None] | None = None,
) -> dict:
    user_prompt = (
        f"## Baseline Resume Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Skills Inventory\n{json.dumps(skills_data['skills_inventory'], indent=2)}\n\n"
        f"## Resume-Ready Skill Lines\n{json.dumps(skills_data['resume_ready_outputs'], indent=2)}\n\n"
        f"Target Role: {analysis.get('role_title', job.title)}\n"
        f"Target Company: {analysis.get('company_name', job.company)}\n"
        f"Summary Angle: {analysis.get('summary_angle', 'general security engineering')}\n"
    )
    return chat_expect_json(
        _RESUME_STRATEGY_SYSTEM,
        user_prompt,
        max_tokens=1800,
        temperature=0.2,
        trace={
            "doc_type": "resume",
            "phase": "strategy",
            "attempt": attempt,
            "response_parse_kind": "json",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
    )


def _cover_strategy(
    job: SelectedJob,
    analysis: dict,
    baseline: str,
    soul: str,
    attempt: int,
    trace_recorder: Callable[[dict], None] | None = None,
) -> dict:
    from datetime import date
    today = date.today().strftime("%B %d, %Y")
    user_prompt = (
        f"## Baseline Cover Letter Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Candidate Persona\n{soul[:4000]}\n\n"
        f"Target Role: {analysis.get('role_title', job.title)}\n"
        f"Target Company: {analysis.get('company_name', job.company)}\n"
        f"Today's Date: {today}\n"
        f"Tone Notes: {analysis.get('tone_notes', 'standard professional tone')}\n"
    )
    return chat_expect_json(
        _COVER_STRATEGY_SYSTEM,
        user_prompt,
        max_tokens=1400,
        temperature=0.2,
        trace={
            "doc_type": "cover",
            "phase": "strategy",
            "attempt": attempt,
            "response_parse_kind": "json",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
    )


def write_resume(
    job: SelectedJob,
    analysis: dict,
    output_dir: Path,
    previous_errors: str | None = None,
    attempt: int = 1,
    trace_recorder: Callable[[dict], None] | None = None,
) -> Path:
    """Generate a tailored resume with a 3-stage pipeline: strategy, draft, QA."""
    baseline = cfg.RESUME_TEX.read_text()
    skills_data = json.loads(cfg.SKILLS_JSON.read_text())
    strategy = _resume_strategy(
        job,
        analysis,
        baseline,
        skills_data,
        attempt=attempt,
        trace_recorder=trace_recorder,
    )
    (output_dir / "resume_strategy.json").write_text(json.dumps(strategy, indent=2))

    draft_prompt = (
        f"## Baseline Resume Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Resume Strategy\n{json.dumps(strategy, indent=2)}\n\n"
        f"## Skills Inventory\n{json.dumps(skills_data['skills_inventory'], indent=2)}\n\n"
        f"## Resume-Ready Skill Lines\n{json.dumps(skills_data['resume_ready_outputs'], indent=2)}\n\n"
        f"Target Role: {analysis.get('role_title', job.title)}\n"
        f"Target Company: {analysis.get('company_name', job.company)}\n"
        f"Summary Angle: {analysis.get('summary_angle', 'general security engineering')}\n"
    )

    if previous_errors:
        draft_prompt += f"\n## PREVIOUS ATTEMPT ERRORS (CRITICAL: FIX THESE)\n{previous_errors}\n"

    draft_raw = chat(
        _RESUME_DRAFT_SYSTEM,
        draft_prompt,
        max_tokens=8192,
        temperature=0.25,
        trace={
            "doc_type": "resume",
            "phase": "draft",
            "attempt": attempt,
            "response_parse_kind": "latex",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
    )
    draft_tex = extract_latex(draft_raw)
    draft_tex = _strip_disallowed_dashes(draft_tex)

    # Compute length metrics so the QA model knows exactly what to fix
    baseline_body_len = len(_extract_body_text(baseline))
    draft_body_len = len(_extract_body_text(draft_tex))
    draft_bullets = _count_resume_bullets(draft_tex)
    char_ratio = draft_body_len / baseline_body_len if baseline_body_len else 1.0
    length_status = (
        f"DRAFT IS TOO SHORT ({draft_body_len} chars vs baseline {baseline_body_len}, ratio {char_ratio:.2f}). "
        f"You MUST expand bullet content to reach at least {int(baseline_body_len * 0.85)} chars. "
        f"Add grounded technical detail to each bullet until length matches."
        if char_ratio < 0.85
        else f"Length OK ({draft_body_len} vs baseline {baseline_body_len}, ratio {char_ratio:.2f})"
    )
    bullet_status = (
        f"BULLET COUNT WRONG: {draft_bullets} found, need exactly 14 (6 + 5 + 3). Fix this."
        if draft_bullets != cfg.RESUME_BULLET_COUNT
        else f"Bullet count OK ({draft_bullets})"
    )

    qa_prompt = (
        f"## Baseline Resume Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Resume Strategy\n{json.dumps(strategy, indent=2)}\n\n"
        f"## Draft Resume\n```latex\n{draft_tex}\n```\n\n"
        f"## STRUCTURAL CHECKS (fix these before anything else)\n"
        f"- {length_status}\n"
        f"- {bullet_status}\n\n"
        f"## Reviewer Focus\n"
        f"- remove em/en dashes\n"
        f"- remove or soften ungrounded percentage claims\n"
        f"- replace generic corporate language with concrete technical phrasing\n"
    )
    if previous_errors:
        qa_prompt += f"\n## PRIOR VALIDATION FAILURES TO FIX\n{previous_errors}\n"

    qa_raw = chat(
        _RESUME_QA_SYSTEM,
        qa_prompt,
        max_tokens=8192,
        temperature=0.15,
        trace={
            "doc_type": "resume",
            "phase": "qa",
            "attempt": attempt,
            "response_parse_kind": "latex",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
    )
    tex = _strip_disallowed_dashes(extract_latex(qa_raw))

    out_path = output_dir / "Conner_Jordan_Resume.tex"
    out_path.write_text(tex)
    logger.info("Resume written to %s (%d chars)", out_path, len(tex))
    return out_path


def write_cover_letter(
    job: SelectedJob,
    analysis: dict,
    output_dir: Path,
    previous_errors: str | None = None,
    attempt: int = 1,
    trace_recorder: Callable[[dict], None] | None = None,
) -> Path:
    """Generate a tailored cover letter with a 3-stage pipeline: strategy, draft, QA."""
    baseline = cfg.COVER_TEX.read_text()
    soul = cfg.SOUL_MD.read_text()
    strategy = _cover_strategy(
        job,
        analysis,
        baseline,
        soul,
        attempt=attempt,
        trace_recorder=trace_recorder,
    )
    (output_dir / "cover_strategy.json").write_text(json.dumps(strategy, indent=2))

    from datetime import date
    today = date.today().strftime("%B %d, %Y")

    draft_prompt = (
        f"## Baseline Cover Letter Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Cover Strategy\n{json.dumps(strategy, indent=2)}\n\n"
        f"## Candidate Persona\n{soul[:4000]}\n\n"
        f"Target Role: {analysis.get('role_title', job.title)}\n"
        f"Target Company: {analysis.get('company_name', job.company)}\n"
        f"Today's Date: {today}\n"
        f"Tone Notes: {analysis.get('tone_notes', 'standard professional tone')}\n"
    )

    if previous_errors:
        draft_prompt += f"\n## PREVIOUS ATTEMPT ERRORS (CRITICAL: FIX THESE)\n{previous_errors}\n"

    draft_raw = chat(
        _COVER_DRAFT_SYSTEM,
        draft_prompt,
        max_tokens=4096,
        temperature=0.25,
        trace={
            "doc_type": "cover",
            "phase": "draft",
            "attempt": attempt,
            "response_parse_kind": "latex",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
    )
    draft_tex = _strip_disallowed_dashes(extract_latex(draft_raw))

    qa_prompt = (
        f"## Baseline Cover Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Cover Strategy\n{json.dumps(strategy, indent=2)}\n\n"
        f"## Candidate Persona\n{soul[:4000]}\n\n"
        f"## Draft Cover Letter\n```latex\n{draft_tex}\n```\n\n"
        f"## Reviewer Focus\n"
        f"- remove em/en dashes\n"
        f"- remove or soften ungrounded percentage claims\n"
        f"- reduce corporate-speak and keep concrete language\n"
    )
    if previous_errors:
        qa_prompt += f"\n## PRIOR VALIDATION FAILURES TO FIX\n{previous_errors}\n"

    qa_raw = chat(
        _COVER_QA_SYSTEM,
        qa_prompt,
        max_tokens=4096,
        temperature=0.15,
        trace={
            "doc_type": "cover",
            "phase": "qa",
            "attempt": attempt,
            "response_parse_kind": "latex",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
    )
    tex = _strip_disallowed_dashes(extract_latex(qa_raw))

    out_path = output_dir / "Conner_Jordan_Cover_Letter.tex"
    out_path.write_text(tex)
    logger.info("Cover letter written to %s (%d chars)", out_path, len(tex))
    return out_path
