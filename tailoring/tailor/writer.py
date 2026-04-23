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
import re
from pathlib import Path
from typing import Any, Callable

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
    _extract_work_experience_section,
    _extract_body_text,
    inspect_resume_pdf_fit,
)

logger = logging.getLogger(__name__)

RetryFeedback = dict[str, Any]

_RESUME_COMPANY_HEADER_PATTERN = re.compile(
    r"\\resumeSubheading\s*"
    r"\{\s*(?P<company>[^}]*)\s*\}\s*"
    r"\{\s*(?P<location>[^}]*)\s*\}\s*"
    r"\{\s*(?P<role>[^}]*)\s*\}\s*"
    r"\{\s*(?P<dates>[^}]*)\s*\}",
    re.DOTALL,
)


def _log_vignette_selection(
    trace_recorder: Callable[[dict], None] | None,
    analysis: dict,
    doc_type: str,
    stage: str,
    attempt: int,
) -> None:
    """Emit a ``vignette_selection`` trace event for observability.

    Records which vignettes were picked, their scores, skipped candidates, and
    budget usage so selection behavior can be audited per-run without inspecting
    PersonaStore internals.
    """
    if trace_recorder is None:
        return
    try:
        meta = get_persona().explain_selection(analysis, doc_type, stage)
    except Exception as exc:  # pragma: no cover - defensive, trace must never break run
        trace_recorder({
            "event_type": "vignette_selection_error",
            "doc_type": doc_type,
            "phase": stage,
            "attempt": attempt,
            "error": str(exc),
        })
        return
    trace_recorder({
        "event_type": "vignette_selection",
        "phase": stage,
        "attempt": attempt,
        **meta,
    })


def _format_retry_feedback_block(previous_feedback: RetryFeedback | None) -> str:
    if not previous_feedback:
        return ""

    parts: list[str] = [
        "Treat this as the authoritative repair target for this retry.",
        "Fix every listed failure category before making any optional wording improvements.",
    ]

    summary = previous_feedback.get("summary")
    if summary:
        parts.append(f"Summary: {summary}")

    banned_phrases: list[str] = []
    cumulative = previous_feedback.get("cumulative_banned_phrases")
    if isinstance(cumulative, list):
        for phrase in cumulative:
            if isinstance(phrase, str) and phrase and phrase not in banned_phrases:
                banned_phrases.append(phrase)

    failure_details = previous_feedback.get("failure_details")
    if failure_details:
        for detail in failure_details:
            phrase = detail.get("matched_text") if isinstance(detail, dict) else None
            if phrase and phrase not in banned_phrases:
                banned_phrases.append(phrase)

    if banned_phrases:
        bullets = "\n".join(f'- "{p}"' for p in banned_phrases)
        parts.append(
            "BANNED PHRASES — remove every occurrence of these exact strings "
            "from all paragraphs/bullets in the next attempt. Do NOT reintroduce "
            "any phrase from this list, even if a past retry removed it:\n" + bullets
        )

    if failure_details:
        serialized = json.dumps(failure_details, indent=2, sort_keys=True)
        parts.append(
            "Structured validator failures (JSON):\n```json\n"
            f"{serialized}\n```"
        )
    elif previous_feedback.get("error"):
        parts.append(f"Previous attempt error: {previous_feedback['error']}")

    return "\n\n".join(parts)

_STYLE_GUARDRAILS = """\
STYLE GUARDRAILS (HARD):
- No em dash or en dash characters anywhere. Use commas, periods, or parentheses instead.
- No hallucinations: do not invent projects, tools, scope, timelines, outcomes, or responsibilities.
- No fake metrics: only keep quantitative claims if they are directly supported by provided source material.
- If a number is uncertain, remove the number and keep a factual qualitative claim instead.
- Avoid empty corporate language. Prefer concrete technical actions and outcomes.
- Immutable facts stay immutable: do not rename employers, role titles, or dates.
- Skills inventory proves the candidate can claim a skill, but it does NOT prove that the skill was used in a specific employer bullet."""

# Cover letters need different grounding rules than resumes.
# Resumes: only factual claims from source evidence.
# Cover letters: factual claims must be grounded, but reasoning, motivation,
# opinions, tradeoffs, and forward-looking statements are encouraged and
# do NOT require source evidence. Narrative vignettes provide this material.
_COVER_GUARDRAILS = _STYLE_GUARDRAILS + """
- Persona vignettes contain reasoning, tradeoffs, and lessons learned. Use these as PRIMARY content for cover letters, not just for voice.
- Motivation and opinion statements from the persona are encouraged. They do not require factual source evidence.
- The cover letter must ADD value beyond the resume. If a paragraph could be reconstructed from resume bullets alone, it is failing its purpose."""

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
You are a resume content generator.

{_STYLE_GUARDRAILS}

Output requirements:
- Return ONLY JSON. No explanations, no markdown fences.
- Return plain text content chunks, not LaTeX.
- Professional Summary must be exactly one sentence.
- Bullet distribution is fixed:
  - University of California, Office of the President: exactly 6 bullets
  - Great Wolf Resorts: exactly 5 bullets
  - Simple.biz: exactly 3 bullets
  - Total: exactly 14 bullets
- ONE-PAGE FIT MATTERS: keep sentences concise enough to fit the one-page baseline layout.
  Keep the resume dense, concise, and information-rich enough to fit that layout.
  Preserve technical substance, but cut filler, redundant lead-ins, and overly long transitions.
  Write entirely new and structurally different sentences when needed, but avoid bloated phrasing.
- Do not output literal \\n tokens.
- Keep content factual and grounded in provided source content only.
- The TECHNICAL SKILLS block is assembled deterministically in code. Do NOT return skills.
- Never change the role title shown under any employer heading.
- BULLET ORDERING: Within each company's bullets, place bullets addressing HIGH priority JD requirements first. The most JD-relevant bullet should come first.
- BULLET REWRITES ARE MANDATORY: The prompt will list specific bullets to rewrite with explicit angles. You MUST execute them. Do NOT copy the baseline sentence structure. You MUST write a completely new sentence using DIFFERENT verbiage, DIFFERENT sentence structure, and DIFFERENT ordering of information. If a rewritten bullet looks structurally similar to the baseline, it has failed.
- VOICE: Apply the candidate voice and thematic priorities from the persona section to all rewrites. Concrete actions and outcomes. Pragmatic, operationally focused. No corporate filler.

Return ONLY JSON:
{{
  "summary": "one sentence plain text",
  "experience": [
    {{
      "company": "University of California, Office of the President",
      "bullets": ["bullet1", "bullet2", "bullet3", "bullet4", "bullet5", "bullet6"]
    }},
    {{
      "company": "Great Wolf Resorts",
      "bullets": ["bullet1", "bullet2", "bullet3", "bullet4", "bullet5"]
    }},
    {{
      "company": "Simple.biz",
      "bullets": ["bullet1", "bullet2", "bullet3"]
    }}
  ]
}}"""

_RESUME_QA_SYSTEM = f"""\
You are a strict final quality reviewer for resume content chunks.

{_STYLE_GUARDRAILS}

Task:
- Review draft resume JSON for factual grounding, style violations, and structural compliance.
- Repair issues directly and return corrected JSON only.
- Preserve the exact structure and fixed bullet counts (exactly 14 bullets: 6 + 5 + 3).
- Remove or rewrite risky claims rather than inventing evidence.
- Restore canonical role titles if they drift.
- Remove unsupported tools, compliance labels, identity stacks, AI deployment details, or release mechanics that are not grounded in the contract.
- The TECHNICAL SKILLS block is assembled deterministically in code. Do NOT add, remove, or rewrite skills.
- CRITICAL LENGTH CHECK: Compare the draft against the baseline template provided.
  The output body text must stay within ±20% of the baseline's character count.
  If the structural checks say the draft is too short, expand with grounded detail.
  If the structural checks say the draft is too long, tighten phrasing aggressively while
  preserving the factual payload.
  Prefer concise, high-density bullets that can still render on one page with the baseline layout.
Return ONLY JSON with the same schema as the draft input."""

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
  - tighten skill-line wording and reorder emphasis toward JD-relevant items without dropping required baseline items
  - shorten bulky UCOP/GWR bullets when they are not central to the JD
  - cut low-value clauses before touching high-signal evidence
  - avoid widow-like one-word lines at the bottom of a page
- If overflow looks marginal, prefer tiny sentence-level edits over broad rewrites."""

