"""Unit tests for lib/crm_scrape.py's logic that doesn't require a real
Chrome/CDP connection. The module's only external dependency is a `page`
object used through exactly two methods -- `.url` (a string) and
`.evaluate(js, arg)` -- so tests fake that narrow interface directly rather
than mocking Playwright itself; this still exercises real logic (URL/OData
construction, regex extraction, response-shape handling), not just a mock
echoing back what we told it to.

Security/correctness focus:
  - `lookup_by_ticket` interpolates the ticket number into an OData $filter
    string. A ticket number containing a single quote could otherwise break
    out of the string literal (OData injection) -- `'` -> `''` escaping is
    the only thing preventing that, so it's tested explicitly.
  - `extract`'s case-id regex must not silently produce a wrong id (or a
    match from the wrong part of the URL) since that id is used to build the
    deep link shown to the user.
  - Every `page.evaluate(...)` call site must treat `{"__error": ...}` from
    the in-page fetch as a real failure that surfaces to the caller instead
    of being unpacked as if it were case data.

Not covered: `is_authenticated`/`lookup_by_ticket`/`extract` actually running
inside a browser against a live Dataverse session, and `_FETCH_JS` itself
(it's opaque JS text from Python's point of view) -- those need Playwright +
a real, logged-in CRM tab.

Run with: python -m unittest discover -s tests -v   (from case-brief/)
      or: python -m pytest tests                     (if pytest is installed)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import crm_scrape


class FakePage:
    """Stands in for a Playwright Page, implementing only what crm_scrape.py
    actually calls: `.url` and `.evaluate(js, arg)`."""
    def __init__(self, url, eval_result=None, eval_error=None, eval_fn=None):
        self.url = url
        self._eval_result = eval_result if eval_result is not None else {}
        self._eval_error = eval_error
        self._eval_fn = eval_fn
        self.last_eval_arg = None

    def evaluate(self, js, arg=None):
        self.last_eval_arg = arg
        if self._eval_error is not None:
            raise self._eval_error
        if self._eval_fn:
            return self._eval_fn(arg)
        return self._eval_result


class StripHtmlTests(unittest.TestCase):
    def test_converts_common_block_tags_to_newlines(self):
        html = "<div>Line one</div><p>Line two</p>Line<br>three"
        result = crm_scrape._strip_html(html)
        self.assertIn("Line one", result)
        self.assertIn("Line two", result)
        self.assertNotIn("<div>", result)
        self.assertNotIn("<br>", result)

    def test_unescapes_html_entities(self):
        self.assertIn("&", crm_scrape._strip_html("Tom &amp; Jerry"))

    def test_collapses_triple_plus_newlines_to_a_blank_line(self):
        result = crm_scrape._strip_html("a<div></div><div></div><div></div>b")
        self.assertNotIn("\n\n\n", result)

    def test_passes_through_none_and_empty_string_unchanged(self):
        self.assertIsNone(crm_scrape._strip_html(None))
        self.assertEqual(crm_scrape._strip_html(""), "")


class ToResultTests(unittest.TestCase):
    def test_maps_dataverse_fields_including_formatted_value_fallback(self):
        case = {
            "incidentid": "abc-123",
            "title": "Posting error",
            "ticketnumber": "T1",
            "prioritycode@OData.Community.Display.V1.FormattedValue": "High",
            "prioritycode": 1,
            "statuscode": 2,
            "createdon": "2026-08-01T00:00:00Z",
            "description": "<div>broke</div>",
            "customerid_account": {"name": "Contoso"},
            "owninguser": {"fullname": "Jane"},
        }
        result = crm_scrape._to_result(case, "https://org.crm.dynamics.com", "https://tab-url")
        self.assertEqual(result["priority"], "High")  # formatted value preferred over raw code
        self.assertEqual(result["status"], 2)  # no formatted value given -> falls back to the raw field
        self.assertEqual(result["customer"], "Contoso")
        self.assertEqual(result["owner"], "Jane")
        self.assertIn("broke", result["description"])
        self.assertIn("abc-123", result["url"])

    def test_falls_back_to_the_tab_url_when_no_incident_id(self):
        result = crm_scrape._to_result({}, "https://org.crm.dynamics.com", "https://tab-url")
        self.assertEqual(result["url"], "https://tab-url")

    def test_missing_related_records_do_not_crash(self):
        result = crm_scrape._to_result({"incidentid": "1"}, "https://x", "https://tab")
        self.assertIsNone(result["customer"])
        self.assertIsNone(result["owner"])


class FindTabsTests(unittest.TestCase):
    def test_find_authenticated_tabs_filters_by_host_substring(self):
        pages = [FakePage("https://a.dynamics.com/x"), FakePage("https://other.example.com/y")]
        result = crm_scrape.find_authenticated_tabs(pages, ["dynamics.com"])
        self.assertEqual(result, [pages[0]])

    def test_find_case_tabs_requires_both_host_and_incident_marker(self):
        pages = [
            FakePage("https://a.dynamics.com/main.aspx?etn=incident&id=1"),
            FakePage("https://a.dynamics.com/main.aspx?etn=account&id=2"),  # right host, wrong entity
            FakePage("https://other.example.com/?etn=incident&id=3"),       # right entity, wrong host
        ]
        result = crm_scrape.find_case_tabs(pages, ["dynamics.com"])
        self.assertEqual(result, [pages[0]])


class IsAuthenticatedTests(unittest.TestCase):
    def test_true_when_the_whoami_call_succeeds(self):
        page = FakePage("https://org.crm.dynamics.com/main.aspx", eval_result={"UserId": "u1"})
        self.assertTrue(crm_scrape.is_authenticated(page))

    def test_false_when_the_fetch_reports_an_error(self):
        page = FakePage("https://org.crm.dynamics.com/main.aspx", eval_result={"__error": "HTTP 401"})
        self.assertFalse(crm_scrape.is_authenticated(page))

    def test_false_when_evaluate_itself_raises(self):
        page = FakePage("https://org.crm.dynamics.com/main.aspx", eval_error=RuntimeError("page closed"))
        self.assertFalse(crm_scrape.is_authenticated(page))


class LookupByTicketTests(unittest.TestCase):
    def test_builds_the_expected_whoami_style_odata_filter_url(self):
        page = FakePage("https://org.crm.dynamics.com/main.aspx", eval_result={"value": []})
        crm_scrape.lookup_by_ticket(page, "T123")
        self.assertIn("ticketnumber eq 'T123'", page.last_eval_arg)
        self.assertTrue(page.last_eval_arg.startswith("https://org.crm.dynamics.com/api/data/v9.2/incidents"))

    def test_a_single_quote_in_the_ticket_number_is_escaped_not_injected_raw(self):
        # Without escaping, a ticket number like "T1' or '1'='1" would break
        # out of the OData string literal -- confirms the doubling actually
        # happens in the constructed URL.
        page = FakePage("https://org.crm.dynamics.com/main.aspx", eval_result={"value": []})
        crm_scrape.lookup_by_ticket(page, "T1' or '1'='1")
        self.assertIn("ticketnumber eq 'T1'' or ''1''=''1'", page.last_eval_arg)
        self.assertNotIn("'1'='1'", page.last_eval_arg)

    def test_respects_a_custom_ticket_field_name(self):
        page = FakePage("https://org.crm.dynamics.com/main.aspx", eval_result={"value": []})
        crm_scrape.lookup_by_ticket(page, "T1", ticket_field="custom_ticketid")
        self.assertIn("custom_ticketid eq 'T1'", page.last_eval_arg)

    def test_fetch_error_is_surfaced_as_an_error_result(self):
        page = FakePage("https://org.crm.dynamics.com/main.aspx", eval_result={"__error": "HTTP 403: forbidden"})
        result = crm_scrape.lookup_by_ticket(page, "T1")
        self.assertEqual(result["error"], "HTTP 403: forbidden")

    def test_no_matching_case_is_a_clear_not_found_error_not_a_crash(self):
        page = FakePage("https://org.crm.dynamics.com/main.aspx", eval_result={"value": []})
        result = crm_scrape.lookup_by_ticket(page, "T404")
        self.assertIn("No case found", result["error"])

    def test_returns_the_first_match_mapped_via_to_result(self):
        case = {"incidentid": "id1", "ticketnumber": "T1"}
        page = FakePage("https://org.crm.dynamics.com/main.aspx", eval_result={"value": [case]})
        result = crm_scrape.lookup_by_ticket(page, "T1")
        self.assertEqual(result["ticket_number"], "T1")


class ExtractTests(unittest.TestCase):
    def test_extracts_a_plain_guid_from_the_url(self):
        page = FakePage(
            "https://org.crm.dynamics.com/main.aspx?pagetype=entityrecord&etn=incident&id=11111111-1111-1111-1111-111111111111",
            eval_result={"incidentid": "11111111-1111-1111-1111-111111111111", "ticketnumber": "T1"},
        )
        result = crm_scrape.extract(page)
        self.assertEqual(result["ticket_number"], "T1")

    def test_extracts_a_percent7b_encoded_guid_from_the_url(self):
        page = FakePage(
            "https://org.crm.dynamics.com/main.aspx?etn=incident&id=%7B22222222-2222-2222-2222-222222222222%7D",
            eval_result={"incidentid": "22222222-2222-2222-2222-222222222222"},
        )
        result = crm_scrape.extract(page)
        self.assertNotIn("error", result)

    def test_no_id_in_the_url_returns_an_error_without_calling_evaluate(self):
        page = FakePage("https://org.crm.dynamics.com/main.aspx?etn=incident")
        result = crm_scrape.extract(page)
        self.assertIn("error", result)
        self.assertIsNone(page.last_eval_arg)

    def test_fetch_error_is_surfaced_as_an_error_result(self):
        page = FakePage(
            "https://org.crm.dynamics.com/main.aspx?etn=incident&id=11111111-1111-1111-1111-111111111111",
            eval_result={"__error": "HTTP 500"},
        )
        result = crm_scrape.extract(page)
        self.assertEqual(result["error"], "HTTP 500")


if __name__ == "__main__":
    unittest.main()
