"""QUALITY_BAR hard-gate validation for tailored documents.

Gates and thresholds are defined in config.py. See QUALITY_BAR.md for the full spec.
Key tuning points: RESUME_CHAR_TOLERANCE, COVER_CHAR_TOLERANCE, RESUME_BULLET_COUNT.
"""

from __future__ import annotations

import json
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
from .grounding import build_grounding_context

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    failure_details: list[dict[str, Any]] = field(default_factory=list)

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
    page_fill_ratio: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "page_count": self.page_count,
            "page_2_word_count": self.page_2_word_count,
            "has_suspicious_single_word_lines": self.has_suspicious_single_word_lines,
            "suspicious_single_word_lines": list(self.suspicious_single_word_lines),
            "render_inspection_ok": self.render_inspection_ok,
            "inspection_error": self.inspection_error,
            "page_fill_ratio": self.page_fill_ratio,
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


def _extract_section(tex: str, section_name: str) -> str:
    m = re.search(
        rf"\\section\{{{re.escape(section_name)}\}}(.*?)(?=\\section\{{|\\end\{{document\}})",
        tex,
        re.DOTALL,
    )
    return m.group(1) if m else ""


def _extract_resume_role_map(tex: str) -> dict[str, str]:
    roles: dict[str, str] = {}
    for company, _, role, _ in re.findall(
        r"\\resumeSubheading\s*"
        r"\{\s*([^}]*)\s*\}\s*"
        r"\{\s*([^}]*)\s*\}\s*"
        r"\{\s*([^}]*)\s*\}\s*"
        r"\{\s*([^}]*)\s*\}",
        _extract_work_experience_section(tex),
        re.DOTALL,
    ):
        roles[_normalize_company_name(company)] = _normalize_company_name(role)
    return roles


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


def _strip_xml_namespaces(root: ET.Element) -> ET.Element:
    for elem in root.iter():
        if isinstance(elem.tag, str) and "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
    return root


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
    root = _strip_xml_namespaces(root)

    pages = root.findall(".//page")
    if not pages:
        metrics.inspection_error = "pdftotext XML missing page elements"
        return metrics

    suspicious: list[str] = []
    for page_index, page in enumerate(pages, start=1):
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

    # Compute page 1 fill ratio from bounding box data
    page1 = next(iter(root.findall(".//page")), None)
    if page1 is not None:
        page_height = float(page1.attrib.get("height", "0") or 0)
        if page_height > 0:
            max_y = 0.0
            for word in page1.findall(".//word"):
                y_max = float(word.attrib.get("yMax", "0") or 0)
                if y_max > max_y:
                    max_y = y_max
            if max_y > 0:
                metrics.page_fill_ratio = round(max_y / page_height, 4)

    metrics.render_inspection_ok = True

    return metrics


def _add_failure(
    failures: list[str],
    failure_details: list[dict[str, Any]],
    category: str,
    message: str,
    *,
    snippet: str | None = None,
) -> None:
    failures.append(message)
    detail: dict[str, Any] = {"category": category, "message": message}
    if snippet:
        detail["snippet"] = snippet
    failure_details.append(detail)


