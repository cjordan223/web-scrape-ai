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
from .grounding import (
    build_grounding_context,
    enrich_cover_strategy_with_grounding,
    enrich_resume_strategy_with_grounding,
    grounding_prompt_block,
    write_grounding_artifacts,
)
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
- Avoid empty corporate language. Prefer concrete technical actions and outcomes.
- Immutable facts stay immutable: do not rename employers, role titles, or dates.
- Skills inventory proves the candidate can claim a skill, but it does NOT prove that the skill was used in a specific employer bullet.
- Persona text is for voice and emphasis only. Do not infer new implementation details from persona prose alone."""

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
- Treat prior employer names, role titles, and dates as immutable. They are not tailoring knobs.

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
          "jd_requirement_addressed": "the specific JD requirement this rewrite targets",
          "allowed_evidence": {{
            "immutable_role": "baseline role title for this employer",
            "approved_terms": ["grounded terms already present in source truth"],
            "approved_metrics": ["grounded metrics already present in source truth"]
          }}
        }}
      ],
      "bullets_to_preserve": ["baseline bullet topics that need minor polish only"],
      "safe_metrics_to_keep": ["specific numeric claims known to be grounded in source"],
      "claims_to_avoid": ["specific risky claim patterns to avoid"],
      "allowed_evidence": {{
        "company": "employer name",
        "immutable_role": "baseline role title for this employer",
        "approved_terms": ["grounded terms already present in source truth"]
      }}
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
- Every rewrite must stay inside allowed_evidence. If a term is not in allowed_evidence or the grounding contract, do not propose it.

CRITICAL — WHAT A REWRITE ANGLE IS:
- A rewrite angle tells the draft writer to COMPLETELY RESTRUCTURE the bullet to focus on the JD requirement.
- Do NOT just copy the baseline sentence and add a wrapper. You must instruct the writer to rethink the sentence structure completely.
- ALL baseline metrics (numbers, tool names, concrete outcomes) MUST survive into the rewritten bullet, but you may only incorporate supplemental facts if they are explicitly present in the grounding contract.
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
- Never change the role title shown under any employer heading.
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
- Restore canonical role titles if they drift.
- Remove unsupported tools, compliance labels, identity stacks, AI deployment details, or release mechanics that are not grounded in the contract.
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
- Preserve attribution exactly. If evidence comes from a Great Wolf Resorts bullet, name Great Wolf Resorts, not a vendor or tool mentioned inside that bullet.
- School, capstone, and personal projects must stay labeled as school, capstone, or personal. Never rewrite them as internal employer recognition or on-the-job work.
- Each paragraph must stay inside the allowed_evidence attached to its chosen source material.

Return ONLY JSON:
{{
  "company_hook": "the specific company/team insight that opens the letter — must reference what they build or care about",
  "structure": [
    {{
      "focus": "what this paragraph covers",
      "experience_sources": ["which roles/projects to draw from"],
      "theme": "the organizing principle (not just a company name)",
      "allowed_evidence": ["grounded terms allowed in this paragraph"]
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
- Never rename a prior employer role to sound like the target role.
- Never add tools, frameworks, compliance labels, identity platforms, or deployment architecture unless they appear in the allowed_evidence for that paragraph.
- Apply the candidate voice from the persona section. Use the narrative vignettes as source material to reshape, not to copy.
- Preserve attribution exactly:
  - do not reassign an employer's work to a vendor, product, or tool named inside the evidence
  - school, capstone, and personal projects must remain explicitly labeled that way
  - if a project is not employer work, do not imply it happened on the job or won internal recognition."""

