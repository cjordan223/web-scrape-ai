import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tailor.selector import SelectedJob
from tailor.validator import ResumeFitMetrics, _count_resume_bullets_by_company, _extract_body_text
from tailor.writer import (
    _COVER_DRAFT_SYSTEM,
    _COVER_HUMANIZE_SYSTEM,
    _COVER_QA_SYSTEM,
    _COVER_STYLE_REPAIR_SYSTEM,
    _coerce_cover_chunks,
    _coerce_resume_chunks,
    _repair_cover_style_chunks,
    _trim_cover_text_to_budget,
    write_cover_letter,
    write_resume,
)


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
        self.baseline_skills = {
            "Languages": ["Python", "SQL"],
            "Security Tooling": ["Splunk"],
            "AI/ML and Research": ["RAG pipelines"],
            "Frameworks and Infrastructure": ["Flask"],
            "DevOps and CI/CD": ["CI/CD pipelines"],
            "Databases": ["PostgreSQL"],
        }
        self.baseline_resume = Path(
            "/Users/conner/Documents/TexTailor/tailoring/Baseline-Dox/Conner_Jordan_Software_Engineer/Conner_Jordan_Resume.tex"
        ).read_text(encoding="utf-8")

    def test_resume_chunk_coercion_accepts_dict_shaped_experience(self):
        payload = {
            "summary": "Security engineer building reliable systems.",
            "experience": {
                "University of California, Office of the President": ["a", "b", "c", "d", "e", "f"],
                "Great Wolf Resorts": ["a", "b", "c", "d", "e"],
                "Simple.biz": ["a", "b", "c"],
            },
        }

        chunks = _coerce_resume_chunks(
            payload,
            baseline=self.baseline_resume,
            baseline_skills=self.baseline_skills,
            selected_skills=self.baseline_skills,
        )

        self.assertEqual(len(chunks["experience"]["University of California, Office of the President"]), 6)
        self.assertEqual(len(chunks["experience"]["Great Wolf Resorts"]), 5)
        self.assertEqual(len(chunks["experience"]["Simple.biz"]), 3)
        self.assertEqual(chunks["skills"], self.baseline_skills)

    def test_resume_chunk_coercion_backfills_missing_gwr_bullets_from_baseline(self):
        payload = {
            "summary": "Security engineer building reliable systems.",
            "experience": {
                "University of California, Office of the President": ["a", "b", "c", "d", "e", "f"],
                "Great Wolf Resorts": ["a", "b", "c"],
                "Simple.biz": ["a", "b", "c"],
            },
        }

        chunks = _coerce_resume_chunks(
            payload,
            baseline=self.baseline_resume,
            baseline_skills=self.baseline_skills,
            selected_skills=self.baseline_skills,
        )

        self.assertEqual(len(chunks["experience"]["Great Wolf Resorts"]), 5)
        self.assertEqual(chunks["experience"]["Great Wolf Resorts"][:3], ["a", "b", "c"])

    def test_resume_chunk_coercion_backfills_missing_ucop_bullet_from_baseline(self):
        payload = {
            "summary": "Security engineer building reliable systems.",
            "experience": {
                "University of California, Office of the President": ["a", "b", "c", "d", "e"],
                "Great Wolf Resorts": ["a", "b", "c", "d", "e"],
                "Simple.biz": ["a", "b", "c"],
            },
        }

        chunks = _coerce_resume_chunks(
            payload,
            baseline=self.baseline_resume,
            baseline_skills=self.baseline_skills,
            selected_skills=self.baseline_skills,
        )

        self.assertEqual(len(chunks["experience"]["University of California, Office of the President"]), 6)
        self.assertEqual(chunks["experience"]["University of California, Office of the President"][:5], ["a", "b", "c", "d", "e"])

    def test_cover_chunk_coercion_rejects_empty_body(self):
        with self.assertRaisesRegex(
            ValueError,
            "Cover chunk payload missing body paragraphs: expected at least 2, found 0",
        ):
            _coerce_cover_chunks({"paragraphs": [], "closing": "Closing."})

    def test_cover_chunk_coercion_rejects_missing_closing(self):
        with self.assertRaisesRegex(ValueError, "Cover chunk payload missing closing"):
            _coerce_cover_chunks({"paragraphs": ["Paragraph one.", "Paragraph two."], "closing": ""})

    def test_resume_and_cover_phase_order(self):
        calls = []

        def fake_chat(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            calls.append((trace or {}).copy())
            doc = (trace or {}).get("doc_type")
            phase = (trace or {}).get("phase")
            # Return a valid full LaTeX doc
            if doc == "resume":
                from tailor import config as cfg
                return Path(cfg.RESUME_TEX).read_text(encoding="utf-8")
            from tailor import config as cfg
            return Path(cfg.COVER_TEX).read_text(encoding="utf-8")

        def fake_chat_expect_json(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            calls.append((trace or {}).copy())
            doc = (trace or {}).get("doc_type")
            phase = (trace or {}).get("phase")
            if doc == "resume" and phase == "strategy":
                return {"summary_strategy": "x", "skills_tailoring": {}, "experience_rewrites": [], "risk_controls": []}
            if doc == "resume":
                return {
                    "summary": "Security engineer building reliable systems.",
                    "skills": self.baseline_skills,
                    "experience": {
                        "University of California, Office of the President": ["a", "b", "c", "d", "e", "f"],
                        "Great Wolf Resorts": ["a", "b", "c", "d", "e"],
                        "Simple.biz": ["a", "b", "c"],
                    },
                }
            return {
                "company_hook": "x",
                "structure": [],
                "closing_angle": "x",
                "voice_controls": [],
                "claims_to_avoid": [],
                "vignettes_to_use": [],
            } if phase == "strategy" else {
                "paragraphs": ["Paragraph one.", "Paragraph two."],
                "closing": "Closing paragraph.",
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
                ("cover", "humanize"),
            ],
        )

    def test_resume_fit_cascade_uses_condense_then_prune_without_compact_layout(self):
        calls = []
        events = []

        def fake_chat(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            calls.append((trace or {}).copy())
            doc = (trace or {}).get("doc_type")
            if doc == "resume":
                from tailor import config as cfg
                return Path(cfg.RESUME_TEX).read_text(encoding="utf-8")
            raise AssertionError("unexpected cover call")

        def fake_chat_expect_json(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            calls.append((trace or {}).copy())
            phase = (trace or {}).get("phase")
            if phase == "strategy":
                return {"summary_strategy": "x", "skills_tailoring": {}, "experience_rewrites": [], "risk_controls": []}
            return {
                "summary": "Security engineer building reliable systems.",
                "skills": self.baseline_skills,
                "experience": {
                    "University of California, Office of the President": ["a", "b", "c", "d", "e", "f"],
                    "Great Wolf Resorts": ["a", "b", "c", "d", "e"],
                    "Simple.biz": ["a", "b", "c"],
                },
            }

        fit_metrics = [
            ResumeFitMetrics(page_count=2, page_2_word_count=12, render_inspection_ok=True),
            ResumeFitMetrics(page_count=2, page_2_word_count=6, render_inspection_ok=True),
            ResumeFitMetrics(page_count=1, render_inspection_ok=True),
        ]

        # Stub _extract_body_text so the post-QA char ratio stays >= 0.95,
        # ensuring the fit-skip optimization does not short-circuit this test.
        _stable_body = "x" * 2100

        with (
            tempfile.TemporaryDirectory() as td,
            patch("tailor.writer.chat", side_effect=fake_chat),
            patch("tailor.writer.chat_expect_json", side_effect=fake_chat_expect_json),
            patch("tailor.writer.compile_tex", side_effect=lambda tex_path: tex_path.with_suffix(".pdf")),
            patch("tailor.writer.inspect_resume_pdf_fit", side_effect=fit_metrics),
            patch("tailor.writer._extract_body_text", return_value=_stable_body),
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
        self.assertIn("\\compactresumefalse", final_tex)
        self.assertIn("\\prunedresumetrue", final_tex)
        fit_event_modes = [event.get("fit_mode") for event in events if event.get("phase") == "fit"]
        self.assertIn("condense", fit_event_modes)
        self.assertIn("prune", fit_event_modes)
        self.assertNotIn("compact", fit_event_modes)

    def test_resume_condense_underfill_triggers_loose_layout_repair(self):
        events = []

        def fake_chat(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            from tailor import config as cfg
            return Path(cfg.RESUME_TEX).read_text(encoding="utf-8")

        def fake_chat_expect_json(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            phase = (trace or {}).get("phase")
            if phase == "strategy":
                return {"summary_strategy": "x", "skills_tailoring": {}, "experience_rewrites": [], "risk_controls": []}
            return {
                "summary": "Security engineer building reliable systems.",
                "skills": self.baseline_skills,
                "experience": {
                    "University of California, Office of the President": ["a", "b", "c", "d", "e", "f"],
                    "Great Wolf Resorts": ["a", "b", "c", "d", "e"],
                    "Simple.biz": ["a", "b", "c"],
                },
            }

        fit_metrics = [
            ResumeFitMetrics(page_count=2, render_inspection_ok=True),
            ResumeFitMetrics(page_count=1, page_fill_ratio=0.84, render_inspection_ok=True),
            ResumeFitMetrics(page_count=1, page_fill_ratio=0.88, render_inspection_ok=True),
        ]

        with (
            tempfile.TemporaryDirectory() as td,
            patch("tailor.writer.chat", side_effect=fake_chat),
            patch("tailor.writer.chat_expect_json", side_effect=fake_chat_expect_json),
            patch("tailor.writer.compile_tex", side_effect=lambda tex_path: tex_path.with_suffix(".pdf")),
            patch("tailor.writer.inspect_resume_pdf_fit", side_effect=fit_metrics),
            patch("tailor.writer._extract_body_text", return_value="x" * 2100),
        ):
            out = Path(td)
            write_resume(self.job, self.analysis, out, attempt=1, trace_recorder=events.append)
            final_tex = (out / "Conner_Jordan_Resume.tex").read_text(encoding="utf-8")

        self.assertIn("\\compactresumefalse", final_tex)
        self.assertIn("\\looseresumetrue", final_tex)
        fit_event_modes = [event.get("fit_mode") for event in events if event.get("phase") == "fit"]
        self.assertIn("condense", fit_event_modes)
        self.assertIn("loose", fit_event_modes)
        self.assertNotIn("compact", fit_event_modes)

    def test_resume_rejects_fit_pass_that_drops_ucop_bullet(self):
        def fake_chat(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            from tailor import config as cfg
            fit_mode = (trace or {}).get("fit_mode")
            baseline = Path(cfg.RESUME_TEX).read_text(encoding="utf-8")
            if fit_mode == "condense":
                return baseline.replace(
                    "  \\resumeItem{Pioneered audit-ready governance for AI security tooling across UC’s developer ecosystem, including org-wide runbooks that operationalized standardized asset remediation.}\n",
                    "",
                    1,
                )
            return baseline

        def fake_chat_expect_json(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            phase = (trace or {}).get("phase")
            if phase == "strategy":
                return {"summary_strategy": "x", "skills_tailoring": {}, "experience_rewrites": [], "risk_controls": []}
            return {
                "summary": "Security engineer building reliable systems.",
                "skills": self.baseline_skills,
                "experience": {
                    "University of California, Office of the President": ["a", "b", "c", "d", "e", "f"],
                    "Great Wolf Resorts": ["a", "b", "c", "d", "e"],
                    "Simple.biz": ["a", "b", "c"],
                },
            }

        fit_metrics = [
            ResumeFitMetrics(page_count=2, render_inspection_ok=True),
            ResumeFitMetrics(page_count=1, page_fill_ratio=0.9, render_inspection_ok=True),
            ResumeFitMetrics(page_count=1, page_fill_ratio=0.9, render_inspection_ok=True),
        ]

        with (
            tempfile.TemporaryDirectory() as td,
            patch("tailor.writer.chat", side_effect=fake_chat),
            patch("tailor.writer.chat_expect_json", side_effect=fake_chat_expect_json),
            patch("tailor.writer.compile_tex", side_effect=lambda tex_path: tex_path.with_suffix(".pdf")),
            patch("tailor.writer.inspect_resume_pdf_fit", side_effect=fit_metrics),
            patch("tailor.writer._extract_body_text", return_value="x" * 2100),
        ):
            out = Path(td)
            write_resume(self.job, self.analysis, out, attempt=1)
            final_tex = (out / "Conner_Jordan_Resume.tex").read_text(encoding="utf-8")

        self.assertEqual(
            _count_resume_bullets_by_company(final_tex),
            {
                "University of California, Office of the President": 6,
                "Great Wolf Resorts": 5,
                "Simple.biz": 3,
            },
        )
        self.assertIn("\\compactresumefalse", final_tex)

    def test_cover_trim_helper_reduces_small_overshoot_without_emptying_letter(self):
        from tailor import config as cfg

        baseline = Path(cfg.COVER_TEX).read_text(encoding="utf-8")
        baseline_body_len = len(_extract_body_text(baseline))
        target_hi = int(baseline_body_len * (1 + cfg.COVER_CHAR_TOLERANCE))
        paragraphs = [
            "I am excited to help build reliable products that feel useful to the people depending on them every day.",
            "I know that the best work usually starts with a messy problem, a rough manual process, and a willingness to keep refining the details after people start using the first version.",
            "I would be excited to bring that same habit of shipping, listening, and tightening the edges to this team.",
        ]
        closing = "I'd love to talk more about how I can help the team keep shipping thoughtful product work."

        before_len = len(
            _extract_body_text(
                baseline.replace("Dear Hiring Team,", "Dear Hiring Team,\n\n" + "\n\n".join(paragraphs + [closing]), 1)
            )
        )
        self.assertGreater(before_len, target_hi)

        trimmed_paragraphs, trimmed_closing = _trim_cover_text_to_budget(
            paragraphs,
            closing,
            target_hi=target_hi,
            baseline=baseline,
            company_name="Example",
            date_text="April 14, 2026",
        )

        trimmed_tex = baseline
        from tailor.writer import _assemble_cover_tex
        trimmed_tex = _assemble_cover_tex(
            baseline,
            company_name="Example",
            date_text="April 14, 2026",
            paragraphs=trimmed_paragraphs,
            closing=trimmed_closing,
        )
        trimmed_len = len(_extract_body_text(trimmed_tex))
        self.assertLessEqual(trimmed_len, target_hi)
        self.assertGreaterEqual(len(trimmed_paragraphs), 2)
        self.assertTrue(trimmed_closing)

    def test_resume_retry_feedback_is_included_in_draft_and_qa_prompts(self):
        prompts = []
        previous_feedback = {
            "source": "validator",
            "summary": "FAIL — bullet count wrong",
            "failure_details": [
                {
                    "category": "bullet_count_mismatch",
                    "message": "expected 14 bullets, found 13",
                    "snippet": "\\resumeItem{Only 13 bullets here}",
                }
            ],
        }

        def fake_chat(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            prompts.append(((trace or {}).copy(), user_prompt))
            from tailor import config as cfg
            return Path(cfg.RESUME_TEX).read_text(encoding="utf-8")

        def fake_chat_expect_json(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            prompts.append(((trace or {}).copy(), user_prompt))
            phase = (trace or {}).get("phase")
            if phase == "strategy":
                return {"summary_strategy": "x", "skills_tailoring": {}, "experience_rewrites": [], "risk_controls": []}
            if phase in {"draft", "qa"}:
                return {
                    "summary": "x",
                    "skills": {
                        "Languages": ["Python", "C", "C++", "TypeScript", "Java", "SQL", "PowerShell", "Bash", "Swift", "Rust", "Go"],
                        "Security Tooling": ["Vulnerability management"],
                        "AI/ML and Research": ["RAG pipelines"],
                        "Frameworks and Infrastructure": ["Flask"],
                        "DevOps and CI/CD": ["CI/CD pipelines"],
                        "Databases": ["PostgreSQL", "MySQL", "MongoDB", "DynamoDB", "SQLite", "Redis", "Snowflake", "ClickHouse", "Databricks", "vector databases"],
                    },
                    "experience": [
                        {"company": "University of California, Office of the President", "bullets": ["a", "b", "c", "d", "e", "f"]},
                        {"company": "Great Wolf Resorts", "bullets": ["a", "b", "c", "d", "e"]},
                        {"company": "Simple.biz", "bullets": ["a", "b", "c"]},
                    ],
                }
            return {"summary_strategy": "x", "skills_tailoring": {}, "experience_rewrites": [], "risk_controls": []}

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
            write_resume(self.job, self.analysis, out, previous_feedback=previous_feedback, attempt=2)

        draft_prompt = next(prompt for trace, prompt in prompts if trace.get("phase") == "draft")
        qa_prompt = next(prompt for trace, prompt in prompts if trace.get("phase") == "qa")
        for prompt in [draft_prompt, qa_prompt]:
            self.assertIn("Structured validator failures (JSON)", prompt)
            self.assertIn('"category": "bullet_count_mismatch"', prompt)
            self.assertIn("\\\\resumeItem{Only 13 bullets here}", prompt)
            self.assertIn("Summary: FAIL — bullet count wrong", prompt)

    def test_cover_retry_feedback_is_included_in_draft_and_qa_prompts(self):
        prompts = []
        previous_feedback = {
            "source": "validator",
            "summary": "FAIL — company name mismatch",
            "failure_details": [
                {
                    "category": "company_rendering_mismatch",
                    "message": "expected Example, found Exampel",
                    "snippet": "Dear Exampel hiring team",
                }
            ],
        }

        def fake_chat(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            prompts.append(((trace or {}).copy(), user_prompt))
            from tailor import config as cfg
            return Path(cfg.COVER_TEX).read_text(encoding="utf-8")

        def fake_chat_expect_json(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            prompts.append(((trace or {}).copy(), user_prompt))
            phase = (trace or {}).get("phase")
            if phase == "strategy":
                return {
                    "company_hook": "x",
                    "structure": [],
                    "closing_angle": "x",
                    "voice_controls": [],
                    "claims_to_avoid": [],
                    "vignettes_to_use": [],
                }
            return {
                "paragraphs": ["Paragraph one.", "Paragraph two."],
                "closing": "Closing paragraph.",
            }

        with (
            tempfile.TemporaryDirectory() as td,
            patch("tailor.writer.chat", side_effect=fake_chat),
            patch("tailor.writer.chat_expect_json", side_effect=fake_chat_expect_json),
        ):
            out = Path(td)
            write_cover_letter(self.job, self.analysis, out, previous_feedback=previous_feedback, attempt=2)

        strategy_prompt = next(prompt for trace, prompt in prompts if trace.get("phase") == "strategy")
        draft_prompt = next(prompt for trace, prompt in prompts if trace.get("phase") == "draft")
        qa_prompt = next(prompt for trace, prompt in prompts if trace.get("phase") == "qa")
        humanize_prompt = next(prompt for trace, prompt in prompts if trace.get("phase") == "humanize")
        for prompt in [strategy_prompt, draft_prompt, qa_prompt, humanize_prompt]:
            self.assertIn("Structured validator failures (JSON)", prompt)
            self.assertIn('"category": "company_rendering_mismatch"', prompt)
            self.assertIn("Dear Exampel hiring team", prompt)
            self.assertIn("Summary: FAIL — company name mismatch", prompt)

    def test_cover_prompts_hard_ban_banned_rhetorical_patterns(self):
        for prompt in [_COVER_DRAFT_SYSTEM, _COVER_QA_SYSTEM, _COVER_HUMANIZE_SYSTEM, _COVER_STYLE_REPAIR_SYSTEM]:
            self.assertIn("BANNED COVER-LETTER RHETORICAL PATTERNS", prompt)
            self.assertIn("zero occurrences", prompt)
            self.assertNotIn("at most ONE", prompt)
            self.assertNotIn("at most one", prompt)

    def test_cover_style_repair_rewrites_banned_sentences_before_validation(self):
        prompts = []
        payload = {
            "paragraphs": [
                "I didn't just write runbooks, I walked teams through the tradeoffs.",
                "This is grounded supporting detail.",
            ],
            "closing": "I've learned that security only works when people use it.",
        }

        def fake_repair(system_prompt, user_prompt, **kwargs):
            prompts.append((system_prompt, user_prompt, kwargs.get("trace")))
            return {
                "paragraphs": [
                    "I paired runbooks with team walkthroughs so each tradeoff was clear.",
                    "This is grounded supporting detail.",
                ],
                "closing": "Security works best when people can use it without friction.",
            }

        repaired = _repair_cover_style_chunks(
            payload,
            analysis={"company_name": "Example", "role_title": "Role"},
            grounding={},
            attempt=2,
            trace_recorder=None,
            repair_fn=fake_repair,
        )

        self.assertEqual(
            repaired["paragraphs"][0],
            "I paired runbooks with team walkthroughs so each tradeoff was clear.",
        )
        self.assertEqual(
            repaired["closing"],
            "Security works best when people can use it without friction.",
        )
        self.assertEqual(len(prompts), 1)
        self.assertIn("I didn't just write runbooks", prompts[0][1])
        self.assertIn("I've learned that security only works", prompts[0][1])
        self.assertEqual(prompts[0][2]["phase"], "style_repair")


if __name__ == "__main__":
    unittest.main()
