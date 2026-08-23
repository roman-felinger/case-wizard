"""Unit tests for lib/implementer.py: the prompt-building logic (does the
plan prompt actually include the guide text, case number, and repo
structure -- checked with plain substring assertions since prompt wording
changes often and isn't worth pinning exactly), the claude-call wrapper's
error handling (timeout -> clear message, non-zero exit -> clear message),
step-parsing from Claude's freeform response, and step-application
(create/modify/delete) against a real temporary directory.

subprocess.run is always mocked for the claude CLI call and for the git
diff helper -- no real `claude` process, no real git operations. File
writes from _apply_step land only in tempfile.TemporaryDirectory.

Special focus: `_call_claude` is the single highest-risk regression target
in this whole project -- it is the actual call to the `claude` CLI, whose
output (git/npm/claude commonly emit Unicode) crashes on Windows' default
codepage without `encoding="utf-8", errors="replace"`. A dedicated test
asserts those exact kwargs are still passed.

Deliberately not covered: real Claude output quality/parsing edge cases
beyond the documented FILE/ACTION/DESCRIPTION/code-fence format, and the
full plan-then-steps-then-apply pipeline end-to-end (that needs a real or
recorded `claude` conversation, out of scope for a mocked unit test).

Run with: python -m unittest discover -s tests -v   (from case-solve/)
"""
import os
import subprocess as sp
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.implementer import Change, Implementer


def _workspace(repo_dir):
    return mock.Mock(repo_dir=Path(repo_dir))


def _cfg(agent="case-solver", model=None, timeout=900, extra_args=None):
    return {
        "claude": {
            "agent": agent,
            "model": model,
            "timeout": timeout,
            "extra_args": extra_args or [],
        }
    }


def _completed(returncode=0, stdout="", stderr=""):
    result = mock.Mock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class BuildPlanPromptTests(unittest.TestCase):
    def test_prompt_includes_case_number_guide_text_and_repo_structure(self):
        impl = Implementer(
            workspace=_workspace("/repo"),
            guide_text="## Fix the widget\nDo the thing.",
            case_number="T2611845",
            cfg=_cfg(),
        )
        with mock.patch.object(impl, "_get_repo_structure", return_value="app.py\nlib/"):
            prompt = impl._build_plan_prompt()
        self.assertIn("T2611845", prompt)
        self.assertIn("Do the thing.", prompt)
        self.assertIn("app.py", prompt)
        self.assertIn("lib/", prompt)


