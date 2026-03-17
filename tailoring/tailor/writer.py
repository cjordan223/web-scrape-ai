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
from .compiler import compile_tex
from .ollama import chat, chat_expect_json, extract_latex
from .persona import get_store as get_persona
from .selector import SelectedJob
from .validator import (
    ResumeFitMetrics,
    _count_resume_bullets,
    _count_resume_bullets_by_company,
    _extract_body_text,
    inspect_resume_pdf_fit,
)

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

SKILLS TAILORING RULES:
- The baseline resume has EXACTLY these 6 skill categories (use these EXACT names, do not rename):
  1. "Languages" (11 items in baseline — do NOT drop any)
  2. "Security Tooling"
  3. "AI/ML and Research" (do NOT rename to "AI for SecOps" or anything else)
  4. "Frameworks and Infrastructure"
  5. "DevOps and CI/CD"
  6. "Databases" (10 items in baseline — do NOT drop any)
- Your strategy should describe how to REORDER items within each category (JD-relevant first).
- You may suggest ADDING items from the Skills Inventory, but NEVER removing baseline items.
- Do NOT rename, delete, merge, or consolidate categories.

Return ONLY JSON:
{{
  "summary_strategy": "one sentence describing summary angle and tone",
  "skills_tailoring": {{
    "Languages": "reordering guidance only — all 11 languages must remain",
    "Security Tooling": "reordering/additions guidance",
    "AI/ML and Research": "reordering/additions guidance",
    "Frameworks and Infrastructure": "reordering/additions guidance",
    "DevOps and CI/CD": "reordering/additions guidance",
    "Databases": "reordering guidance only — all 10 databases must remain"
  }},
  "experience_rewrites": [
    {{
      "company": "University of California, Office of the President",
      "bullet_rewrites": [
        {{
          "baseline_topic": "short description of which baseline bullet to rewrite",
          "rewrite_angle": "how to reframe this bullet to address the JD requirement",
          "jd_requirement_addressed": "the specific JD requirement this rewrite targets"
        }}
      ],
      "bullets_to_preserve": ["baseline bullet topics that need minor polish only"],
      "safe_metrics_to_keep": ["specific numeric claims known to be grounded in source"],
      "claims_to_avoid": ["specific risky claim patterns to avoid"]
    }},
    {{
      "company": "Great Wolf Resorts",
      "bullet_rewrites": [...],
      "bullets_to_preserve": [...],
      "safe_metrics_to_keep": [...],
      "claims_to_avoid": [...]
    }},
    {{
      "company": "Simple.biz",
      "bullet_rewrites": [...],
      "bullets_to_preserve": [...],
      "safe_metrics_to_keep": [...],
      "claims_to_avoid": [...]
    }}
  ],
  "risk_controls": [
    "specific anti-hallucination and anti-corporate-speak reminders for final draft"
  ]
}}

EXPERIENCE REWRITE RULES:
- You MUST provide one entry for EACH of the 3 companies (never collapse or skip one).
- HIGH priority JD requirements should each have a bullet_rewrite targeting a specific baseline bullet.
- LOW priority requirements do NOT need bullet rewrites — the baseline is fine.
- bullets_to_preserve lists bullet topics that should get minor polish only (no reframing).
- Every baseline bullet must appear in EITHER bullet_rewrites OR bullets_to_preserve.
- When the JD mentions a specific tool and the candidate knows it (per skills inventory), the rewrite_angle MUST name that tool.

