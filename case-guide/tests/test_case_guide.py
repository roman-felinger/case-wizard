"""Unit tests for case_guide.py's security/correctness-sensitive pure-logic
pieces: the case-number sanitizer, the brief-lookup traversal guard and
ambiguous-match safety, and the config-comment stripper. Deliberately not
exhaustive over every formatting/rendering branch -- those are low-risk and
easy to eyeball with --show-prompt; this file locks in the handful of things
that would otherwise fail silently and dangerously (path traversal, a wrong
guess presented as certain, a stray `_comment` leaking into a request dict).

Run with: python -m unittest discover -s tests   (from case-guide/)
      or: python -m pytest tests                 (if pytest is installed)
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import case_guide as cg


class SanitizeCaseNumberTests(unittest.TestCase):
    def test_strips_path_separators_and_dots(self):
        self.assertEqual(cg._sanitize_case_number("../../../etc/T123"), "......etcT123")

    def test_leaves_a_normal_case_number_untouched(self):
        self.assertEqual(cg._sanitize_case_number("T2611845"), "T2611845")

    def test_dots_and_dashes_are_kept(self):
        self.assertEqual(cg._sanitize_case_number("T26-11.845"), "T26-11.845")


class FindBriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.brief_dir = self.tmp.name
        open(os.path.join(self.brief_dir, "case-T111.md"), "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_match(self):
        path = cg.find_brief(self.brief_dir, "T111")
        self.assertEqual(os.path.basename(path), "case-T111.md")

    def test_ambiguous_match_exits_rather_than_guessing(self):
        open(os.path.join(self.brief_dir, "case-T3330.md"), "w").close()
        open(os.path.join(self.brief_dir, "case-T3331.md"), "w").close()
        with self.assertRaises(SystemExit):
            cg.find_brief(self.brief_dir, "T333")

    def test_traversal_attempt_is_blocked(self):
        # A case number crafted to escape brief_dir must not resolve to
        # anything outside it, even if a same-named file exists elsewhere.
        outside = tempfile.NamedTemporaryFile(suffix=".md", delete=False)
        outside.close()
        try:
            case_number = "../" * 6 + os.path.splitext(os.path.basename(outside.name))[0]
            self.assertIsNone(cg.find_brief(self.brief_dir, case_number))
        finally:
            os.unlink(outside.name)


class FindExampleGuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, text, mtime_offset=0):
        path = os.path.join(self.output_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        if mtime_offset:
            stat = os.stat(path)
            os.utime(path, (stat.st_atime, stat.st_mtime + mtime_offset))
        return path

    def test_none_on_first_guide_ever(self):
        self._write("case-T1-for-dummies.md", "current case's own leftover, if any")
        result = cg.find_example_guide(self.output_dir, "case-T1-for-dummies.md")
        self.assertIsNone(result)

    def test_none_when_output_dir_does_not_exist_yet(self):
        result = cg.find_example_guide(os.path.join(self.output_dir, "missing"), "case-T1-for-dummies.md")
        self.assertIsNone(result)

    def test_picks_most_recent_excluding_current_case(self):
        self._write("case-T1-for-dummies.md", "older", mtime_offset=-100)
        self._write("case-T2-for-dummies.md", "newest", mtime_offset=0)
        self._write("case-T3-for-dummies.md", "current run's own target", mtime_offset=100)
        result = cg.find_example_guide(self.output_dir, "case-T3-for-dummies.md")
        self.assertEqual(result, "newest")

    def test_count_joins_multiple_most_recent(self):
        self._write("case-T1-for-dummies.md", "oldest", mtime_offset=-200)
        self._write("case-T2-for-dummies.md", "middle", mtime_offset=-100)
        self._write("case-T3-for-dummies.md", "newest", mtime_offset=0)
        result = cg.find_example_guide(self.output_dir, "case-T4-for-dummies.md", count=2)
        self.assertEqual(result, "newest\n\n---\n\nmiddle")

    def test_zero_count_disables(self):
        self._write("case-T1-for-dummies.md", "irrelevant")
        result = cg.find_example_guide(self.output_dir, "case-T2-for-dummies.md", count=0)
        self.assertIsNone(result)


class StripCommentsTests(unittest.TestCase):
    def test_removes_any_underscore_prefixed_key(self):
        cfg = {
            "_comment": "top",
            "azure_devops": {"_comment": "x", "_other_meta": "y", "org_url": None},
            "claude": {"_comment": "z"},
        }
        cleaned = cg._strip_comments(cfg)
        self.assertNotIn("_comment", cleaned)
        self.assertNotIn("_comment", cleaned["azure_devops"])
        self.assertNotIn("_other_meta", cleaned["azure_devops"])
        self.assertEqual(cleaned["azure_devops"]["org_url"], None)


if __name__ == "__main__":
    unittest.main()
