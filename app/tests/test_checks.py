"""Unit tests for checks.py's system health checks and diagnostics.

Scope: every external process/tool is mocked -- subprocess.run is patched
in every test that would otherwise shell out to a real `git`/`claude`
binary, and check_crm_tab's delegation to crm_playwright is exercised by
mocking `crm_playwright.check_login_headless` (imported lazily inside the
function, so it's patched at its source module rather than on `checks`).
No real subprocess, no real browser, no real network anywhere in this file.

Deliberately skipped: check_python is exercised only via its real
sys.version_info (mocking that reliably across Python's C-level namedtuple
is more trouble than it's worth for a two-branch version comparison) --
its True/False shape is still asserted against whatever interpreter is
actually running the suite.

Run with: python -m unittest discover -s tests -v   (from app/)
"""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import checks


class CheckPythonTests(unittest.TestCase):
    def test_reports_true_on_the_interpreter_actually_running_the_tests(self):
        # This suite requires Python 3.8+ to run at all (f-strings, etc. in
        # the app aside), so the real interpreter should always pass.
        status, message = checks.check_python()
        self.assertTrue(status)
        self.assertIn("Python", message)


class CheckGitTests(unittest.TestCase):
    def test_true_when_git_returns_zero(self):
        with mock.patch.object(checks.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["git", "--version"], 0, stdout="git version 2.40.0\n", stderr="")
            status, message = checks.check_git()
        self.assertTrue(status)
        self.assertEqual(message, "git version 2.40.0")
        run.assert_called_once_with(["git", "--version"], capture_output=True, text=True, timeout=5)

    def test_false_when_git_returns_nonzero(self):
        with mock.patch.object(checks.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["git", "--version"], 1, stdout="", stderr="error")
            status, message = checks.check_git()
        self.assertFalse(status)
        self.assertEqual(message, "Git not found in PATH")

    def test_false_when_git_is_not_on_path(self):
        with mock.patch.object(checks.subprocess, "run", side_effect=FileNotFoundError("no git")):
            status, message = checks.check_git()
        self.assertFalse(status)

    def test_false_on_timeout(self):
        with mock.patch.object(checks.subprocess, "run",
                                side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=5)):
            status, message = checks.check_git()
        self.assertFalse(status)


class CheckClaudeTests(unittest.TestCase):
    def test_true_when_claude_returns_zero(self):
        with mock.patch.object(checks.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["claude", "--version"], 0, stdout="1.2.3\n", stderr="")
            status, message = checks.check_claude()
        self.assertTrue(status)
        self.assertEqual(message, "1.2.3")

    def test_false_when_claude_returns_nonzero(self):
        with mock.patch.object(checks.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["claude", "--version"], 1, stdout="", stderr="")
            status, message = checks.check_claude()
        self.assertFalse(status)
        self.assertEqual(message, "Claude CLI not in PATH")

    def test_false_when_claude_not_installed(self):
        with mock.patch.object(checks.subprocess, "run", side_effect=FileNotFoundError("no claude")):
            status, message = checks.check_claude()
        self.assertFalse(status)
        self.assertEqual(message, "Claude CLI not installed")

    def test_false_on_timeout(self):
        with mock.patch.object(checks.subprocess, "run",
                                side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=5)):
            status, message = checks.check_claude()
        self.assertFalse(status)


class CheckClaudeLoginTests(unittest.TestCase):
    def test_true_when_claude_responds_to_the_test_prompt(self):
        with mock.patch.object(checks.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["claude", "-p"], 0, stdout="OK", stderr="")
            status, message = checks.check_claude_login()
        self.assertTrue(status)
        self.assertEqual(message, "Responding to prompts")
        _, kwargs = run.call_args
        self.assertEqual(kwargs["input"], "Say 'OK' if you can read this.")

    def test_false_when_stderr_says_not_authenticated(self):
        with mock.patch.object(checks.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["claude", "-p"], 1, stdout="", stderr="Error: not authenticated")
            status, message = checks.check_claude_login()
        self.assertFalse(status)
        self.assertEqual(message, "Not logged in (run: claude login)")

    def test_false_when_stderr_mentions_login(self):
        with mock.patch.object(checks.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["claude", "-p"], 1, stdout="", stderr="please login first")
            status, message = checks.check_claude_login()
        self.assertFalse(status)
        self.assertEqual(message, "Not logged in (run: claude login)")

    def test_false_when_nonzero_exit_without_a_recognizable_reason(self):
        with mock.patch.object(checks.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["claude", "-p"], 1, stdout="", stderr="boom")
            status, message = checks.check_claude_login()
        self.assertFalse(status)
        self.assertEqual(message, "Not responding")

    def test_false_when_zero_exit_but_empty_stdout(self):
        with mock.patch.object(checks.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["claude", "-p"], 0, stdout="", stderr="")
            status, message = checks.check_claude_login()
        self.assertFalse(status)
        self.assertEqual(message, "Check failed")

    def test_false_when_claude_binary_missing(self):
        with mock.patch.object(checks.subprocess, "run", side_effect=FileNotFoundError()):
            status, message = checks.check_claude_login()
        self.assertFalse(status)
        self.assertEqual(message, "Claude CLI not found")

    def test_false_on_timeout(self):
        with mock.patch.object(checks.subprocess, "run",
                                side_effect=subprocess.TimeoutExpired(cmd=["claude", "-p"], timeout=10)):
            status, message = checks.check_claude_login()
        self.assertFalse(status)
        self.assertEqual(message, "Timeout (Claude not responding)")


