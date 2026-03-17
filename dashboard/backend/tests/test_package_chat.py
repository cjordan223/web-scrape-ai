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

            def fake_chat(system_prompt: str, user_prompt: str, *, mode: str):
                captured["system_prompt"] = system_prompt
                captured["user_prompt"] = user_prompt
                captured["mode"] = mode
                return "Primary answer:\nI am excited to apply because I like building reliable systems."

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
        self.assertIn("APPLICATION QUESTION MODE", captured["system_prompt"])
        self.assertIn("CURRENT COVER LETTER CONTENT", captured["system_prompt"])
        self.assertNotIn("CURRENT COVER LATEX", captured["system_prompt"])
        self.assertEqual(captured["mode"], "application_answer")

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

            def fake_chat(system_prompt: str, user_prompt: str, *, mode: str):
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

            def fake_chat(system_prompt: str, user_prompt: str, *, mode: str):
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
