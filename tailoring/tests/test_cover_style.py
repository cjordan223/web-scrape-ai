import tempfile
import unittest
from pathlib import Path

from tailor import config as cfg
from tailor.cover_style import (
    COVER_STYLE_RULE_PROMPT,
    audit_cover_letter_paths,
    audit_cover_style_text,
    lint_cover_source_paths,
)


class TestCoverStyleAudit(unittest.TestCase):
    def test_known_bad_cover_patterns_are_reported_with_sentences(self):
        text = (
            "I don't just build APIs; I build trust. "
            "I didn't just write runbooks, I walked teams through the tradeoffs. "
            "This is not just speed, but control. "
            "That same mindset shaped how I approach identity work. "
            "I learned that reliability starts with boring interfaces. "
            "I've learned that security only works when people use it."
        )

        findings = audit_cover_style_text(text)

        families = {finding["family"] for finding in findings}
        self.assertIn("i_dont_just", families)
        self.assertIn("not_just_but", families)
        self.assertIn("same_mindset", families)
        self.assertIn("lesson_closer", families)
        self.assertEqual(
            len([finding for finding in findings if finding["family"] == "i_dont_just"]),
            2,
        )
        self.assertEqual(
            len([finding for finding in findings if finding["family"] == "lesson_closer"]),
            2,
        )
        self.assertTrue(all(finding["matched_text"] for finding in findings))

    def test_clean_cover_letter_has_no_banned_pattern_hits(self):
        text = (
            "I build security tools by starting with the operational failure mode. "
            "For identity-heavy systems, that means making ownership and recovery paths explicit. "
            "That approach fits teams that need reliable controls without slowing delivery."
        )

        self.assertEqual(audit_cover_style_text(text), [])

    def test_audit_cover_letter_paths_reports_counts_per_letter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clean = root / "clean"
            bad = root / "bad"
            clean.mkdir()
            bad.mkdir()
            (clean / "Conner_Jordan_Cover_Letter.tex").write_text(
                r"\begin{document}I build reliable security tools.\end{document}",
                encoding="utf-8",
            )
            (bad / "Conner_Jordan_Cover_Letter.tex").write_text(
                r"\begin{document}This is not just coverage, but confidence.\end{document}",
                encoding="utf-8",
            )

            report = audit_cover_letter_paths([root])

        by_path = {Path(item["path"]).parent.name: item for item in report["letters"]}
        self.assertEqual(by_path["clean"]["total_hits"], 0)
        self.assertEqual(by_path["bad"]["total_hits"], 1)
        self.assertEqual(report["total_hits"], 1)

    def test_real_cover_source_corpus_has_no_banned_style_patterns(self):
        findings = lint_cover_source_paths([cfg.PERSONA_DIR, cfg.SOUL_MD])

        self.assertEqual(findings, [])

    def test_prompt_rule_text_uses_hard_bans_not_soft_caps(self):
        self.assertIn("BANNED", COVER_STYLE_RULE_PROMPT)
        self.assertIn("zero occurrences", COVER_STYLE_RULE_PROMPT)
        self.assertNotIn("at most ONE", COVER_STYLE_RULE_PROMPT)


if __name__ == "__main__":
    unittest.main()