_RESUME_FIT_PRUNE_SYSTEM = f"""\
You are a last-resort LaTeX resume compression specialist.

{_STYLE_GUARDRAILS}

Task:
- The resume still renders to more than one page after a light condensation pass.
- Return ONLY the complete .tex file content.
- Preserve the exact LaTeX preamble, commands, and section order from the template.
- Preserve all 3 employers and keep the resume credible, targeted, and factual.
- Focus on content triage, not layout compression.
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

{_COVER_GUARDRAILS}

THE COVER LETTER'S JOB:
A cover letter must say things the resume CANNOT say: reasoning behind decisions, tradeoffs navigated, lessons learned, genuine motivation for this company, and opinions that show judgment. If a paragraph could be reconstructed from resume bullets alone, it is worthless.

The candidate persona includes narrative vignettes with real stories — learning curves, technical discoveries, collaboration, and honest reasoning. These are the PRIMARY source material for cover letters, not the resume bullets.

PERSONALIZATION RULES:
- The opening MUST reference something specific about the company — their product, team mission, or engineering challenge. Never open with "I am reaching out to apply for X."
- Structure is FLEXIBLE. You choose how many body paragraphs (2-4) and what order to present experience. Lead with whichever experience is most relevant to THIS role, not chronological order.
- You may organize paragraphs by THEME (e.g., "automation at scale" drawing from multiple roles) instead of by company.
- The closing must connect back to the company-specific hook, not generic "thank you for your consideration."
- Use the selected narrative vignettes in the candidate persona as the authority. Not every letter needs Coraline, GWR, or an AI story — pick from what was provided because the selector already filtered for this JD.
- BREADTH OVER DEPTH: When multiple source projects are provided, distribute body paragraphs across distinct projects or experience areas. Do not force extra stories that were not selected for this JD.
- KEEP PROJECT SPECIFICS LIGHT: Reference projects by what they demonstrate (judgment, tradeoffs, reasoning), not by exhaustive technical detail. The resume carries the specifics; the cover letter carries the perspective.
- Adapt voice to the company type provided in the analysis (large_tech, startup, security_focused, etc.).
- Preserve attribution exactly. If evidence comes from a Great Wolf Resorts bullet, name Great Wolf Resorts, not a vendor or tool mentioned inside that bullet.
- School, capstone, and personal projects must stay labeled as school, capstone, or personal. Never rewrite them as internal employer recognition or on-the-job work.

WHAT EACH PARAGRAPH SHOULD CONTAIN:
- At least one concrete REASONING element: why you chose an approach, what you tried first that didn't work, what tradeoff you navigated, or what you learned.
- A connection to the company's specific situation — not "I have experience in X" but "I learned Y from doing X, which matters for your Z problem."
- Motivation content from the persona where relevant — what drives the candidate, what they're looking for, what frustrates them about the field.

Return ONLY JSON:
{{
  "company_hook": "the specific company/team insight that opens the letter — must reference what they build or care about",
  "structure": [
    {{
      "focus": "what this paragraph covers",
      "experience_sources": ["which roles/projects to draw from"],
      "theme": "the organizing principle (not just a company name)",
      "narrative_angle": "the reasoning, collaboration, or lesson from a vignette that drives this paragraph — NOT a resume bullet. Frame as constructive problem-solving, not adversarial pushback.",
      "connection_to_role": "WHY this experience matters for THIS company's specific situation — not just that you have it, but what it means for them"
    }}
  ],
  "closing_angle": "how to close — must tie back to the company hook, not generic",
  "voice_controls": [
    "specific wording/tone controls to avoid fluff and keep concrete"
  ],
  "claims_to_avoid": [
    "specific risky claims or inflated phrasing to avoid"
  ],
  "vignettes_to_use": ["which narrative vignettes are most relevant and what reasoning/lessons to draw from them"]
}}"""

_COVER_DRAFT_SYSTEM = f"""\
You are a cover letter content generator.

{_COVER_GUARDRAILS}

THE COVER LETTER'S JOB:
The resume already lists what the candidate built. The cover letter must say what the resume CANNOT: why they made the choices they made, what they learned, what didn't work at first, what tradeoffs they navigated, and why this company's problems interest them. A cover letter that reads like resume bullets expanded into prose is a failure.

The candidate persona includes narrative vignettes with real stories. Use the REASONING and LESSONS from these vignettes as the core content of each paragraph, not just the factual outcomes.

Output requirements:
- Return ONLY JSON. No markdown fences.
- Return plain text paragraphs, not LaTeX.
- LENGTH IS A HARD GATE: the combined body text must stay within the char budget declared in the user message (±{int(cfg.COVER_CHAR_TOLERANCE * 100)}% of baseline). Three to four focused paragraphs of 4–6 sentences each is the right shape. Overlong drafts fail validation and are regenerated; cut detail rather than sprawl.
- Follow the paragraph structure from the strategy — do NOT default to a fixed 4-paragraph formula.
- The opening paragraph MUST reference the company specifically (their product, mission, or challenge). Never start with "I am reaching out to apply for X at Y."
- Body paragraphs may be organized by theme rather than by employer. Draw from whichever roles/projects the strategy specifies.
- BREADTH RULE: If the persona section provides multiple source projects, body paragraphs should reference distinct projects or experience areas. If it provides one highly relevant source, use that source without inventing breadth.
- LIGHTEN PROJECT SPECIFICS: Reference projects through the reasoning, tradeoff, or lesson they illustrate — not through exhaustive technical inventories. Resume carries the specifics; the cover letter carries the perspective. One concrete anchor per project is enough; do not enumerate stacks, metrics, and architecture.
- SOURCE-BLOCK BOUNDARY: Each `### Source project:` block is a separate story. Bad example: "I used the RAG chatbot's vector database lessons when deploying Coraline to ECS" unless both facts appear in the same source block. Good example: keep the chatbot retrieval lesson and Coraline deployment lesson in separate sentences with separate attribution.
- Each body paragraph must tell a STORY, not list accomplishments:
  - Lead with a goal, a question you were solving, or a technical decision — not "I built X" and not "I pushed back on Y"
  - Include what you learned, why you chose one approach over another, or how you collaborated to get there
  - Connect it to the company's situation: why this experience matters for their specific needs
  - If a paragraph reads like resume bullets expanded into prose, rewrite it. Ask: "what does this paragraph say that the resume doesn't?"
  - TONE: Frame stories as collaborative problem-solving, not adversarial. Avoid "pushed back", "stepped in because others couldn't", "bridged a gap no one else could", or similar phrasing that positions the candidate against colleagues. Show teamwork and initiative, not conflict.
- AVOID COVER-LETTER CLICHÉS (these patterns mark the letter as AI-generated when stacked):
  - "not just X, Y" / "not X, but Y" — use at most ONCE per letter
  - "I don't just X — I Y" — use at most ONCE per letter
  - "That same mindset / pattern / insight shaped Y" — use at most ONCE
  - "That taught me that…" / "I learned that…" at the END of a body paragraph — NEVER in body paragraphs; save for the closing if at all
  - Stacked aphoristic maxims ("reliable first, clever second") — at most ONE such maxim in the whole letter
  Do not end body paragraphs with a distilled moral. End on what shipped or what the candidate decided.
- Use the strategy's narrative_angle to drive each paragraph. The reasoning and tradeoffs from vignettes are the content, not decoration.
- The closing MUST tie back to the company-specific hook. Never end with generic "thank you for your consideration" or "I would welcome the opportunity to discuss."
- Keep tone grounded, direct, and technically credible. This is a mid-career engineer who builds above their experience level, not a senior architect.
- Do not use literal \\n tokens or Python list syntax.
- Factual claims (projects, tools, metrics, employers) must be grounded in provided source text. Reasoning, motivation, opinions, and lessons learned do NOT require source evidence.
- Never rename a prior employer role to sound like the target role.
- Apply the candidate voice from the persona section. Use the narrative vignettes as source material to reshape, not to copy verbatim.
- If the persona includes motivation content (what drives the candidate, what they're looking for), weave it in where it connects naturally to the company.
- Preserve attribution exactly:
  - do not reassign an employer's work to a vendor, product, or tool named inside the evidence
  - school, capstone, and personal projects must remain explicitly labeled that way
  - if a project is not employer work, do not imply it happened on the job or won internal recognition.

Return ONLY JSON:
{{
  "paragraphs": ["opening paragraph", "body paragraph", "body paragraph"],
  "closing": "closing paragraph tied back to the company hook"
}}"""

