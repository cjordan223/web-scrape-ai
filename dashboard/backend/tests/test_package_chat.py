import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import package_chat


class TestPackageChat(unittest.TestCase):
    def _write_package(self, root: Path, slug: str) -> Path:
        pkg = root / slug
        pkg.mkdir(parents=True)
        (pkg / "meta.json").write_text(
            json.dumps(
                {
                    "job_id": 1,
                    "title": "Software Engineer",
                    "url": "https://example.com/jobs/1",
                    "jd_text": "Additional Information\nPlease share anything else you want us to know.",
                }
            ),
            encoding="utf-8",
        )
        (pkg / "analysis.json").write_text(
            json.dumps(
                {
                    "company_name": "OpenAI",
                    "role_title": "Software Engineer",
                    "summary_angle": "Lead with platform reliability and AI infrastructure delivery.",
                    "tone_notes": "Direct, thoughtful, practical.",
                    "requirements": [
                        {"jd_requirement": "Build reliable systems", "priority": "high"},
                        {"jd_requirement": "Communicate clearly", "priority": "medium"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (pkg / "resume_strategy.json").write_text(
            json.dumps({"summary_strategy": "Emphasize platform engineering and security automation."}),
            encoding="utf-8",
        )
        (pkg / "cover_strategy.json").write_text(
            json.dumps({"summary_strategy": "Connect motivation to safe AI deployment."}),
            encoding="utf-8",
        )
        (pkg / "Conner_Jordan_Resume.tex").write_text(
            r"""\documentclass{article}
\begin{document}
\section{PROFESSIONAL SUMMARY}
Platform-focused security engineer building reliable automation for production systems.
\section{WORK EXPERIENCE}
\resumeItem{Built endpoint and cloud automation for production security workflows.}
\end{document}
""",
            encoding="utf-8",
        )
        (pkg / "Conner_Jordan_Cover_Letter.tex").write_text(
            r"""\documentclass{article}
\begin{document}
I want to help OpenAI ship safe and reliable systems.
\end{document}
""",
            encoding="utf-8",
        )
        return pkg

    def test_application_question_mode_uses_answer_prompt_not_edit_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "output"
            output_dir.mkdir()
            soul_path = Path(td) / "soul.md"
            soul_path.write_text("Conner Jordan builds reliable security automation.", encoding="utf-8")
            self._write_package(output_dir, "pkg-1")

            captured: dict = {}

            def fake_chat(system_prompt: str, user_prompt: str, *, mode: str, **kwargs):
                captured["system_prompt"] = system_prompt
                captured["user_prompt"] = user_prompt
                captured["mode"] = mode
                return "Primary answer:\nI am excited to apply because I like building reliable systems — and I communicate clearly."

            with (
                patch.object(package_chat, "OUTPUT_DIR", output_dir),
                patch.object(package_chat, "SOUL_MD", soul_path),
                patch.object(package_chat._app, "_get_job_context", return_value=None),
                patch.object(package_chat, "_call_package_chat_model", side_effect=fake_chat),
            ):
                result = package_chat.send_chat(
                    "pkg-1",
                    "Help me answer this application question: Additional Information. Please share anything else you want us to know.",
                    "cover",
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "application_answer")
        self.assertNotIn("edits", result)
        self.assertEqual(result["reply"], "I am excited to apply because I like building reliable systems, and I communicate clearly.")
        self.assertIn("APPLICATION QUESTION MODE", captured["system_prompt"])
        self.assertIn("This mode is the primary purpose of package chat.", captured["system_prompt"])
        self.assertIn("Default to one compact paragraph of 80-140 words", captured["system_prompt"])
        self.assertIn("Return plain text only. Do not use Markdown", captured["system_prompt"])
        self.assertIn("Do not use bullets unless the user explicitly asks for bullets.", captured["system_prompt"])
        self.assertIn("Do not use em dashes.", captured["system_prompt"])
        self.assertIn("Use the package strategy and cover letter for facts only.", captured["system_prompt"])
        self.assertIn("Mention at most one prior employer or project.", captured["system_prompt"])
        self.assertIn("Do not start with 'What excites me about [company] is'.", captured["system_prompt"])
        self.assertIn("Weak example:", captured["system_prompt"])
        self.assertIn("Strong example:", captured["system_prompt"])
        self.assertIn("CURRENT COVER LETTER CONTENT", captured["system_prompt"])
        self.assertNotIn("CURRENT COVER LATEX", captured["system_prompt"])
        self.assertEqual(captured["mode"], "application_answer")

    def test_application_answer_cleanup_removes_markdown_and_em_dashes(self):
        raw = (
            "Suggested answer:\n"
            "What excites me about Replit is that you treat infrastructure as a *product* — not a cost center. "
            "At UCOP, I built **Coraline** because teams were drowning in manual reconciliation — the goal was *actionable visibility*."
        )

        cleaned = package_chat._clean_application_answer(
            raw,
            user_message="Help me answer why are you interested in Replit?",
        )

        self.assertNotIn("—", cleaned)
        self.assertNotIn("*", cleaned)
        self.assertNotIn("Suggested answer", cleaned)
        self.assertIn("infrastructure as something developers can trust, not a cost center", cleaned)
        self.assertIn("Coraline", cleaned)
        self.assertIn("clear view of what needed attention", cleaned)

    def test_application_answer_cleanup_rewrites_strategy_phrases(self):
        raw = (
            "What excites me most about Replit is the chance to apply that same builder-first mindset at scale. "
            "It mirrors my own instinct around infrastructure as a product and actionable visibility."
        )

        cleaned = package_chat._clean_application_answer(raw, user_message="what excites you most abour replit")

        self.assertNotIn("builder-first", cleaned.lower())
        self.assertNotIn("at scale", cleaned.lower())
        self.assertNotIn("mirrors my own instinct", cleaned.lower())
        self.assertNotIn("infrastructure as a product", cleaned.lower())
        self.assertNotIn("actionable visibility", cleaned.lower())

    def test_application_answer_cleanup_flattens_unrequested_bullets(self):
        raw = (
            "Draft:\n"
            "- I like ambiguous infrastructure problems.\n"
            "- I have built tooling for noisy operational data.\n"
            "- I care about shipping something usable."
        )

        cleaned = package_chat._clean_application_answer(
            raw,
            user_message="Help me answer this application question.",
        )

        self.assertNotIn("- I like", cleaned)
        self.assertNotIn("\n-", cleaned)
        self.assertIn("I like ambiguous infrastructure problems", cleaned)

    def test_excites_question_routes_to_application_answer(self):
        self.assertEqual(
            package_chat._detect_chat_mode("what excites you most abour replit", "resume"),
            "application_answer",
        )
        self.assertEqual(
            package_chat._detect_chat_mode("What excites you about Replit?", "cover"),
            "application_answer",
        )

    def test_application_history_omits_prior_assistant_answers(self):
        history = [
            {"role": "user", "content": "What excites you about Replit?", "mode": "general"},
            {
                "role": "assistant",
                "content": "What excites me is *product*—not cost center.\n- Bad list",
                "mode": "general",
            },
            {
                "role": "assistant",
                "content": "I like infrastructure as a product.",
                "mode": "application_answer",
            },
            {"role": "user", "content": "Try again", "mode": "application_answer"},
        ]

        rendered = package_chat._render_recent_history(history, mode="application_answer")

        self.assertIn("USER[general]: What excites you about Replit?", rendered)
        self.assertIn("USER[application_answer]: Try again", rendered)
        self.assertNotIn("Bad list", rendered)
        self.assertNotIn("*product*", rendered)
        self.assertNotIn("infrastructure as a product", rendered)

    def test_edit_mode_can_target_resume_when_cover_is_selected(self):
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "output"
            output_dir.mkdir()
            soul_path = Path(td) / "soul.md"
            soul_path.write_text("Conner Jordan builds reliable security automation.", encoding="utf-8")
            pkg = self._write_package(output_dir, "pkg-1")

            captured: dict = {}
            old_summary = "Platform-focused security engineer building reliable automation for production systems."
            new_summary = "Platform and infrastructure engineer building reliable automation for AI and security systems."

            def fake_chat(system_prompt: str, user_prompt: str, *, mode: str, **kwargs):
                captured["system_prompt"] = system_prompt
                captured["user_prompt"] = user_prompt
                captured["mode"] = mode
                return (
                    "Tightened the summary for a stronger platform angle.\n\n"
                    "<<<EDIT\n"
                    "OLD:\n"
                    f"{old_summary}\n"
                    "NEW:\n"
                    f"{new_summary}\n"
                    "EDIT>>>"
                )

            with (
                patch.object(package_chat, "OUTPUT_DIR", output_dir),
                patch.object(package_chat, "SOUL_MD", soul_path),
                patch.object(package_chat._app, "_get_job_context", return_value=None),
                patch.object(package_chat, "_call_package_chat_model", side_effect=fake_chat),
            ):
                result = package_chat.send_chat(
                    "pkg-1",
                    "Retailor the resume summary to be more platform-focused.",
                    "cover",
                )

            resume_tex = (pkg / "Conner_Jordan_Resume.tex").read_text(encoding="utf-8")
            cover_tex = (pkg / "Conner_Jordan_Cover_Letter.tex").read_text(encoding="utf-8")

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "edit")
        self.assertEqual(result["doc_updated"], "resume")
        self.assertIn(new_summary, resume_tex)
        self.assertIn("OpenAI ship safe and reliable systems", cover_tex)
        self.assertIn("EDIT MODE", captured["system_prompt"])
        self.assertIn("CURRENT RESUME LATEX", captured["system_prompt"])
        self.assertNotIn("CURRENT COVER LATEX", captured["system_prompt"])
        self.assertEqual(captured["mode"], "edit")

    def test_apply_edits_falls_back_to_flexible_whitespace_matching(self):
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "output"
            output_dir.mkdir()
            soul_path = Path(td) / "soul.md"
            soul_path.write_text("Conner Jordan builds reliable security automation.", encoding="utf-8")
            pkg = self._write_package(output_dir, "pkg-1")

            old_block = (
                "\\section{WORK EXPERIENCE}\n"
                "\n"
                "\\resumeItem{Built endpoint and cloud automation for production security workflows.}"
            )
            new_block = (
                "\\section{WORK EXPERIENCE}\n"
                "\\resumeItem{Built secure delivery and rollback automation for production platforms.}"
            )

            def fake_chat(system_prompt: str, user_prompt: str, *, mode: str, **kwargs):
                return (
                    "Applying a targeted resume edit.\n\n"
                    "<<<EDIT\n"
                    "OLD:\n"
                    f"{old_block}\n"
                    "NEW:\n"
                    f"{new_block}\n"
                    "EDIT>>>"
                )

            with (
                patch.object(package_chat, "OUTPUT_DIR", output_dir),
                patch.object(package_chat, "SOUL_MD", soul_path),
                patch.object(package_chat._app, "_get_job_context", return_value=None),
                patch.object(package_chat, "_call_package_chat_model", side_effect=fake_chat),
            ):
                result = package_chat.send_chat(
                    "pkg-1",
                    "Update the resume bullet to emphasize delivery and rollback automation.",
                    "resume",
                )

            resume_tex = (pkg / "Conner_Jordan_Resume.tex").read_text(encoding="utf-8")

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "edit")
        self.assertEqual(result["doc_updated"], "resume")
        self.assertIn("Built secure delivery and rollback automation for production platforms.", resume_tex)
        self.assertEqual(result["edits"][0]["match_mode"], "flex_whitespace")


if __name__ == "__main__":
    unittest.main()
