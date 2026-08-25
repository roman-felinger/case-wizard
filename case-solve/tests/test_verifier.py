"""Unit tests for lib/verifier.py: which test/lint/build tools get selected
based on which marker files actually exist in the repo (pytest vs unittest,
npm/cargo/dotnet additions, optional-vs-required lint tools), the pass/fail
bookkeeping in VerificationResults, and _run_check's error handling
(success, non-zero exit, timeout, tool not installed).

subprocess.run is always mocked -- no real pytest/npm/cargo/dotnet/black/
pylint/eslint/clippy process is ever spawned. Marker files are created only
inside tempfile.TemporaryDirectory.

Special focus: `_run_check` was given explicit `encoding="utf-8",
errors="replace"` this session (git/npm/pytest output can include Unicode
that crashes on Windows' default codepage). A regression test asserts the
exact kwargs passed to the mocked subprocess.run.

Deliberately not covered: real output content/formatting from any specific
tool (pytest -v output shape, black's diff format, etc) -- only whether the
right command gets chosen and whether pass/fail is recorded correctly.

Run with: python -m unittest discover -s tests -v   (from case-solve/)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.verifier import CheckResult, VerificationResults, Verifier


def _completed(returncode=0, stdout="", stderr=""):
    result = mock.Mock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def _workspace(repo_dir):
    return mock.Mock(repo_dir=Path(repo_dir))


class VerificationResultsTests(unittest.TestCase):
    def test_add_updates_totals_and_passed_count(self):
        results = VerificationResults()
        results.add(CheckResult(name="a", passed=True, output=""))
        results.add(CheckResult(name="b", passed=False, output="err"))
        self.assertEqual(results.total_checks, 2)
        self.assertEqual(results.passed_checks, 1)


class RunCheckTests(unittest.TestCase):
    def setUp(self):
        self.verifier = Verifier(workspace=_workspace("/repo"), cfg={})

    def test_success_is_recorded_as_passed(self):
        results = VerificationResults()
        with mock.patch(
            "lib.verifier.subprocess.run", return_value=_completed(returncode=0, stdout="ok")
        ):
            self.verifier._run_check("pytest", ["python", "-m", "pytest"], results)
        self.assertEqual(results.total_checks, 1)
        self.assertTrue(results.checks[0].passed)

    def test_nonzero_exit_is_recorded_as_failed(self):
        results = VerificationResults()
        with mock.patch(
            "lib.verifier.subprocess.run",
            return_value=_completed(returncode=1, stdout="", stderr="assertion failed"),
        ):
            self.verifier._run_check("pytest", ["python", "-m", "pytest"], results)
        self.assertFalse(results.checks[0].passed)
        self.assertIn("assertion failed", results.checks[0].output)

    def test_timeout_is_recorded_as_failed_without_raising(self):
        import subprocess as sp

        results = VerificationResults()
        with mock.patch(
            "lib.verifier.subprocess.run",
            side_effect=sp.TimeoutExpired(cmd="pytest", timeout=120),
        ):
            self.verifier._run_check("pytest", ["python", "-m", "pytest"], results)
        self.assertEqual(results.total_checks, 1)
        self.assertFalse(results.checks[0].passed)
        self.assertIn("timed out", results.checks[0].output.lower())

    def test_missing_tool_is_recorded_as_failed_when_required(self):
        results = VerificationResults()
        with mock.patch("lib.verifier.subprocess.run", side_effect=FileNotFoundError()):
            self.verifier._run_check("cargo test", ["cargo", "test"], results, optional=False)
        self.assertEqual(results.total_checks, 1)
        self.assertFalse(results.checks[0].passed)

    def test_missing_tool_is_silently_skipped_when_optional(self):
        results = VerificationResults()
        with mock.patch("lib.verifier.subprocess.run", side_effect=FileNotFoundError()):
            self.verifier._run_check("black --check", ["black", "."], results, optional=True)
        self.assertEqual(results.total_checks, 0)  # not recorded at all

    def test_subprocess_run_called_with_utf8_encoding_and_replace_errors(self):
        results = VerificationResults()
        with mock.patch(
            "lib.verifier.subprocess.run", return_value=_completed()
        ) as run:
            self.verifier._run_check("pytest", ["python", "-m", "pytest"], results)
        _, kwargs = run.call_args
        self.assertEqual(kwargs.get("encoding"), "utf-8")
        self.assertEqual(kwargs.get("errors"), "replace")
        self.assertTrue(kwargs.get("capture_output"))
        self.assertTrue(kwargs.get("text"))
        self.assertEqual(kwargs.get("timeout"), 120)


class RunAllChecksTests(unittest.TestCase):
    def test_respects_cfg_flags_for_which_check_groups_run(self):
        verifier = Verifier(
            workspace=_workspace("/repo"),
            cfg={"run_tests": True, "run_build": False, "run_lint": False},
        )
        with mock.patch.object(verifier, "_run_tests") as tests, mock.patch.object(
            verifier, "_run_build"
        ) as build, mock.patch.object(verifier, "_run_lint") as lint:
            verifier.run_all_checks()
        tests.assert_called_once()
        build.assert_not_called()
        lint.assert_not_called()

    def test_all_flags_false_runs_nothing(self):
        verifier = Verifier(
            workspace=_workspace("/repo"),
            cfg={"run_tests": False, "run_build": False, "run_lint": False},
        )
        results = verifier.run_all_checks()
        self.assertEqual(results.total_checks, 0)


class TestAutoDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.tmp.name)
        self.verifier = Verifier(workspace=_workspace(self.repo_dir), cfg={})

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_markers_runs_no_test_checks(self):
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_tests(results)
        run_check.assert_not_called()

    def test_tests_dir_with_pyproject_toml_selects_pytest(self):
        (self.repo_dir / "tests").mkdir()
        (self.repo_dir / "pyproject.toml").write_text("[tool.pytest]\n")
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_tests(results)
        names = [c[0][0] for c in run_check.call_args_list]
        self.assertIn("pytest", names)
        self.assertNotIn("unittest", names)

    def test_tests_dir_without_pytest_config_selects_unittest(self):
        (self.repo_dir / "tests").mkdir()
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_tests(results)
        names = [c[0][0] for c in run_check.call_args_list]
        self.assertIn("unittest", names)
        self.assertNotIn("pytest", names)

    def test_top_level_test_files_without_tests_dir_also_trigger_detection(self):
        (self.repo_dir / "test_foo.py").write_text("")
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_tests(results)
        names = [c[0][0] for c in run_check.call_args_list]
        self.assertIn("unittest", names)

    def test_package_json_adds_npm_test_alongside_python_tests(self):
        (self.repo_dir / "tests").mkdir()
        (self.repo_dir / "package.json").write_text("{}")
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_tests(results)
        names = [c[0][0] for c in run_check.call_args_list]
        self.assertIn("unittest", names)
        self.assertIn("npm test", names)

    def test_cargo_toml_adds_cargo_test(self):
        (self.repo_dir / "Cargo.toml").write_text("[package]\n")
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_tests(results)
        names = [c[0][0] for c in run_check.call_args_list]
        self.assertIn("cargo test", names)

    def test_csproj_adds_dotnet_test(self):
        (self.repo_dir / "App.csproj").write_text("<Project/>")
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_tests(results)
        names = [c[0][0] for c in run_check.call_args_list]
        self.assertIn("dotnet test", names)


class LintAutoDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.tmp.name)
        self.verifier = Verifier(workspace=_workspace(self.repo_dir), cfg={})

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_py_files_skips_python_lint_tools(self):
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_lint(results)
        names = [c[0][0] for c in run_check.call_args_list]
        self.assertNotIn("black --check", names)
        self.assertNotIn("pylint", names)

    def test_py_files_trigger_black_and_pylint_as_optional(self):
        (self.repo_dir / "app.py").write_text("x = 1\n")
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_lint(results)
        calls = {c[0][0]: c for c in run_check.call_args_list}
        self.assertIn("black --check", calls)
        self.assertIn("pylint", calls)
        self.assertTrue(calls["black --check"][1].get("optional"))
        self.assertTrue(calls["pylint"][1].get("optional"))

    def test_eslintrc_triggers_eslint_check(self):
        (self.repo_dir / ".eslintrc").write_text("{}")
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_lint(results)
        names = [c[0][0] for c in run_check.call_args_list]
        self.assertIn("eslint", names)

    def test_cargo_toml_triggers_clippy(self):
        (self.repo_dir / "Cargo.toml").write_text("[package]\n")
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_lint(results)
        names = [c[0][0] for c in run_check.call_args_list]
        self.assertIn("cargo clippy", names)


class BuildAutoDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.tmp.name)
        self.verifier = Verifier(workspace=_workspace(self.repo_dir), cfg={})

    def tearDown(self):
        self.tmp.cleanup()

    def test_setup_py_triggers_python_build(self):
        (self.repo_dir / "setup.py").write_text("")
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_build(results)
        names = [c[0][0] for c in run_check.call_args_list]
        self.assertIn("python setup.py build", names)

    def test_cargo_toml_triggers_cargo_build(self):
        (self.repo_dir / "Cargo.toml").write_text("[package]\n")
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_build(results)
        names = [c[0][0] for c in run_check.call_args_list]
        self.assertIn("cargo build", names)

    def test_csproj_triggers_dotnet_build(self):
        (self.repo_dir / "App.csproj").write_text("<Project/>")
        results = VerificationResults()
        with mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_build(results)
        names = [c[0][0] for c in run_check.call_args_list]
        self.assertIn("dotnet build", names)

    def test_package_json_with_successful_probe_registers_npm_build_check(self):
        (self.repo_dir / "package.json").write_text("{}")
        results = VerificationResults()
        with mock.patch(
            "lib.verifier.subprocess.run", return_value=_completed(returncode=0)
        ), mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_build(results)
        names = [c[0][0] for c in run_check.call_args_list]
        self.assertIn("npm run build", names)

    def test_package_json_with_failed_probe_does_not_register_npm_build_check(self):
        (self.repo_dir / "package.json").write_text("{}")
        results = VerificationResults()
        with mock.patch(
            "lib.verifier.subprocess.run", return_value=_completed(returncode=1)
        ), mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_build(results)
        run_check.assert_not_called()

    def test_package_json_probe_timeout_is_swallowed_not_raised(self):
        import subprocess as sp

        (self.repo_dir / "package.json").write_text("{}")
        results = VerificationResults()
        with mock.patch(
            "lib.verifier.subprocess.run",
            side_effect=sp.TimeoutExpired(cmd="npm", timeout=30),
        ), mock.patch.object(self.verifier, "_run_check") as run_check:
            self.verifier._run_build(results)  # must not raise
        run_check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