_COVER_QA_SYSTEM = f"""\
You are a strict final quality reviewer for cover letter content chunks.

{_COVER_GUARDRAILS}

Task:
- Review draft cover-letter JSON for factual grounding, style violations, and structural compliance.
- Repair issues directly and return corrected JSON only.
- Preserve the paragraph structure from the strategy.
- Remove or rewrite risky claims rather than inventing evidence.
- Fix any drift from canonical role titles, employer attribution, or company rendering.
- LENGTH CHECK: If the structural checks section reports the letter is too short or too long, fix it.
  Too short: expand with grounded detail. Too long: tighten language. Target ±15% of baseline length.

RESUME REGURGITATION CHECK (highest priority — fix if violated):
- Read each body paragraph and ask: "Does this paragraph say anything the resume doesn't?"
- If a paragraph is just resume bullets rewritten as prose (e.g., "I built X using Y for Z endpoints"), it MUST be rewritten to include reasoning, tradeoffs, or lessons learned from the narrative vignettes.
- The test: if you could reconstruct this paragraph from the resume alone without any persona/vignette content, it is failing.
- Fix by adding: why the candidate chose that approach, what they tried first, what they learned, or why it matters for this specific company.

TONE CHECK (fix if violated):
- The letter must NOT frame stories as adversarial or combative. Rewrite any phrasing like "pushed back", "stepped in because others couldn't", "bridged a gap no one else could", "despite resistance", or similar language that positions the candidate against colleagues or leadership. Replace with collaborative framing: initiative, coordination, problem-solving together.
- The opening paragraph especially must NOT position the candidate as combative or contrarian. Lead with curiosity, alignment, or shared goals.

DIFFERENTIATION CHECKS (fix if violated):
- The opening paragraph MUST mention something specific about the company. If it starts with "I am reaching out to apply for X" or similar generic opener, rewrite it to lead with a company-specific insight.
- The closing MUST NOT be generic "thank you for your consideration" or "I would welcome the opportunity to discuss." It must connect to the company or role specifically.
- If the letter follows a rigid formula of opening → UCOP paragraph → GWR paragraph → closing, restructure to follow the strategy's prescribed order instead.

BREADTH CHECK (fix if violated):
- If the persona section provided multiple source projects and the body paragraphs all deep-dive the same one, rewrite one paragraph to draw from another selected source. If only one source project was selected, do not invent a second source.
- Each `### Source project:` block is a separate story. If details from two blocks have been fused into one invented causal chain, split or remove the fused claim.
- Trim exhaustive technical inventories. One concrete anchor per project is enough — no enumerating every tool, metric, or architectural detail. The resume carries specifics; the cover letter carries perspective.
- Fix attribution drift:
  - if a sentence starts with the wrong employer, rewrite it to match the source evidence exactly
  - if a tool or vendor name (for example Rapid7 or KnowBe4) appears inside Great Wolf evidence, do not turn it into a separate employer
  - if a project is a school, capstone, or personal project, label it as such and remove any "internal recognition" wording.

Return ONLY JSON with the same schema as the draft input."""

