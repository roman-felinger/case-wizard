"""Unit tests for lib/committer.py: the logical grouping of changed files
into commit categories (Tests/Configuration/Documentation/Dependencies/
Source Code/Other), commit-message formatting, hash extraction from git's
porcelain-ish output, and the subprocess wrapper's error handling.

All git operations are mocked -- no real repository, no real commits.

**Bugs found while writing these tests, since fixed** (see
CommitterGroupingBugTests / DictShapedChangeBugTests below, which now lock
in the corrected behavior as regression tests):

1. `_group_changes` used to check categories in an order where
   Documentation's `.txt` and Configuration's `.json` branches came before
   the Dependencies branch, so `requirements.txt`/`package.json` could never
   actually reach "Dependencies" despite being explicitly listed there.
   Fixed by moving the dependency-manifest check before the generic
   extension checks.
2. The `isinstance(change, dict)` branch did `change.file_path` (attribute
   access) instead of `change["file_path"]` -- both ternary branches were
   identical, so a dict-shaped change raised AttributeError despite the
   isinstance check implying dicts were supported. Fixed (same bug, same
   fix, also existed in lib/report.py).

Run with: python -m unittest discover -s tests -v   (from case-solve/)
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.committer import Commit, Committer


def _change(file_path):
    return mock.Mock(file_path=file_path)


def _workspace(case_number="T1", repo_dir="/repo"):
    return mock.Mock(case_number=case_number, repo_dir=Path(repo_dir))


class GroupChangesTests(unittest.TestCase):
    def setUp(self):
        self.committer = Committer(workspace=_workspace())

    def test_test_files_are_grouped_as_tests(self):
        groups = self.committer._group_changes([_change("tests/test_foo.py")])
        self.assertEqual(groups["Tests"], ["tests/test_foo.py"])

    def test_yaml_and_json_config_files_are_grouped_as_configuration(self):
        groups = self.committer._group_changes(
            [_change("config/settings.yaml"), _change("app.config")]
        )
        self.assertEqual(groups["Configuration"], ["config/settings.yaml", "app.config"])

    def test_markdown_is_grouped_as_documentation(self):
        groups = self.committer._group_changes([_change("README.md")])
        self.assertEqual(groups["Documentation"], ["README.md"])

    def test_source_extensions_are_grouped_as_source_code(self):
        groups = self.committer._group_changes(
            [_change("src/main.py"), _change("src/app.ts"), _change("src/lib.rs")]
        )
        self.assertEqual(
            groups["Source Code"], ["src/main.py", "src/app.ts", "src/lib.rs"]
        )

    def test_unrecognized_extension_is_grouped_as_other(self):
        groups = self.committer._group_changes([_change("data.bin")])
        self.assertEqual(groups["Other"], ["data.bin"])

    def test_test_substring_check_wins_over_source_extension(self):
        # "test" anywhere in the path takes priority over the .py extension.
        groups = self.committer._group_changes([_change("src/test_helpers.py")])
        self.assertEqual(groups["Tests"], ["src/test_helpers.py"])
        self.assertEqual(groups["Source Code"], [])

    def test_cargo_toml_and_csproj_do_reach_the_dependencies_bucket(self):
        # These two extensions aren't shadowed by an earlier elif branch,
        # so they behave as documented.
        groups = self.committer._group_changes(
            [_change("Cargo.toml"), _change("src/App.csproj")]
        )
        self.assertEqual(groups["Dependencies"], ["Cargo.toml", "src/App.csproj"])

    def test_empty_change_list_yields_all_empty_groups(self):
        groups = self.committer._group_changes([])
        self.assertTrue(all(files == [] for files in groups.values()))


class CommitterGroupingBugTests(unittest.TestCase):
    """Regression test for the requirements.txt/package.json
    misclassification bug described in this file's module docstring - now
    fixed in lib/committer.py's _group_changes."""

    def setUp(self):
        self.committer = Committer(workspace=_workspace())

    def test_requirements_txt_and_package_json_are_dependencies(self):
        groups = self.committer._group_changes(
            [_change("requirements.txt"), _change("package.json")]
        )
        self.assertEqual(groups["Dependencies"], ["requirements.txt", "package.json"])
        self.assertEqual(groups["Documentation"], [])
        self.assertEqual(groups["Configuration"], [])


class DictShapedChangeBugTests(unittest.TestCase):
    """Regression test for module docstring bug #2: a dict-shaped change
    must be read via change["file_path"], not change.file_path - now fixed
    in lib/committer.py's _group_changes."""

    def setUp(self):
        self.committer = Committer(workspace=_workspace())

    def test_dict_change_is_grouped_normally(self):
        change_dict = {"file_path": "src/thing.py"}
        groups = self.committer._group_changes([change_dict])
        self.assertEqual(groups["Source Code"], ["src/thing.py"])