_COVER_QA_SYSTEM = f"""\
You are a strict final quality reviewer for LaTeX cover letters.

{_STYLE_GUARDRAILS}

Task:
- Review draft LaTeX for factual grounding, style violations, and LaTeX safety.
- Repair issues directly and return corrected LaTeX only.
- Preserve the paragraph structure from the strategy.
- Remove or rewrite risky claims rather than inventing evidence.
- Fix any drift from canonical role titles, employer attribution, or company rendering.
- LENGTH CHECK: If the structural checks section reports the letter is too short or too long, fix it.
  Too short: expand with grounded detail. Too long: tighten language. Target ±15% of baseline length.

DIFFERENTIATION CHECKS (fix if violated):
- The opening paragraph MUST mention something specific about the company. If it starts with "I am reaching out to apply for X" or similar generic opener, rewrite it to lead with a company-specific insight.
- The closing MUST NOT be generic "thank you for your consideration" or "I would welcome the opportunity to discuss." It must connect to the company or role specifically.
- If the letter follows a rigid formula of opening → UCOP paragraph → GWR paragraph → closing, restructure to follow the strategy's prescribed order instead.
- Fix attribution drift:
  - if a sentence starts with the wrong employer, rewrite it to match the source evidence exactly
  - if a tool or vendor name (for example Rapid7 or KnowBe4) appears inside Great Wolf evidence, do not turn it into a separate employer
  - if a project is a school, capstone, or personal project, label it as such and remove any "internal recognition" wording."""

# ---------------------------------------------------------------------------
# Stage 4 – Humanize: remove AI writing patterns
# Curated from https://github.com/conorbronsdon/avoid-ai-writing (v3.0.0)
# ---------------------------------------------------------------------------
_COVER_HUMANIZE_SYSTEM = f"""\
You are a final-pass editor. Your sole job is to remove AI writing patterns \
("AI-isms") from a LaTeX cover letter so it reads like a human wrote it.

You receive QA-cleaned LaTeX. Return ONLY the corrected LaTeX document — no \
markdown fences, no commentary, no explanation.

{_STYLE_GUARDRAILS}

PRESERVE (never change):
- All LaTeX commands, preamble, \\documentclass, \\begin{{document}}, \\end{{document}}
- The \\companyname macro and every place it appears
- Company names, employer names, role titles, dates, tool/framework names
- All grounded claims and evidence (do not invent, remove, or rephrase factual content)
- Overall letter structure, paragraph count, and paragraph order

─── P0 — CREDIBILITY KILLERS (fix immediately) ───
- Significance inflation: "marking a pivotal moment", "watershed moment", \
"the future looks bright", "only time will tell" → state what happened or cut.
- Vague attributions: "Experts believe", "Industry leaders agree" → cite a \
source or drop the attribution.
- Promotional language: "vibrant", "nestled", "thriving", "bustling" → plain \
description or cut.
- Formulaic challenges: "Despite challenges… continues to thrive" → name the \
challenge and response, or cut.

─── P1 — OBVIOUS AI SMELL (fix before output) ───

TIER 1 WORDS — always replace:
  delve/delve into → explore, dig into, look at
  landscape (metaphor) → field, space, area
  tapestry → (describe the complexity)
  realm → area, field, domain
  paradigm → model, approach, framework
  embark → start, begin
  beacon → (rewrite entirely)
  testament to → shows, proves, demonstrates
  robust → strong, reliable, solid
  comprehensive → thorough, complete, full
  cutting-edge → latest, advanced
  leverage (verb) → use
  pivotal → important, key, critical
  underscores → highlights, shows
  meticulous/meticulously → careful, detailed, precise
  seamless/seamlessly → smooth, easy, without friction
  game-changer → (describe what changed and why)
  utilize → use
  showcasing → showing, demonstrating
  deep dive → examine, explore
  unpack → explain, break down
  intricate/intricacies → complex, detailed
  ever-evolving → changing, growing
  holistic → complete, full, whole
  actionable → practical, useful, concrete
  impactful → effective, significant
  learnings → lessons, findings, takeaways
  best practices → what works, proven methods
  at its core → (cut — just state the thing)
  synergy → (describe the actual combined effect)
  in order to → to
  due to the fact that → because
  serves as → is
  features (verb) → has, includes
  boasts → has
  commence → start, begin
  ascertain → find out, determine
  endeavor → effort, attempt, try

TIER 2 — flag when 2+ appear in the SAME paragraph:
  harness, navigate, foster, elevate, unleash, streamline, empower, bolster, \
spearhead, resonate, revolutionize, facilitate, underpin, nuanced, crucial, \
ecosystem (metaphor), myriad, plethora, encompass, catalyze, reimagine, \
cultivate, illuminate, transformative, cornerstone, paramount, poised, \
burgeoning, nascent, overarching.
  If two or more appear together → rewrite the paragraph using plain words.

TIER 3 — flag only when the letter is saturated with them:
  significant, innovative, dynamic, scalable, compelling, unprecedented, \
exceptional, remarkable, sophisticated, instrumental.
  Replace some with specifics: numbers, comparisons, concrete examples.

SENTENCE-LEVEL FIXES:
- Hollow intensifiers: cut "genuine", "truly", "quite frankly", "to be honest", \
"it's worth noting that". Just state the fact.
- Hedging: cut "perhaps", "could potentially", "it's important to note that". \
Make the point directly.
- Copula avoidance: "serves as" → "is", "features" → "has", "boasts" → "has". \
Default to "is"/"has" unless a specific verb genuinely adds meaning.
- Synonym cycling: if the same noun appears 3 times and it's the right word, \
keep all three. Forced variation reads as thesaurus abuse.
- Template phrases: "a [adj] step toward [noun]" → describe the specific outcome.
- Transition padding: "Moreover", "Furthermore", "Additionally" → restructure \
so the connection is obvious, or use "and", "also".

─── P2 — STYLISTIC POLISH ───
- Vary sentence length: mix short (3-8 words) with longer (20+). Fragments OK.
- Vary paragraph length: not every paragraph should be the same size.
- Compulsive rule of three: vary groupings. Two items or four, not always three.
- If a sentence works after deleting an inflation clause, delete it.

TONE TARGET:
1. Vary sentence length — mix short with long. Fragments are fine.
2. Be concrete — replace vague claims with specifics.
3. Have a voice — use first person, state preferences, show reactions where natural.
4. Cut neutrality — if the letter takes a position, commit to it.
5. Earn emphasis — don't tell the reader something is interesting. Make it interesting.

If the letter is already clean, return it unchanged. Do not over-edit."""


