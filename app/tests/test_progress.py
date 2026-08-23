"""Unit tests for progress.py's pure-logic pieces: ProgressMessage/
format_progress_line's rendering, and stream_subprocess_output's
JSON-parsing fallback.

Scope: `subprocess.Popen` is entirely mocked in every stream_subprocess_output
test -- no real process is ever spawned. Streamlit itself (`st.spinner`) is
imported by progress.py at module level; `st.spinner` is a no-op-safe
context manager even outside a real Streamlit script run (it just renders
nothing when there's no active ScriptRunContext), so it's left real rather
than mocked -- but stream_subprocess_output's actual subprocess plumbing is
always mocked regardless.

Deliberately skipped: ProgressReporter and show_progress_stream both push
content through `st.container`/`st.markdown`/`st.empty` -- that's
Streamlit UI rendering, not logic, and is out of scope for this suite (see
the task's main.py scope note). agent_available/get_available_agents are
thin subprocess wrappers with no branching worth locking in beyond what
check_claude/check_git already demonstrate in test_checks.py.

Run with: python -m unittest discover -s tests -v   (from app/)
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

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


class LogProgressTests(unittest.TestCase):
    def test_builds_a_progress_message_with_the_given_fields(self):
        msg = progress.log_progress("case-brief", "Extracting context", "running", detail="step 1", progress_pct=10)
        self.assertEqual(msg.agent, "case-brief")
        self.assertEqual(msg.operation, "Extracting context")
        self.assertEqual(msg.status, "running")
        self.assertEqual(msg.detail, "step 1")
        self.assertEqual(msg.progress_pct, 10)


def _make_fake_process(stdout_lines, returncode=0, wait_raises=None):
    """A stand-in for subprocess.Popen's return value: stdout.readline()
    yields each line in turn then "" (EOF), matching the `iter(readline, "")`
    pattern stream_subprocess_output uses."""
    process = mock.Mock()
    lines = iter(stdout_lines + [""])
    process.stdout.readline.side_effect = lambda: next(lines)
    if wait_raises:
        process.wait.side_effect = wait_raises
    else:
        process.wait.return_value = returncode
    process.kill = mock.Mock()
    return process


class StreamSubprocessOutputTests(unittest.TestCase):
    def test_valid_progress_json_passes_through_unchanged(self):
        line = json.dumps({"operation": "Step 1", "status": "running", "detail": "working"})
        fake_process = _make_fake_process([line + "\n"])
        with mock.patch.object(progress.subprocess, "Popen", return_value=fake_process):
            results = list(progress.stream_subprocess_output(["cmd"], Path("."), "agent"))
        self.assertEqual(len(results), 1)
        self.assertEqual(json.loads(results[0]), {"operation": "Step 1", "status": "running", "detail": "working"})

    def test_json_missing_required_keys_is_wrapped_as_output_info(self):
        line = json.dumps({"detail": "no operation or status key"})
        fake_process = _make_fake_process([line + "\n"])
        with mock.patch.object(progress.subprocess, "Popen", return_value=fake_process):
            results = list(progress.stream_subprocess_output(["cmd"], Path("."), "agent"))
        self.assertEqual(len(results), 1)
        parsed = json.loads(results[0])
        self.assertEqual(parsed["operation"], "Output")
        self.assertEqual(parsed["status"], "info")
        self.assertEqual(parsed["detail"], line)

    def test_invalid_json_is_wrapped_as_output_info(self):
        fake_process = _make_fake_process(["not json at all\n"])
        with mock.patch.object(progress.subprocess, "Popen", return_value=fake_process):
            results = list(progress.stream_subprocess_output(["cmd"], Path("."), "agent"))
        self.assertEqual(len(results), 1)
        parsed = json.loads(results[0])
        self.assertEqual(parsed["operation"], "Output")
        self.assertEqual(parsed["status"], "info")
        self.assertEqual(parsed["detail"], "not json at all")

    def test_blank_lines_are_skipped(self):
        fake_process = _make_fake_process(["\n", "   \n", json.dumps({"operation": "X", "status": "running"}) + "\n"])
        with mock.patch.object(progress.subprocess, "Popen", return_value=fake_process):
            results = list(progress.stream_subprocess_output(["cmd"], Path("."), "agent"))
        self.assertEqual(len(results), 1)

    def test_nonzero_return_code_yields_a_final_error_message(self):
        fake_process = _make_fake_process([], returncode=1)
        with mock.patch.object(progress.subprocess, "Popen", return_value=fake_process):
            results = list(progress.stream_subprocess_output(["cmd"], Path("."), "agent"))
        self.assertEqual(len(results), 1)
        parsed = json.loads(results[0])
        self.assertEqual(parsed["status"], "error")
        self.assertIn("Exit code 1", parsed["detail"])

    def test_zero_return_code_yields_no_extra_message(self):
        fake_process = _make_fake_process([], returncode=0)
        with mock.patch.object(progress.subprocess, "Popen", return_value=fake_process):
            results = list(progress.stream_subprocess_output(["cmd"], Path("."), "agent"))
        self.assertEqual(results, [])

    def test_timeout_kills_the_process_and_yields_a_timeout_error_message(self):
        fake_process = _make_fake_process([], wait_raises=subprocess.TimeoutExpired(cmd=["cmd"], timeout=600))
        with mock.patch.object(progress.subprocess, "Popen", return_value=fake_process):
            results = list(progress.stream_subprocess_output(["cmd"], Path("."), "agent", timeout=600))
        fake_process.kill.assert_called_once()
        self.assertEqual(len(results), 1)
        parsed = json.loads(results[0])
        self.assertEqual(parsed["status"], "error")
        self.assertIn("timeout", parsed["operation"])
        self.assertIn("600s", parsed["detail"])

    def test_popen_raising_yields_a_generic_error_message_instead_of_propagating(self):
        with mock.patch.object(progress.subprocess, "Popen", side_effect=OSError("cannot launch")):
            results = list(progress.stream_subprocess_output(["cmd"], Path("."), "agent"))
        self.assertEqual(len(results), 1)
        parsed = json.loads(results[0])
        self.assertEqual(parsed["status"], "error")
        self.assertIn("cannot launch", parsed["detail"])

    def test_env_is_forwarded_to_popen(self):
        fake_process = _make_fake_process([])
        custom_env = {"AZDO_PAT": "secret"}
        with mock.patch.object(progress.subprocess, "Popen", return_value=fake_process) as popen:
            list(progress.stream_subprocess_output(["cmd"], Path("."), "agent", env=custom_env))
        _, kwargs = popen.call_args
        self.assertEqual(kwargs["env"], custom_env)


if __name__ == "__main__":
    unittest.main()