# ---------------------------------------------------------------------------
# Stage 4 – Humanize: remove AI writing patterns
# Curated from https://github.com/conorbronsdon/avoid-ai-writing (v3.0.0)
# ---------------------------------------------------------------------------
_COVER_HUMANIZE_SYSTEM = f"""\
You are a final-pass editor. Your sole job is to remove AI writing patterns \
("AI-isms") from cover letter paragraph text so it reads like a human wrote it.

You receive QA-cleaned JSON. Return ONLY corrected JSON — no markdown fences, \
no commentary, no explanation.

{_COVER_GUARDRAILS}

PRESERVE (never change):
- Company names, employer names, role titles, dates, tool/framework names
- All grounded claims and evidence (do not invent, remove, or rephrase factual content)
- Overall letter structure, paragraph count, and paragraph order

─── P0 — CREDIBILITY KILLERS (fix immediately) ───
- Resume regurgitation: if a sentence could be copy-pasted into a resume bullet \
without changes, it does not belong in a cover letter. Rewrite it to include \
the candidate's reasoning, motivation, or connection to the target company. \
"I automated X" → "I automated X because [reason], which is relevant to your \
team's [challenge]."
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

─── COVER-LETTER TIC CAPS (audit 2026-04 — fix if exceeded) ───
Recent audit found the same rhetorical devices repeated across every \
letter, which reads as AI-generated when compared side-by-side. Enforce \
these caps across the whole letter (opening + body + closing combined):

- "not just X, Y" / "not X, but Y" construction: at most ONE occurrence.
- "I don't just X — I Y" / "I don't just X, I Y" construction: at most ONE.
- "That same mindset / instinct / pattern / insight / approach shaped Y": \
  at most ONE occurrence.
- "That taught me that…" / "I learned that…" paragraph-ender: at most ONE \
  in the entire letter. Body paragraphs should end on what happened or \
  shipped, NOT on a distilled lesson. Save the single lesson for the \
  closing paragraph only.
- Triplet lists ("X, Y, and Z"): at most TWO per letter. Vary to pairs \
  or quads when a third item isn't earned.
- Aphoristic maxims ("reliable first, clever second"; "I'd rather be \
  slow than wrong"; "the right action is also the easiest"; etc.): at \
  most ONE per letter. Stacking multiple reads as performance, not voice.

MORAL-AT-END RULE (HARD): body paragraphs 2 and 3 must NOT end with a \
sentence that abstracts the story into a lesson or principle. End on what \
the candidate did, shipped, or decided. The closing paragraph is the only \
place a lesson may land.

When a cap is exceeded, rewrite the offending sentence to say the same \
thing in plain language, or cut it. Do not merely swap one tic for \
another from the list.

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


def _normalize_plain_text(text: str) -> str:
    """Normalize model text before LaTeX escaping/assembly."""
    cleaned = _strip_disallowed_dashes(text or "")
    cleaned = cleaned.replace("\u2019", "'").replace("\u2018", "'")
    cleaned = cleaned.replace("\u201c", '"').replace("\u201d", '"')
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _latex_escape_text(text: str) -> str:
    """Escape plain text for safe insertion into trusted LaTeX templates."""
    escaped = _normalize_plain_text(text)
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        escaped = escaped.replace(old, new)
    return escaped


def _parse_resume_baseline_sections(baseline: str) -> dict[str, Any]:
    """Extract trusted resume template parts for deterministic reassembly."""
    summary_match = re.search(
        r"(.*?% SUMMARY\s*\\section\{PROFESSIONAL SUMMARY\}\s*\\vspace\{\s*\\resumeSectionIntroGap\s*\}\s*"
        r"\\resumeSubHeadingListStart\s*\\item \{\s*\\resumeBodySize\s*)(.*?)(\}\s*\\resumeSubHeadingListEnd\s*"
        r"\\vspace\{\s*\\resumeSectionOutroGap\s*\}\s*% SKILLS)",
        baseline,
        re.DOTALL,
    )
    skills_match = re.search(
        r"(% SKILLS\s*\\section\{TECHNICAL SKILLS\}\s*\\vspace\{\s*\\resumeSectionOutroGap\s*\}\s*"
        r"\\resumeSubHeadingListStart\s*\\item \{\s*\\resumeBodySize\s*)(.*?)(\}\s*\\resumeSubHeadingListEnd\s*"
        r"\\vspace\{\s*\\resumeSectionOutroGap\s*\}\s*% EXPERIENCE)",
        baseline,
        re.DOTALL,
    )
    experience_match = re.search(
        r"(% EXPERIENCE\s*\\section\{WORK EXPERIENCE\}\s*\\vspace\{\s*\\resumeSectionIntroGap\s*\}\s*"
        r"\\resumeSubHeadingListStart\s*)(.*?)(\\resumeSubHeadingListEnd\s*\\vspace\{\s*\\resumeHeaderBottomGap\s*\}.*)",
        baseline,
        re.DOTALL,
    )
    if not summary_match or not skills_match or not experience_match:
        raise ValueError("Could not parse trusted resume baseline template")

    experience_entries: list[dict[str, str]] = []
    for match in _RESUME_COMPANY_HEADER_PATTERN.finditer(experience_match.group(2)):
        experience_entries.append(match.groupdict())

    return {
        "summary_prefix": summary_match.group(1),
        "summary_suffix": summary_match.group(3),
        "skills_prefix": skills_match.group(1),
        "skills_suffix": skills_match.group(3),
        "experience_prefix": experience_match.group(1),
        "experience_suffix": experience_match.group(3),
        "experience_entries": experience_entries,
    }


def _parse_baseline_skill_categories(baseline: str) -> dict[str, list[str]]:
    """Extract baseline skill lists so required categories stay anchored."""
    skills_block = re.search(
        r"\\section\{TECHNICAL SKILLS\}.*?\\item \{\s*\\resumeBodySize(.*?)\}\s*\\resumeSubHeadingListEnd",
        baseline,
        re.DOTALL,
    )
    if not skills_block:
        raise ValueError("Could not parse baseline skills block")

    categories: dict[str, list[str]] = {}
    for name, items in re.findall(r"\\textbf\{([^:]+):\}\s*(.*?)(?=(?:\\vspace\{3pt\}\s*\\textbf\{)|\Z)", skills_block.group(1), re.DOTALL):
        categories[_normalize_plain_text(name)] = [
            _normalize_plain_text(item) for item in items.split(",") if _normalize_plain_text(item)
        ]
    return categories


def _extract_baseline_resume_bullets_by_company(baseline: str) -> dict[str, list[str]]:
    """Extract trusted baseline bullets for each employer from the resume template."""
    section = _extract_work_experience_section(baseline)
    bullets_by_company = {company: [] for company in cfg.RESUME_COMPANIES}
    if not section:
        return bullets_by_company

    pattern = re.compile(
        r"\\resumeSubheading\s*"
        r"\{\s*(?P<company>[^}]*)\s*\}\s*"
        r"\{[^}]*\}\s*\{[^}]*\}\s*\{[^}]*\}"
        r"(?P<body>.*?)(?=(?:\\resumeSubheading\s*\{)|\\resumeSubHeadingListEnd|\\section\{|\\end\{document\})",
        re.DOTALL,
    )
    for match in pattern.finditer(section):
        company = _normalize_plain_text(match.group("company"))
        if company not in bullets_by_company:
            continue
        bullets_by_company[company] = [
            _normalize_plain_text(item)
            for item in re.findall(r"\\resumeItem\{(.*?)\}", match.group("body"), re.DOTALL)
            if _normalize_plain_text(item)
        ]
    return bullets_by_company


def _repair_missing_resume_bullets(
    experience_map: dict[str, list[str]],
    *,
    baseline: str,
) -> dict[str, list[str]]:
    """Backfill short employer sections from the trusted baseline instead of failing."""
    repaired = {company: list(bullets) for company, bullets in experience_map.items()}
    baseline_bullets = _extract_baseline_resume_bullets_by_company(baseline)
    expected_counts = cfg.RESUME_COMPANY_BULLET_TARGETS

    for company, expected in expected_counts.items():
        current = repaired.get(company) or []
        if len(current) >= expected:
            repaired[company] = current[:expected]
            continue

        seen = {_normalize_plain_text(bullet) for bullet in current if _normalize_plain_text(bullet)}
        for baseline_bullet in baseline_bullets.get(company, []):
            normalized = _normalize_plain_text(baseline_bullet)
            if not normalized or normalized in seen:
                continue
            current.append(normalized)
            seen.add(normalized)
            if len(current) >= expected:
                break
        repaired[company] = current[:expected]

    return repaired


def _coerce_skill_lines(raw_skills: dict[str, Any], baseline_skills: dict[str, list[str]]) -> dict[str, list[str]]:
    """Normalize model skills output while preserving hard baseline requirements."""
    normalized: dict[str, list[str]] = {}
    for category, baseline_items in baseline_skills.items():
        items = raw_skills.get(category) or []
        if isinstance(items, str):
            items = [part.strip() for part in items.split(",")]

        seen: set[str] = set()
        cleaned_items: list[str] = []
        for item in items:
            text = _normalize_plain_text(str(item))
            if text and text not in seen:
                cleaned_items.append(text)
                seen.add(text)

        if category in {"Languages", "Databases"}:
            required = list(baseline_items)
            ordered = [item for item in cleaned_items if item in required]
            for item in required:
                if item not in ordered:
                    ordered.append(item)
            normalized[category] = ordered
            continue

        for item in baseline_items:
            if item not in seen:
                cleaned_items.append(item)
                seen.add(item)
        normalized[category] = cleaned_items
    return normalized


def _normalize_skill_key(text: str) -> str:
    return _normalize_plain_text(text).casefold()


def _resume_skill_category_map() -> dict[str, str]:
    return {
        "Languages": "Languages",
        "Databases": "Databases",
        "Frameworks and Infrastructure": "Frameworks and Infrastructure",
        "Security Tooling": "Security Tooling",
        "DevOps and CI/CD": "DevOps and CI/CD",
        "AI/ML and Research": "AI/ML and Research",
        "AI-Native Development": "AI/ML and Research",
        "AI for SecOps": "AI/ML and Research",
        "Full-Stack Development": "Frameworks and Infrastructure",
        "Infrastructure and Reliability": "DevOps and CI/CD",
        "Security Engineering": "Security Tooling",
        "Security Automation": "Security Tooling",
        "Threat Hunting and Incident Response": "Security Tooling",
        "Cloud Security": "DevOps and CI/CD",
        "Application Security": "Security Tooling",
        "Penetration Testing and Offensive Tools": "Security Tooling",
        "DevSecOps": "DevOps and CI/CD",
        "Identity and Access": "Security Tooling",
        "Security Data Engineering": "AI/ML and Research",
        "Security Analytics": "AI/ML and Research",
        "API and Integrations": "Frameworks and Infrastructure",
        "Endpoint Operations and Remediation": "Security Tooling",
        "Web and Internal Security Tooling": "Frameworks and Infrastructure",
        "Testing and Quality Automation": "Frameworks and Infrastructure",
        "Technical Communication and Delivery": "Frameworks and Infrastructure",
        "data_and_ai": "AI/ML and Research",
        "api_and_enterprise": "Frameworks and Infrastructure",
    }


def _build_resume_skill_catalog(
    skills_data: dict[str, Any],
    baseline_skills: dict[str, list[str]],
) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    """Build canonical resume-skill mappings from the broader grounded inventory."""
    category_map = _resume_skill_category_map()
    catalog: dict[str, dict[str, str]] = {category: {} for category in baseline_skills}
    source_order: dict[str, list[str]] = {category: [] for category in baseline_skills}

    def register(category: str | None, skill: Any) -> None:
        if not category or category not in catalog:
            return
        text = _normalize_plain_text(str(skill))
        if not text:
            return
        key = _normalize_skill_key(text)
        if key not in catalog[category]:
            catalog[category][key] = text
            source_order[category].append(key)

    for category, items in baseline_skills.items():
        for item in items:
            register(category, item)

    inventory = skills_data.get("skills_inventory", {})
    for item in inventory.get("programming_languages", []):
        register("Languages", item)
    for item in inventory.get("databases", []):
        register("Databases", item)
    for item in inventory.get("frameworks_and_infrastructure", []):
        register("Frameworks and Infrastructure", item)
    for item in inventory.get("security_tooling", []):
        register("Security Tooling", item)
    for item in inventory.get("devops_and_cloud", []):
        register("DevOps and CI/CD", item)

    for bucket in inventory.get("core_skills", []) + inventory.get("supporting_skills", []):
        mapped = category_map.get(_normalize_plain_text(str(bucket.get("name") or "")))
        for skill in bucket.get("skills", []):
            register(mapped, skill)

    for bucket_name, items in (inventory.get("tools_and_platforms") or {}).items():
        mapped = category_map.get(_normalize_plain_text(str(bucket_name)))
        for item in items:
            register(mapped, item)

    return catalog, source_order


def _select_resume_skills(
    analysis: dict[str, Any],
    *,
    baseline_skills: dict[str, list[str]],
    skills_data: dict[str, Any],
) -> dict[str, list[str]]:
    """Deterministically assemble resume skills from grounded inventory + JD matches."""
    catalog, source_order = _build_resume_skill_catalog(skills_data, baseline_skills)
    category_map = _resume_skill_category_map()
    display_order = list(baseline_skills)
    priority_score = {"high": 12, "medium": 7, "low": 3}

    scores: dict[str, dict[str, int]] = {category: {} for category in display_order}
    baseline_keys: dict[str, list[str]] = {
        category: [_normalize_skill_key(item) for item in items]
        for category, items in baseline_skills.items()
    }

    for category, items in baseline_skills.items():
        for position, item in enumerate(items):
            key = _normalize_skill_key(item)
            scores[category][key] = max(scores[category].get(key, 0), max(1, len(items) - position))

    for req in analysis.get("requirements", []):
        mapped_category = category_map.get(_normalize_plain_text(str(req.get("matched_category") or "")))
        priority = priority_score.get(_normalize_plain_text(str(req.get("priority") or "medium")).lower(), 5)
        for raw_skill in req.get("matched_skills") or []:
            skill_key = _normalize_skill_key(str(raw_skill))
            for category in display_order:
                if skill_key not in catalog[category]:
                    continue
                scores[category][skill_key] = scores[category].get(skill_key, 0) + priority
                if mapped_category == category:
                    scores[category][skill_key] += 2

    selected: dict[str, list[str]] = {}
    for category in display_order:
        baseline_items = baseline_skills[category]
        if category in {"Languages", "Databases"}:
            ranked = sorted(
                ((_normalize_skill_key(item), item) for item in baseline_items),
                key=lambda pair: (-scores[category].get(pair[0], 0), baseline_items.index(pair[1])),
            )
            selected[category] = [item for _, item in ranked]
            continue

        cap = len(baseline_items)
        ranked_keys = sorted(
            source_order[category],
            key=lambda key: (
                -scores[category].get(key, 0),
                0 if key in baseline_keys[category] else 1,
                source_order[category].index(key),
            ),
        )

        chosen: list[str] = []
        for key in ranked_keys:
            if len(chosen) >= cap:
                break
            value = catalog[category][key]
            if value not in chosen:
                chosen.append(value)

        for item in baseline_items:
            if len(chosen) >= cap:
                break
            if item not in chosen:
                chosen.append(item)

        selected[category] = chosen

    return selected


def _coerce_resume_chunks(
    payload: dict[str, Any],
    *,
    baseline: str,
    baseline_skills: dict[str, list[str]],
    selected_skills: dict[str, list[str]],
) -> dict[str, Any]:
    """Normalize resume chunk JSON into a deterministic assembly shape."""
    summary = _normalize_plain_text(str(payload.get("summary") or ""))
    if not summary:
        raise ValueError("Resume chunk payload missing summary")

    experience_rows = payload.get("experience") or []
    experience_map: dict[str, list[str]] = {
        "University of California, Office of the President": [],
        "Great Wolf Resorts": [],
        "Simple.biz": [],
    }
    if isinstance(experience_rows, dict):
        for company, bullets in experience_rows.items():
            company_name = _normalize_plain_text(str(company))
            if company_name not in experience_map:
                continue
            if isinstance(bullets, list):
                experience_map[company_name] = [
                    _normalize_plain_text(str(b)) for b in bullets if _normalize_plain_text(str(b))
                ]
    elif isinstance(experience_rows, list):
        for row in experience_rows:
            if not isinstance(row, dict):
                continue
            company = _normalize_plain_text(str(row.get("company") or ""))
            if company not in experience_map:
                continue
            bullets = row.get("bullets") or []
            if isinstance(bullets, list):
                experience_map[company] = [_normalize_plain_text(str(b)) for b in bullets if _normalize_plain_text(str(b))]

    experience_map = _repair_missing_resume_bullets(experience_map, baseline=baseline)
    expected_counts = cfg.RESUME_COMPANY_BULLET_TARGETS
    for company, expected in expected_counts.items():
        bullets = experience_map.get(company) or []
        if len(bullets) < expected:
            raise ValueError(
                f"Resume chunk payload missing bullets for {company}: expected {expected}, found {len(bullets)}"
            )
        experience_map[company] = bullets[:expected]

    return {
        "summary": summary,
        "skills": selected_skills,
        "experience": experience_map,
    }


# Aggregators and job boards must never be rendered as the hiring company.
# If the analyzer or scraper propagates one of these as company_name, fail
# fast so the user sees it before a letter ships addressed to "dice" or "jobs".
_BOARD_NAME_BLOCKLIST = frozenset({
    "linkedin", "indeed", "glassdoor", "dice", "workingnomads",
    "working nomads", "jobs", "remoteok", "remote ok", "usajobs",
    "hn_hiring", "hn hiring", "hackernews", "hacker news",
    "greenhouse", "lever", "ashby", "ashbyhq", "workday",
    "aggregator", "searxng", "unknown",
})

# Narrow override map for names we've seen rendered compressed/lowercase.
# Keep this short — extend only when a real case appears in audit.
_COMPANY_CASE_OVERRIDES = {
    "apexsystems": "Apex Systems",
    "apex systems": "Apex Systems",
}


def _resolve_company_name(analysis: dict[str, Any], job: "SelectedJob") -> str:
    """Resolve the hiring company display name for cover letter rendering.

    Prefers `analysis.company_name` (LLM-extracted from JD), falls back to
    `job.company` (scraper heuristic). Raises RuntimeError if the resolved
    value is a known job-board/aggregator, because that means the body
    letter would end up addressed to the wrong entity.
    """
    raw = str(analysis.get("company_name") or job.company or "").strip()
    if not raw:
        raise RuntimeError(
            f"Cover letter generation blocked: no company name resolved "
            f"(job {job.id}). Analyzer returned empty company_name and "
            f"job.company is blank. Fix the JD extraction before re-running."
        )
    lowered = raw.lower()
    if lowered in _BOARD_NAME_BLOCKLIST:
        raise RuntimeError(
            f"Cover letter generation blocked: company_name resolved to "
            f"job-board/aggregator '{raw}' (job {job.id}). The JD must name "
            f"the real hiring employer. Fix analysis.json `company_name` or "
            f"the scraper's company field before re-running."
        )
    if lowered in _COMPANY_CASE_OVERRIDES:
        return _COMPANY_CASE_OVERRIDES[lowered]
    # Title-case a lowercase single-token name so headers render as
    # "Arcadia" instead of "arcadia".
    if raw.islower():
        return raw.title()
    return raw


def _dedupe_adjacent_paragraphs(paragraphs: list[str]) -> list[str]:
    """Collapse adjacent identical or near-identical paragraphs.

    Observed in the 4514 humanize output, which shipped the closing
    paragraph twice back-to-back. Compares on a whitespace-collapsed key
    so trailing punctuation/spacing differences still dedupe.
    """
    deduped: list[str] = []
    last_key: str | None = None
    for paragraph in paragraphs:
        key = re.sub(r"\s+", " ", paragraph).strip().lower()
        if key and key == last_key:
            continue
        deduped.append(paragraph)
        last_key = key
    return deduped


def _coerce_cover_chunks(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize cover letter chunk JSON into safe assembly fields."""
    paragraphs = payload.get("paragraphs") or []
    if isinstance(paragraphs, str):
        paragraphs = [paragraphs]
    normalized_paragraphs = [_normalize_plain_text(str(p)) for p in paragraphs if _normalize_plain_text(str(p))]
    normalized_paragraphs = _dedupe_adjacent_paragraphs(normalized_paragraphs)
    closing = _normalize_plain_text(str(payload.get("closing") or ""))
    # Also guard against the final paragraph being duplicated as the closing.
    if normalized_paragraphs and closing:
        last_key = re.sub(r"\s+", " ", normalized_paragraphs[-1]).strip().lower()
        closing_key = re.sub(r"\s+", " ", closing).strip().lower()
        if last_key == closing_key:
            normalized_paragraphs = normalized_paragraphs[:-1]
    if len(normalized_paragraphs) < 2:
        raise ValueError(
            f"Cover chunk payload missing body paragraphs: expected at least 2, found {len(normalized_paragraphs)}"
        )
    if not closing:
        raise ValueError("Cover chunk payload missing closing")
    return {"paragraphs": normalized_paragraphs, "closing": closing}


