"""Unit tests for crm_playwright.py's pure-logic pieces.

Scope: `_page_state`'s DOM classification is exercised entirely against a
mocked Playwright `page` object (`page.url`, `page.locator(sel).count()`)
-- no real browser, no real Chromium process, no real network anywhere in
this file. `_chrome_cfg` is tested against a tempfile-based fake
case-brief/config.json, never the real one. `reset_profile()` just
delegates to case-brief's own lib.browser.close_chrome_window (already
covered by case-brief's own test suite) - here it's checked only for
delegating with the right config, fully mocked.

Deliberately skipped: check_login_headless and ensure_crm_tab_open both
attach to a real (or freshly-launched) Chrome over the CDP protocol via
case-brief's lib.browser.ensure_chrome + Playwright's connect_over_cdp --
mocking that chain deeply enough to be meaningful would mostly be
re-asserting "the mock returns what we told it to", so those two functions
are left uncovered here in favor of `_page_state`, which holds all of
their actual decision logic, and `_find_or_open_tab`, which holds the
find-existing-tab-vs-open-new-one logic they both depend on.

Run with: python -m unittest discover -s tests -v   (from app/)
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
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


class ChromeCfgTests(unittest.TestCase):
    """_chrome_cfg reads case-brief's own config.json chrome.* section and
    resolves profile_dir to an absolute path relative to case-brief/, not
    this process's cwd - that's the whole point of sharing the profile."""

    def test_falls_back_to_documented_defaults_when_config_missing(self):
        with mock.patch.object(Path, "exists", return_value=False):
            cfg = crmp._chrome_cfg()
        self.assertEqual(cfg["debug_port"], 9222)
        self.assertTrue(cfg["profile_dir"].endswith("chrome-automation-profile"))
        self.assertTrue(os.path.isabs(cfg["profile_dir"]))

    def test_reads_overrides_from_a_real_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps({"chrome": {"debug_port": 9333, "profile_dir": "./custom-profile"}}))
            with mock.patch.object(crmp, "CASE_BRIEF_DIR", Path(tmp)):
                cfg = crmp._chrome_cfg()
            self.assertEqual(cfg["debug_port"], 9333)
            self.assertEqual(cfg["profile_dir"], str((Path(tmp) / "custom-profile").resolve()))

    def test_an_already_absolute_profile_dir_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            abs_profile = str(Path(tmp) / "somewhere-else")
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps({"chrome": {"profile_dir": abs_profile}}))
            with mock.patch.object(crmp, "CASE_BRIEF_DIR", Path(tmp)):
                cfg = crmp._chrome_cfg()
            self.assertEqual(cfg["profile_dir"], abs_profile)

    def test_a_malformed_config_file_falls_back_to_defaults_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config.json").write_text("{not valid json")
            with mock.patch.object(crmp, "CASE_BRIEF_DIR", Path(tmp)):
                cfg = crmp._chrome_cfg()  # must not raise
            self.assertEqual(cfg["debug_port"], 9222)


class FindOrOpenTabTests(unittest.TestCase):
    """The find-existing-tab-vs-open-new-one logic both check_login_headless
    and ensure_crm_tab_open depend on - never opens a second Chrome window,
    only ever a new tab in the one already-attached browser/context."""

    def _browser_with_pages(self, pages):
        ctx = mock.Mock(pages=pages)
        return mock.Mock(contexts=[ctx]), ctx

    def test_reuses_an_existing_tab_for_the_same_host(self):
        existing = mock.Mock(url="https://artex-crm.crm4.dynamics.com/main.aspx")
        browser_handle, ctx = self._browser_with_pages([existing])
        result = crmp._find_or_open_tab(browser_handle, "https://artex-crm.crm4.dynamics.com/", 15000)
        self.assertIs(result, existing)
        ctx.new_page.assert_not_called()

    def test_opens_a_new_tab_when_no_matching_host_is_open(self):
        other = mock.Mock(url="https://example.com/")
        browser_handle, ctx = self._browser_with_pages([other])
        new_page = mock.Mock()
        ctx.new_page.return_value = new_page
        result = crmp._find_or_open_tab(browser_handle, "https://artex-crm.crm4.dynamics.com/", 15000)
        self.assertIs(result, new_page)
        new_page.goto.assert_called_once()
        self.assertEqual(new_page.goto.call_args[0][0], "https://artex-crm.crm4.dynamics.com/")

    def test_creates_a_context_when_the_browser_has_none_yet(self):
        browser_handle = mock.Mock(contexts=[])
        new_ctx = mock.Mock(pages=[])
        browser_handle.new_context.return_value = new_ctx
        new_page = mock.Mock()
        new_ctx.new_page.return_value = new_page
        result = crmp._find_or_open_tab(browser_handle, "https://artex-crm.crm4.dynamics.com/", 15000)
        self.assertIs(result, new_page)


class ResetProfileTests(unittest.TestCase):
    """reset_profile is a thin delegation to case-brief's own
    lib.browser.close_chrome_window (already exercised by case-brief's own
    test suite against the real kill/lockfile-cleanup logic) - here just
    checking it's called with this shared config, fully mocked."""

    def test_delegates_to_case_brief_close_chrome_window_with_shared_config(self):
        fake_cfg = {"debug_port": 9222, "profile_dir": "/some/shared/profile"}
        with mock.patch.object(crmp, "_chrome_cfg", return_value=fake_cfg), \
             mock.patch.object(crmp.cb_browser, "close_chrome_window") as close_fn:
            crmp.reset_profile()
        close_fn.assert_called_once_with(fake_cfg)


if __name__ == "__main__":
    unittest.main()
