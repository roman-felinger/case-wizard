"""Unit tests for crm_playwright.py's pure-logic pieces.

Scope: `_page_state`'s DOM classification is exercised entirely against a
mocked Playwright `page` object (`page.url`, `page.locator(sel).count()`)
-- no real browser, no real Chromium process, no real network anywhere in
this file. `reset_profile()`'s Windows-only early-return guard is tested by
patching `sys.platform`; everything past that guard (subprocess/taskkill/
file deletion) is mocked so nothing real ever runs, including on an actual
Windows test machine.

Deliberately skipped: check_login_headless and open_login_window both
launch a real (or headless) Playwright browser via
`sync_playwright().chromium.launch_persistent_context(...)` -- mocking that
context-manager chain deeply enough to be meaningful would mostly be
re-asserting "the mock returns what we told it to", so those two functions
are left uncovered here in favor of `_page_state`, which holds all of their
actual decision logic.

Run with: python -m unittest discover -s tests -v   (from app/)
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crm_playwright as crmp


def _fake_page(url="", present_selectors=()):
    """A minimal stand-in for a Playwright Page: .url is an attribute,
    .locator(sel).count() returns >0 only for selectors in present_selectors."""
    page = mock.Mock()
    page.url = url

    def locator(sel):
        loc = mock.Mock()
        loc.count.return_value = 1 if sel in present_selectors else 0
        return loc

    page.locator.side_effect = locator
    return page


class PageStateTests(unittest.TestCase):
    def test_login_when_url_is_on_the_microsoft_login_host(self):
        page = _fake_page(url="https://login.microsoftonline.com/common/oauth2/authorize")
        self.assertEqual(crmp._page_state(page), "login")

    def test_login_when_url_is_login_live_com(self):
        page = _fake_page(url="https://login.live.com/something")
        self.assertEqual(crmp._page_state(page), "login")

    def test_login_when_url_check_is_case_insensitive(self):
        page = _fake_page(url="HTTPS://LOGIN.MICROSOFTONLINE.COM/common")
        self.assertEqual(crmp._page_state(page), "login")

    def test_login_when_a_login_marker_selector_is_present_even_off_login_host(self):
        # e.g. the CRM's own URL, but the SPA redirected client-side to an
        # embedded/iframed login form before the top-level URL changed.
        page = _fake_page(url="https://artex-crm.crm4.dynamics.com/", present_selectors=["#i0116"])
        self.assertEqual(crmp._page_state(page), "login")

    def test_login_marker_check_short_circuits_on_the_first_match(self):
        page = _fake_page(url="https://artex-crm.crm4.dynamics.com/", present_selectors=["text=Sign in"])
        self.assertEqual(crmp._page_state(page), "login")

    def test_app_when_an_app_shell_selector_is_present(self):
        page = _fake_page(url="https://artex-crm.crm4.dynamics.com/main.aspx", present_selectors=["#ApplicationBody"])
        self.assertEqual(crmp._page_state(page), "app")

    def test_app_when_a_different_app_shell_selector_is_present(self):
        page = _fake_page(url="https://artex-crm.crm4.dynamics.com/main.aspx", present_selectors=["#shell-container"])
        self.assertEqual(crmp._page_state(page), "app")

    def test_unknown_when_neither_login_nor_app_markers_are_present(self):
        page = _fake_page(url="https://artex-crm.crm4.dynamics.com/some/other/page")
        self.assertEqual(crmp._page_state(page), "unknown")

    def test_unknown_when_url_is_empty(self):
        page = _fake_page(url="")
        self.assertEqual(crmp._page_state(page), "unknown")

    def test_unknown_when_url_is_none(self):
        page = _fake_page(url=None)
        self.assertEqual(crmp._page_state(page), "unknown")

    def test_login_takes_priority_over_app_when_both_markers_are_present(self):
        page = _fake_page(
            url="https://artex-crm.crm4.dynamics.com/",
            present_selectors=["#i0116", "#ApplicationBody"],
        )
        self.assertEqual(crmp._page_state(page), "login")

    def test_a_locator_that_raises_is_treated_as_absent_not_fatal(self):
        page = mock.Mock()
        page.url = "https://artex-crm.crm4.dynamics.com/"

        def locator(sel):
            raise Exception("detached frame")

        page.locator.side_effect = locator
        # Must not raise, and with every selector raising -> no marker
        # found -> unknown.
        self.assertEqual(crmp._page_state(page), "unknown")

    def test_a_locator_that_raises_only_for_the_login_markers_still_finds_an_app_marker(self):
        page = mock.Mock()
        page.url = "https://artex-crm.crm4.dynamics.com/"

        def locator(sel):
            if sel in crmp.LOGIN_MARKERS:
                raise Exception("detached frame")
            loc = mock.Mock()
            loc.count.return_value = 1 if sel == "#ApplicationBody" else 0
            return loc

        page.locator.side_effect = locator
        self.assertEqual(crmp._page_state(page), "app")


class ResetProfileTests(unittest.TestCase):
    def test_early_return_on_non_windows_platforms_does_nothing(self):
        with mock.patch.object(crmp.sys, "platform", "linux"), \
             mock.patch.object(crmp.subprocess, "run") as run, \
             mock.patch.object(crmp.Path, "unlink") as unlink:
            crmp.reset_profile()
        run.assert_not_called()
        unlink.assert_not_called()

    def test_on_windows_it_queries_and_kills_matching_processes(self):
        ps_result = mock.Mock(stdout="1234\n5678\n")
        taskkill_result = mock.Mock()
        with mock.patch.object(crmp.sys, "platform", "win32"), \
             mock.patch.object(crmp.subprocess, "run", side_effect=[ps_result, taskkill_result, taskkill_result]) as run, \
             mock.patch.object(crmp.Path, "unlink") as unlink:
            crmp.reset_profile()
        self.assertEqual(run.call_count, 3)  # 1 powershell query + 2 taskkills
        first_call_args = run.call_args_list[0][0][0]
        self.assertIn("powershell", first_call_args)
        second_call_args = run.call_args_list[1][0][0]
        self.assertEqual(second_call_args, ["taskkill", "/F", "/PID", "1234"])
        # Lock files are still cleaned up regardless.
        self.assertEqual(unlink.call_count, 2)

    def test_on_windows_a_powershell_failure_is_swallowed_and_lockfiles_still_get_removed(self):
        with mock.patch.object(crmp.sys, "platform", "win32"), \
             mock.patch.object(crmp.subprocess, "run", side_effect=Exception("powershell not found")), \
             mock.patch.object(crmp.Path, "unlink") as unlink:
            crmp.reset_profile()  # must not raise
        self.assertEqual(unlink.call_count, 2)

    def test_on_windows_a_lockfile_unlink_failure_is_swallowed(self):
        ps_result = mock.Mock(stdout="")
        with mock.patch.object(crmp.sys, "platform", "win32"), \
             mock.patch.object(crmp.subprocess, "run", return_value=ps_result), \
             mock.patch.object(crmp.Path, "unlink", side_effect=OSError("in use")):
            crmp.reset_profile()  # must not raise


if __name__ == "__main__":
    unittest.main()