CRITICAL — WHAT A REWRITE ANGLE IS:
- A rewrite angle tells the draft writer to COMPLETELY RESTRUCTURE the bullet to focus on the JD requirement.
- Do NOT just copy the baseline sentence and add a wrapper. You must instruct the writer to rethink the sentence structure completely.
- ALL baseline metrics (numbers, tool names, concrete outcomes) MUST survive into the rewritten bullet, but you can incorporate additional facts from the Candidate Persona or Skills Inventory if they support the JD requirement and fit the project.
- The candidate persona includes narrative vignettes — specific stories with problem/approach/outcome. Use the most relevant vignette to shape each rewrite angle. The candidate is a "builder-operator" who ships production systems, not an analyst who writes reports.
- Good angle: "Keep 5-source ingestion, 500 drifted assets, 7,000+ endpoints. Rewrite completely to lead with the correlation logic as the candidate's core pattern: reconciling inconsistent records into actionable data. Structure the sentence around the Flask/React/Docker stack as production security tooling built and operated."
- Bad angle: "Reframe to emphasize secure-by-design principles" — vague corporate filler with no connection to baseline facts or candidate voice. NEVER write angles like this.
- Each rewrite_angle MUST reference: (1) specific baseline numbers/tools/outcomes to KEEP, (2) which JD requirement to frame them against, (3) which candidate contribution pattern from the persona applies."""

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
- ONE-PAGE FIT MATTERS: The baseline template is designed to render on exactly one page.
  Keep the resume dense, concise, and information-rich enough to fit that layout.
  Preserve technical substance, but cut filler, redundant lead-ins, and overly long transitions.
  Write entirely new and structurally different sentences when needed, but avoid bloated phrasing.
- Escape LaTeX special characters (for example '&' as '\\&', '_' as '\\_').
- Do not output literal \\n tokens.
- Do not output Python list syntax.
- Keep content factual and grounded in provided source content only.
- TECHNICAL SKILLS — STRICT RULES:
  - The baseline has EXACTLY 6 categories. Use these EXACT \\textbf names (do NOT rename):
    1. Languages (11 items) — reorder only, keep ALL 11
    2. Security Tooling — reorder, may add from inventory
    3. AI/ML and Research — reorder, may add. Do NOT rename to "AI for SecOps"
    4. Frameworks and Infrastructure — reorder, may add
    5. DevOps and CI/CD — reorder, may add
    6. Databases (10 items) — reorder only, keep ALL 10
  - NEVER delete items from Languages or Databases. NEVER drop a category. NEVER merge categories.
  - Tailoring means moving JD-relevant items to the FRONT of each line, not removing irrelevant ones.
  - Example: if the JD emphasizes Rust, change Languages to: Rust, Python, C, C++, TypeScript, Java, SQL, PowerShell, Bash, Swift, Go
- BULLET ORDERING: Within each company's bullets, place bullets addressing HIGH priority JD requirements first. The most JD-relevant bullet should come first.
- BULLET REWRITES ARE MANDATORY: The prompt will list specific bullets to rewrite with explicit angles. You MUST execute them. Do NOT copy the baseline sentence structure. You MUST write a completely new sentence using DIFFERENT verbiage, DIFFERENT sentence structure, and DIFFERENT ordering of information. If a rewritten bullet looks structurally similar to the baseline, it has failed.
- VOICE: Apply the candidate voice and thematic priorities from the persona section to all rewrites. Concrete actions and outcomes. Pragmatic, operationally focused. No corporate filler."""

_RESUME_QA_SYSTEM = f"""\
You are a strict final quality reviewer for LaTeX resumes.

{_STYLE_GUARDRAILS}

Task:
- Review draft LaTeX for factual grounding, style violations, and LaTeX safety.
- Repair issues directly and return corrected LaTeX only.
- Preserve the exact structure and fixed bullet counts (exactly 14 \\resumeItem: 6 + 5 + 3).
- Remove or rewrite risky claims rather than inventing evidence.
- CRITICAL LENGTH CHECK: Compare the draft against the baseline template provided.
  The output body text must stay within ±20% of the baseline's character count.
  If the structural checks say the draft is too short, expand with grounded detail.
  If the structural checks say the draft is too long, tighten phrasing aggressively while
  preserving the factual payload.
  Prefer concise, high-density bullets that can still render on one page with the baseline layout.
- SKILLS CHECK (HARD GATE):
  - Must have EXACTLY 6 categories with these EXACT \\textbf names: Languages, Security Tooling, AI/ML and Research, Frameworks and Infrastructure, DevOps and CI/CD, Databases.
  - Languages must have ALL 11 from baseline (Python, C, C++, TypeScript, Java, SQL, PowerShell, Bash, Swift, Rust, Go). Order may change.
  - Databases must have ALL 10 from baseline (PostgreSQL, MySQL, MongoDB, DynamoDB, SQLite, Redis, Snowflake, ClickHouse, Databricks, vector databases). Order may change.
  - If any category is renamed (e.g., "AI for SecOps" instead of "AI/ML and Research"), fix the name back.
  - If any items are missing from Languages or Databases, restore them."""

