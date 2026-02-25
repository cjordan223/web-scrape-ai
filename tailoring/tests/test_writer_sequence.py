import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tailor.selector import SelectedJob
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
            if phase == "strategy":
                if doc == "resume":
                    return '{"summary_strategy":"x","skills_strategy":"y","experience_focus":[],"risk_controls":[]}'
                return '{"opening_angle":"x","paragraph_focus":[],"voice_controls":[],"claims_to_avoid":[]}'

            # Return a valid full LaTeX doc
            if doc == "resume":
                from tailor import config as cfg
                return Path(cfg.RESUME_TEX).read_text(encoding="utf-8")
            from tailor import config as cfg
            return Path(cfg.COVER_TEX).read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as td, patch("tailor.writer.chat", side_effect=fake_chat):
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


if __name__ == "__main__":
    unittest.main()
