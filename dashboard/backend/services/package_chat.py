"""Package chat — intent-routed LLM interface for tailoring output packages."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import app as _app

logger = logging.getLogger(__name__)

TAILORING_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "tailoring"
OUTPUT_DIR = TAILORING_ROOT / "output"
SOUL_MD = TAILORING_ROOT / "soul.md"

MAX_HISTORY = 12
HISTORY_PREVIEW_CHARS = 700
DOC_SUMMARY_CHARS = 2200
JD_SUMMARY_CHARS = 2600

TEX_MAP = {
    "resume": "Conner_Jordan_Resume.tex",
    "cover": "Conner_Jordan_Cover_Letter.tex",
}

MODE_CONFIG = {
    "edit": {
        "max_tokens": 4096,
        "temperature": 0.2,
        "model_env": "TAILOR_PACKAGE_CHAT_EDIT_MODEL",
    },
    "application_answer": {
        "max_tokens": 900,
        "temperature": 0.28,
        "model_env": "TAILOR_PACKAGE_CHAT_APPLICATION_MODEL",
    },
    "general": {
        "max_tokens": 1600,
        "temperature": 0.3,
        "model_env": "TAILOR_PACKAGE_CHAT_GENERAL_MODEL",
    },
}

APPLICATION_HINTS = (
    "application question",
    "additional information",
    "help me answer",
    "supplemental question",
    "what excites you",
    "what excites me",
    "what excites",
    "what interests you",
    "what interests me",
    "what drew you",
    "what draws you",
    "why do you want",
    "why are you interested",
    "why this company",
    "why this role",
    "why us",
    "tell us about",
    "please share anything else",
    "short answer",
)

EDIT_HINTS = (
    "edit",
    "rewrite",
    "revise",
    "retailor",
    "tailor",
    "update",
    "change",
    "fix",
    "tighten",
    "shorten",
    "condense",
    "expand",
    "rephrase",
    "add",
    "remove",
    "swap",
    "improve",
)

DOC_HINTS = (
    "resume",
    "cover letter",
    "cover",
    "summary",
    "bullet",
    "skills",
    "paragraph",
    "letter",
)


def _pkg_dir(slug: str) -> Path | None:
    d = OUTPUT_DIR / slug
    if not d.is_dir() or ".." in slug:
        return None
    return d


def _history_path(slug: str) -> Path | None:
    d = _pkg_dir(slug)
    return d / "chat_history.jsonl" if d else None


def _load_json(path: Path) -> dict | None:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _read_text(path: Path, max_chars: int = 0) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    if max_chars > 0:
        return text[:max_chars]
    return text


def _strip_edit_blocks(text: str) -> str:
    return re.sub(r"<<<EDIT\s*\nOLD:\s*\n[\s\S]*?\nEDIT>>>", "", text, flags=re.DOTALL).strip()


def _clean_application_answer(text: str, *, user_message: str = "") -> str:
    """Remove model scaffolding that makes short application answers feel canned."""
    cleaned = _strip_edit_blocks(text)
    cleaned = re.sub(r"```(?:[a-zA-Z0-9_-]+)?\n?([\s\S]*?)```", r"\1", cleaned)
    cleaned = re.sub(
        r"^\s*(?:primary answer|answer|draft|suggested answer|response|option\s+\d+)\s*:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s*[—–]\s*", ", ", cleaned)
    cleaned = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"__([^_\n]+)__", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"`([^`\n]+)`", r"\1", cleaned)
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    phrase_replacements = {
        r"\binfrastructure as a product\b": "infrastructure as something developers can trust",
        r"\bactionable visibility\b": "a clear view of what needed attention",
        r"\bdemocratizing software development\b": "making software development more accessible",
        r"\bbuilder-first\b": "practical",
        r"\bself-service\b": "usable tooling",
        r"\bpractical ethos\b": "way of building",
        r"\bat scale\b": "",
        r"\baligns with\b": "matches",
        r"\baligns directly with\b": "fits",
        r"\bmirrors my own instinct\b": "fits how I like to work",
        r"\bmirrors how I approach\b": "fits how I approach",
        r"\bmirrors how I work\b": "fits how I work",
    }
    for pattern, replacement in phrase_replacements.items():
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(
        r"\bWhat excites me most about ([A-Z][A-Za-z0-9 .&-]+) is the chance to\b",
        "The exciting part is the chance to",
        cleaned,
    )
    if not re.search(r"\b(bullet|bullets|list)\b", user_message, flags=re.IGNORECASE):
        bullet_lines = re.findall(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+(.+)$", cleaned)
        non_bullet = re.sub(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+.+$", "", cleaned).strip()
        if bullet_lines and len(bullet_lines) >= 2:
            joined = " ".join(line.strip().rstrip(".") for line in bullet_lines if line.strip())
            cleaned = " ".join(part for part in [non_bullet, joined] if part).strip()
        else:
            cleaned = re.sub(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _truncate(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _latex_to_plain_text(text: str, max_chars: int = 0) -> str:
    if not text:
        return ""
    body = re.sub(r"%.*$", "", text, flags=re.MULTILINE)
    match = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", body, re.DOTALL)
    if match:
        body = match.group(1)
    body = re.sub(r"\\(?:textbf|textit|small|large|Large|Huge|emph|href)\{([^}]*)\}", r"\1", body)
    body = re.sub(r"\\(?:section|resumeSubheading)\{([^}]*)\}", r"\n\1\n", body)
    body = re.sub(r"\\resumeItem\{([^}]*)\}", r"- \1\n", body)
    body = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^]]*\])?(?:\{[^}]*\})?", " ", body)
    body = body.replace("{", " ").replace("}", " ")
    body = re.sub(r"\s+\n", "\n", body)
    body = re.sub(r"\n{2,}", "\n\n", body)
    body = re.sub(r"[ \t]{2,}", " ", body)
    plain = body.strip()
    if max_chars > 0:
        return _truncate(plain, max_chars)
    return plain


def _find_whitespace_flexible_span(tex: str, old: str) -> tuple[int, int] | None:
    """Find a unique substring while tolerating whitespace and indentation drift."""
    normalized_old = old.strip()
    if not normalized_old:
        return None

    pattern_parts: list[str] = []
    for token in re.split(r"(\s+)", normalized_old):
        if not token:
            continue
        if token.isspace():
            pattern_parts.append(r"\s+")
        else:
            pattern_parts.append(re.escape(token))
    if not pattern_parts:
        return None

    pattern = "".join(pattern_parts)
    matches = list(re.finditer(pattern, tex, flags=re.DOTALL))
    if len(matches) != 1:
        return None
    match = matches[0]
    return match.start(), match.end()


def _load_job_context(meta: dict | None) -> dict:
    job: dict[str, Any] = {}
    raw_job_id = (meta or {}).get("job_id")
    try:
        job_id = int(raw_job_id) if raw_job_id is not None else None
    except (TypeError, ValueError):
        job_id = None

    if job_id is not None:
        try:
            loaded = _app._get_job_context(job_id)
            if loaded:
                job = loaded
        except Exception as exc:
            logger.debug("Could not load job context for %s: %s", job_id, exc)

    if not job:
        job = {
            "id": raw_job_id,
            "url": (meta or {}).get("url"),
            "title": (meta or {}).get("title"),
            "snippet": (meta or {}).get("snippet"),
            "jd_text": (meta or {}).get("jd_text"),
        }
    return job


def _requirements_summary(analysis: dict | None) -> str:
    if not analysis:
        return ""
    reqs = analysis.get("requirements") or analysis.get("key_requirements") or []
    if not isinstance(reqs, list) or not reqs:
        return ""

    high_priority: list[str] = []
    other: list[str] = []
    for item in reqs[:12]:
        if isinstance(item, dict):
            text = str(item.get("jd_requirement") or item.get("requirement") or "").strip()
            priority = str(item.get("priority") or "").lower()
        else:
            text = str(item).strip()
            priority = ""
        if not text:
            continue
        if priority == "high":
            high_priority.append(text)
        else:
            other.append(text)
    ordered = high_priority + other
    return "\n".join(f"- {entry}" for entry in ordered[:8])


def _strategy_summary(strategy: dict | None, *, max_chars: int = 1200) -> str:
    if not strategy:
        return ""
    lines: list[str] = []
    if strategy.get("summary_strategy"):
        lines.append(f"Summary strategy: {strategy['summary_strategy']}")
    skills_tailoring = strategy.get("skills_tailoring")
    if isinstance(skills_tailoring, dict) and skills_tailoring:
        items = [f"{key}: {value}" for key, value in list(skills_tailoring.items())[:4]]
        lines.append("Skills tailoring:\n" + "\n".join(f"- {item}" for item in items))
    rewrites = strategy.get("experience_rewrites")
    if isinstance(rewrites, list) and rewrites:
        summary_lines: list[str] = []
        for item in rewrites[:3]:
            if not isinstance(item, dict):
                continue
            company = item.get("company")
            preserve = item.get("bullets_to_preserve")
            summary_lines.append(f"{company}: preserve {preserve}" if preserve else str(company))
        if summary_lines:
            lines.append("Experience guidance:\n" + "\n".join(f"- {item}" for item in summary_lines))
    risk_controls = strategy.get("risk_controls")
    if isinstance(risk_controls, list) and risk_controls:
        lines.append("Risk controls:\n" + "\n".join(f"- {item}" for item in risk_controls[:4]))
    return _truncate("\n".join(line for line in lines if line).strip(), max_chars)


def _detect_chat_mode(message: str, doc_focus: str | None) -> str:
    lower = message.strip().lower()
    if not lower:
        return "general"
    if lower.startswith("/edit"):
        return "edit"
    if lower.startswith("/answer") or lower.startswith("/application"):
        return "application_answer"
    if any(hint in lower for hint in APPLICATION_HINTS):
        return "application_answer"
    if any(hint in lower for hint in EDIT_HINTS) and (any(hint in lower for hint in DOC_HINTS) or doc_focus in TEX_MAP):
        return "edit"
    return "general"


def _resolve_doc_target(message: str, doc_focus: str | None) -> str | None:
    lower = message.lower()
    if "resume" in lower:
        return "resume"
    if "cover letter" in lower or re.search(r"\bcover\b", lower):
        return "cover"
    if doc_focus in TEX_MAP:
        return doc_focus
    return None


def _render_recent_history(history: list[dict], *, mode: str = "general") -> str:
    recent = history[-MAX_HISTORY:]
    if not recent:
        return ""
    lines: list[str] = []
    for msg in recent:
        role = msg.get("role", "user")
        msg_mode = msg.get("mode")
        if mode == "application_answer" and role == "assistant":
            continue
        content = _strip_edit_blocks(str(msg.get("content", "")))
        content = _truncate(content, HISTORY_PREVIEW_CHARS)
        tag = f"[{msg_mode}]" if msg_mode else ""
        lines.append(f"{role.upper()}{tag}: {content}")
    return "\n".join(lines)


def _load_package_context(slug: str) -> dict | None:
    d = _pkg_dir(slug)
    if not d:
        return None

    meta = _load_json(d / "meta.json") or {}
    analysis = _load_json(d / "analysis.json") or {}
    resume_strategy = _load_json(d / "resume_strategy.json") or {}
    cover_strategy = _load_json(d / "cover_strategy.json") or {}
    resume_tex = _read_text(d / TEX_MAP["resume"])
    cover_tex = _read_text(d / TEX_MAP["cover"])
    job = _load_job_context(meta)

    return {
        "dir": d,
        "meta": meta,
        "job": job,
        "analysis": analysis,
        "resume_strategy": resume_strategy,
        "cover_strategy": cover_strategy,
        "resume_tex": resume_tex,
        "cover_tex": cover_tex,
        "resume_plain": _latex_to_plain_text(resume_tex, DOC_SUMMARY_CHARS),
        "cover_plain": _latex_to_plain_text(cover_tex, DOC_SUMMARY_CHARS),
        "soul": _read_text(SOUL_MD, 1800),
    }


def build_system_prompt(context: dict, mode: str, target_doc: str | None) -> str:
    job = context["job"]
    analysis = context["analysis"]
    resume_strategy = context["resume_strategy"]
    cover_strategy = context["cover_strategy"]

    parts: list[str] = [
        "You are an application materials assistant working on a real package for a specific job.",
        "Ground every answer in the provided resume, cover letter, job description, and package strategy.",
        "Do not invent facts, achievements, technologies, or motivations that are not supported by the package context.",
        "If the user asks for advice or drafting help, answer directly in a practical, candidate-ready way.",
    ]

    if mode == "edit":
        parts.extend(
            [
                "=== EDIT MODE ===",
                f"Target document: {target_doc or 'unknown'}",
                "The user wants document changes applied, not just general advice.",
                "Use edit blocks when changing the target TeX file.",
                "Format every applied edit like this:",
                "<<<EDIT",
                "OLD:",
                "exact text to find in the .tex file",
                "NEW:",
                "replacement text",
                "EDIT>>>",
                "Rules:",
                "- OLD must be an exact substring from the current target TeX file.",
                "- Copy OLD directly from the CURRENT target LaTeX block below; do not paraphrase or normalize it.",
                "- Prefer small, surgical edits over large multi-section rewrites.",
                "- If you cannot quote the existing text exactly, ask a clarifying question instead of guessing.",
                "- Include enough context to uniquely match the target text.",
                "- Keep commentary short, then provide the edit blocks.",
                "- Only emit edit blocks for the target document.",
            ]
        )
    elif mode == "application_answer":
        parts.extend(
            [
                "=== APPLICATION QUESTION MODE ===",
                "This mode is the primary purpose of package chat.",
                "The user wants a short-form application answer or supplemental response.",
                "Respond as a candidate-writing assistant, not as a TeX editor, resume reviewer, or generic career coach.",
                "Draft a candidate-ready answer in first person using only supported facts from the package.",
                "Do not emit edit blocks unless the user explicitly asks you to update a document too.",
                "Default to one compact paragraph of 80-140 words unless the user asks for a different length.",
                "If the prompt is a tiny form field, keep the answer closer to 50-90 words.",
                "Return plain text only. Do not use Markdown, asterisks, italics, bold, headings, code fences, or decorative formatting.",
                "Do not add labels like 'Primary answer', 'Draft', or 'Suggested answer'.",
                "Do not use bullets unless the user explicitly asks for bullets.",
                "Do not list accomplishments one after another; shape the evidence into a natural answer with a clear point.",
                "Use one grounded example at most unless the user asks for a longer answer. Mention at most one prior employer or project.",
                "If you use Coraline, do not add a second example from Great Wolf, Checkmarx, TexTailor, or another project.",
                "Do not braid multiple resume facts into one overstuffed sentence.",
                "Do not repeat the company's own slogans back at them as praise.",
                "Use the package strategy and cover letter for facts only. Do not copy their wording or rhetorical structure.",
                "Avoid polished strategy phrases even if they appear in context, including: infrastructure as a product, actionable visibility, democratizing software development, builder-first, self-service infrastructure, at scale, aligns directly, mirrors my own instinct.",
                "Prefer plain, conversational specifics over abstractions. Say what kind of work sounds interesting and why.",
                "For 'why this company' questions, connect the company's work to the candidate's judgment, curiosity, and work style.",
                "Do not start with 'What excites me about [company] is'. Start more naturally.",
                "Write in an organic, earnest, confident voice that sounds like a real person.",
                "Use specific skills and work-style evidence, but connect them to motivation, judgment, or fit.",
                "Avoid robotic transitions, corporate filler, exaggerated praise, and resume-recitation.",
                "Do not use em dashes. Prefer commas, periods, or simple sentence breaks.",
                "The answer should feel grounded, warm, capable, and direct.",
                "Before finalizing, silently check: no Markdown, no em dash, no banned strategy phrase, no more than one prior-work example.",
                "Weak example: 'What excites me about the company is that you treat infrastructure as a product, and I built X, Y, and Z.'",
                "Strong example: 'I like building tools that make messy work easier for people who are moving fast. That is what drew me to this role.'",
            ]
        )
    else:
        parts.extend(
            [
                "=== GENERAL PACKAGE MODE ===",
                "The user may ask about the role, the package, tailoring choices, next steps, or how to improve the materials.",
                "Answer directly and concisely.",
                "Do not emit edit blocks unless the user explicitly asks for document changes.",
            ]
        )

    context_blocks: list[str] = []
    if context["soul"]:
        context_blocks.append(f"=== CANDIDATE PROFILE ===\n{context['soul']}")

    job_lines = []
    if job.get("title"):
        job_lines.append(f"Role: {job['title']}")
    company_name = analysis.get("company_name") or context["meta"].get("company")
    if company_name:
        job_lines.append(f"Company: {company_name}")
    if job.get("url"):
        job_lines.append(f"URL: {job['url']}")
    if job.get("snippet"):
        job_lines.append(f"Job summary: {job['snippet']}")
    if job_lines:
        context_blocks.append("=== JOB SNAPSHOT ===\n" + "\n".join(job_lines))

    if analysis:
        analysis_lines = []
        if analysis.get("summary_angle"):
            analysis_lines.append(f"Summary angle: {analysis['summary_angle']}")
        if analysis.get("tone_notes"):
            analysis_lines.append(f"Tone notes: {analysis['tone_notes']}")
        company_context = analysis.get("company_context")
        if company_context:
            analysis_lines.append(f"Company context: {_truncate(json.dumps(company_context), 700)}")
        reqs = _requirements_summary(analysis)
        if reqs:
            analysis_lines.append("Top requirements:\n" + reqs)
        gaps = analysis.get("gaps")
        if isinstance(gaps, list) and gaps:
            analysis_lines.append("Gaps:\n" + "\n".join(f"- {item}" for item in gaps[:5]))
        if analysis_lines:
            context_blocks.append("=== JOB ANALYSIS ===\n" + "\n".join(analysis_lines))

    jd_text = job.get("jd_text") or context["meta"].get("jd_text") or analysis.get("jd_text")
    if jd_text:
        context_blocks.append(f"=== JOB DESCRIPTION EXCERPT ===\n{_truncate(str(jd_text), JD_SUMMARY_CHARS)}")

    resume_summary = _strategy_summary(resume_strategy)
    if resume_summary:
        context_blocks.append(f"=== RESUME STRATEGY ===\n{resume_summary}")

    cover_summary = _strategy_summary(cover_strategy)
    if cover_summary:
        context_blocks.append(f"=== COVER STRATEGY ===\n{cover_summary}")

    context_blocks.append(f"=== CURRENT RESUME CONTENT ===\n{context['resume_plain'] or '(resume unavailable)'}")
    context_blocks.append(f"=== CURRENT COVER LETTER CONTENT ===\n{context['cover_plain'] or '(cover letter unavailable)'}")

    if mode == "edit" and target_doc in TEX_MAP:
        tex = context[f"{target_doc}_tex"]
        if tex:
            context_blocks.append(f"=== CURRENT {target_doc.upper()} LATEX ===\n{tex}")

    return "\n\n".join(parts + context_blocks)


def _build_user_prompt(message: str, history: list[dict], mode: str, target_doc: str | None) -> str:
    blocks: list[str] = []
    history_block = _render_recent_history(history, mode=mode)
    if history_block:
        blocks.append("=== RECENT CHAT HISTORY ===\n" + history_block)
    blocks.append(f"=== CURRENT MODE ===\n{mode}")
    if target_doc:
        blocks.append(f"=== TARGET DOCUMENT ===\n{target_doc}")
    blocks.append("=== USER MESSAGE ===\n" + message.strip())
    return "\n\n".join(blocks)


def _call_package_chat_model(
    system_prompt: str,
    user_prompt: str,
    *,
    mode: str,
    model: str | None = None,
    llm_runtime: dict | None = None,
) -> str:
    import sys

    sys.path.insert(0, str(TAILORING_ROOT))
    from tailor.ollama import chat as llm_chat

    config = MODE_CONFIG[mode]
    # Per-mode env override takes priority, then the resolved model from
    # runtime controls, then auto-discovery as last resort.
    resolved_model = os.environ.get(config["model_env"]) or model or None
    return llm_chat(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=config["max_tokens"],
        temperature=config["temperature"],
        model=resolved_model,
        runtime=(
            {
                "provider": llm_runtime.get("provider"),
                "chat_url": llm_runtime.get("chat_url"),
                "api_key": llm_runtime.get("api_key", ""),
            }
            if llm_runtime
            else None
        ),
    )


def _apply_edits(slug: str, doc_focus: str | None, reply: str) -> list[dict]:
    """Parse <<<EDIT...EDIT>>> blocks from reply and apply them to the .tex file."""
    if not doc_focus or doc_focus not in TEX_MAP:
        return []

    d = _pkg_dir(slug)
    if not d:
        return []

    tex_path = d / TEX_MAP[doc_focus]
    if not tex_path.exists():
        return []

    pattern = r"<<<EDIT\s*\nOLD:\s*\n(.*?)\nNEW:\s*\n(.*?)\nEDIT>>>"
    matches = re.findall(pattern, reply, re.DOTALL)
    if not matches:
        return []

    tex = tex_path.read_text(encoding="utf-8")
    results = []

    for old, new in matches:
        old = old.rstrip("\n")
        new = new.rstrip("\n")
        if old in tex:
            tex = tex.replace(old, new, 1)
            results.append(
                {
                    "old_preview": old[:80],
                    "new_preview": new[:80],
                    "applied": True,
                    "match_mode": "exact",
                    "doc_type": doc_focus,
                }
            )
            continue

        span = _find_whitespace_flexible_span(tex, old)
        if span:
            start, end = span
            tex = tex[:start] + new + tex[end:]
            results.append(
                {
                    "old_preview": old[:80],
                    "new_preview": new[:80],
                    "applied": True,
                    "match_mode": "flex_whitespace",
                    "doc_type": doc_focus,
                }
            )
        else:
            results.append(
                {
                    "old_preview": old[:80],
                    "applied": False,
                    "reason": "text not found",
                    "doc_type": doc_focus,
                }
            )

    if any(r["applied"] for r in results):
        tex_path.write_text(tex, encoding="utf-8")

    return results


def load_history(slug: str) -> list[dict]:
    hp = _history_path(slug)
    if not hp or not hp.exists():
        return []
    messages: list[dict] = []
    for line in hp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                messages.append(json.loads(line))
            except Exception:
                pass
    return messages


def clear_history(slug: str) -> bool:
    hp = _history_path(slug)
    if hp and hp.exists():
        hp.unlink()
        return True
    return False


def send_chat(slug: str, message: str, doc_focus: str | None = None, *, model: str | None = None, llm_runtime: dict | None = None) -> dict:
    context = _load_package_context(slug)
    if not context:
        return {"ok": False, "error": "Package not found"}

    history = load_history(slug)
    mode = _detect_chat_mode(message, doc_focus)
    target_doc = _resolve_doc_target(message, doc_focus)

    system_prompt = build_system_prompt(context, mode, target_doc)
    user_prompt = _build_user_prompt(message, history, mode, target_doc)

    try:
        reply = _call_package_chat_model(system_prompt, user_prompt, mode=mode, model=model, llm_runtime=llm_runtime)
    except TimeoutError:
        return {"ok": False, "error": "LLM is busy (lock timeout). Try again shortly."}
    except Exception as e:
        return {"ok": False, "error": f"LLM error: {e}"}

    edits: list[dict] = []
    if mode == "edit":
        edits = _apply_edits(slug, target_doc, reply)
    if mode == "edit":
        clean_reply = reply
    elif mode == "application_answer":
        clean_reply = _clean_application_answer(reply, user_message=message)
    else:
        clean_reply = _strip_edit_blocks(reply)

    hp = _history_path(slug)
    if hp:
        with open(hp, "a", encoding="utf-8") as f:
            f.write(json.dumps({"role": "user", "content": message, "mode": mode, "doc_focus": doc_focus}) + "\n")
            f.write(
                json.dumps(
                    {
                        "role": "assistant",
                        "content": clean_reply,
                        "mode": mode,
                        "doc_focus": target_doc or doc_focus,
                    }
                )
                + "\n"
            )

    result: dict[str, Any] = {
        "ok": True,
        "reply": clean_reply,
        "mode": mode,
    }
    if any(edit.get("applied") for edit in edits):
        result["edits"] = edits
        result["doc_updated"] = target_doc
    elif edits:
        result["edits"] = edits
    return result