_RESUME_FIT_CONDENSE_SYSTEM = f"""\
You are a LaTeX resume compression specialist.

{_STYLE_GUARDRAILS}

Task:
- The current resume rendered to more than one page. Repair the content so it fits back onto one page.
- Return ONLY the complete .tex file content.
- Preserve the exact LaTeX preamble, commands, and section order from the template.
- Preserve all 3 employers and the exact bullet counts: UCOP 6, Great Wolf 5, Simple.biz 3.
- Preserve all factual evidence, named systems, grounded metrics, and JD-relevant tools.
- Do NOT delete bullets, employers, or sections.
- Make the smallest edits that solve fit:
  - tighten summary language
  - shorten low-value phrasing and repetitive lead-ins
  - compress skill-line wording without removing required items
  - shorten bulky UCOP/GWR bullets when they are not central to the JD
  - avoid widow-like one-word lines at the bottom of a page
- If overflow looks marginal, prefer tiny sentence-level edits over broad rewrites."""

_RESUME_FIT_PRUNE_SYSTEM = f"""\
You are a last-resort LaTeX resume compression specialist.

{_STYLE_GUARDRAILS}

Task:
- The resume still renders to more than one page even after a light condensation pass and compact layout mode.
- Return ONLY the complete .tex file content.
- Preserve the exact LaTeX preamble, commands, and section order from the template.
- Preserve all 3 employers and keep the resume credible, targeted, and factual.
- Compact layout is already enabled. Focus on content triage.
- You MAY reduce bullets only as a last resort, and only under these limits:
  - University of California, Office of the President: minimum 4 bullets
  - Great Wolf Resorts: minimum 4 bullets
  - Simple.biz: exactly 3 bullets
- Never remove a bullet that directly addresses a high-priority JD requirement if a lower-value alternative exists.
- Prefer merging or removing overlapping operational/support bullets before stronger builder-operator bullets.
- Preserve unique evidence, named systems, and differentiated technical wins.
- Keep skills categories intact and preserve all required Languages and Databases entries."""

_COVER_STRATEGY_SYSTEM = f"""\
You are a cover-letter strategist creating a concise writing plan.

{_STYLE_GUARDRAILS}

PERSONALIZATION RULES:
- The opening MUST reference something specific about the company — their product, team mission, or engineering challenge. Never open with "I am reaching out to apply for X."
- Structure is FLEXIBLE. You choose how many body paragraphs (2-4) and what order to present experience. Lead with whichever experience is most relevant to THIS role, not chronological order.
- You may organize paragraphs by THEME (e.g., "automation at scale" drawing from multiple roles) instead of by company.
- The closing must connect back to the company-specific hook, not generic "thank you for your consideration."
- Select the most relevant narrative vignettes from the candidate persona. Not every letter needs Coraline or GWR — pick what fits.
- Adapt voice to the company type provided in the analysis (large_tech, startup, security_focused, etc.).

Return ONLY JSON:
{{
  "company_hook": "the specific company/team insight that opens the letter — must reference what they build or care about",
  "structure": [
    {{
      "focus": "what this paragraph covers",
      "experience_sources": ["which roles/projects to draw from"],
      "theme": "the organizing principle (not just a company name)"
    }}
  ],
  "closing_angle": "how to close — must tie back to the company hook, not generic",
  "voice_controls": [
    "specific wording/tone controls to avoid fluff and keep concrete"
  ],
  "claims_to_avoid": [
    "specific risky claims or inflated phrasing to avoid"
  ],
  "vignettes_to_use": ["which narrative vignettes from soul.md are most relevant"]
}}"""