class BuildCommitMessageTests(unittest.TestCase):
    def setUp(self):
        self.committer = Committer(workspace=_workspace(case_number="T2611845"))

    def test_message_includes_case_number_and_group_name(self):
        message = self.committer._build_commit_message("Source Code", ["a.py"])
        self.assertIn("case/T2611845", message)
        self.assertIn("Source Code", message)
        self.assertIn("a.py", message)

    def test_lists_at_most_five_files_then_summarizes_the_rest(self):
        files = [f"f{i}.py" for i in range(8)]
        message = self.committer._build_commit_message("Source Code", files)
        for f in files[:5]:
            self.assertIn(f, message)
        for f in files[5:]:
            self.assertNotIn(f, message)
        self.assertIn("... and 3 more", message)

    def test_exactly_five_files_shows_no_more_summary_line(self):
        files = [f"f{i}.py" for i in range(5)]
        message = self.committer._build_commit_message("Source Code", files)
        self.assertNotIn("more", message)


class CommitHashExtractionTests(unittest.TestCase):
    def setUp(self):
        self.committer = Committer(workspace=_workspace())

    def test_extracts_hash_from_typical_git_commit_output(self):
        with mock.patch.object(
            self.committer, "_run_git", return_value="[case/T1 d3adb33] some message\n 2 files changed"
        ):
            self.assertEqual(self.committer._commit("some message"), "d3adb33")

    def test_returns_unknown_when_output_has_no_brackets(self):
        with mock.patch.object(self.committer, "_run_git", return_value="nothing useful here"):
            self.assertEqual(self.committer._commit("some message"), "unknown")

    def test_returns_unknown_on_empty_output(self):
        with mock.patch.object(self.committer, "_run_git", return_value=""):
            self.assertEqual(self.committer._commit("some message"), "unknown")


class RunGitTests(unittest.TestCase):
    def setUp(self):
        self.committer = Committer(workspace=_workspace(repo_dir="/repo"))

    def test_passes_utf8_encoding_and_replace_errors(self):
        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch("lib.committer.subprocess.run", return_value=completed) as run:
            self.committer._run_git(["status"])
        _, kwargs = run.call_args
        self.assertEqual(kwargs.get("encoding"), "utf-8")
        self.assertEqual(kwargs.get("errors"), "replace")
        self.assertTrue(kwargs.get("capture_output"))
        self.assertTrue(kwargs.get("text"))

    def test_nonzero_returncode_exits_with_stderr_in_message(self):
        completed = mock.Mock(returncode=1, stdout="", stderr="fatal: not a git repo")
        with mock.patch("lib.committer.subprocess.run", return_value=completed):
            with self.assertRaises(SystemExit) as ctx:
                self.committer._run_git(["commit", "-m", "x"])
        self.assertIn("fatal: not a git repo", str(ctx.exception))

    def test_capture_true_returns_stdout_capture_false_returns_empty_string(self):
        completed = mock.Mock(returncode=0, stdout="the output\n", stderr="")
        with mock.patch("lib.committer.subprocess.run", return_value=completed):
            self.assertEqual(self.committer._run_git(["diff"], capture=True), "the output\n")
        with mock.patch("lib.committer.subprocess.run", return_value=completed):
            self.assertEqual(self.committer._run_git(["add", "."], capture=False), "")


class CommitChangesIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.committer = Committer(workspace=_workspace(case_number="T1"))

    def test_stages_and_commits_each_nonempty_group_once(self):
        changes = [_change("src/a.py"), _change("README.md")]
        with mock.patch.object(self.committer, "_run_git") as run_git, mock.patch.object(
            self.committer, "_commit", return_value="abc1234"
        ):
            commits = self.committer.commit_changes(changes)
        # One "add" per file, plus no commit calls tracked via _run_git
        # (commit itself goes through the mocked _commit helper).
        add_calls = [c for c in run_git.call_args_list if c[0][0][0] == "add"]
        self.assertEqual(len(add_calls), 2)
        self.assertEqual(len(commits), 2)  # Source Code group + Documentation group
        for commit in commits:
            self.assertIsInstance(commit, Commit)
            self.assertEqual(commit.hash, "abc1234")

    def test_empty_groups_produce_no_commit(self):
        changes = [_change("src/a.py")]  # only Source Code has files
        with mock.patch.object(self.committer, "_run_git"), mock.patch.object(
            self.committer, "_commit", return_value="abc1234"
        ):
            commits = self.committer.commit_changes(changes)
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0].files_changed, ["src/a.py"])

    def test_no_changes_produces_no_commits(self):
        with mock.patch.object(self.committer, "_run_git") as run_git:
            commits = self.committer.commit_changes([])
        run_git.assert_not_called()
        self.assertEqual(commits, [])


if __name__ == "__main__":
    unittest.main()