def _assemble_resume_tex(
    baseline: str,
    *,
    summary: str,
    skills: dict[str, list[str]],
    experience_bullets: dict[str, list[str]],
) -> str:
    """Rebuild the resume from trusted template scaffolding and safe content chunks."""
    sections = _parse_resume_baseline_sections(baseline)
    summary_tex = f"{sections['summary_prefix']}{_latex_escape_text(summary)}{sections['summary_suffix']}"

    skill_lines: list[str] = []
    category_order = [
        "Languages",
        "Security Tooling",
        "AI/ML and Research",
        "Frameworks and Infrastructure",
        "DevOps and CI/CD",
        "Databases",
    ]
    for index, category in enumerate(category_order):
        items = skills.get(category) or []
        items_text = ", ".join(_latex_escape_text(item) for item in items)
        skill_lines.append(rf"\textbf{{{category}:}} {items_text}")
        if index != len(category_order) - 1:
            skill_lines.append("")
            skill_lines.append(r"\vspace{3pt}")
    skills_body = "\n".join(skill_lines)
    skills_tex = f"{sections['skills_prefix']}{skills_body}\n{sections['skills_suffix']}"

    work_blocks: list[str] = []
    for index, entry in enumerate(sections["experience_entries"]):
        company = _normalize_plain_text(entry["company"])
        bullets = experience_bullets.get(company) or []
        block_lines = [
            r"\resumeSubheading",
            f"  {{{_latex_escape_text(entry['company'])}}}{{{_latex_escape_text(entry['location'])}}}",
            f"  {{{_latex_escape_text(entry['role'])}}}{{{_latex_escape_text(entry['dates'])}}}",
            r"\vspace{2pt}",
            r"\resumeItemListStart",
        ]
        for bullet in bullets:
            block_lines.append(f"  \\resumeItem{{{_latex_escape_text(bullet)}}}")
        block_lines.append(r"\resumeItemListEnd")
        if index != len(sections["experience_entries"]) - 1:
            block_lines.append(r"\vspace{\resumeSectionOutroGap}")
            block_lines.append("")
        work_blocks.append("\n".join(block_lines))
    experience_tex = sections["experience_prefix"] + "\n\n".join(work_blocks) + "\n\n" + sections["experience_suffix"]
    return summary_tex + "\n\n" + skills_tex + "\n\n" + experience_tex