_COVER_DRAFT_SYSTEM = f"""\
You are a LaTeX cover letter tailoring expert.

{_STYLE_GUARDRAILS}

Output requirements:
- Return ONLY complete .tex content. No markdown fences.
- Preserve exact LaTeX preamble and document structure from template.
- Replace [COMPANY_NAME] in \\companyname.
- Replace [DATE] with today's date.
- Follow the paragraph structure from the strategy — do NOT default to a fixed 4-paragraph formula.
- The opening paragraph MUST reference the company specifically (their product, mission, or challenge). Never start with "I am reaching out to apply for X at Y."
- Body paragraphs may be organized by theme rather than by employer. Draw from whichever roles/projects the strategy specifies.
- The closing MUST tie back to the company-specific hook. Never end with generic "thank you for your consideration" or "I would welcome the opportunity to discuss."
- Keep tone grounded, direct, and technically credible.
- Do not use literal \\n tokens or Python list syntax.
- Keep content factual and grounded in provided source text only.
- Apply the candidate voice from the persona section. Use the narrative vignettes as source material to reshape, not to copy."""

_COVER_QA_SYSTEM = f"""\
You are a strict final quality reviewer for LaTeX cover letters.

{_STYLE_GUARDRAILS}

Task:
- Review draft LaTeX for factual grounding, style violations, and LaTeX safety.
- Repair issues directly and return corrected LaTeX only.
- Preserve the paragraph structure from the strategy.
- Remove or rewrite risky claims rather than inventing evidence.
- LENGTH CHECK: If the structural checks section reports the letter is too short or too long, fix it.
  Too short: expand with grounded detail. Too long: tighten language. Target ±15% of baseline length.

DIFFERENTIATION CHECKS (fix if violated):
- The opening paragraph MUST mention something specific about the company. If it starts with "I am reaching out to apply for X" or similar generic opener, rewrite it to lead with a company-specific insight.
- The closing MUST NOT be generic "thank you for your consideration" or "I would welcome the opportunity to discuss." It must connect to the company or role specifically.
- If the letter follows a rigid formula of opening → UCOP paragraph → GWR paragraph → closing, restructure to follow the strategy's prescribed order instead."""


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
    persona_text = get_persona().for_strategy(analysis, "resume")

    # Extract matched tools from analysis requirements for easy reference
    matched_tools: list[str] = []
    for req in analysis.get("requirements", []):
        matched_tools.extend(req.get("matched_skills", []))
    matched_tools = sorted(set(matched_tools))

    user_prompt = (
        f"## Baseline Resume Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Candidate Persona (voice, contribution patterns, evidence anchors)\n"
        f"{persona_text}\n\n"
        f"## JD-Relevant Tools (from analysis — use these names in rewrite angles)\n"
        f"{', '.join(matched_tools) if matched_tools else 'none extracted'}\n\n"
        f"## Skills Inventory (supplemental — these category names are NOT resume section names)\n"
        f"{json.dumps(skills_data['skills_inventory'], indent=2)}\n\n"
        f"Target Role: {analysis.get('role_title', job.title)}\n"
        f"Target Company: {analysis.get('company_name', job.company)}\n"
        f"Summary Angle: {analysis.get('summary_angle', 'general security engineering')}\n"
    )
    return chat_expect_json(
        _RESUME_STRATEGY_SYSTEM,
        user_prompt,
        max_tokens=3000,
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
    attempt: int,
    trace_recorder: Callable[[dict], None] | None = None,
    resume_strategy: dict | None = None,
) -> dict:
    from datetime import date
    today = date.today().strftime("%B %d, %Y")
    persona_text = get_persona().for_strategy(analysis, "cover")
    company_ctx = analysis.get("company_context", {})
    user_prompt = (
        f"## Baseline Cover Letter Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Company Context\n"
        f"What they build: {company_ctx.get('what_they_build', 'unknown')}\n"
        f"Engineering challenges: {company_ctx.get('engineering_challenges', 'unknown')}\n"
        f"Company type: {company_ctx.get('company_type', 'other')}\n"
        f"Suggested hook: {company_ctx.get('cover_letter_hook', 'none')}\n\n"
        f"## Candidate Persona\n{persona_text}\n\n"
    )
    if resume_strategy:
        user_prompt += (
            f"## Resume Strategy (already committed — cover letter must be consistent)\n"
            f"{json.dumps(resume_strategy, indent=2)}\n\n"
            f"CONSISTENCY RULES:\n"
            f"- Do NOT recommend claims the resume strategy listed in claims_to_avoid.\n"
            f"- Body paragraphs should reference the same bullet angles from the resume strategy, but organized by theme, not by company.\n\n"
        )
    user_prompt += (
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


def _extract_rewrite_directives(strategy: dict) -> tuple[list[dict], list[dict]]:
    """Parse experience_rewrites from strategy, handling string-encoded inner arrays."""
    rewrites = []
    preserves = []
    for entry in strategy.get("experience_rewrites", []):
        company = entry.get("company", "")
        # bullet_rewrites may be a JSON-encoded string (model serialization bug) or a real list
        bw = entry.get("bullet_rewrites", [])
        if isinstance(bw, str):
            try:
                bw = json.loads(bw)
            except Exception:
                bw = []
        for rw in bw:
            rewrites.append({
                "company": company,
                "baseline_topic": rw.get("baseline_topic", ""),
                "rewrite_angle": rw.get("rewrite_angle", ""),
                "jd_req": rw.get("jd_requirement_addressed", ""),
            })
        bp = entry.get("bullets_to_preserve", [])
        if isinstance(bp, str):
            try:
                bp = json.loads(bp)
            except Exception:
                bp = []
        for topic in bp:
            preserves.append({"company": company, "topic": topic})
    return rewrites, preserves


def _set_resume_fit_flags(
    tex: str,
    *,
    compact: bool | None = None,
    pruned: bool | None = None,
) -> str:
    """Toggle deterministic resume fit flags without asking the LLM to edit layout."""
    if compact is not None:
        tex = tex.replace(
            "\\compactresumetrue" if not compact else "\\compactresumefalse",
            "\\compactresumetrue" if compact else "\\compactresumefalse",
            1,
        )
    if pruned is not None:
        tex = tex.replace(
            "\\prunedresumetrue" if not pruned else "\\prunedresumefalse",
            "\\prunedresumetrue" if pruned else "\\prunedresumefalse",
            1,
        )
    return tex


def _resume_fit_metrics_block(metrics: ResumeFitMetrics) -> str:
    suspicious = ", ".join(metrics.suspicious_single_word_lines) if metrics.suspicious_single_word_lines else "none"
    return (
        f"- Rendered page count: {metrics.page_count}\n"
        f"- Page 2 word count: {metrics.page_2_word_count}\n"
        f"- Widow-like single-word lines: "
        f"{'yes' if metrics.has_suspicious_single_word_lines else 'no'} ({suspicious})"
    )


def _inspect_resume_candidate(
    out_path: Path,
    tex: str,
    *,
    attempt: int,
    fit_mode: str,
    baseline_body_len: int,
    trace_recorder: Callable[[dict], None] | None = None,
) -> tuple[bool, ResumeFitMetrics]:
    """Write, compile, and inspect a resume candidate for rendered fit."""
    out_path.write_text(tex)
    pdf = compile_tex(out_path)
    metrics = ResumeFitMetrics()
    if pdf is not None:
        metrics = inspect_resume_pdf_fit(pdf)

    body_len = len(_extract_body_text(tex))
    if trace_recorder:
        trace_recorder(
            {
                "event_type": "resume_fit_inspection",
                "doc_type": "resume",
                "phase": "fit",
                "fit_mode": fit_mode,
                "attempt": attempt,
                "compiled": pdf is not None,
                "body_chars": body_len,
                "baseline_body_chars": baseline_body_len,
                "char_ratio": round(body_len / baseline_body_len, 4) if baseline_body_len else 1.0,
                **metrics.as_dict(),
            }
        )
    return pdf is not None, metrics


def _run_resume_fit_pass(
    mode: str,
    *,
    job: SelectedJob,
    analysis: dict,
    baseline: str,
    strategy: dict,
    rewrite_block: str,
    current_tex: str,
    metrics: ResumeFitMetrics,
    attempt: int,
    trace_recorder: Callable[[dict], None] | None = None,
) -> str:
    """Run an LLM fit pass to condense or prune a resume."""
    system_prompt = _RESUME_FIT_CONDENSE_SYSTEM if mode == "condense" else _RESUME_FIT_PRUNE_SYSTEM
    counts = _count_resume_bullets_by_company(current_tex)
    user_prompt = (
        f"## Baseline Resume Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Resume Strategy\n{json.dumps(strategy, indent=2)}\n\n"
        f"## Current Resume\n```latex\n{current_tex}\n```\n\n"
        f"## Rendered Fit Diagnostics\n{_resume_fit_metrics_block(metrics)}\n\n"
        f"## Current Bullet Counts\n{json.dumps(counts, indent=2)}\n\n"
        f"## Rewrite Directives (preserve JD-critical coverage)\n"
        f"{rewrite_block if rewrite_block else '(no rewrite directives extracted)'}\n\n"
        f"Target Role: {analysis.get('role_title', job.title)}\n"
        f"Target Company: {analysis.get('company_name', job.company)}\n"
    )
    if mode == "prune":
        user_prompt += (
            f"\n## Hard Floors\n"
            f"{json.dumps(cfg.RESUME_COMPANY_BULLET_FLOORS, indent=2)}\n"
            f"\n## Hard Caps\n"
            f"{json.dumps(cfg.RESUME_COMPANY_BULLET_TARGETS, indent=2)}\n"
        )

    raw = chat(
        system_prompt,
        user_prompt,
        max_tokens=8192,
        temperature=0.15 if mode == "prune" else 0.1,
        trace={
            "doc_type": "resume",
            "phase": "fit",
            "fit_mode": mode,
            "attempt": attempt,
            "response_parse_kind": "latex",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
    )
    tex = _strip_disallowed_dashes(extract_latex(raw))
    return _set_resume_fit_flags(
        tex,
        compact="\\compactresumetrue" in current_tex,
        pruned=(mode == "prune"),
    )


def _fit_resume_to_one_page(
    job: SelectedJob,
    analysis: dict,
    baseline: str,
    strategy: dict,
    rewrite_block: str,
    tex: str,
    output_dir: Path,
    attempt: int,
    trace_recorder: Callable[[dict], None] | None = None,
) -> str:
    """Apply resume-only fit stages until the PDF renders on one page or stages are exhausted."""
    out_path = output_dir / "Conner_Jordan_Resume.tex"
    baseline_body_len = len(_extract_body_text(baseline))
    current_tex = _set_resume_fit_flags(tex, compact=False, pruned=False)

    compiled, metrics = _inspect_resume_candidate(
        out_path,
        current_tex,
        attempt=attempt,
        fit_mode="initial",
        baseline_body_len=baseline_body_len,
        trace_recorder=trace_recorder,
    )
    if not compiled or metrics.page_count == cfg.RESUME_TARGET_PAGES:
        return current_tex

    if cfg.RESUME_FIT_MAX_STAGES >= 1:
        condensed_tex = _run_resume_fit_pass(
            "condense",
            job=job,
            analysis=analysis,
            baseline=baseline,
            strategy=strategy,
            rewrite_block=rewrite_block,
            current_tex=current_tex,
            metrics=metrics,
            attempt=attempt,
            trace_recorder=trace_recorder,
        )
        compiled, condensed_metrics = _inspect_resume_candidate(
            out_path,
            condensed_tex,
            attempt=attempt,
            fit_mode="condense",
            baseline_body_len=baseline_body_len,
            trace_recorder=trace_recorder,
        )
        if compiled:
            current_tex = condensed_tex
            metrics = condensed_metrics
        if metrics.page_count == cfg.RESUME_TARGET_PAGES:
            return current_tex

    if cfg.RESUME_COMPACT_MODE_ENABLED and cfg.RESUME_FIT_MAX_STAGES >= 2:
        compact_tex = _set_resume_fit_flags(current_tex, compact=True, pruned=False)
        if trace_recorder:
            trace_recorder(
                {
                    "event_type": "resume_fit_stage",
                    "doc_type": "resume",
                    "phase": "fit",
                    "fit_mode": "compact",
                    "attempt": attempt,
                    "action": "enable_compact_layout",
                }
            )
        compiled, compact_metrics = _inspect_resume_candidate(
            out_path,
            compact_tex,
            attempt=attempt,
            fit_mode="compact",
            baseline_body_len=baseline_body_len,
            trace_recorder=trace_recorder,
        )
        if compiled:
            current_tex = compact_tex
            metrics = compact_metrics
        if metrics.page_count == cfg.RESUME_TARGET_PAGES:
            return current_tex

    if cfg.RESUME_FIT_MAX_STAGES < 3:
        return current_tex

    compact_active = "\\compactresumetrue" in current_tex
    pruned_tex = _run_resume_fit_pass(
        "prune",
        job=job,
        analysis=analysis,
        baseline=baseline,
        strategy=strategy,
        rewrite_block=rewrite_block,
        current_tex=_set_resume_fit_flags(current_tex, compact=compact_active, pruned=False),
        metrics=metrics,
        attempt=attempt,
        trace_recorder=trace_recorder,
    )
    compiled, prune_metrics = _inspect_resume_candidate(
        out_path,
        _set_resume_fit_flags(pruned_tex, compact=compact_active, pruned=True),
        attempt=attempt,
        fit_mode="prune",
        baseline_body_len=baseline_body_len,
        trace_recorder=trace_recorder,
    )
    if compiled:
        current_tex = _set_resume_fit_flags(pruned_tex, compact=compact_active, pruned=True)
        metrics = prune_metrics

    return current_tex


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

    # Extract rewrite directives into a flat, numbered list the draft LLM cannot ignore
    rewrites, preserves = _extract_rewrite_directives(strategy)

    rewrite_block = ""
    if rewrites:
        rewrite_block += "BULLETS TO REWRITE — execute each one. A rewritten bullet MUST be structurally different from the baseline:\n"
        for i, rw in enumerate(rewrites, 1):
            rewrite_block += (
                f"  {i}. [{rw['company']}] Baseline topic: \"{rw['baseline_topic']}\"\n"
                f"     → Rewrite angle: {rw['rewrite_angle']}\n"
                f"     → JD requirement addressed: {rw['jd_req']}\n"
            )
    if preserves:
        rewrite_block += "\nBULLETS TO POLISH ONLY (preserve framing, minor wording improvements only):\n"
        for p in preserves:
            rewrite_block += f"  - [{p['company']}] {p['topic']}\n"

    draft_prompt = (
        f"## Baseline Resume Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Candidate Persona (voice, contribution patterns, evidence anchors — use this to guide HOW bullets are written)\n"
        f"{get_persona().for_draft(analysis, 'resume')}\n\n"
        f"## Skills Inventory (supplemental context — these category names are NOT resume section names)\n"
        f"Note: The resume's TECHNICAL SKILLS categories come from the baseline template above, NOT from this inventory.\n"
        f"This inventory lists additional skills the candidate knows that you may ADD to resume categories if JD-relevant.\n"
        f"{json.dumps(skills_data['skills_inventory'], indent=2)}\n\n"
        f"Target Role: {analysis.get('role_title', job.title)}\n"
        f"Target Company: {analysis.get('company_name', job.company)}\n"
        f"Summary Angle: {analysis.get('summary_angle', 'general security engineering')}\n\n"
        f"## BULLET REWRITE DIRECTIVES\n"
        f"{rewrite_block if rewrite_block else '(no rewrites extracted from strategy)'}\n\n"
        f"## Skills Tailoring\n"
        f"{json.dumps(strategy.get('skills_tailoring', {}), indent=2)}\n"
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
        f"You MUST expand bullet content to reach at least {int(baseline_body_len * 0.80)} chars. "
        f"Add grounded technical detail to each bullet until length matches."
        if char_ratio < 0.80
        else (
            f"DRAFT MAY BE TOO LONG ({draft_body_len} chars vs baseline {baseline_body_len}, ratio {char_ratio:.2f}). "
            f"Tighten summary language, shorten low-value phrasing, and reduce line wrapping pressure while preserving facts."
            if char_ratio > 1.05
            else f"Length OK ({draft_body_len} vs baseline {baseline_body_len}, ratio {char_ratio:.2f})"
        )
    )
    bullet_status = (
        f"BULLET COUNT WRONG: {draft_bullets} found, need exactly 14 (6 + 5 + 3). Fix this."
        if draft_bullets != cfg.RESUME_BULLET_COUNT
        else f"Bullet count OK ({draft_bullets})"
    )

    qa_prompt = (
        f"## Baseline Resume Template\n```latex\n{baseline}\n```\n\n"
        f"## Resume Strategy\n{json.dumps(strategy, indent=2)}\n\n"
        f"## Draft Resume\n```latex\n{draft_tex}\n```\n\n"
        f"## STRUCTURAL CHECKS (fix these before anything else)\n"
        f"- {length_status}\n"
        f"- {bullet_status}\n\n"
        f"## Reviewer Focus\n"
        f"- remove em/en dashes\n"
        f"- remove or soften ungrounded percentage claims\n"
        f"- replace generic corporate language with concrete technical phrasing\n"
        f"- keep the resume concise enough to fit the one-page baseline layout\n"
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
    tex = _fit_resume_to_one_page(
        job,
        analysis,
        baseline,
        strategy,
        rewrite_block,
        tex,
        output_dir,
        attempt,
        trace_recorder=trace_recorder,
    )

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

    # Load resume strategy for cross-document consistency
    resume_strat_path = output_dir / "resume_strategy.json"
    resume_strategy = None
    if resume_strat_path.exists():
        try:
            resume_strategy = json.loads(resume_strat_path.read_text())
        except Exception:
            logger.warning("Could not load resume_strategy.json for cover strategy chaining")

    strategy = _cover_strategy(
        job,
        analysis,
        baseline,
        attempt=attempt,
        trace_recorder=trace_recorder,
        resume_strategy=resume_strategy,
    )
    (output_dir / "cover_strategy.json").write_text(json.dumps(strategy, indent=2))

    from datetime import date
    today = date.today().strftime("%B %d, %Y")

    company_ctx = analysis.get("company_context", {})
    draft_prompt = (
        f"## Baseline Cover Letter Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Cover Strategy\n{json.dumps(strategy, indent=2)}\n\n"
        f"## Company Context\n"
        f"What they build: {company_ctx.get('what_they_build', 'unknown')}\n"
        f"Engineering challenges: {company_ctx.get('engineering_challenges', 'unknown')}\n"
        f"Company type: {company_ctx.get('company_type', 'other')}\n"
        f"Cover letter hook: {company_ctx.get('cover_letter_hook', 'none')}\n\n"
        f"## Candidate Persona\n{get_persona().for_draft(analysis, 'cover')}\n\n"
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

    # Compute cover letter length metrics for QA
    baseline_cover_len = len(_extract_body_text(baseline))
    draft_cover_len = len(_extract_body_text(draft_tex))
    cover_ratio = draft_cover_len / baseline_cover_len if baseline_cover_len else 1.0
    cover_length_status = (
        f"COVER LETTER IS TOO SHORT ({draft_cover_len} chars vs baseline {baseline_cover_len}, ratio {cover_ratio:.2f}). "
        f"Expand paragraphs with grounded detail to reach at least {int(baseline_cover_len * 0.85)} chars."
        if cover_ratio < 0.85
        else (
            f"COVER LETTER IS TOO LONG ({draft_cover_len} chars vs baseline {baseline_cover_len}, ratio {cover_ratio:.2f}). "
            f"Tighten language to stay within {int(baseline_cover_len * 1.15)} chars."
            if cover_ratio > 1.15
            else f"Length OK ({draft_cover_len} vs baseline {baseline_cover_len}, ratio {cover_ratio:.2f})"
        )
    )

    qa_prompt = (
        f"## Baseline Cover Template\n```latex\n{baseline}\n```\n\n"
        f"## Cover Strategy\n{json.dumps(strategy, indent=2)}\n\n"
        f"## Draft Cover Letter\n```latex\n{draft_tex}\n```\n\n"
        f"## STRUCTURAL CHECKS\n"
        f"- {cover_length_status}\n\n"
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
