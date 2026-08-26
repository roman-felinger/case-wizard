"""Unit tests for lib/dataverse_page.py.

DataverseApiPage exists to duck-type crm_scrape.py's `page` interface
(`.url` / `.evaluate(js, arg)`) over `requests` instead of an in-page
fetch. The key thing to lock in is that its `.evaluate()` return shape
matches crm_scrape._FETCH_JS's exactly (same {"__error": ...} convention on
failure, raw JSON dict on success) -- crm_scrape.py's own extensive test
suite (test_crm_scrape.py) already covers what happens once that dict
reaches it, so these tests only need to cover the HTTP <-> dict translation
itself, via a fake `requests.Session`.

Run with: python -m unittest discover -s tests -v   (from case-brief/)
      or: python -m pytest tests                     (if pytest is installed)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.dataverse_page import DataverseApiPage


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise ValueError("no JSON body")
        return self._json_data


class FakeSession:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        if self._exc:
            raise self._exc
        return self._response


class DataverseApiPageTests(unittest.TestCase):
    def test_url_is_derived_from_origin_for_crm_scrapes_regex(self):
        page = DataverseApiPage("https://org.crm.dynamics.com", "tok", session=FakeSession())
        self.assertTrue(page.url.startswith("https://org.crm.dynamics.com"))

    def test_successful_json_response_is_returned_as_is(self):
        session = FakeSession(FakeResponse(200, json_data={"value": [{"a": 1}]}))
        page = DataverseApiPage("https://org.crm.dynamics.com", "tok", session=session)
        result = page.evaluate("ignored-js", "https://org.crm.dynamics.com/api/data/v9.2/incidents")
        self.assertEqual(result, {"value": [{"a": 1}]})

    def test_authorization_header_carries_the_bearer_token(self):
        session = FakeSession(FakeResponse(200, json_data={}))
        page = DataverseApiPage("https://org.crm.dynamics.com", "secret-tok", session=session)
        page.evaluate("js", "https://x/api")
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer secret-tok")

    def test_non_ok_status_is_surfaced_as_the_fetch_js_error_shape(self):
        session = FakeSession(FakeResponse(403, text="Forbidden: insufficient privileges"))
        page = DataverseApiPage("https://org.crm.dynamics.com", "tok", session=session)
        result = page.evaluate("js", "https://x/api")
        self.assertIn("__error", result)
        self.assertIn("HTTP 403", result["__error"])
        self.assertIn("Forbidden", result["__error"])

    def test_network_failure_is_surfaced_not_raised(self):
        import requests
        session = FakeSession(exc=requests.ConnectionError("DNS failure"))
        page = DataverseApiPage("https://org.crm.dynamics.com", "tok", session=session)
        result = page.evaluate("js", "https://x/api")
        self.assertIn("__error", result)
        self.assertIn("DNS failure", result["__error"])

    def test_non_json_ok_response_is_surfaced_as_an_error_not_a_crash(self):
        page = DataverseApiPage(
            "https://org.crm.dynamics.com", "tok",
            session=FakeSession(FakeResponse(200, json_data=None, text="<html>not json</html>")),
        )
        result = page.evaluate("js", "https://x/api")
        self.assertIn("__error", result)


if __name__ == "__main__":
    unittest.main()
