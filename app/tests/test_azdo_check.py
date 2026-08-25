"""Unit tests for azdo_check.py's check_azdo_access.

Scope: `requests.get` is patched everywhere -- no real network call is ever
made. Covers every status-code branch (200/401/404/other), the two
requests exception branches (Timeout/ConnectionError), a generic exception
fallback, and the early-return-without-a-network-call path when org_url or
pat_token is missing (asserted explicitly via `mock.assert_not_called()`).

Run with: python -m unittest discover -s tests -v   (from app/)
"""
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import azdo_check


def _response(status_code):
    resp = mock.Mock()
    resp.status_code = status_code
    return resp


class CheckAzdoAccessTests(unittest.TestCase):
    def test_returns_early_without_a_network_call_when_org_url_missing(self):
        with mock.patch.object(azdo_check.requests, "get") as get:
            success, message = azdo_check.check_azdo_access(None, "some-pat")
        get.assert_not_called()
        self.assertFalse(success)
        self.assertIn("required", message)

    def test_returns_early_without_a_network_call_when_pat_missing(self):
        with mock.patch.object(azdo_check.requests, "get") as get:
            success, message = azdo_check.check_azdo_access("https://dev.azure.com/org", None)
        get.assert_not_called()
        self.assertFalse(success)

    def test_returns_early_without_a_network_call_when_both_missing(self):
        with mock.patch.object(azdo_check.requests, "get") as get:
            success, message = azdo_check.check_azdo_access("", "")
        get.assert_not_called()
        self.assertFalse(success)

    def test_200_reports_success_with_org_name_from_the_url(self):
        with mock.patch.object(azdo_check.requests, "get", return_value=_response(200)):
            success, message = azdo_check.check_azdo_access("https://dev.azure.com/myorg", "pat")
        self.assertTrue(success)
        self.assertIn("myorg", message)

    def test_200_still_works_when_org_url_has_a_trailing_slash(self):
        with mock.patch.object(azdo_check.requests, "get", return_value=_response(200)):
            success, message = azdo_check.check_azdo_access("https://dev.azure.com/myorg/", "pat")
        self.assertTrue(success)
        self.assertIn("myorg", message)

    def test_bare_org_name_gets_expanded_to_a_dev_azure_com_url(self):
        captured = {}

        def fake_get(url, headers=None, timeout=None):
            captured["url"] = url
            return _response(200)

        with mock.patch.object(azdo_check.requests, "get", side_effect=fake_get):
            success, message = azdo_check.check_azdo_access("myorg", "pat")
        self.assertTrue(success)
        self.assertTrue(captured["url"].startswith("https://dev.azure.com/myorg"))

    def test_401_reports_invalid_credentials(self):
        with mock.patch.object(azdo_check.requests, "get", return_value=_response(401)):
            success, message = azdo_check.check_azdo_access("https://dev.azure.com/org", "bad-pat")
        self.assertFalse(success)
        self.assertIn("Invalid credentials", message)

    def test_404_reports_org_not_found(self):
        with mock.patch.object(azdo_check.requests, "get", return_value=_response(404)):
            success, message = azdo_check.check_azdo_access("https://dev.azure.com/nosuchorg", "pat")
        self.assertFalse(success)
        self.assertIn("not found", message)

    def test_other_status_code_reports_a_generic_api_error(self):
        with mock.patch.object(azdo_check.requests, "get", return_value=_response(500)):
            success, message = azdo_check.check_azdo_access("https://dev.azure.com/org", "pat")
        self.assertFalse(success)
        self.assertIn("500", message)

    def test_timeout_is_reported_distinctly(self):
        with mock.patch.object(azdo_check.requests, "get", side_effect=requests.exceptions.Timeout()):
            success, message = azdo_check.check_azdo_access("https://dev.azure.com/org", "pat")
        self.assertFalse(success)
        self.assertIn("timeout", message.lower())

    def test_connection_error_is_reported_distinctly(self):
        with mock.patch.object(azdo_check.requests, "get", side_effect=requests.exceptions.ConnectionError()):
            success, message = azdo_check.check_azdo_access("https://dev.azure.com/org", "pat")
        self.assertFalse(success)
        self.assertIn("Cannot connect", message)

    def test_unexpected_exception_is_caught_and_reported(self):
        with mock.patch.object(azdo_check.requests, "get", side_effect=ValueError("boom")):
            success, message = azdo_check.check_azdo_access("https://dev.azure.com/org", "pat")
        self.assertFalse(success)
        self.assertIn("boom", message)

    def test_auth_header_is_basic_encoded_from_an_empty_username_and_the_pat(self):
        captured = {}

        def fake_get(url, headers=None, timeout=None):
            captured["headers"] = headers
            return _response(200)

        with mock.patch.object(azdo_check.requests, "get", side_effect=fake_get):
            azdo_check.check_azdo_access("https://dev.azure.com/org", "my-pat", timeout=7)
        self.assertTrue(captured["headers"]["Authorization"].startswith("Basic "))

    def test_timeout_kwarg_is_forwarded_to_requests_get(self):
        captured = {}

        def fake_get(url, headers=None, timeout=None):
            captured["timeout"] = timeout
            return _response(200)

        with mock.patch.object(azdo_check.requests, "get", side_effect=fake_get):
            azdo_check.check_azdo_access("https://dev.azure.com/org", "pat", timeout=42)
        self.assertEqual(captured["timeout"], 42)


if __name__ == "__main__":
    unittest.main()
