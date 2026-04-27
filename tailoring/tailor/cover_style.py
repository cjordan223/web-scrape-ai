"""Deterministic cover-letter style audits for banned AI-writing tics."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


COVER_STYLE_RULE_PROMPT = """\
BANNED COVER-LETTER RHETORICAL PATTERNS (HARD):
Use zero occurrences of these constructions anywhere in cover strategy, draft,
QA output, humanize output, or final LaTeX:
- "not just ..." contrast setups, including "not just X, but Y"
- "not because X, but Y"
- "I don't just X" / "I didn't just X" / "I do not just X"
- "not as X, but as Y"
- "That same mindset/instinct/pattern/insight/approach ..."
- "I learned that ..." / "I've learned that ..." / "That taught me ..."

If source material contains one of these ideas, rewrite it in direct language.
Do not replace one banned pattern with another."""


_BANNED_PATTERNS: tuple[dict[str, Any], ...] = (
    {
        "family": "not_because_but",
        "label": "not because X, but Y",
        "regex": re.compile(r"\bnot\s+because\b[^.!?]{0,180}\bbut\b", re.IGNORECASE | re.DOTALL),
    },
    {
        "family": "not_as_but_as",
        "label": "not as X, but as Y",
        "regex": re.compile(r"\bnot\s+as\b[^.!?]{0,160}\bbut\s+as\b", re.IGNORECASE | re.DOTALL),
    },
    {
        "family": "i_dont_just",
        "label": "I don't/didn't just X",
        "regex": re.compile(r"\bI\s+(?:don't|didn't|do\s+not|did\s+not)\s+just\b", re.IGNORECASE),
    },
    {
        "family": "not_just_but",
        "label": "not just X, but Y",
        "regex": re.compile(r"\bnot\s+just\b", re.IGNORECASE),
    },
    {
        "family": "same_mindset",
        "label": "That same mindset/instinct/pattern/insight/approach",
        "regex": re.compile(
            r"\bThat\s+same\s+(?:mindset|instinct|pattern|insight|approach)\b",
            re.IGNORECASE,
        ),
    },
    {
        "family": "lesson_closer",
        "label": "I learned that / I've learned that / That taught me / that's why",
        "regex": re.compile(
            r"\b(?:I(?:\s+learned|\s+have\s+learned|['’]ve\s+learned)\s+that|That\s+taught\s+me(?:\s+that)?|that['’]s\s+why|is\s+why\s+I)\b",
            re.IGNORECASE,
        ),
    },
)


def _strip_markdown_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text


def _strip_latex_to_text(text: str) -> str:
    text = re.sub(r"%.*$", "", text, flags=re.MULTILINE)
    match = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", text, re.DOTALL)
    if match:
        text = match.group(1)
    text = re.sub(r"\\(?:textbf|textit|small|large|Large|Huge|emph|href)\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?", " ", text)
    text = re.sub(r"[{}\[\]]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _sentence_for_match(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("!", 0, start), text.rfind("?", 0, start))
    right_candidates = [idx for idx in (text.find(".", end), text.find("!", end), text.find("?", end)) if idx != -1]
    right = min(right_candidates) if right_candidates else len(text) - 1
    sentence = text[left + 1 : right + 1].strip()
    return re.sub(r"\s+", " ", sentence)


def audit_cover_style_text(text: str, *, source: str | None = None) -> list[dict[str, Any]]:
    """Return banned cover-style pattern hits with exact sentence context."""
    normalized = _strip_latex_to_text(text)
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for rule in _BANNED_PATTERNS:
        for match in rule["regex"].finditer(normalized):
            matched_text = _sentence_for_match(normalized, match.start(), match.end()) or match.group(0)
            key = (rule["family"], matched_text.lower())
            if key in seen:
                continue
            seen.add(key)
            finding = {
                "family": rule["family"],
                "label": rule["label"],
                "matched_text": matched_text,
            }
            if source:
                finding["source"] = source
            findings.append(finding)
    return findings


def _cover_letter_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.name == "Conner_Jordan_Cover_Letter.tex" or path.suffix == ".tex" else []
    return sorted(path.rglob("Conner_Jordan_Cover_Letter.tex"))


def audit_cover_letter_paths(paths: list[Path]) -> dict[str, Any]:
    """Audit one or more cover-letter files or output roots."""
    letters: list[dict[str, Any]] = []
    for path in paths:
        for tex_path in _cover_letter_files(Path(path)):
            findings = audit_cover_style_text(tex_path.read_text(encoding="utf-8"), source=str(tex_path))
            counts: dict[str, int] = {}
            for finding in findings:
                family = str(finding["family"])
                counts[family] = counts.get(family, 0) + 1
            letters.append(
                {
                    "path": str(tex_path),
                    "total_hits": len(findings),
                    "counts": counts,
                    "findings": findings,
                }
            )

    return {
        "letters": letters,
        "total_letters": len(letters),
        "total_hits": sum(item["total_hits"] for item in letters),
    }


def _markdown_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix == ".md" else []
    return sorted(path.rglob("*.md"))


def lint_cover_source_paths(paths: list[Path]) -> list[dict[str, Any]]:
    """Scan cover-letter source markdown for banned rhetoric."""
    findings: list[dict[str, Any]] = []
    for path in paths:
        for md_path in _markdown_files(Path(path)):
            text = _strip_markdown_frontmatter(md_path.read_text(encoding="utf-8"))
            findings.extend(audit_cover_style_text(text, source=str(md_path)))
    return findings