def _assemble_cover_tex(
    baseline: str,
    *,
    company_name: str,
    date_text: str,
    paragraphs: list[str],
    closing: str,
) -> str:
    """Rebuild the cover letter from trusted template scaffolding and text chunks."""
    tex = baseline.replace(r"\lbrack COMPANY\_NAME\rbrack", _latex_escape_text(company_name), 1)
    tex = tex.replace("[DATE]", _latex_escape_text(date_text), 1)

    body_match = re.search(
        r"(% Salutation\s*\\noindent\s*Dear Hiring Team,\s*\\vspace\{16pt\}\s*)(.*?)(\s*Sincerely,\\\\\s*Conner Jordan\s*\\end\{document\})",
        tex,
        re.DOTALL,
    )
    if not body_match:
        raise ValueError("Could not parse trusted cover baseline template")

    body_parts = [body_match.group(1)]
    for paragraph in paragraphs:
        body_parts.append(_latex_escape_text(paragraph))
        body_parts.append("\n\n\\vspace{16pt}\n\n")
    body_parts.append(_latex_escape_text(closing))
    body_parts.append("\n\n\\vspace{16pt}\n\n")
    body_parts.append("Sincerely,\\\\\n\n\\vspace{16pt}\n\nConner Jordan\n\n\\end{document}")
    rebuilt = "".join(body_parts)
    return tex[:body_match.start()] + rebuilt


def _resume_strategy(
    job: SelectedJob,
    analysis: dict,
    baseline: str,
    skills_data: dict,
    grounding: dict,
    attempt: int,
    trace_recorder: Callable[[dict], None] | None = None,
) -> dict:
    _log_vignette_selection(trace_recorder, analysis, "resume", "strategy", attempt)
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
    _log_vignette_selection(trace_recorder, analysis, "cover", "strategy", attempt)
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
            f"## Resume Strategy (already committed — cover letter must COMPLEMENT, not repeat)\n"
            f"{json.dumps(resume_strategy, indent=2)}\n\n"
            f"CONSISTENCY RULES:\n"
            f"- Do NOT recommend claims the resume strategy listed in claims_to_avoid.\n"
            f"- The cover letter should NOT restate resume bullets. The resume already covers what was built. The cover letter must add: reasoning, tradeoffs, lessons, motivation, and connection to the company.\n"
            f"- Use the resume strategy to know what facts the resume already covers, then deliberately say something DIFFERENT in the cover letter.\n\n"
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
    for entry in (strategy.get("experience_rewrites") or []):
        company = entry.get("company", "")
        # bullet_rewrites may be a JSON-encoded string (model serialization bug) or a real list
        bw = entry.get("bullet_rewrites") or []
        if isinstance(bw, str):
            try:
                bw = json.loads(bw)
            except Exception:
                bw = []
        for rw in (bw or []):
            rewrites.append({
                "company": company,
                "baseline_topic": rw.get("baseline_topic", ""),
                "rewrite_angle": rw.get("rewrite_angle", ""),
                "jd_req": rw.get("jd_requirement_addressed", ""),
                "allowed_evidence": rw.get("allowed_evidence", {}),
            })
        bp = entry.get("bullets_to_preserve") or []
        if isinstance(bp, str):
            try:
                bp = json.loads(bp)
            except Exception:
                bp = []
        for topic in (bp or []):
            preserves.append({"company": company, "topic": topic})
    return rewrites, preserves


def _set_resume_fit_flags(
    tex: str,
    *,
    compact: bool | None = None,
    pruned: bool | None = None,
    loose: bool | None = None,
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
    if loose is not None:
        tex = tex.replace(
            "\\looseresumetrue" if not loose else "\\looseresumefalse",
            "\\looseresumetrue" if loose else "\\looseresumefalse",
            1,
        )
    return tex


def _resume_fit_candidate_is_structurally_valid(tex: str, *, mode: str) -> bool:
    """Reject fit-pass outputs that silently violate bullet-count contracts."""
    counts = _count_resume_bullets_by_company(tex)
    if mode == "prune":
        for company in cfg.RESUME_COMPANIES:
            count = counts.get(company, 0)
            floor = cfg.RESUME_COMPANY_BULLET_FLOORS[company]
            cap = cfg.RESUME_COMPANY_BULLET_TARGETS[company]
            if not (floor <= count <= cap):
                return False
        return True

    return counts == cfg.RESUME_COMPANY_BULLET_TARGETS


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
        thinking_multiplier=2,
    )
    tex = _strip_disallowed_dashes(extract_latex(raw))
    return _set_resume_fit_flags(
        tex,
        compact="\\compactresumetrue" in current_tex,
        pruned=(mode == "prune"),
    )


def _maybe_expand_underfilled_resume(
    out_path: Path,
    tex: str,
    metrics: ResumeFitMetrics,
    *,
    attempt: int,
    fit_mode: str,
    baseline_body_len: int,
    trace_recorder: Callable[[dict], None] | None = None,
) -> tuple[str, ResumeFitMetrics]:
    """Try loose layout whenever a one-page resume is too vertically sparse."""
    if not (
        metrics.page_count == cfg.RESUME_TARGET_PAGES
        and metrics.page_fill_ratio is not None
        and metrics.page_fill_ratio < cfg.RESUME_MIN_FILL_RATIO
    ):
        return tex, metrics

    loose_tex = _set_resume_fit_flags(tex, loose=True)
    if trace_recorder:
        trace_recorder(
            {
                "event_type": "resume_fit_stage",
                "doc_type": "resume",
                "phase": "fit",
                "fit_mode": "loose",
                "attempt": attempt,
                "action": "enable_loose_layout",
                "trigger_fit_mode": fit_mode,
                "pre_fill_ratio": metrics.page_fill_ratio,
            }
        )
    loose_compiled, loose_metrics = _inspect_resume_candidate(
        out_path,
        loose_tex,
        attempt=attempt,
        fit_mode="loose",
        baseline_body_len=baseline_body_len,
        trace_recorder=trace_recorder,
    )
    if (
        loose_compiled
        and loose_metrics.page_count == cfg.RESUME_TARGET_PAGES
        and loose_metrics.page_fill_ratio is not None
        and loose_metrics.page_fill_ratio > (metrics.page_fill_ratio or 0.0)
    ):
        return loose_tex, loose_metrics

    out_path.write_text(tex)
    compile_tex(out_path)
    return tex, metrics


