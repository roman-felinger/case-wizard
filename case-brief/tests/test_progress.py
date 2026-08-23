"""Unit tests for lib/progress.py, the newest module here: a thin JSON-lines
progress protocol that case-wizard's Streamlit app parses line-by-line from
this subprocess's stdout to drive a live progress display.

The correctness bar for this module is narrow but important precisely
because the consumer is another program, not a human: every line MUST be
valid, single-line JSON with exactly the {"operation", "status", "detail"}
shape the app expects, and the `Phase` context manager MUST NOT swallow an
exception it's reporting -- a silently-eaten exception here would make a
real failure look like a clean run to both the app and the caller of
case_brief.py's main(). Not covered: the Streamlit-side consumer
(app/progress.py) itself, which lives outside this project and needs a real
Streamlit run to exercise meaningfully.

Run with: python -m unittest discover -s tests -v   (from case-brief/)
      or: python -m pytest tests                     (if pytest is installed)
"""
import contextlib
import io
import json
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
    def test_progress_prints_one_line_of_valid_json_with_the_expected_shape(self):
        lines = _captured_lines(progress, "Doing a thing")
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(set(payload.keys()), {"operation", "status", "detail"})
        self.assertEqual(payload["operation"], "Doing a thing")
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["detail"], "")

    def test_progress_success_sets_status_and_carries_the_detail_through(self):
        lines = _captured_lines(progress_success, "Loaded", "3 items")
        payload = json.loads(lines[0])
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["detail"], "3 items")

    def test_progress_error_sets_status_error(self):
        lines = _captured_lines(progress_error, "Failed", "connection refused")
        payload = json.loads(lines[0])
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["detail"], "connection refused")

    def test_a_message_containing_special_characters_still_round_trips_as_json(self):
        # Quotes/newlines/unicode in a detail string must not corrupt the
        # line's JSON structure -- json.dumps handles this, but it's worth
        # locking in given the consumer parses stdout line-by-line.
        lines = _captured_lines(progress, "op", detail='has "quotes", a\nnewline, and é')
        self.assertEqual(len(lines), 1)  # still exactly one line despite the embedded newline
        payload = json.loads(lines[0])
        self.assertEqual(payload["detail"], 'has "quotes", a\nnewline, and é')


class PhaseContextManagerTests(unittest.TestCase):
    def test_emits_running_then_success_on_a_clean_exit(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with Phase("Loading demo data"):
                pass
        lines = [json.loads(l) for l in buf.getvalue().splitlines() if l]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], {"operation": "Loading demo data...", "status": "running", "detail": ""})
        self.assertEqual(lines[1], {"operation": "Loading demo data", "status": "success", "detail": ""})

    def test_emits_running_then_error_with_the_exception_message_on_failure(self):
        buf = io.StringIO()
        with self.assertRaises(ValueError):
            with contextlib.redirect_stdout(buf):
                with Phase("Loading demo data"):
                    raise ValueError("bad data")
        lines = [json.loads(l) for l in buf.getvalue().splitlines() if l]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["status"], "running")
        self.assertEqual(lines[1], {"operation": "Loading demo data", "status": "error", "detail": "bad data"})

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
        lines = [json.loads(l) for l in buf.getvalue().splitlines() if l]
        self.assertEqual(lines[0]["detail"], "context info")
        self.assertEqual(lines[1]["detail"], "")  # success line doesn't repeat the entry detail


if __name__ == "__main__":
    unittest.main()
