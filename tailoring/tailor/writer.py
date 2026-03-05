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
- The candidate persona describes their voice, contribution patterns, and evidence anchors. Use these to shape the angle — the candidate is a "builder-operator" who ships production systems, not an analyst who writes reports.
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
- LENGTH IS FLEXIBLE: Your output must match the baseline template's body length within ±20%.
  You are highly encouraged to write entirely new and structurally different sentences.
  Do NOT shorten the overall resume too much, but you can restructure and combine ideas.
  When in doubt, write longer rather than shorter by adding relevant technical detail.
  Shorter output WILL fail validation.
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
  The output body text must be within ±20% of the baseline's character count.
  If the draft is shorter than the baseline, expand bullets with additional grounded technical detail
  until the length matches. Do NOT trim or shorten content. Every bullet should be a substantial
  sentence comparable in length to its baseline counterpart.
- SKILLS CHECK (HARD GATE):
  - Must have EXACTLY 6 categories with these EXACT \\textbf names: Languages, Security Tooling, AI/ML and Research, Frameworks and Infrastructure, DevOps and CI/CD, Databases.
  - Languages must have ALL 11 from baseline (Python, C, C++, TypeScript, Java, SQL, PowerShell, Bash, Swift, Rust, Go). Order may change.
  - Databases must have ALL 10 from baseline (PostgreSQL, MySQL, MongoDB, DynamoDB, SQLite, Redis, Snowflake, ClickHouse, Databricks, vector databases). Order may change.
  - If any category is renamed (e.g., "AI for SecOps" instead of "AI/ML and Research"), fix the name back.
  - If any items are missing from Languages or Databases, restore them."""

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
- Remove or rewrite risky claims rather than inventing evidence.
- LENGTH CHECK: If the structural checks section reports the letter is too short or too long, fix it.
  Too short: expand with grounded detail. Too long: tighten language. Target ±15% of baseline length."""


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
    soul = cfg.SOUL_MD.read_text()

    # Extract matched tools from analysis requirements for easy reference
    matched_tools: list[str] = []
    for req in analysis.get("requirements", []):
        matched_tools.extend(req.get("matched_skills", []))
    matched_tools = sorted(set(matched_tools))

    user_prompt = (
        f"## Baseline Resume Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Candidate Persona (voice, contribution patterns, evidence anchors)\n"
        f"{soul}\n\n"
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
    soul: str,
    attempt: int,
    trace_recorder: Callable[[dict], None] | None = None,
    resume_strategy: dict | None = None,
) -> dict:
    from datetime import date
    today = date.today().strftime("%B %d, %Y")
    user_prompt = (
        f"## Baseline Cover Letter Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Candidate Persona\n{soul[:4000]}\n\n"
    )
    if resume_strategy:
        user_prompt += (
            f"## Resume Strategy (already committed — cover letter must be consistent)\n"
            f"{json.dumps(resume_strategy, indent=2)}\n\n"
            f"CONSISTENCY RULES:\n"
            f"- Do NOT recommend claims the resume strategy listed in claims_to_avoid.\n"
            f"- Paragraph 2 (current role) should reference the same UCOP bullet angles from the resume strategy.\n"
            f"- Paragraph 3 (prior experience) should reference the same GWR bullet angles.\n\n"
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
    soul = cfg.SOUL_MD.read_text()
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
        f"{soul}\n\n"
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
        else f"Length OK ({draft_body_len} vs baseline {baseline_body_len}, ratio {char_ratio:.2f})"
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
        soul,
        attempt=attempt,
        trace_recorder=trace_recorder,
        resume_strategy=resume_strategy,
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
