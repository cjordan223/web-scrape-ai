"""QUALITY_BAR hard-gate validation for tailored documents.

Gates and thresholds are defined in config.py. See QUALITY_BAR.md for the full spec.
Key tuning points: RESUME_CHAR_TOLERANCE, COVER_CHAR_TOLERANCE, RESUME_BULLET_COUNT.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any

from . import config as cfg
from .compiler import compile_tex

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        if self.passed:
            return "PASS — all gates cleared"
        return "FAIL — " + "; ".join(self.failures)


@dataclass
class ResumeFitMetrics:
    page_count: int | None = None
    page_2_word_count: int = 0
    has_suspicious_single_word_lines: bool = False
    suspicious_single_word_lines: list[str] = field(default_factory=list)
    render_inspection_ok: bool = False
    inspection_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "page_count": self.page_count,
            "page_2_word_count": self.page_2_word_count,
            "has_suspicious_single_word_lines": self.has_suspicious_single_word_lines,
            "suspicious_single_word_lines": list(self.suspicious_single_word_lines),
            "render_inspection_ok": self.render_inspection_ok,
            "inspection_error": self.inspection_error,
        }


def _count_resume_bullets(tex: str) -> int:
    """Count \\resumeItem entries in WORK EXPERIENCE section only."""
    section = _extract_work_experience_section(tex)
    return len(re.findall(r"\\resumeItem\{", section))


def _extract_work_experience_section(tex: str) -> str:
    """Extract the WORK EXPERIENCE section body for bullet counting."""
    # Extract work experience section
    m = re.search(
        r"\\section\{WORK EXPERIENCE\}(.*?)\\section\{",
        tex, re.DOTALL,
    )
    if not m:
        # Try to end at document end
        m = re.search(r"\\section\{WORK EXPERIENCE\}(.*?)\\end\{document\}", tex, re.DOTALL)
    if not m:
        return ""
    return m.group(1)


def _normalize_company_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def _count_resume_bullets_by_company(tex: str) -> dict[str, int]:
    """Count bullets for each expected employer in WORK EXPERIENCE."""
    section = _extract_work_experience_section(tex)
    counts = {company: 0 for company in cfg.RESUME_COMPANIES}
    if not section:
        return counts

    pattern = re.compile(
        r"\\resumeSubheading\s*"
        r"\{\s*(?P<company>[^}]*)\s*\}\s*"
        r"\{[^}]*\}\s*\{[^}]*\}\s*\{[^}]*\}"
        r"(?P<body>.*?)(?=(?:\\resumeSubheading\s*\{)|\\resumeSubHeadingListEnd|\\section\{|\\end\{document\})",
        re.DOTALL,
    )
    for match in pattern.finditer(section):
        company = _normalize_company_name(match.group("company"))
        if company in counts:
            counts[company] = len(re.findall(r"\\resumeItem\{", match.group("body")))
    return counts


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


def _resume_uses_pruned_mode(tex: str) -> bool:
    return "\\prunedresumetrue" in tex


def _resolve_external_binary(binary_name: str, env_var: str) -> str | None:
    env_bin = os.environ.get(env_var)
    if env_bin:
        candidate = Path(env_bin)
        if candidate.exists():
            return str(candidate)
        return env_bin

    return (
        shutil.which(binary_name)
        or (f"/opt/homebrew/bin/{binary_name}" if Path(f"/opt/homebrew/bin/{binary_name}").exists() else None)
        or (f"/usr/local/bin/{binary_name}" if Path(f"/usr/local/bin/{binary_name}").exists() else None)
        or (f"/usr/bin/{binary_name}" if Path(f"/usr/bin/{binary_name}").exists() else None)
    )


def inspect_resume_pdf_fit(pdf_path: Path) -> ResumeFitMetrics:
    """Inspect rendered resume pagination and line-wrapping diagnostics."""
    metrics = ResumeFitMetrics()
    if not pdf_path.exists():
        metrics.inspection_error = f"PDF not found: {pdf_path}"
        return metrics

    pdfinfo_bin = _resolve_external_binary("pdfinfo", "PDFINFO_BIN")
    if not pdfinfo_bin:
        metrics.inspection_error = "pdfinfo not found"
        logger.warning("Could not inspect PDF with pdfinfo: binary not found")
        return metrics

    try:
        result = subprocess.run(
            [pdfinfo_bin, str(pdf_path)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        metrics.inspection_error = f"pdfinfo unavailable: {exc}"
        logger.warning("Could not inspect PDF with pdfinfo: %s", exc)
        return metrics

    if result.returncode != 0:
        metrics.inspection_error = f"pdfinfo failed: {result.stderr.strip() or result.stdout.strip()}"
        logger.warning("pdfinfo failed for %s: %s", pdf_path, result.stderr.strip())
        return metrics

    m = re.search(r"^Pages:\s+(\d+)$", result.stdout, re.MULTILINE)
    if not m:
        metrics.inspection_error = "pdfinfo output missing page count"
        return metrics
    metrics.page_count = int(m.group(1))
    metrics.render_inspection_ok = True

    pdftotext_bin = _resolve_external_binary("pdftotext", "PDFTOTEXT_BIN")
    if not pdftotext_bin:
        metrics.inspection_error = "pdftotext not found"
        logger.warning("Could not inspect PDF text boxes with pdftotext: binary not found")
        return metrics

    try:
        text_result = subprocess.run(
            [pdftotext_bin, "-bbox-layout", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        metrics.inspection_error = f"pdftotext unavailable: {exc}"
        logger.warning("Could not inspect PDF text boxes with pdftotext: %s", exc)
        return metrics

    if text_result.returncode != 0 or not text_result.stdout.strip():
        metrics.inspection_error = "pdftotext produced no parseable output"
        return metrics

    try:
        root = ET.fromstring(text_result.stdout)
    except ET.ParseError as exc:
        metrics.inspection_error = f"pdftotext XML parse failed: {exc}"
        logger.warning("Could not parse pdftotext bbox output for %s: %s", pdf_path, exc)
        return metrics

    suspicious: list[str] = []
    for page_index, page in enumerate(root.findall(".//page"), start=1):
        if page_index == 2:
            metrics.page_2_word_count = len([
                word.text.strip()
                for word in page.findall(".//word")
                if word.text and word.text.strip()
            ])

        height = float(page.attrib.get("height", "0") or 0)
        lower_page_threshold = height * 0.70 if height else 0
        for line in page.findall(".//line"):
            words = [
                word.text.strip()
                for word in line.findall(".//word")
                if word.text and word.text.strip()
            ]
            if len(words) != 1:
                continue
            token = words[0]
            if len(token) <= 2 or token.isupper():
                continue
            y_min = float(line.attrib.get("yMin", "0") or 0)
            if page_index > 1 or (lower_page_threshold and y_min >= lower_page_threshold):
                suspicious.append(token)

    metrics.suspicious_single_word_lines = suspicious[:5]
    metrics.has_suspicious_single_word_lines = bool(suspicious)
    return metrics


def validate_resume(tex_path: Path) -> ValidationResult:
    """Run all hard gates on a tailored resume."""
    failures = []
    metrics: dict[str, Any] = {}
    tex = tex_path.read_text()
    baseline_tex = cfg.RESUME_TEX.read_text()

    # Gate 1: Compilation
    pdf = compile_tex(tex_path)
    if pdf is None:
        failures.append("compilation failed")
    else:
        fit_metrics = inspect_resume_pdf_fit(pdf)
        metrics.update(fit_metrics.as_dict())
        if fit_metrics.page_count != cfg.RESUME_TARGET_PAGES:
            if fit_metrics.page_count is None and fit_metrics.inspection_error:
                failures.append(
                    f"rendered page count unavailable ({fit_metrics.inspection_error}), expected {cfg.RESUME_TARGET_PAGES}"
                )
            else:
                failures.append(
                    f"rendered page count {fit_metrics.page_count}, expected {cfg.RESUME_TARGET_PAGES} "
                    f"(page 2 words: {fit_metrics.page_2_word_count}, "
                    f"widow-like lines: {'yes' if fit_metrics.has_suspicious_single_word_lines else 'no'})"
                )

    # Gate 2: Bullet count
    bullets = _count_resume_bullets(tex)
    counts_by_company = _count_resume_bullets_by_company(tex)
    metrics["bullet_count"] = bullets
    metrics["company_bullet_counts"] = counts_by_company
    if _resume_uses_pruned_mode(tex):
        for company in cfg.RESUME_COMPANIES:
            count = counts_by_company.get(company, 0)
            floor = cfg.RESUME_COMPANY_BULLET_FLOORS[company]
            cap = cfg.RESUME_COMPANY_BULLET_TARGETS[company]
            if not (floor <= count <= cap):
                failures.append(
                    f"{company} bullet count {count}, expected {floor}-{cap} in pruned mode"
                )
    else:
        for company in cfg.RESUME_COMPANIES:
            count = counts_by_company.get(company, 0)
            expected = cfg.RESUME_COMPANY_BULLET_TARGETS[company]
            if count != expected:
                failures.append(f"{company} bullet count {count}, expected {expected}")
    if bullets != sum(counts_by_company.values()):
        failures.append(
            f"work experience bullet structure mismatch: counted {bullets} total vs {sum(counts_by_company.values())} attributed"
        )

    # Gate 3: Character count (see RESUME_CHAR_TOLERANCE in config.py)
    body = _extract_body_text(tex)
    baseline_body = _extract_body_text(baseline_tex)
    metrics["body_chars"] = len(body)
    metrics["baseline_body_chars"] = len(baseline_body)
    if baseline_body:
        ratio = len(body) / len(baseline_body)
        metrics["char_ratio"] = round(ratio, 4)
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

    return ValidationResult(passed=len(failures) == 0, failures=failures, metrics=metrics)


def validate_cover_letter(tex_path: Path) -> ValidationResult:
    """Run hard gates on a tailored cover letter."""
    failures = []
    metrics: dict[str, Any] = {}
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
        metrics["char_ratio"] = round(ratio, 4)
        if abs(ratio - 1.0) > cfg.COVER_CHAR_TOLERANCE:
            failures.append(f"char count ratio {ratio:.2f} (±{cfg.COVER_CHAR_TOLERANCE} allowed)")

    # Gate 3: No Python list literals
    if re.search(r"\['", tex) or re.search(r'"\]', tex):
        failures.append("Python list literal found in .tex")

    # Gate 4: No literal \\n tokens
    if re.search(r"(?<!\\newcommand)(?<!\\noindent)(?<!\\newpage)\\n(?![a-zA-Z])", tex):
        failures.append("literal \\n token found in .tex")

    return ValidationResult(passed=len(failures) == 0, failures=failures, metrics=metrics)