class CallClaudeTests(unittest.TestCase):
    def setUp(self):
        self.impl = Implementer(
            workspace=_workspace("/repo"), guide_text="g", case_number="T1", cfg=_cfg()
        )

    def test_success_returns_stdout(self):
        with mock.patch(
            "lib.implementer.subprocess.run", return_value=_completed(stdout="the plan")
        ):
            self.assertEqual(self.impl._call_claude("prompt"), "the plan")

    def test_passes_utf8_encoding_and_replace_errors(self):
        with mock.patch(
            "lib.implementer.subprocess.run", return_value=_completed()
        ) as run:
            self.impl._call_claude("prompt")
        _, kwargs = run.call_args
        self.assertEqual(kwargs.get("encoding"), "utf-8")
        self.assertEqual(kwargs.get("errors"), "replace")
        self.assertTrue(kwargs.get("capture_output"))
        self.assertTrue(kwargs.get("text"))

    def test_timeout_exits_with_a_clear_message(self):
        with mock.patch(
            "lib.implementer.subprocess.run",
            side_effect=sp.TimeoutExpired(cmd="claude", timeout=900),
        ):
            with self.assertRaises(SystemExit) as ctx:
                self.impl._call_claude("prompt")
        self.assertIn("timed out", str(ctx.exception).lower())
        self.assertIn("900", str(ctx.exception))

    def test_nonzero_exit_code_exits_with_stderr_in_message(self):
        with mock.patch(
            "lib.implementer.subprocess.run",
            return_value=_completed(returncode=1, stderr="permission denied"),
        ):
            with self.assertRaises(SystemExit) as ctx:
                self.impl._call_claude("prompt")
        self.assertIn("permission denied", str(ctx.exception))

    def test_includes_configured_agent_and_model_flags(self):
        impl = Implementer(
            workspace=_workspace("/repo"),
            guide_text="g",
            case_number="T1",
            cfg=_cfg(agent="case-solver", model="opus"),
        )
        with mock.patch(
            "lib.implementer.subprocess.run", return_value=_completed()
        ) as run:
            impl._call_claude("prompt")
        cmd = run.call_args[0][0]
        self.assertIn("--agent", cmd)
        self.assertIn("case-solver", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("opus", cmd)

    def test_omits_agent_and_model_flags_when_not_configured(self):
        impl = Implementer(
            workspace=_workspace("/repo"),
            guide_text="g",
            case_number="T1",
            cfg=_cfg(agent=None, model=None),
        )
        with mock.patch(
            "lib.implementer.subprocess.run", return_value=_completed()
        ) as run:
            impl._call_claude("prompt")
        cmd = run.call_args[0][0]
        self.assertNotIn("--agent", cmd)
        self.assertNotIn("--model", cmd)

    def test_appends_extra_args(self):
        impl = Implementer(
            workspace=_workspace("/repo"),
            guide_text="g",
            case_number="T1",
            cfg=_cfg(extra_args=["--verbose", "--foo=bar"]),
        )
        with mock.patch(
            "lib.implementer.subprocess.run", return_value=_completed()
        ) as run:
            impl._call_claude("prompt")
        cmd = run.call_args[0][0]
        self.assertIn("--verbose", cmd)
        self.assertIn("--foo=bar", cmd)

    def test_prompt_is_passed_via_stdin_not_argv(self):
        with mock.patch(
            "lib.implementer.subprocess.run", return_value=_completed()
        ) as run:
            self.impl._call_claude("secret prompt text")
        cmd = run.call_args[0][0]
        _, kwargs = run.call_args
        self.assertNotIn("secret prompt text", cmd)
        self.assertEqual(kwargs.get("input"), "secret prompt text")

    def test_uses_configured_timeout(self):
        impl = Implementer(
            workspace=_workspace("/repo"), guide_text="g", case_number="T1", cfg=_cfg(timeout=42)
        )
        with mock.patch(
            "lib.implementer.subprocess.run", return_value=_completed()
        ) as run:
            impl._call_claude("prompt")
        _, kwargs = run.call_args
        self.assertEqual(kwargs.get("timeout"), 42)


class ParseStepsTests(unittest.TestCase):
    def setUp(self):
        self.impl = Implementer(
            workspace=_workspace("/repo"), guide_text="g", case_number="T1", cfg=_cfg()
        )

    def test_parses_a_single_step(self):
        response = (
            "FILE: src/app.py\n"
            "ACTION: modify\n"
            "DESCRIPTION: fix the bug\n"
            "```\n"
            "print('fixed')\n"
            "```\n"
        )
        steps = self.impl._parse_steps(response)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["file"], "src/app.py")
        self.assertEqual(steps[0]["action"], "modify")
        self.assertEqual(steps[0]["description"], "fix the bug")
        self.assertEqual(steps[0]["content"], "print('fixed')")

    def test_parses_multiple_steps(self):
        response = (
            "FILE: a.py\nACTION: create\nDESCRIPTION: new file\n```\ncontent a\n```\n"
            "FILE: b.py\nACTION: delete\nDESCRIPTION: remove file\n```\n```\n"
        )
        steps = self.impl._parse_steps(response)
        self.assertEqual([s["file"] for s in steps], ["a.py", "b.py"])
        self.assertEqual(steps[0]["content"], "content a")
        self.assertEqual(steps[1]["content"], "")

    def test_ignores_preamble_text_before_first_file_marker(self):
        response = "Here are the steps:\n\nFILE: a.py\nACTION: create\n```\nx\n```\n"
        steps = self.impl._parse_steps(response)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["file"], "a.py")

    def test_empty_response_yields_no_steps(self):
        self.assertEqual(self.impl._parse_steps(""), [])

    def test_step_without_file_marker_is_dropped(self):
        # A stray code block with no FILE: line before it never becomes a step.
        response = "```\norphaned content\n```\n"
        self.assertEqual(self.impl._parse_steps(response), [])


class ApplyStepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.tmp.name)
        self.impl = Implementer(
            workspace=_workspace(self.repo_dir), guide_text="g", case_number="T1", cfg=_cfg()
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_writes_a_new_file_with_content(self):
        with mock.patch.object(self.impl, "_get_file_diff", return_value="(new file)"):
            change = self.impl._apply_step(
                {"file": "new/thing.py", "action": "create", "content": "hello", "description": "d"}
            )
        self.assertEqual((self.repo_dir / "new" / "thing.py").read_text(), "hello")
        self.assertIsInstance(change, Change)
        self.assertEqual(change.file_path, "new/thing.py")

    def test_modify_overwrites_an_existing_file(self):
        existing = self.repo_dir / "app.py"
        existing.write_text("old content")
        with mock.patch.object(self.impl, "_get_file_diff", return_value="diff"):
            self.impl._apply_step(
                {"file": "app.py", "action": "modify", "content": "new content", "description": ""}
            )
        self.assertEqual(existing.read_text(), "new content")

    def test_modify_on_a_nonexistent_file_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.impl._apply_step(
                {"file": "missing.py", "action": "modify", "content": "x", "description": ""}
            )

    def test_delete_removes_an_existing_file(self):
        existing = self.repo_dir / "old.py"
        existing.write_text("bye")
        with mock.patch.object(self.impl, "_get_file_diff", return_value="(deleted)"):
            self.impl._apply_step({"file": "old.py", "action": "delete", "content": "", "description": ""})
        self.assertFalse(existing.exists())

    def test_delete_on_a_nonexistent_file_does_not_raise(self):
        with mock.patch.object(self.impl, "_get_file_diff", return_value="(deleted)"):
            self.impl._apply_step({"file": "never-existed.py", "action": "delete", "content": "", "description": ""})
        # No exception -- the delete branch checks .exists() before unlinking.


class GetFileDiffTests(unittest.TestCase):
    def test_passes_utf8_encoding_and_replace_errors(self):
        impl = Implementer(workspace=_workspace("/repo"), guide_text="g", case_number="T1", cfg=_cfg())
        with mock.patch(
            "lib.implementer.subprocess.run", return_value=_completed(stdout="diff text")
        ) as run:
            diff = impl._get_file_diff("a.py")
        self.assertEqual(diff, "diff text")
        _, kwargs = run.call_args
        self.assertEqual(kwargs.get("encoding"), "utf-8")
        self.assertEqual(kwargs.get("errors"), "replace")


class GetRepoStructureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.tmp.name)
        self.impl = Implementer(workspace=_workspace(self.repo_dir), guide_text="g", case_number="T1", cfg=_cfg())

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_files_and_directories(self):
        (self.repo_dir / "app.py").write_text("")
        (self.repo_dir / "lib").mkdir()
        (self.repo_dir / "lib" / "helper.py").write_text("")
        structure = self.impl._get_repo_structure()
        self.assertIn("app.py", structure)
        self.assertIn("lib/", structure)
        self.assertIn("helper.py", structure)

    def test_skips_hidden_files_and_directories(self):
        (self.repo_dir / ".git").mkdir()
        (self.repo_dir / ".git" / "config").write_text("")
        (self.repo_dir / ".hidden_file").write_text("")
        (self.repo_dir / "visible.py").write_text("")
        structure = self.impl._get_repo_structure()
        self.assertNotIn(".git", structure)
        self.assertNotIn(".hidden_file", structure)
        self.assertIn("visible.py", structure)


if __name__ == "__main__":
    unittest.main()
