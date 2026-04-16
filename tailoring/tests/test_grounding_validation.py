import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tailor.selector import SelectedJob
from tailor.validator import ResumeFitMetrics, validate_cover_letter, validate_resume
from tailor.writer import write_cover_letter, write_resume


class TestGroundingValidation(unittest.TestCase):
    def test_validate_resume_rejects_role_rename_and_unsupported_claims(self):
        tex = r"""
\documentclass{article}
\begin{document}
\section{PROFESSIONAL SUMMARY}
Builder using Terraform and zero-trust rollout patterns.
\section{TECHNICAL SKILLS}
\textbf{Languages:} Python, C, C++, TypeScript, Java, SQL, PowerShell, Bash, Swift, Rust, Go
\textbf{Security Tooling:} CrowdStrike RTR
\textbf{AI/ML and Research:} RAG pipelines
\textbf{Frameworks and Infrastructure:} Flask
\textbf{DevOps and CI/CD:} CI/CD pipelines
\textbf{Databases:} PostgreSQL, MySQL, MongoDB, DynamoDB, SQLite, Redis, Snowflake, ClickHouse, Databricks, vector databases
\section{WORK EXPERIENCE}
\resumeSubheading{University of California, Office of the President}{Oakland, CA (Remote)}{Applied AI Engineer}{March 2025 - Present}
\resumeItem{Built a RAG chatbot on AWS Lambda with Step Functions and SNS for latency constraints.}
\resumeSubheading{Great Wolf Resorts}{Chicago Corporate Office (Remote)}{Security Support Engineer}{May 2023 - March 2025}
\resumeItem{Used rollback and idempotent Terraform workflows.}
\resumeSubheading{Simple.biz}{Durham, NC (Remote)}{Freelance Web Developer}{August 2022 - May 2023}
\resumeItem{Built secure apps.}
\section{EDUCATION}
CS
\section{CERTIFICATIONS}
AWS
\end{document}
"""
        with tempfile.TemporaryDirectory() as td:
            tex_path = Path(td) / "Conner_Jordan_Resume.tex"
            tex_path.write_text(tex, encoding="utf-8")
            with (
                patch("tailor.validator.compile_tex", return_value=tex_path.with_suffix(".pdf")),
                patch("tailor.validator.inspect_resume_pdf_fit", return_value=ResumeFitMetrics(page_count=1, page_fill_ratio=0.9, render_inspection_ok=True)),
            ):
                result = validate_resume(tex_path)

        self.assertFalse(result.passed)
        categories = {item["category"] for item in result.failure_details}
        self.assertIn("role_title_renamed", categories)
        self.assertIn("unsupported_tool_claim", categories)
        self.assertIn("unsupported_identity_stack_claim", categories)
        self.assertIn("unsupported_ai_deployment_claim", categories)
        self.assertIn("unsupported_operational_mechanic_claim", categories)

    def test_validate_cover_rejects_company_rendering_and_compliance_drift(self):
        tex = r"""
\documentclass{article}
\newcommand{\companyname}{tdsynnex}
\begin{document}
Hiring Manager\\
\companyname

I built a SOC 2-aligned RAG chatbot on AWS Lambda.
\end{document}
"""
        with tempfile.TemporaryDirectory() as td:
            tex_path = Path(td) / "Conner_Jordan_Cover_Letter.tex"
            tex_path.write_text(tex, encoding="utf-8")
            (Path(td) / "analysis.json").write_text(json.dumps({"company_name": "TD SYNNEX"}), encoding="utf-8")
            with patch("tailor.validator.compile_tex", return_value=tex_path.with_suffix(".pdf")):
                result = validate_cover_letter(tex_path)

        self.assertFalse(result.passed)
        categories = {item["category"] for item in result.failure_details}
        self.assertIn("unsupported_compliance_claim", categories)
        self.assertIn("unsupported_ai_deployment_claim", categories)
        self.assertIn("company_name_rendering_issue", categories)

    def test_writer_persists_grounding_artifacts(self):
        job = SelectedJob(
            id=1,
            url="https://example.com/job/1",
            title="Role",
            board="lever",
            seniority="mid",
            jd_text="desc",
            snippet="",
            company="example",
        )
        analysis = {
            "role_title": "Role",
            "company_name": "Example",
            "summary_angle": "angle",
            "tone_notes": "tone",
            "company_context": {"company_type": "other"},
            "requirements": [],
        }

        baseline_skills = {
            "Languages": ["Python", "SQL"],
            "Security Tooling": ["Splunk"],
            "AI/ML and Research": ["RAG pipelines"],
            "Frameworks and Infrastructure": ["Flask"],
            "DevOps and CI/CD": ["CI/CD pipelines"],
            "Databases": ["PostgreSQL"],
        }

        def fake_chat(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            from tailor import config as cfg
            if (trace or {}).get("doc_type") == "resume":
                return Path(cfg.RESUME_TEX).read_text(encoding="utf-8")
            return Path(cfg.COVER_TEX).read_text(encoding="utf-8")

        def fake_chat_expect_json(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            doc = (trace or {}).get("doc_type")
            phase = (trace or {}).get("phase")
            if doc == "resume" and phase == "strategy":
                return {"summary_strategy": "x", "skills_tailoring": {}, "experience_rewrites": [], "risk_controls": []}
            if doc == "resume":
                return {
                    "summary": "Security engineer building reliable systems.",
                    "skills": baseline_skills,
                    "experience": {
                        "University of California, Office of the President": ["a", "b", "c", "d", "e", "f"],
                        "Great Wolf Resorts": ["a", "b", "c", "d", "e"],
                        "Simple.biz": ["a", "b", "c"],
                    },
                }
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
            patch("tailor.writer.compile_tex", side_effect=lambda tex_path: tex_path.with_suffix(".pdf")),
            patch("tailor.writer.inspect_resume_pdf_fit", return_value=ResumeFitMetrics(page_count=1, page_fill_ratio=0.9, render_inspection_ok=True)),
        ):
            out = Path(td)
            write_resume(job, analysis, out, attempt=1)
            write_cover_letter(job, analysis, out, attempt=1)
            self.assertTrue((out / "grounding.json").exists())
            self.assertTrue((out / "grounding_audit.json").exists())


    def test_humanize_prompt_contains_key_patterns(self):
        from tailor.writer import _COVER_HUMANIZE_SYSTEM

        for word in ["delve", "leverage", "robust", "utilize", "seamless"]:
            self.assertIn(word, _COVER_HUMANIZE_SYSTEM, f"Tier 1 word '{word}' missing from humanize prompt")
        for phrase in ["serves as", "TIER 2", "TIER 3", "PRESERVE"]:
            self.assertIn(phrase, _COVER_HUMANIZE_SYSTEM, f"'{phrase}' missing from humanize prompt")

    def test_humanize_stage_emits_pre_humanize_artifact(self):
        job = SelectedJob(
            id=1,
            url="https://example.com/job/1",
            title="Role",
            board="lever",
            seniority="mid",
            jd_text="desc",
            snippet="",
            company="example",
        )
        analysis = {
            "role_title": "Role",
            "company_name": "Example",
            "summary_angle": "angle",
            "tone_notes": "tone",
            "company_context": {"company_type": "other"},
            "requirements": [],
        }

        def fake_chat(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
            from tailor import config as cfg
            return Path(cfg.COVER_TEX).read_text(encoding="utf-8")

        def fake_chat_expect_json(system_prompt, user_prompt, max_tokens=0, temperature=0.0, trace=None, trace_recorder=None, **kwargs):
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
            write_cover_letter(job, analysis, out, attempt=1)
            self.assertTrue(
                (out / "cover_pre_humanize.tex").exists(),
                "cover_pre_humanize.tex artifact not emitted",
            )
            # Both files should contain valid LaTeX
            pre = (out / "cover_pre_humanize.tex").read_text()
            final = (out / "Conner_Jordan_Cover_Letter.tex").read_text()
            self.assertIn("\\begin{document}", pre)
            self.assertIn("\\begin{document}", final)


if __name__ == "__main__":
    unittest.main()