def _first_match_snippet(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    start = max(0, m.start() - 80)
    end = min(len(text), m.end() + 80)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def _validate_grounding_claims(
    *,
    text: str,
    failures: list[str],
    failure_details: list[dict[str, Any]],
    grounding: dict[str, Any],
) -> None:
    patterns = grounding.get("high_risk_patterns", {})
    category_map = {
        "unsupported_tool_claim": "unsupported_tool_claim",
        "unsupported_compliance_claim": "unsupported_compliance_claim",
        "unsupported_identity_stack_claim": "unsupported_identity_stack_claim",
        "unsupported_ai_deployment_claim": "unsupported_ai_deployment_claim",
        "unsupported_operational_mechanic_claim": "unsupported_operational_mechanic_claim",
        "unsupported_scale_claim": "unsupported_operational_mechanic_claim",
    }
    for rule_name, patterns_for_rule in patterns.items():
        if rule_name == "role_title_renamed":
            continue
        for pattern in patterns_for_rule:
            snippet = _first_match_snippet(text, pattern)
            if snippet:
                category = category_map.get(rule_name, rule_name)
                _add_failure(
                    failures,
                    failure_details,
                    category,
                    f"{category}: unsupported claim pattern detected",
                    snippet=snippet,
                )
                break


def _validate_cover_company_rendering(
    tex_path: Path,
    tex: str,
    failures: list[str],
    failure_details: list[dict[str, Any]],
) -> None:
    def _norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    analysis_path = tex_path.parent / "analysis.json"
    if not analysis_path.exists():
        return
    try:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    except Exception:
        return
    canonical = str(analysis.get("company_name") or "").strip()
    if not canonical:
        return
    m = re.search(r"\\newcommand\{\\companyname\}\{([^}]*)\}", tex)
    if not m:
        return
    actual = m.group(1).strip()
    if not actual:
        return
    if _norm(actual) == _norm(canonical) and actual != canonical and any(ch.isupper() for ch in canonical):
        _add_failure(
            failures,
            failure_details,
            "company_name_rendering_issue",
            f"company name rendered as '{actual}' instead of canonical '{canonical}'",
        )


def validate_resume(tex_path: Path) -> ValidationResult:
    """Run all hard gates on a tailored resume."""
    failures = []
    failure_details: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    tex = tex_path.read_text()
    baseline_tex = cfg.RESUME_TEX.read_text()
    grounding = build_grounding_context(baseline_tex=baseline_tex)

    # Gate 1: Compilation
    pdf = compile_tex(tex_path)
    if pdf is None:
        _add_failure(failures, failure_details, "compilation_failed", "compilation failed")
    else:
        fit_metrics = inspect_resume_pdf_fit(pdf)
        metrics.update(fit_metrics.as_dict())
        if fit_metrics.inspection_error:
            _add_failure(
                failures,
                failure_details,
                "render_inspection_incomplete",
                f"render inspection incomplete ({fit_metrics.inspection_error})",
            )
        if fit_metrics.page_count != cfg.RESUME_TARGET_PAGES:
            if fit_metrics.page_count is None and fit_metrics.inspection_error:
                _add_failure(
                    failures,
                    failure_details,
                    "page_count_unavailable",
                    f"rendered page count unavailable ({fit_metrics.inspection_error}), expected {cfg.RESUME_TARGET_PAGES}",
                )
            else:
                _add_failure(
                    failures,
                    failure_details,
                    "page_count_mismatch",
                    f"rendered page count {fit_metrics.page_count}, expected {cfg.RESUME_TARGET_PAGES} "
                    f"(page 2 words: {fit_metrics.page_2_word_count}, "
                    f"widow-like lines: {'yes' if fit_metrics.has_suspicious_single_word_lines else 'no'})",
                )

        if (
            fit_metrics.inspection_error is None
            and fit_metrics.page_fill_ratio is None
            and fit_metrics.page_count == cfg.RESUME_TARGET_PAGES
        ):
            _add_failure(failures, failure_details, "page_fill_ratio_unavailable", "page fill ratio unavailable")

        if (
            fit_metrics.page_fill_ratio is not None
            and fit_metrics.page_count == cfg.RESUME_TARGET_PAGES
            and fit_metrics.page_fill_ratio < cfg.RESUME_MIN_FILL_RATIO
        ):
            _add_failure(
                failures,
                failure_details,
                "page_underfilled",
                f"page underfilled: {fit_metrics.page_fill_ratio:.1%} vertical fill, "
                f"need ≥{cfg.RESUME_MIN_FILL_RATIO:.0%}",
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
                _add_failure(
                    failures,
                    failure_details,
                    "bullet_count_mismatch",
                    f"{company} bullet count {count}, expected {floor}-{cap} in pruned mode",
                )
    else:
        for company in cfg.RESUME_COMPANIES:
            count = counts_by_company.get(company, 0)
            expected = cfg.RESUME_COMPANY_BULLET_TARGETS[company]
            if count != expected:
                _add_failure(
                    failures,
                    failure_details,
                    "bullet_count_mismatch",
                    f"{company} bullet count {count}, expected {expected}",
                )
    if bullets != sum(counts_by_company.values()):
        _add_failure(
            failures,
            failure_details,
            "bullet_structure_mismatch",
            f"work experience bullet structure mismatch: counted {bullets} total vs {sum(counts_by_company.values())} attributed",
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
            _add_failure(
                failures,
                failure_details,
                "char_ratio_out_of_bounds",
                f"char count ratio {ratio:.2f} (±{cfg.RESUME_CHAR_TOLERANCE} allowed); "
                f"draft has {len(body)} chars, baseline has {len(baseline_body)} chars, "
                f"need {int(len(baseline_body) * (1 - cfg.RESUME_CHAR_TOLERANCE))}-"
                f"{int(len(baseline_body) * (1 + cfg.RESUME_CHAR_TOLERANCE))}",
            )

    # Gate 4: No Python list literals
    if re.search(r"\['", tex) or re.search(r'"\]', tex):
        _add_failure(failures, failure_details, "python_list_literal", "Python list literal found in .tex")

    # Gate 5: No literal \\n tokens
    if "\\n" in tex and "\\newcommand" not in tex[tex.index("\\n") - 20 : tex.index("\\n")]:
        # More precise: look for \n that isn't part of a command name
        if re.search(r"(?<!\\newcommand)(?<!\\noindent)(?<!\\newpage)\\n(?![a-zA-Z])", tex):
            _add_failure(failures, failure_details, "literal_newline_token", "literal \\n token found in .tex")

    # Gate 6: Section order (see RESUME_SECTIONS in config.py)
    if not _check_section_order(tex):
        _add_failure(failures, failure_details, "section_order_mismatch", "section order does not match canonical template")

    role_map = _extract_resume_role_map(tex)
    expected_roles = {
        exp["company"]: exp["role"]
        for exp in grounding.get("immutable_facts", {}).get("experience", [])
    }
    for company, expected_role in expected_roles.items():
        actual_role = role_map.get(company)
        if actual_role and actual_role != expected_role:
            _add_failure(
                failures,
                failure_details,
                "role_title_renamed",
                f"{company} role changed to '{actual_role}' (expected '{expected_role}')",
            )

    resume_narrative = "\n".join(
        [
            _extract_section(tex, "PROFESSIONAL SUMMARY"),
            _extract_section(tex, "WORK EXPERIENCE"),
            _extract_section(tex, "EDUCATION"),
        ]
    )
    _validate_grounding_claims(
        text=resume_narrative,
        failures=failures,
        failure_details=failure_details,
        grounding=grounding,
    )
    metrics["failure_details"] = failure_details
    return ValidationResult(
        passed=len(failures) == 0,
        failures=failures,
        metrics=metrics,
        failure_details=failure_details,
    )


def validate_cover_letter(tex_path: Path) -> ValidationResult:
    """Run hard gates on a tailored cover letter."""
    failures = []
    failure_details: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    tex = tex_path.read_text()
    baseline_tex = cfg.COVER_TEX.read_text()
    grounding = build_grounding_context()

    # Gate 1: Compilation
    pdf = compile_tex(tex_path)
    if pdf is None:
        _add_failure(failures, failure_details, "compilation_failed", "compilation failed")

    # Gate 2: Character count (see COVER_CHAR_TOLERANCE in config.py)
    body = _extract_body_text(tex)
    baseline_body = _extract_body_text(baseline_tex)
    if baseline_body:
        ratio = len(body) / len(baseline_body)
        metrics["char_ratio"] = round(ratio, 4)
        if abs(ratio - 1.0) > cfg.COVER_CHAR_TOLERANCE:
            _add_failure(
                failures,
                failure_details,
                "char_ratio_out_of_bounds",
                f"char count ratio {ratio:.2f} (±{cfg.COVER_CHAR_TOLERANCE} allowed)",
            )

    # Gate 3: No Python list literals
    if re.search(r"\['", tex) or re.search(r'"\]', tex):
        _add_failure(failures, failure_details, "python_list_literal", "Python list literal found in .tex")

    # Gate 4: No literal \\n tokens
    if re.search(r"(?<!\\newcommand)(?<!\\noindent)(?<!\\newpage)\\n(?![a-zA-Z])", tex):
        _add_failure(failures, failure_details, "literal_newline_token", "literal \\n token found in .tex")

    _validate_grounding_claims(
        text=tex,
        failures=failures,
        failure_details=failure_details,
        grounding=grounding,
    )
    _validate_cover_company_rendering(tex_path, tex, failures, failure_details)
    metrics["failure_details"] = failure_details
    return ValidationResult(
        passed=len(failures) == 0,
        failures=failures,
        metrics=metrics,
        failure_details=failure_details,
    )