def _trim_cover_text_to_budget(
    paragraphs: list[str],
    closing: str,
    *,
    target_hi: int,
    baseline: str,
    company_name: str,
    date_text: str,
) -> tuple[list[str], str]:
    """Deterministically tighten small cover-letter overshoots before retrying."""
    trimmed_paragraphs = list(paragraphs)
    trimmed_closing = closing

    replacements = [
        ("I would be excited to", "I would"),
        ("I'd love to", "I'd like to"),
        ("I am excited to", "I want to"),
        ("I am drawn to", "I like"),
        ("especially as someone who", "as someone who"),
        ("I know that ", ""),
        ("I believe in ", ""),
        ("just ", ""),
        ("really ", ""),
        ("very ", ""),
    ]

    def current_body_len() -> int:
        tex = _assemble_cover_tex(
            baseline,
            company_name=company_name,
            date_text=date_text,
            paragraphs=trimmed_paragraphs,
            closing=trimmed_closing,
        )
        return len(_extract_body_text(tex))

    def tighten_text(text: str) -> str:
        updated = text
        for old, new in replacements:
            updated = updated.replace(old, new)
        updated = re.sub(r"\s+,", ",", updated)
        updated = re.sub(r"\s{2,}", " ", updated)
        return updated.strip()

    for index, paragraph in enumerate(trimmed_paragraphs):
        if current_body_len() <= target_hi:
            break
        trimmed_paragraphs[index] = tighten_text(paragraph)

    if current_body_len() > target_hi:
        trimmed_closing = tighten_text(trimmed_closing)

    for index, paragraph in enumerate(trimmed_paragraphs):
        if current_body_len() <= target_hi:
            break
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", paragraph) if s.strip()]
        while len(sentences) > 2 and current_body_len() > target_hi:
            sentences.pop()
            trimmed_paragraphs[index] = " ".join(sentences)

    if current_body_len() > target_hi:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", trimmed_closing) if s.strip()]
        while len(sentences) > 1 and current_body_len() > target_hi:
            sentences.pop()
            trimmed_closing = " ".join(sentences)

    return trimmed_paragraphs, trimmed_closing


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
    char_ratio: float = 1.0,
    trace_recorder: Callable[[dict], None] | None = None,
) -> str:
    """Apply resume-only fit stages until the PDF renders on one page or stages are exhausted."""
    # If draft is shorter than the baseline (which fits on one page), skip the
    # compile+inspect cycle entirely — the content cannot overflow.
    if char_ratio < 0.95:
        logger.info("Skipping fit-to-page: char_ratio %.2f < 0.95 (draft shorter than baseline)", char_ratio)
        current_tex = _set_resume_fit_flags(tex, compact=False, pruned=False)
        # Still compile so the PDF exists for validation reuse
        out_path = output_dir / "Conner_Jordan_Resume.tex"
        out_path.write_text(current_tex)
        compile_tex(out_path)
        return current_tex

    out_path = output_dir / "Conner_Jordan_Resume.tex"
    baseline_body_len = len(_extract_body_text(baseline))
    current_tex = _set_resume_fit_flags(tex, compact=False, pruned=False, loose=False)

    compiled, metrics = _inspect_resume_candidate(
        out_path,
        current_tex,
        attempt=attempt,
        fit_mode="initial",
        baseline_body_len=baseline_body_len,
        trace_recorder=trace_recorder,
    )
    if not compiled:
        return current_tex

    current_tex, metrics = _maybe_expand_underfilled_resume(
        out_path,
        current_tex,
        metrics,
        attempt=attempt,
        fit_mode="initial",
        baseline_body_len=baseline_body_len,
        trace_recorder=trace_recorder,
    )

    if metrics.page_count == cfg.RESUME_TARGET_PAGES:
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
        if compiled and _resume_fit_candidate_is_structurally_valid(condensed_tex, mode="condense"):
            current_tex = condensed_tex
            metrics = condensed_metrics
            current_tex, metrics = _maybe_expand_underfilled_resume(
                out_path,
                current_tex,
                metrics,
                attempt=attempt,
                fit_mode="condense",
                baseline_body_len=baseline_body_len,
                trace_recorder=trace_recorder,
            )
        elif compiled:
            out_path.write_text(current_tex)
            compile_tex(out_path)
        if metrics.page_count == cfg.RESUME_TARGET_PAGES:
            return current_tex

    if cfg.RESUME_FIT_MAX_STAGES < 2:
        return current_tex

    pruned_tex = _run_resume_fit_pass(
        "prune",
        job=job,
        analysis=analysis,
        baseline=baseline,
        strategy=strategy,
        grounding=grounding,
        rewrite_block=rewrite_block,
        current_tex=_set_resume_fit_flags(current_tex, compact=False, pruned=False),
        metrics=metrics,
        attempt=attempt,
        trace_recorder=trace_recorder,
    )
    compiled, prune_metrics = _inspect_resume_candidate(
        out_path,
        _set_resume_fit_flags(pruned_tex, compact=False, pruned=True),
        attempt=attempt,
        fit_mode="prune",
        baseline_body_len=baseline_body_len,
        trace_recorder=trace_recorder,
    )
    pruned_candidate = _set_resume_fit_flags(pruned_tex, compact=False, pruned=True)
    if compiled and _resume_fit_candidate_is_structurally_valid(pruned_candidate, mode="prune"):
        current_tex = _set_resume_fit_flags(pruned_tex, compact=False, pruned=True)
        metrics = prune_metrics
        current_tex, metrics = _maybe_expand_underfilled_resume(
            out_path,
            current_tex,
            metrics,
            attempt=attempt,
            fit_mode="prune",
            baseline_body_len=baseline_body_len,
            trace_recorder=trace_recorder,
        )
    elif compiled:
        out_path.write_text(current_tex)
        compile_tex(out_path)

    return current_tex


