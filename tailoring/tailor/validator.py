"""QUALITY_BAR hard-gate validation for tailored documents.

Gates and thresholds are defined in config.py. See QUALITY_BAR.md for the full spec.
Key tuning points: RESUME_CHAR_TOLERANCE, COVER_CHAR_TOLERANCE, RESUME_BULLET_COUNT.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config as cfg
from .compiler import compile_tex

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    passed: bool
    failures: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.passed:
            return "PASS — all gates cleared"
        return "FAIL — " + "; ".join(self.failures)


def _count_resume_bullets(tex: str) -> int:
    """Count \\resumeItem entries in WORK EXPERIENCE section only."""
    # Extract work experience section
    m = re.search(
        r"\\section\{WORK EXPERIENCE\}(.*?)\\section\{",
        tex, re.DOTALL,
    )
    if not m:
        # Try to end at document end
        m = re.search(r"\\section\{WORK EXPERIENCE\}(.*?)\\end\{document\}", tex, re.DOTALL)
    if not m:
        return 0
    section = m.group(1)
    return len(re.findall(r"\\resumeItem\{", section))


def _extract_body_text(tex: str) -> str:
    """Strip LaTeX commands to get approximate body text for char counting."""
    # Remove comments
    text = re.sub(r"%.*$", "", tex, flags=re.MULTILINE)
    # Remove preamble
    m = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", text, re.DOTALL)
    if m:
        text = m.group(1)
    # Strip common commands but keep their content
    text = re.sub(r"\\(?:textbf|textit|small|large|Large|Huge|emph|href)\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?\{[^}]*\}", "", text)
    text = re.sub(r"\\[a-zA-Z]+\*?", "", text)
    text = re.sub(r"[{}\[\]]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _check_section_order(tex: str) -> bool:
    """Verify sections appear in canonical order."""
    positions = []
    for section in cfg.RESUME_SECTIONS:
        m = re.search(rf"\\section\{{{re.escape(section)}\}}", tex)
        if m:
            positions.append(m.start())
        else:
            return False  # missing section
    return positions == sorted(positions)


def validate_resume(tex_path: Path) -> ValidationResult:
    """Run all hard gates on a tailored resume."""
    failures = []
    tex = tex_path.read_text()
    baseline_tex = cfg.RESUME_TEX.read_text()

    # Gate 1: Compilation
    pdf = compile_tex(tex_path)
    if pdf is None:
        failures.append("compilation failed")

    # Gate 2: Bullet count
    bullets = _count_resume_bullets(tex)
    if bullets != cfg.RESUME_BULLET_COUNT:
        failures.append(f"bullet count {bullets}, expected {cfg.RESUME_BULLET_COUNT}")

    # Gate 3: Character count (see RESUME_CHAR_TOLERANCE in config.py)
    body = _extract_body_text(tex)
    baseline_body = _extract_body_text(baseline_tex)
    if baseline_body:
        ratio = len(body) / len(baseline_body)
        if abs(ratio - 1.0) > cfg.RESUME_CHAR_TOLERANCE:
            failures.append(
                f"char count ratio {ratio:.2f} (±{cfg.RESUME_CHAR_TOLERANCE} allowed); "
                f"draft has {len(body)} chars, baseline has {len(baseline_body)} chars, "
                f"need {int(len(baseline_body) * (1 - cfg.RESUME_CHAR_TOLERANCE))}-"
                f"{int(len(baseline_body) * (1 + cfg.RESUME_CHAR_TOLERANCE))}"
            )

    # Gate 4: No Python list literals
    if re.search(r"\['", tex) or re.search(r'"\]', tex):
        failures.append("Python list literal found in .tex")

    # Gate 5: No literal \\n tokens
    if "\\n" in tex and "\\newcommand" not in tex[tex.index("\\n") - 20 : tex.index("\\n")]:
        # More precise: look for \n that isn't part of a command name
        if re.search(r"(?<!\\newcommand)(?<!\\noindent)(?<!\\newpage)\\n(?![a-zA-Z])", tex):
            failures.append("literal \\n token found in .tex")

    # Gate 6: Section order (see RESUME_SECTIONS in config.py)
    if not _check_section_order(tex):
        failures.append("section order does not match canonical template")

    return ValidationResult(passed=len(failures) == 0, failures=failures)


def validate_cover_letter(tex_path: Path) -> ValidationResult:
    """Run hard gates on a tailored cover letter."""
    failures = []
    tex = tex_path.read_text()
    baseline_tex = cfg.COVER_TEX.read_text()

    # Gate 1: Compilation
    pdf = compile_tex(tex_path)
    if pdf is None:
        failures.append("compilation failed")

    # Gate 2: Character count (see COVER_CHAR_TOLERANCE in config.py)
    body = _extract_body_text(tex)
    baseline_body = _extract_body_text(baseline_tex)
    if baseline_body:
        ratio = len(body) / len(baseline_body)
        if abs(ratio - 1.0) > cfg.COVER_CHAR_TOLERANCE:
            failures.append(f"char count ratio {ratio:.2f} (±{cfg.COVER_CHAR_TOLERANCE} allowed)")

    # Gate 3: No Python list literals
    if re.search(r"\['", tex) or re.search(r'"\]', tex):
        failures.append("Python list literal found in .tex")

    # Gate 4: No literal \\n tokens
    if re.search(r"(?<!\\newcommand)(?<!\\noindent)(?<!\\newpage)\\n(?![a-zA-Z])", tex):
        failures.append("literal \\n token found in .tex")

    return ValidationResult(passed=len(failures) == 0, failures=failures)
