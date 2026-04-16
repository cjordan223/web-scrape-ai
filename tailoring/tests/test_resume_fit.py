import subprocess
import tempfile
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

from tailor import config as cfg
from tailor.validator import ResumeFitMetrics, inspect_resume_pdf_fit, validate_resume


class TestResumeFitInspection(unittest.TestCase):
    def test_inspect_resume_pdf_fit_parses_page_count_and_widows(self):
        bbox_xml = """<doc>
  <page width="612.000000" height="792.000000">
    <flow>
      <block>
        <line xMin="10" yMin="720"><word>Experience</word><word>continues</word></line>
      </block>
    </flow>
  </page>
  <page width="612.000000" height="792.000000">
    <flow>
      <block>
        <line xMin="25" yMin="710"><word>Festival.</word></line>
        <line xMin="25" yMin="730"><word>AWS</word><word>Certified</word></line>
      </block>
    </flow>
  </page>
</doc>"""

        with tempfile.TemporaryDirectory() as td:
            pdf_path = Path(td) / "resume.pdf"
            pdf_path.write_text("stub", encoding="utf-8")
            with patch(
                "tailor.validator.subprocess.run",
                side_effect=[
                    subprocess.CompletedProcess(
                        args=["pdfinfo", str(pdf_path)],
                        returncode=0,
                        stdout="Pages:           2\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["pdftotext", "-bbox-layout", str(pdf_path), "-"],
                        returncode=0,
                        stdout=bbox_xml,
                        stderr="",
                    ),
                ],
            ):
                metrics = inspect_resume_pdf_fit(pdf_path)

        self.assertEqual(metrics.page_count, 2)
        self.assertEqual(metrics.page_2_word_count, 3)
        self.assertTrue(metrics.has_suspicious_single_word_lines)
        self.assertEqual(metrics.suspicious_single_word_lines, ["Festival."])

    def test_inspect_resume_pdf_fit_handles_namespaced_xhtml_bbox_output(self):
        bbox_xml = """<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml">
<body><doc>
  <page width="612.000000" height="792.000000">
    <flow>
      <block>
        <line xMin="10" yMin="700" yMax="710"><word xMin="10" yMin="700" xMax="80" yMax="710">Dense</word></line>
        <line xMin="10" yMin="740" yMax="760"><word xMin="10" yMin="740" xMax="80" yMax="760">Footer</word></line>
      </block>
    </flow>
  </page>
</doc></body></html>"""

        with tempfile.TemporaryDirectory() as td:
            pdf_path = Path(td) / "resume.pdf"
            pdf_path.write_text("stub", encoding="utf-8")
            with patch(
                "tailor.validator.subprocess.run",
                side_effect=[
                    subprocess.CompletedProcess(
                        args=["pdfinfo", str(pdf_path)],
                        returncode=0,
                        stdout="Pages:           1\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["pdftotext", "-bbox-layout", str(pdf_path), "-"],
                        returncode=0,
                        stdout=bbox_xml,
                        stderr="",
                    ),
                ],
            ):
                metrics = inspect_resume_pdf_fit(pdf_path)

        self.assertTrue(metrics.render_inspection_ok)
        self.assertEqual(metrics.page_count, 1)
        self.assertEqual(metrics.page_fill_ratio, round(760 / 792, 4))

    def test_inspect_resume_pdf_fit_uses_env_override_for_poppler_tools(self):
        bbox_xml = """<doc>
  <page width="612.000000" height="792.000000">
    <flow><block><line xMin="10" yMin="720"><word>Resume</word></line></block></flow>
  </page>
</doc>"""

        with tempfile.TemporaryDirectory() as td:
            pdf_path = Path(td) / "resume.pdf"
            pdf_path.write_text("stub", encoding="utf-8")

            calls: list[list[str]] = []

            def fake_run(args, **kwargs):
                calls.append(args)
                if "pdfinfo" in args[0]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="Pages:           1\n", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=bbox_xml, stderr="")

            with (
                patch.dict(environ, {"PDFINFO_BIN": "/custom/bin/pdfinfo", "PDFTOTEXT_BIN": "/custom/bin/pdftotext"}, clear=False),
                patch("tailor.validator.subprocess.run", side_effect=fake_run),
                patch("tailor.validator.Path.exists", return_value=True),
            ):
                metrics = inspect_resume_pdf_fit(pdf_path)

        self.assertEqual(metrics.page_count, 1)
        self.assertEqual(calls[0][0], "/custom/bin/pdfinfo")
        self.assertEqual(calls[1][0], "/custom/bin/pdftotext")