def write_resume(
    job: SelectedJob,
    analysis: dict,
    output_dir: Path,
    previous_feedback: RetryFeedback | None = None,
    attempt: int = 1,
    trace_recorder: Callable[[dict], None] | None = None,
    on_strategy_ready: Callable[[], None] | None = None,
) -> Path:
    """Generate a tailored resume with a 3-stage pipeline: strategy, draft, QA.

    If on_strategy_ready is provided, it is called after resume_strategy.json
    is written, allowing parallel work (e.g. cover letter) to begin.
    """
    baseline = cfg.read_cached(cfg.RESUME_TEX)
    baseline_skills = _parse_baseline_skill_categories(baseline)
    skills_data = cfg.read_json_cached(cfg.SKILLS_JSON)
    selected_skills = _select_resume_skills(
        analysis,
        baseline_skills=baseline_skills,
        skills_data=skills_data,
    )
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
    if on_strategy_ready is not None:
        on_strategy_ready()

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

    _log_vignette_selection(trace_recorder, analysis, "resume", "draft", attempt)
    resume_draft_persona = get_persona().for_draft(analysis, "resume")

    draft_prompt = (
        f"## Baseline Resume Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"{grounding_prompt_block(grounding)}\n\n"
        f"## Candidate Persona (voice, contribution patterns, evidence anchors — use this to guide HOW bullets are written)\n"
        f"{resume_draft_persona}\n\n"
        f"## Skills Inventory (supplemental context — these category names are NOT resume section names)\n"
        f"Note: The resume's TECHNICAL SKILLS block is assembled deterministically in code, not authored by the model.\n"
        f"This inventory is provided only to support grounded summary and bullet wording.\n"
        f"{json.dumps(skills_data['skills_inventory'], indent=2)}\n\n"
        f"## Final Skills Block (already selected from grounded inventory — DO NOT rewrite)\n"
        f"{json.dumps(selected_skills, indent=2)}\n\n"
        f"Target Role: {analysis.get('role_title', job.title)}\n"
        f"Target Company: {analysis.get('company_name', job.company)}\n"
        f"Summary Angle: {analysis.get('summary_angle', 'general security engineering')}\n\n"
        f"## BULLET REWRITE DIRECTIVES\n"
        f"{rewrite_block if rewrite_block else '(no rewrites extracted from strategy)'}\n\n"
        f"## Skills Tailoring\n"
        f"{json.dumps(strategy.get('skills_tailoring', {}), indent=2)}\n"
    )

    retry_feedback_block = _format_retry_feedback_block(previous_feedback)
    if retry_feedback_block:
        draft_prompt += f"\n## PREVIOUS ATTEMPT FEEDBACK (CRITICAL: FIX THESE)\n{retry_feedback_block}\n"

    draft_chunks = chat_expect_json(
        _RESUME_DRAFT_SYSTEM,
        draft_prompt,
        max_tokens=4096,
        temperature=0.25,
        trace={
            "doc_type": "resume",
            "phase": "draft",
            "attempt": attempt,
            "response_parse_kind": "json",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
    )
    draft_payload = _coerce_resume_chunks(
        draft_chunks,
        baseline=baseline,
        baseline_skills=baseline_skills,
        selected_skills=selected_skills,
    )
    draft_tex = _assemble_resume_tex(
        baseline,
        summary=draft_payload["summary"],
        skills=draft_payload["skills"],
        experience_bullets=draft_payload["experience"],
    )
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
        f"## Draft Resume Chunks\n```json\n{json.dumps(draft_payload, indent=2)}\n```\n\n"
        f"## Final Skills Block (already selected from grounded inventory — preserve exactly)\n"
        f"```json\n{json.dumps(selected_skills, indent=2)}\n```\n\n"
        f"## STRUCTURAL CHECKS (fix these before anything else)\n"
        f"- {length_status}\n"
        f"- {bullet_status}\n\n"
        f"## Reviewer Focus\n"
        f"- remove em/en dashes\n"
        f"- remove or soften ungrounded percentage claims\n"
        f"- replace generic corporate language with concrete technical phrasing\n"
        f"- keep the resume concise enough to fit the one-page baseline layout\n"
    )
    if retry_feedback_block:
        qa_prompt += f"\n## PRIOR VALIDATION FAILURES TO FIX\n{retry_feedback_block}\n"

    qa_chunks = chat_expect_json(
        _RESUME_QA_SYSTEM,
        qa_prompt,
        max_tokens=4096,
        temperature=0.15,
        trace={
            "doc_type": "resume",
            "phase": "qa",
            "attempt": attempt,
            "response_parse_kind": "json",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
        thinking_multiplier=2,
    )
    qa_payload = _coerce_resume_chunks(
        qa_chunks,
        baseline=baseline,
        baseline_skills=baseline_skills,
        selected_skills=selected_skills,
    )
    tex = _assemble_resume_tex(
        baseline,
        summary=qa_payload["summary"],
        skills=qa_payload["skills"],
        experience_bullets=qa_payload["experience"],
    )
    tex = _strip_disallowed_dashes(tex)
    # Recompute char ratio from post-QA tex — QA may have expanded a short draft
    qa_body_len = len(_extract_body_text(tex))
    qa_char_ratio = qa_body_len / baseline_body_len if baseline_body_len else 1.0
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
        char_ratio=qa_char_ratio,
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
    previous_feedback: RetryFeedback | None = None,
    attempt: int = 1,
    trace_recorder: Callable[[dict], None] | None = None,
) -> Path:
    """Generate a tailored cover letter with a 4-stage pipeline: strategy, draft, QA, humanize."""
    baseline = cfg.read_cached(cfg.COVER_TEX)
    skills_data = cfg.read_json_cached(cfg.SKILLS_JSON)
    grounding = build_grounding_context(skills_data=skills_data)

    # Resolve the hiring company once, BEFORE any LLM stage, so a job-board
    # or aggregator name never reaches the strategy/draft/QA prompts or the
    # final \companyname render. Raises RuntimeError on known boards.
    company_name = _resolve_company_name(analysis, job)
    # Canonicalize inside the analysis dict so downstream prompts that read
    # analysis.company_name see the rendered form (e.g. "Arcadia" not "arcadia").
    analysis["company_name"] = company_name

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

    baseline_body_len = len(_extract_body_text(baseline))
    target_lo = int(baseline_body_len * (1 - cfg.COVER_CHAR_TOLERANCE))
    target_hi = int(baseline_body_len * (1 + cfg.COVER_CHAR_TOLERANCE))

    company_ctx = analysis.get("company_context", {})
    _log_vignette_selection(trace_recorder, analysis, "cover", "draft", attempt)
    cover_draft_persona = get_persona().for_draft(analysis, "cover")
    draft_prompt = (
        f"## Length Budget (HARD)\n"
        f"Baseline cover letter body is {baseline_body_len} chars. "
        f"Your draft body MUST land between {target_lo} and {target_hi} chars "
        f"(±{int(cfg.COVER_CHAR_TOLERANCE * 100)}% tolerance). "
        f"Going over is a HARD failure. Count roughly as you write — "
        f"three to four focused paragraphs of 4–6 sentences each is the right shape.\n\n"
        f"## Baseline Cover Letter Template\n```latex\n{baseline}\n```\n\n"
        f"## Analysis Mapping\n{json.dumps(analysis, indent=2)}\n\n"
        f"## Cover Strategy\n{json.dumps(strategy, indent=2)}\n\n"
        f"## Strategy Evidence Boundaries (HARD)\n"
        f"Each paragraph in the strategy carries an `allowed_evidence_by_source`\n"
        f"dict mapping each source name to its approved terms. These boundaries\n"
        f"are non-negotiable:\n"
        f"- A term listed under source A may only appear in sentences attributing\n"
        f"  the work to source A. Do not borrow terms across keys.\n"
        f"- Two discrete projects at the same employer are separate sources. A\n"
        f"  sentence about Coraline may not name LangChain, vector databases, or\n"
        f"  RAG; a sentence about the RAG chatbot may not name Flask, React, AWS\n"
        f"  ECS, Docker, 500 drifted assets, Rapid7, BigFix, or Jamf.\n"
        f"- When a paragraph references both projects, keep their stacks, metrics,\n"
        f"  and mechanics in their own sentences. Do not fuse them.\n"
        f"- Do not rewrite the lesson from one project as an outcome of another\n"
        f"  (e.g. do not say lessons from the chatbot were 'applied when building'\n"
        f"  Coraline unless that chaining is in the persona evidence).\n"
        f"- If a needed term is not in any source's list, omit the detail rather\n"
        f"  than inventing or borrowing from an adjacent source.\n\n"
        f"{grounding_prompt_block(grounding)}\n\n"
        f"## Company Context\n"
        f"What they build: {company_ctx.get('what_they_build', 'unknown')}\n"
        f"Engineering challenges: {company_ctx.get('engineering_challenges', 'unknown')}\n"
        f"Company type: {company_ctx.get('company_type', 'other')}\n"
        f"Cover letter hook: {company_ctx.get('cover_letter_hook', 'none')}\n\n"
        f"## Candidate Persona\n{cover_draft_persona}\n\n"
        f"Target Role: {analysis.get('role_title', job.title)}\n"
        f"Target Company: {analysis.get('company_name', job.company)}\n"
        f"Today's Date: {today}\n"
        f"Tone Notes: {analysis.get('tone_notes', 'standard professional tone')}\n"
    )

    retry_feedback_block = _format_retry_feedback_block(previous_feedback)
    if retry_feedback_block:
        draft_prompt += f"\n## PREVIOUS ATTEMPT FEEDBACK (CRITICAL: FIX THESE)\n{retry_feedback_block}\n"

    draft_chunks = chat_expect_json(
        _COVER_DRAFT_SYSTEM,
        draft_prompt,
        max_tokens=2200,
        temperature=0.25,
        trace={
            "doc_type": "cover",
            "phase": "draft",
            "attempt": attempt,
            "response_parse_kind": "json",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
    )
    draft_payload = _coerce_cover_chunks(draft_chunks)
    draft_tex = _assemble_cover_tex(
        baseline,
        company_name=company_name,
        date_text=today,
        paragraphs=draft_payload["paragraphs"],
        closing=draft_payload["closing"],
    )
    draft_tex = _strip_disallowed_dashes(draft_tex)

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

    # Load baseline resume so QA can detect regurgitation
    resume_baseline = cfg.read_cached(cfg.RESUME_TEX) if cfg.RESUME_TEX.exists() else ""
    qa_prompt = (
        f"## Baseline Cover Template\n```latex\n{baseline}\n```\n\n"
        f"## Cover Strategy\n{json.dumps(strategy, indent=2)}\n\n"
        f"{grounding_prompt_block(grounding)}\n\n"
        f"## Draft Cover Chunks\n```json\n{json.dumps(draft_payload, indent=2)}\n```\n\n"
        f"## Baseline Resume (for regurgitation detection — cover letter must NOT restate these bullets)\n```latex\n{resume_baseline}\n```\n\n"
        f"## STRUCTURAL CHECKS\n"
        f"- {cover_length_status}\n\n"
        f"## Reviewer Focus\n"
        f"- HIGHEST PRIORITY: check each paragraph for resume regurgitation (see system prompt)\n"
        f"- remove em/en dashes\n"
        f"- remove or soften ungrounded percentage claims\n"
        f"- reduce corporate-speak and keep concrete language\n"
    )
    if retry_feedback_block:
        qa_prompt += f"\n## PRIOR VALIDATION FAILURES TO FIX\n{retry_feedback_block}\n"

    qa_chunks = chat_expect_json(
        _COVER_QA_SYSTEM,
        qa_prompt,
        max_tokens=2200,
        temperature=0.15,
        trace={
            "doc_type": "cover",
            "phase": "qa",
            "attempt": attempt,
            "response_parse_kind": "json",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
        thinking_multiplier=2,
    )
    qa_payload = _coerce_cover_chunks(qa_chunks)
    tex = _assemble_cover_tex(
        baseline,
        company_name=company_name,
        date_text=today,
        paragraphs=qa_payload["paragraphs"],
        closing=qa_payload["closing"],
    )
    tex = _strip_disallowed_dashes(tex)

    # --- Stage 4: Humanize (remove AI writing patterns) ---
    pre_humanize_tex = tex

    humanize_prompt = (
        f"## Cover Chunks to Edit\n```json\n{json.dumps(qa_payload, indent=2)}\n```\n\n"
        f"## Grounding Context (DO NOT MODIFY THESE FACTS)\n"
        f"Company: {analysis.get('company_name', job.company)}\n"
        f"Role: {analysis.get('role_title', job.title)}\n"
        f"{grounding_prompt_block(grounding)}\n"
    )

    humanize_chunks = chat_expect_json(
        _COVER_HUMANIZE_SYSTEM,
        humanize_prompt,
        max_tokens=2200,
        temperature=0.15,
        trace={
            "doc_type": "cover",
            "phase": "humanize",
            "attempt": attempt,
            "response_parse_kind": "json",
            "response_parse_status": "ok",
        },
        trace_recorder=trace_recorder,
        thinking_multiplier=2,
    )
    humanized_payload = _coerce_cover_chunks(humanize_chunks)
    humanized_payload["paragraphs"], humanized_payload["closing"] = _trim_cover_text_to_budget(
        humanized_payload["paragraphs"],
        humanized_payload["closing"],
        target_hi=target_hi,
        baseline=baseline,
        company_name=company_name,
        date_text=today,
    )
    tex = _assemble_cover_tex(
        baseline,
        company_name=company_name,
        date_text=today,
        paragraphs=humanized_payload["paragraphs"],
        closing=humanized_payload["closing"],
    )
    tex = _strip_disallowed_dashes(tex)

    # Save pre-humanize draft for diff inspection
    (output_dir / "cover_pre_humanize.tex").write_text(pre_humanize_tex)

    out_path = output_dir / "Conner_Jordan_Cover_Letter.tex"
    out_path.write_text(tex)
    compile_tex(out_path)
    write_grounding_artifacts(
        output_dir,
        grounding=grounding,
        analysis=analysis,
        resume_strategy=resume_strategy,
        cover_strategy=strategy,
    )
    logger.info("Cover letter written to %s (%d chars)", out_path, len(tex))
    return out_path