def _strip_disallowed_dashes(text: str) -> str:
    """Normalize Unicode dash variants to ASCII fallback punctuation."""
    return text.replace("\u2014", ", ").replace("\u2013", ", ")


def _resume_strategy(
    job: SelectedJob,
    analysis: dict,
    baseline: str,
    skills_data: dict,
    grounding: dict,
    attempt: int,
    trace_recorder: Callable[[dict], None] | None = None,
) -> dict:
    persona_text = get_persona().for_strategy(analysis, "resume")

    # Extract matched tools from analysis requirements for easy reference
    matched_tools: list[str] = []
    for req in analysis.get("requirements", []):
        matched_tools.extend(req.get("matched_skills") or [])
    matched_tools = sorted(set(matched_tools))

    user_prompt = (
        f"## Baseline Resume Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Candidate Persona (voice, contribution patterns, evidence anchors)\n"
        f"{persona_text}\n\n"
        f"{grounding_prompt_block(grounding)}\n\n"
        f"## JD-Relevant Tools (from analysis — use these names in rewrite angles)\n"
        f"{', '.join(matched_tools) if matched_tools else 'none extracted'}\n\n"
        f"## Skills Inventory (supplemental — these category names are NOT resume section names)\n"
        f"{json.dumps(skills_data['skills_inventory'], indent=2)}\n\n"
        f"Target Role: {analysis.get('role_title', job.title)}\n"
        f"Target Company: {analysis.get('company_name', job.company)}\n"
        f"Summary Angle: {analysis.get('summary_angle', 'general security engineering')}\n"
    )
    strategy = chat_expect_json(
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
    return enrich_resume_strategy_with_grounding(strategy, grounding)


def _cover_strategy(
    job: SelectedJob,
    analysis: dict,
    baseline: str,
    grounding: dict,
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
        f"{grounding_prompt_block(grounding)}\n\n"
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
    strategy = chat_expect_json(
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
    return enrich_cover_strategy_with_grounding(strategy, grounding)


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
                "allowed_evidence": rw.get("allowed_evidence", {}),
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
    grounding: dict,
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
        f"{grounding_prompt_block(grounding)}\n\n"
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
    grounding: dict,
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
            grounding=grounding,
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
        grounding=grounding,
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
    grounding = build_grounding_context(baseline_tex=baseline, skills_data=skills_data)
    strategy = _resume_strategy(
        job,
        analysis,
        baseline,
        skills_data,
        grounding,
        attempt=attempt,
        trace_recorder=trace_recorder,
    )
    (output_dir / "resume_strategy.json").write_text(json.dumps(strategy, indent=2))
    write_grounding_artifacts(output_dir, grounding=grounding, analysis=analysis, resume_strategy=strategy)

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
            allowed = rw.get("allowed_evidence") or {}
            approved_terms = allowed.get("approved_terms") or []
            approved_metrics = allowed.get("approved_metrics") or []
            immutable_role = allowed.get("immutable_role")
            if immutable_role or approved_terms or approved_metrics:
                rewrite_block += (
                    f"     → Immutable role: {immutable_role or 'unknown'}\n"
                    f"     → Approved terms only: {', '.join(approved_terms) if approved_terms else 'none'}\n"
                    f"     → Approved metrics only: {', '.join(approved_metrics) if approved_metrics else 'none'}\n"
                )
    if preserves:
        rewrite_block += "\nBULLETS TO POLISH ONLY (preserve framing, minor wording improvements only):\n"
        for p in preserves:
            rewrite_block += f"  - [{p['company']}] {p['topic']}\n"

    draft_prompt = (
        f"## Baseline Resume Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"{grounding_prompt_block(grounding)}\n\n"
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
        f"You MUST expand bullet content to reach at least {int(baseline_body_len * 0.95)} chars. "
        f"Add grounded technical detail to each bullet until length matches."
        if char_ratio < 0.95
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
        f"{grounding_prompt_block(grounding)}\n\n"
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
        grounding,
        rewrite_block,
        tex,
        output_dir,
        attempt,
        trace_recorder=trace_recorder,
    )

    out_path = output_dir / "Conner_Jordan_Resume.tex"
    out_path.write_text(tex)
    write_grounding_artifacts(output_dir, grounding=grounding, analysis=analysis, resume_strategy=strategy)
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
    """Generate a tailored cover letter with a 4-stage pipeline: strategy, draft, QA, humanize."""
    baseline = cfg.COVER_TEX.read_text()
    skills_data = json.loads(cfg.SKILLS_JSON.read_text())
    grounding = build_grounding_context(skills_data=skills_data)

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
        grounding,
        attempt=attempt,
        trace_recorder=trace_recorder,
        resume_strategy=resume_strategy,
    )
    (output_dir / "cover_strategy.json").write_text(json.dumps(strategy, indent=2))
    write_grounding_artifacts(
        output_dir,
        grounding=grounding,
        analysis=analysis,
        resume_strategy=resume_strategy,
        cover_strategy=strategy,
    )

    from datetime import date
    today = date.today().strftime("%B %d, %Y")

    company_ctx = analysis.get("company_context", {})
    draft_prompt = (
        f"## Baseline Cover Letter Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Cover Strategy\n{json.dumps(strategy, indent=2)}\n\n"
        f"{grounding_prompt_block(grounding)}\n\n"
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
        f"{grounding_prompt_block(grounding)}\n\n"
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

    # --- Stage 4: Humanize (remove AI writing patterns) ---
    pre_humanize_tex = tex

    humanize_prompt = (
        f"## Cover Letter to Edit\n```latex\n{tex}\n```\n\n"
        f"## Grounding Context (DO NOT MODIFY THESE FACTS)\n"
        f"Company: {analysis.get('company_name', job.company)}\n"
        f"Role: {analysis.get('role_title', job.title)}\n"
        f"{grounding_prompt_block(grounding)}\n"
    )

    humanize_raw = chat(
        _COVER_HUMANIZE_SYSTEM,
        humanize_prompt,
        max_tokens=4096,
        temperature=0.15,
        trace={
            "doc_type": "cover",
            "phase": "humanize",
            "attempt": attempt,
            "response_parse_kind": "latex",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
    )
    tex = _strip_disallowed_dashes(extract_latex(humanize_raw))

    # Save pre-humanize draft for diff inspection
    (output_dir / "cover_pre_humanize.tex").write_text(pre_humanize_tex)

    out_path = output_dir / "Conner_Jordan_Cover_Letter.tex"
    out_path.write_text(tex)
    write_grounding_artifacts(
        output_dir,
        grounding=grounding,
        analysis=analysis,
        resume_strategy=resume_strategy,
        cover_strategy=strategy,
    )
    logger.info("Cover letter written to %s (%d chars)", out_path, len(tex))
    return out_path