class CheckCrmTabTests(unittest.TestCase):
    def test_none_when_crm_url_not_configured(self):
        status, message = checks.check_crm_tab(None)
        self.assertIsNone(status)
        self.assertEqual(message, "CRM URL not configured")

    def test_none_when_crm_url_is_empty_string(self):
        status, message = checks.check_crm_tab("")
        self.assertIsNone(status)

    def test_delegates_to_crm_playwright_check_login_headless(self):
        fake_module = mock.Mock()
        fake_module.check_login_headless.return_value = (True, "Logged in")
        with mock.patch.dict(sys.modules, {"crm_playwright": fake_module}):
            status, message = checks.check_crm_tab("https://crm.example.com/")
        self.assertTrue(status)
        self.assertEqual(message, "Logged in")
        fake_module.check_login_headless.assert_called_once_with("https://crm.example.com/")

    def test_none_when_crm_playwright_is_not_importable(self):
        with mock.patch.dict(sys.modules, {"crm_playwright": None}):
            status, message = checks.check_crm_tab("https://crm.example.com/")
        self.assertIsNone(status)
        self.assertEqual(message, "CRM check unavailable")

    def test_none_when_check_login_headless_raises_unexpectedly(self):
        fake_module = mock.Mock()
        fake_module.check_login_headless.side_effect = Exception("playwright blew up")
        with mock.patch.dict(sys.modules, {"crm_playwright": fake_module}):
            status, message = checks.check_crm_tab("https://crm.example.com/")
        self.assertIsNone(status)
        self.assertEqual(message, "CRM check pending")


class CheckConfigTests(unittest.TestCase):
    def test_true_when_pat_and_org_url_are_both_set(self):
        status, message = checks.check_config({"azdo_pat": "x", "azdo_org_url": "https://dev.azure.com/org"})
        self.assertTrue(status)
        self.assertIn("https://dev.azure.com/org", message)

    def test_none_not_false_when_config_incomplete(self):
        """Deliberately a warning (None), not a hard failure (False), so
        the setup wizard can still render instead of blocking startup."""
        status, message = checks.check_config({"azdo_pat": None, "azdo_org_url": None})
        self.assertIsNone(status)

    def test_none_when_only_pat_is_set(self):
        status, _ = checks.check_config({"azdo_pat": "x", "azdo_org_url": None})
        self.assertIsNone(status)

    def test_none_when_only_org_url_is_set(self):
        status, _ = checks.check_config({"azdo_pat": None, "azdo_org_url": "https://dev.azure.com/org"})
        self.assertIsNone(status)


class RunHealthCheckTests(unittest.TestCase):
    def test_aggregates_all_checks_with_their_status_and_message(self):
        with mock.patch.object(checks, "check_python", return_value=(True, "Python 3.11.0")), \
             mock.patch.object(checks, "check_git", return_value=(True, "git 2.40")), \
             mock.patch.object(checks, "check_claude", return_value=(False, "Claude CLI not installed")), \
             mock.patch.object(checks, "check_claude_login", return_value=(False, "Claude CLI not found")), \
             mock.patch.object(checks, "check_crm_tab", return_value=(None, "CRM URL not configured")), \
             mock.patch.object(checks, "check_config", return_value=(None, "Azure DevOps: Configure in next step")):
            results = checks.run_health_check({"crm_url": None})

        self.assertEqual(set(results), {
            "Python 3.8+", "Git", "Claude CLI", "Claude Logged In",
            "CRM Browser Tab", "Azure DevOps Config",
        })
        self.assertEqual(results["Python 3.8+"], {"status": True, "message": "Python 3.11.0"})
        self.assertEqual(results["Claude CLI"], {"status": False, "message": "Claude CLI not installed"})
        self.assertEqual(results["CRM Browser Tab"], {"status": None, "message": "CRM URL not configured"})

    def test_passes_configured_crm_url_through_to_check_crm_tab(self):
        with mock.patch.object(checks, "check_python", return_value=(True, "")), \
             mock.patch.object(checks, "check_git", return_value=(True, "")), \
             mock.patch.object(checks, "check_claude", return_value=(True, "")), \
             mock.patch.object(checks, "check_claude_login", return_value=(True, "")), \
             mock.patch.object(checks, "check_crm_tab", return_value=(True, "Logged in")) as crm_check, \
             mock.patch.object(checks, "check_config", return_value=(True, "")):
            checks.run_health_check({"crm_url": "https://crm.example.com/"})
        crm_check.assert_called_once_with("https://crm.example.com/")


class GetStartupIssuesTests(unittest.TestCase):
    def test_buckets_false_as_critical_and_none_as_warning(self):
        results = {
            "Python 3.8+": {"status": True, "message": "ok"},
            "Git": {"status": False, "message": "missing"},
            "Claude CLI": {"status": False, "message": "missing"},
            "CRM Browser Tab": {"status": None, "message": "not configured"},
        }
        critical, warnings = checks.get_startup_issues(results)
        self.assertEqual(critical, [("Git", "missing"), ("Claude CLI", "missing")])
        self.assertEqual(warnings, [("CRM Browser Tab", "not configured")])

    def test_all_true_yields_no_issues(self):
        results = {"A": {"status": True, "message": "ok"}, "B": {"status": True, "message": "ok"}}
        critical, warnings = checks.get_startup_issues(results)
        self.assertEqual(critical, [])
        self.assertEqual(warnings, [])

    def test_empty_results_yields_no_issues(self):
        critical, warnings = checks.get_startup_issues({})
        self.assertEqual(critical, [])
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
