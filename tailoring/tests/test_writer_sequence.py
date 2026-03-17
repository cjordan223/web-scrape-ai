import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tailor.selector import SelectedJob
from tailor.validator import ResumeFitMetrics
from tailor.writer import write_cover_letter, write_resume


class TestWriterSequence(unittest.TestCase):
    def setUp(self):
        self.job = SelectedJob(
            id=1,
            url="https://example.com/jobs/1",
            title="Role",
            board="lever",
            seniority="mid",
            jd_text="desc",
            snippet="",
            company="example",
        )
        self.analysis = {
            "role_title": "Role",
            "company_name": "Example",
            "summary_angle": "angle",
            "tone_notes": "tone",
        }

    def test_resume_and_cover_phase_order(self):
        calls = []

        def fake_chat(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None):
            calls.append((trace or {}).copy())
            doc = (trace or {}).get("doc_type")
            phase = (trace or {}).get("phase")
            # Return a valid full LaTeX doc
            if doc == "resume":
                from tailor import config as cfg
                return Path(cfg.RESUME_TEX).read_text(encoding="utf-8")
            from tailor import config as cfg
            return Path(cfg.COVER_TEX).read_text(encoding="utf-8")

        def fake_chat_expect_json(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None):
            calls.append((trace or {}).copy())
            doc = (trace or {}).get("doc_type")
            if doc == "resume":
                return {"summary_strategy": "x", "skills_tailoring": {}, "experience_rewrites": [], "risk_controls": []}
            return {
                "company_hook": "x",
                "structure": [],
                "closing_angle": "x",
                "voice_controls": [],
                "claims_to_avoid": [],
                "vignettes_to_use": [],
            }

        with (
            tempfile.TemporaryDirectory() as td,
            patch("tailor.writer.chat", side_effect=fake_chat),
            patch("tailor.writer.chat_expect_json", side_effect=fake_chat_expect_json),
            patch("tailor.writer.compile_tex", side_effect=lambda tex_path: tex_path.with_suffix(".pdf")),
            patch(
                "tailor.writer.inspect_resume_pdf_fit",
                return_value=ResumeFitMetrics(page_count=1, render_inspection_ok=True),
            ),
        ):
            out = Path(td)
            write_resume(self.job, self.analysis, out, attempt=1)
            write_cover_letter(self.job, self.analysis, out, attempt=1)

        sequence = [(c.get("doc_type"), c.get("phase")) for c in calls]
        self.assertEqual(
            sequence,
            [
                ("resume", "strategy"),
                ("resume", "draft"),
                ("resume", "qa"),
                ("cover", "strategy"),
                ("cover", "draft"),
                ("cover", "qa"),
            ],
        )

    def test_resume_fit_cascade_uses_condense_then_compact_then_prune(self):
        calls = []
        events = []

        def fake_chat(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None):
            calls.append((trace or {}).copy())
            doc = (trace or {}).get("doc_type")
            if doc == "resume":
                from tailor import config as cfg
                return Path(cfg.RESUME_TEX).read_text(encoding="utf-8")
            raise AssertionError("unexpected cover call")

        def fake_chat_expect_json(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None):
            calls.append((trace or {}).copy())
            return {"summary_strategy": "x", "skills_tailoring": {}, "experience_rewrites": [], "risk_controls": []}

        fit_metrics = [
            ResumeFitMetrics(page_count=2, page_2_word_count=12, render_inspection_ok=True),
            ResumeFitMetrics(page_count=2, page_2_word_count=6, render_inspection_ok=True),
            ResumeFitMetrics(page_count=2, page_2_word_count=2, has_suspicious_single_word_lines=True, suspicious_single_word_lines=["Festival"], render_inspection_ok=True),
            ResumeFitMetrics(page_count=1, render_inspection_ok=True),
        ]

        with (
            tempfile.TemporaryDirectory() as td,
            patch("tailor.writer.chat", side_effect=fake_chat),
            patch("tailor.writer.chat_expect_json", side_effect=fake_chat_expect_json),
            patch("tailor.writer.compile_tex", side_effect=lambda tex_path: tex_path.with_suffix(".pdf")),
            patch("tailor.writer.inspect_resume_pdf_fit", side_effect=fit_metrics),
        ):
            out = Path(td)
            write_resume(self.job, self.analysis, out, attempt=1, trace_recorder=events.append)
            final_tex = (out / "Conner_Jordan_Resume.tex").read_text(encoding="utf-8")

        sequence = [
            ((c.get("doc_type"), c.get("phase")), c.get("fit_mode"))
            for c in calls
        ]
        self.assertEqual(
            sequence,
            [
                (("resume", "strategy"), None),
                (("resume", "draft"), None),
                (("resume", "qa"), None),
                (("resume", "fit"), "condense"),
                (("resume", "fit"), "prune"),
            ],
        )
        self.assertIn("\\compactresumetrue", final_tex)
        self.assertIn("\\prunedresumetrue", final_tex)
        fit_event_modes = [event.get("fit_mode") for event in events if event.get("phase") == "fit"]
        self.assertIn("condense", fit_event_modes)
        self.assertIn("compact", fit_event_modes)
        self.assertIn("prune", fit_event_modes)


if __name__ == "__main__":
    unittest.main()
