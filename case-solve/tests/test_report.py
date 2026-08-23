"""Unit tests for lib/report.py: checklist/report markdown generation from
plain dict/list inputs (Change/Commit/CheckResult-like objects and, per the
module's own isinstance checks, dicts), and graceful handling of
empty/partial input (no changes, no test_results, no commits).

No real subprocess/filesystem access beyond writing the report file itself,
which is always done inside tempfile.TemporaryDirectory.

**Bugs found while writing these tests, since fixed** (matching the
identical bug fixed in test_committer.py for lib/committer.py):

1. `_section_changes`'s dict branch for `file_path` did `change.file_path`
   (attribute access) in both ternary branches instead of
   `change["file_path"]` for the dict case - a dict-shaped change raised
   AttributeError instead of being rendered. Fixed. See
   DictShapedChangeBugTests below, now a regression test.
2. The diff-rendering block was gated on
   `isinstance(change, dict) and "diff" in change`, but real callers (see
   lib/implementer.py's `implement()`) always pass `Change` dataclass
   instances, never dicts - so the diff was *silently never shown* in any
   real report, even though `Change.diff` is a real, populated field.
   Fixed to read `.diff` the same dict-or-dataclass way as `file_path`/
   `description`. See DiffRenderingDeadCodeTests below, now a regression
   test.

Run with: python -m unittest discover -s tests -v   (from case-solve/)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.committer import Commit
from lib.implementer import Change
from lib.report import ReportGenerator
from lib.verifier import CheckResult, VerificationResults


def _workspace(repo_url="https://github.com/acme/widgets.git", branch_name="case/T1", repo_dir="/repo"):
    return mock.Mock(repo_url=repo_url, branch_name=branch_name, repo_dir=Path(repo_dir))


def _report(**overrides):
    kwargs = dict(
        case_number="T1",
        workspace=_workspace(),
        changes_summary=[],
        test_results=None,
        commits=[],
        guide_path=Path("guide.md"),
    )
    kwargs.update(overrides)
    return ReportGenerator(**kwargs)


class OverviewSectionTests(unittest.TestCase):
    def test_includes_case_number_repo_and_branch(self):
        report = _report()
        text = "\n".join(report._section_overview())
        self.assertIn("T1", text)
        self.assertIn("https://github.com/acme/widgets.git", text)
        self.assertIn("case/T1", text)


class ChangesSectionTests(unittest.TestCase):
    def test_empty_changes_says_no_changes_recorded(self):
        report = _report(changes_summary=[])
        text = "\n".join(report._section_changes())
        self.assertIn("No changes recorded.", text)

    def test_object_shaped_changes_render_file_path_and_description(self):
        change = Change(file_path="src/a.py", description="fixed the thing", diff="")
        report = _report(changes_summary=[change])
        text = "\n".join(report._section_changes())
        self.assertIn("src/a.py", text)
        self.assertIn("fixed the thing", text)

    def test_multiple_changes_are_all_rendered_and_numbered(self):
        changes = [
            Change(file_path="a.py", description="first", diff=""),
            Change(file_path="b.py", description="second", diff=""),
        ]
        report = _report(changes_summary=changes)
        text = "\n".join(report._section_changes())
        self.assertIn("Change 1: a.py", text)
        self.assertIn("Change 2: b.py", text)

    def test_change_without_description_omits_description_line(self):
        change = Change(file_path="a.py", description="", diff="")
        report = _report(changes_summary=[change])
        text = "\n".join(report._section_changes())
        self.assertNotIn("**Description**", text)


class VerificationSectionTests(unittest.TestCase):
    def test_no_test_results_skips_the_verification_section_entirely(self):
        report = _report(test_results=None)
        text = report._build_report()
        self.assertNotIn("## Verification Results", text)

    def test_all_checks_passed_shows_success_banner(self):
        results = VerificationResults()
        results.add(CheckResult(name="pytest", passed=True, output=""))
        report = _report(test_results=results)
        text = "\n".join(report._section_verification())
        self.assertIn("All checks passed", text)
        self.assertNotIn("Failed Checks", text)

    def test_failed_checks_are_listed_with_output(self):
        results = VerificationResults()
        results.add(CheckResult(name="pytest", passed=False, output="AssertionError: boom"))
        report = _report(test_results=results)
        text = "\n".join(report._section_verification())
        self.assertIn("pytest", text)
        self.assertIn("AssertionError: boom", text)

    def test_long_check_output_is_truncated(self):
        results = VerificationResults()
        results.add(CheckResult(name="pytest", passed=False, output="x" * 1000))
        report = _report(test_results=results)
        text = "\n".join(report._section_verification())
        self.assertIn("(truncated)", text)


class CommitsSectionTests(unittest.TestCase):
    def test_no_commits_shows_placeholder_text(self):
        report = _report(commits=[])
        text = "\n".join(report._section_commits())
        self.assertIn("No commits created", text)

    def test_commit_shows_short_hash_and_message(self):
        commit = Commit(hash="d3adb33full", message="[case/T1] Source Code", files_changed=["a.py"])
        report = _report(commits=[commit])
        text = "\n".join(report._section_commits())
        self.assertIn("d3adb33", text)  # first 7 chars
        self.assertIn("[case/T1] Source Code", text)

    def test_more_than_three_files_are_summarized(self):
        commit = Commit(hash="abc1234", message="m", files_changed=[f"f{i}.py" for i in range(5)])
        report = _report(commits=[commit])
        text = "\n".join(report._section_commits())
        self.assertIn("f0.py", text)
        self.assertIn("... and 2 more", text)


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_report_file_and_creates_parent_dirs(self):
        output_path = Path(self.tmp.name) / "nested" / "CHECKLIST.md"
        report = _report()
        result_path = report.generate(output_path)
        self.assertEqual(result_path, output_path)
        self.assertTrue(output_path.exists())
        content = output_path.read_text(encoding="utf-8")
        self.assertIn(f"Case T1", content)

    def test_fully_empty_input_does_not_crash_and_produces_placeholders(self):
        output_path = Path(self.tmp.name) / "CHECKLIST.md"
        report = _report(changes_summary=[], test_results=None, commits=[])
        report.generate(output_path)
        content = output_path.read_text(encoding="utf-8")
        self.assertIn("No changes recorded.", content)
        self.assertIn("No commits created", content)
        self.assertNotIn("## Verification Results", content)

    def test_partial_input_mixes_present_and_absent_sections(self):
        output_path = Path(self.tmp.name) / "CHECKLIST.md"
        results = VerificationResults()
        results.add(CheckResult(name="pytest", passed=True, output=""))
        report = _report(
            changes_summary=[Change(file_path="a.py", description="d", diff="")],
            test_results=results,
            commits=[],
        )
        report.generate(output_path)
        content = output_path.read_text(encoding="utf-8")
        self.assertIn("a.py", content)
        self.assertIn("All checks passed", content)
        self.assertIn("No commits created", content)


class DictShapedChangeBugTests(unittest.TestCase):
    """Regression test: lib/report.py _section_changes' dict branch for
    file_path - now fixed."""

    def test_dict_change_renders_without_error(self):
        report = _report(changes_summary=[{"file_path": "a.py", "description": "d"}])
        text = "\n".join(report._section_changes())
        self.assertIn("a.py", text)


class DiffRenderingTests(unittest.TestCase):
    """Regression test: the diff block in _section_changes used to only
    fire for dict-shaped changes, but real changes are Change dataclass
    instances - now fixed to render for both shapes."""

    def test_object_shaped_change_shows_its_diff(self):
        change = Change(file_path="a.py", description="d", diff="some real diff content")
        report = _report(changes_summary=[change])
        text = "\n".join(report._section_changes())
        self.assertIn("some real diff content", text)
        self.assertIn("```diff", text)

    def test_long_diff_is_truncated(self):
        change = Change(file_path="a.py", description="d", diff="x" * 1000)
        report = _report(changes_summary=[change])
        text = "\n".join(report._section_changes())
        self.assertIn("(truncated)", text)


if __name__ == "__main__":
    unittest.main()
