"""Unit tests for the pure-logic slivers of lib/browser.py: locating a
chrome.exe candidate, the CDP liveness probe, and the last-opened-URLs
cache. Everything else in this module -- launching a real Chrome process
(`ensure_chrome`, via `subprocess.Popen`), connecting to it over CDP
(`get_pages`, `wait_until_ready`, via `playwright.sync_api.sync_playwright`),
and force-killing it (`close_chrome_window`, via a PowerShell subprocess) --
fundamentally requires a real Chrome process and is deliberately NOT covered
here: mocking `sync_playwright()`/`subprocess.Popen` deeply enough to
exercise those functions would only be testing the mock, not anything real
about whether Chrome actually launches or CDP actually connects.

`load_last_urls`/`save_last_urls` read and write `browser.STATE_PATH`, a
fixed path under the repo (`.last_urls.json`) computed at import time --
tests patch that module attribute to a tempfile path so nothing here ever
touches the real file. Covered here because a silent read failure
(corrupt/missing JSON) degrading to `{}` instead of raising is exactly the
kind of thing that should be locked in rather than assumed.

Run with: python -m unittest discover -s tests -v   (from case-brief/)
      or: python -m pytest tests                     (if pytest is installed)
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import browser


class FindChromeExeTests(unittest.TestCase):
    def test_configured_path_is_used_when_it_exists(self):
        with mock.patch("lib.browser.os.path.exists", side_effect=lambda p: p == r"C:\custom\chrome.exe"):
            self.assertEqual(browser.find_chrome_exe(r"C:\custom\chrome.exe"), r"C:\custom\chrome.exe")

    def test_configured_path_that_does_not_exist_falls_back_to_candidates(self):
        real_candidate = browser.CHROME_CANDIDATES[0]
        with mock.patch("lib.browser.os.path.exists", side_effect=lambda p: p == real_candidate):
            self.assertEqual(browser.find_chrome_exe(r"C:\bad\path\chrome.exe"), real_candidate)

    def test_no_configured_path_uses_the_first_existing_candidate(self):
        real_candidate = browser.CHROME_CANDIDATES[1]
        with mock.patch("lib.browser.os.path.exists", side_effect=lambda p: p == real_candidate):
            self.assertEqual(browser.find_chrome_exe(None), real_candidate)

    def test_raises_a_clear_error_when_nothing_is_found(self):
        with mock.patch("lib.browser.os.path.exists", return_value=False):
            with self.assertRaises(RuntimeError):
                browser.find_chrome_exe(None)


class CdpAliveTests(unittest.TestCase):
    def test_true_when_the_version_endpoint_responds_ok(self):
        fake_response = mock.Mock(ok=True)
        with mock.patch("lib.browser.requests.get", return_value=fake_response):
            self.assertTrue(browser._cdp_alive(9222))

    def test_false_when_the_version_endpoint_responds_not_ok(self):
        fake_response = mock.Mock(ok=False)
        with mock.patch("lib.browser.requests.get", return_value=fake_response):
            self.assertFalse(browser._cdp_alive(9222))

    def test_false_on_connection_failure_rather_than_raising(self):
        with mock.patch("lib.browser.requests.get", side_effect=requests.exceptions.ConnectionError("down")):
            self.assertFalse(browser._cdp_alive(9222))


class LastUrlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.tmp.name, ".last_urls.json")
        self._patcher = mock.patch.object(browser, "STATE_PATH", self.state_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self.tmp.cleanup()

    def test_returns_empty_dict_when_the_state_file_does_not_exist_yet(self):
        self.assertEqual(browser.load_last_urls(), {})

    def test_round_trips_through_save_and_load(self):
        browser.save_last_urls({"crm": "https://a", "bc": "https://b"})
        self.assertEqual(browser.load_last_urls(), {"crm": "https://a", "bc": "https://b"})

    def test_corrupt_json_degrades_to_empty_dict_instead_of_raising(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        self.assertEqual(browser.load_last_urls(), {})

    def test_save_overwrites_a_previous_state_rather_than_merging(self):
        browser.save_last_urls({"crm": "https://old-crm", "bc": "https://old-bc"})
        browser.save_last_urls({"crm": "https://new-crm"})
        self.assertEqual(browser.load_last_urls(), {"crm": "https://new-crm"})


if __name__ == "__main__":
    unittest.main()
