"""Unit tests for lib/progress.py: plain, human-readable status lines to
stdout (e.g. "Op..." then "✓ Op"), and the Phase context manager built on
top of it.

The one thing that MUST hold regardless of formatting is that Phase never
swallows an exception it's reporting -- a silently-eaten exception here
would make a real failure look like a clean run to the caller of
case_brief.py's main().

Run with: python -m unittest discover -s tests -v   (from case-brief/)
      or: python -m pytest tests                     (if pytest is installed)
"""
import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.progress import progress, progress_success, progress_error, Phase


def _captured_lines(fn, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kwargs)
    return [line for line in buf.getvalue().splitlines() if line]


class ProgressFunctionTests(unittest.TestCase):
    def test_running_status_has_no_prefix(self):
        lines = _captured_lines(progress, "Doing a thing")
        self.assertEqual(lines, ["Doing a thing"])

    def test_success_status_is_checkmark_prefixed_and_carries_detail(self):
        lines = _captured_lines(progress_success, "Loaded", "3 items")
        self.assertEqual(lines, ["✓ Loaded -- 3 items"])

    def test_error_status_is_cross_prefixed_and_carries_detail(self):
        lines = _captured_lines(progress_error, "Failed", "connection refused")
        self.assertEqual(lines, ["✗ Failed -- connection refused"])

    def test_empty_detail_omits_the_separator_entirely(self):
        lines = _captured_lines(progress_success, "Loaded")
        self.assertEqual(lines, ["✓ Loaded"])


class PhaseContextManagerTests(unittest.TestCase):
    def test_emits_running_then_success_on_a_clean_exit(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with Phase("Loading demo data"):
                pass
        lines = [l for l in buf.getvalue().splitlines() if l]
        self.assertEqual(lines, ["Loading demo data...", "✓ Loading demo data"])

    def test_emits_running_then_error_with_the_exception_message_on_failure(self):
        buf = io.StringIO()
        with self.assertRaises(ValueError):
            with contextlib.redirect_stdout(buf):
                with Phase("Loading demo data"):
                    raise ValueError("bad data")
        lines = [l for l in buf.getvalue().splitlines() if l]
        self.assertEqual(lines, ["Loading demo data...", "✗ Loading demo data -- bad data"])

    def test_never_swallows_the_original_exception(self):
        # The whole point of __exit__ returning False -- confirm the actual
        # exception (type and identity) propagates out, not just "some"
        # exception, and that it isn't replaced/wrapped along the way.
        sentinel = RuntimeError("sentinel failure")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                with Phase("Some step"):
                    raise sentinel
                self.fail("Phase must not swallow the exception")
            except RuntimeError as caught:
                self.assertIs(caught, sentinel)

    def test_detail_passed_at_construction_appears_on_the_running_line_only(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with Phase("Step", detail="context info"):
                pass
        lines = [l for l in buf.getvalue().splitlines() if l]
        self.assertEqual(lines[0], "Step... -- context info")
        self.assertEqual(lines[1], "✓ Step")  # success line doesn't repeat the entry detail


if __name__ == "__main__":
    unittest.main()