class TestResumeValidation(unittest.TestCase):
    def test_validate_resume_fails_when_pdf_is_two_pages(self):
        baseline = cfg.RESUME_TEX.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            tex_path = Path(td) / "Conner_Jordan_Resume.tex"
            tex_path.write_text(baseline, encoding="utf-8")

            with (
                patch("tailor.validator.compile_tex", return_value=tex_path.with_suffix(".pdf")),
                patch(
                    "tailor.validator.inspect_resume_pdf_fit",
                    return_value=ResumeFitMetrics(
                        page_count=2,
                        page_2_word_count=5,
                        has_suspicious_single_word_lines=True,
                        suspicious_single_word_lines=["Festival."],
                        render_inspection_ok=True,
                    ),
                ),
            ):
                result = validate_resume(tex_path)

        self.assertFalse(result.passed)
        self.assertIn("rendered page count 2, expected 1", str(result))
        self.assertEqual(result.metrics["page_count"], 2)

    def test_validate_resume_rejects_simple_biz_prune(self):
        baseline = cfg.RESUME_TEX.read_text(encoding="utf-8")
        pruned = baseline.replace("\\prunedresumefalse", "\\prunedresumetrue", 1)
        pruned = pruned.replace(
            "  \\resumeItem{Managed full project lifecycle for multiple concurrent clients, handling domain configuration, hosting setup, cross-browser testing, and post-launch support to ensure reliable delivery.}\n",
            "",
            1,
        )

        with tempfile.TemporaryDirectory() as td:
            tex_path = Path(td) / "Conner_Jordan_Resume.tex"
            tex_path.write_text(pruned, encoding="utf-8")

            with (
                patch("tailor.validator.compile_tex", return_value=tex_path.with_suffix(".pdf")),
                patch(
                    "tailor.validator.inspect_resume_pdf_fit",
                    return_value=ResumeFitMetrics(page_count=1, render_inspection_ok=True),
                ),
            ):
                result = validate_resume(tex_path)

        self.assertFalse(result.passed)
        floor = cfg.RESUME_COMPANY_BULLET_FLOORS["Simple.biz"]
        cap = cfg.RESUME_COMPANY_BULLET_TARGETS["Simple.biz"]
        self.assertTrue(
            any(
                f"Simple.biz bullet count 2, expected {floor}-{cap} in pruned mode" in failure
                for failure in result.failures
            )
        )

    def test_validate_resume_fails_when_page_underfilled(self):
        baseline = cfg.RESUME_TEX.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            tex_path = Path(td) / "Conner_Jordan_Resume.tex"
            tex_path.write_text(baseline, encoding="utf-8")

            with (
                patch("tailor.validator.compile_tex", return_value=tex_path.with_suffix(".pdf")),
                patch(
                    "tailor.validator.inspect_resume_pdf_fit",
                    return_value=ResumeFitMetrics(
                        page_count=1,
                        page_fill_ratio=0.83,
                        render_inspection_ok=True,
                    ),
                ),
            ):
                result = validate_resume(tex_path)

        self.assertFalse(result.passed)
        self.assertTrue(any("page underfilled" in failure for failure in result.failures))

    def test_validate_resume_reports_fit_inspection_error_clearly(self):
        baseline = cfg.RESUME_TEX.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            tex_path = Path(td) / "Conner_Jordan_Resume.tex"
            tex_path.write_text(baseline, encoding="utf-8")

            with (
                patch("tailor.validator.compile_tex", return_value=tex_path.with_suffix(".pdf")),
                patch(
                    "tailor.validator.inspect_resume_pdf_fit",
                    return_value=ResumeFitMetrics(page_count=None, inspection_error="pdfinfo not found"),
                ),
            ):
                result = validate_resume(tex_path)

        self.assertFalse(result.passed)
        self.assertIn("rendered page count unavailable (pdfinfo not found)", str(result))

    def test_validate_resume_fails_when_render_inspection_incomplete_on_single_page(self):
        baseline = cfg.RESUME_TEX.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            tex_path = Path(td) / "Conner_Jordan_Resume.tex"
            tex_path.write_text(baseline, encoding="utf-8")

            with (
                patch("tailor.validator.compile_tex", return_value=tex_path.with_suffix(".pdf")),
                patch(
                    "tailor.validator.inspect_resume_pdf_fit",
                    return_value=ResumeFitMetrics(
                        page_count=1,
                        inspection_error="pdftotext XML missing page elements",
                    ),
                ),
            ):
                result = validate_resume(tex_path)

        self.assertFalse(result.passed)
        self.assertIn("render inspection incomplete", str(result))


if __name__ == "__main__":
    unittest.main()
