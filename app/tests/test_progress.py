"""Unit tests for progress.py's pure-logic piece: format_progress_line's
rendering of a ProgressMessage into a status-emoji-prefixed line.

ProgressReporter itself pushes content through `st.container`/`st.markdown`/
`st.empty` -- that's Streamlit UI rendering, not logic, and is out of scope
for this suite (see the task's main.py scope note).

Run with: python -m unittest discover -s tests -v   (from app/)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import progress


class FormatProgressLineTests(unittest.TestCase):
    def test_running_status_gets_the_running_emoji(self):
        msg = progress.ProgressMessage(timestamp="t", agent="a", operation="Doing thing", status="running", detail="")
        line = progress.format_progress_line(msg)
        self.assertTrue(line.startswith("📍"))
        self.assertIn("Doing thing", line)

    def test_success_status_gets_the_success_emoji(self):
        msg = progress.ProgressMessage(timestamp="t", agent="a", operation="Done", status="success", detail="")
        self.assertTrue(progress.format_progress_line(msg).startswith("✅"))

    def test_error_status_gets_the_error_emoji(self):
        msg = progress.ProgressMessage(timestamp="t", agent="a", operation="Broke", status="error", detail="")
        self.assertTrue(progress.format_progress_line(msg).startswith("❌"))

    def test_warning_status_gets_the_warning_emoji(self):
        msg = progress.ProgressMessage(timestamp="t", agent="a", operation="Careful", status="warning", detail="")
        self.assertTrue(progress.format_progress_line(msg).startswith("⚠️"))

    def test_unrecognized_status_falls_back_to_info_emoji(self):
        msg = progress.ProgressMessage(timestamp="t", agent="a", operation="?", status="mystery", detail="")
        self.assertTrue(progress.format_progress_line(msg).startswith("ℹ️"))

    def test_detail_is_appended_on_its_own_line_when_present(self):
        msg = progress.ProgressMessage(timestamp="t", agent="a", operation="Op", status="running", detail="extra info")
        line = progress.format_progress_line(msg)
        self.assertIn("\n  extra info", line)

    def test_detail_is_omitted_when_empty(self):
        msg = progress.ProgressMessage(timestamp="t", agent="a", operation="Op", status="running", detail="")
        line = progress.format_progress_line(msg)
        self.assertNotIn("\n", line)

    def test_progress_pct_is_appended_in_parentheses_when_present(self):
        msg = progress.ProgressMessage(timestamp="t", agent="a", operation="Op", status="running", detail="", progress_pct=42)
        line = progress.format_progress_line(msg)
        self.assertIn("(42%)", line)

    def test_progress_pct_omitted_when_none(self):
        msg = progress.ProgressMessage(timestamp="t", agent="a", operation="Op", status="running", detail="", progress_pct=None)
        line = progress.format_progress_line(msg)
        self.assertNotIn("%", line)

    def test_progress_pct_zero_is_still_shown_not_treated_as_falsy(self):
        msg = progress.ProgressMessage(timestamp="t", agent="a", operation="Op", status="running", detail="", progress_pct=0)
        line = progress.format_progress_line(msg)
        self.assertIn("(0%)", line)


if __name__ == "__main__":
    unittest.main()
