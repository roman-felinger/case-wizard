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
  - `_extract_all_fields` is what makes "get everything" actually work: a
    field not on any curated list (e.g. an org's own internal-only custom
    field) must still show up, with its lookup/optionset code resolved to
    the human-readable annotation rather than a raw GUID/number, and must
    not duplicate whatever's already in the curated summary.

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
    actually calls: `.url` and `.evaluate(js, arg)`.

    `eval_result`/`eval_error` answer every call the same way (fine for
    single-fetch tests); `routes` (a dict of {url_substring: result_or_exc})
    answers differently per URL, needed for lookup_by_ticket/extract which
    now make several fetches (the record itself, then metadata/notes/
    activities)."""
    def __init__(self, url, eval_result=None, eval_error=None, routes=None):
        self.url = url
        self._eval_result = eval_result if eval_result is not None else {}
        self._eval_error = eval_error
        self._routes = routes
        self.eval_calls = []

    def evaluate(self, js, arg=None):
        self.eval_calls.append(arg)
        if self._eval_error is not None:
            raise self._eval_error
        if self._routes is not None:
            for needle, value in self._routes.items():
                if needle in (arg or ""):
                    if isinstance(value, Exception):
                        raise value
                    return value
            return {"value": []}
        return self._eval_result

    @property
    def last_eval_arg(self):
        return self.eval_calls[-1] if self.eval_calls else None


def setUpModule():
    crm_scrape.reset_metadata_cache()


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

    def test_keeps_hyperlink_url_instead_of_discarding_it(self):
        # Regression: a rich-text link (e.g. an Azure DevOps PR pasted from
        # Outlook, or CRM's own "Web Portal Link") used to lose its href
        # entirely, since the generic tag-strip only kept the anchor text --
        # which then made the URL invisible to ado_api.parse_direct_references
        # too, not just to a human reading the brief.
        url = "https://dev.azure.com/artexis/BTECH/_git/CU-BTECH/pullrequest/1234"
        result = crm_scrape._strip_html(f'<a href="{url}">PR #1234</a>')
        self.assertIn("PR #1234", result)
        self.assertIn(url, result)

    def test_hyperlink_with_no_link_text_falls_back_to_the_url(self):
        url = "https://dev.azure.com/artexis/BTECH/_git/CU-BTECH/pullrequest/1234"
        result = crm_scrape._strip_html(f'<a href="{url}"></a>')
        self.assertEqual(result, url)

    def test_hyperlink_whose_text_is_already_the_url_is_not_duplicated(self):
        url = "https://dev.azure.com/artexis/BTECH/_git/CU-BTECH/pullrequest/1234"
        result = crm_scrape._strip_html(f'<a href="{url}">{url}</a>')
        self.assertEqual(result.count(url), 1)

    def test_mailto_link_keeps_just_the_visible_address(self):
        result = crm_scrape._strip_html('<a href="mailto:a@b.cz">a@b.cz</a>')
        self.assertEqual(result, "a@b.cz")
        self.assertNotIn("mailto:", result)


class ToResultTests(unittest.TestCase):
    def test_maps_dataverse_fields_via_annotations_not_expand(self):
        # No $expand nested dicts anymore -- customer/owner come from the
        # lookup's own display-name annotation, which (unlike the old
        # $expand=customerid_account/owninguser) works regardless of
        # whether the customer is an account or a contact, and regardless
        # of whether the case is owned by a user or a team.
        case = {
            "incidentid": "abc-123",
            "title": "Posting error",
            "ticketnumber": "T1",
            "prioritycode@OData.Community.Display.V1.FormattedValue": "High",
            "prioritycode": 1,
            "statuscode": 2,
            "createdon": "2026-08-01T00:00:00Z",
            "description": "<div>broke</div>",
            "_customerid_value": "guid-1",
            "_customerid_value@OData.Community.Display.V1.FormattedValue": "Contoso",
            "_ownerid_value": "guid-2",
            "_ownerid_value@OData.Community.Display.V1.FormattedValue": "Jane",
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

    def test_a_field_not_on_the_old_curated_select_list_still_shows_up(self):
        # The whole point: an org's own custom field (e.g. an "internal
        # description") used to be silently dropped by the fixed $select
        # list. It must now appear in all_fields.
        case = {"incidentid": "1", "new_internaldescription": "Only visible to agents"}
        result = crm_scrape._to_result(case, "https://x", "https://tab")
        labels = {f["logical_name"]: f for f in result["all_fields"]}
        self.assertIn("new_internaldescription", labels)
        self.assertEqual(labels["new_internaldescription"]["value"], "Only visible to agents")


class ExtractAllFieldsTests(unittest.TestCase):
    def test_prefers_metadata_label_over_the_raw_logical_name(self):
        record = {"new_internaldescription": "secret notes"}
        fields = crm_scrape._extract_all_fields(record, {"new_internaldescription": "Internal Description"}, set())
        self.assertEqual(fields[0]["label"], "Internal Description")

    def test_falls_back_to_the_logical_name_when_metadata_is_unavailable(self):
        record = {"new_internaldescription": "secret notes"}
        fields = crm_scrape._extract_all_fields(record, {}, set())
        self.assertEqual(fields[0]["label"], "new_internaldescription")

    def test_lookup_field_uses_the_display_name_annotation_not_the_raw_guid(self):
        record = {
            "_new_relatedcontractid_value": "11111111-1111-1111-1111-111111111111",
            "_new_relatedcontractid_value@OData.Community.Display.V1.FormattedValue": "Support Contract 2026",
        }
        fields = crm_scrape._extract_all_fields(record, {}, set())
        self.assertEqual(fields[0]["logical_name"], "new_relatedcontractid")
        self.assertEqual(fields[0]["value"], "Support Contract 2026")

    def test_optionset_field_uses_the_formatted_value_not_the_raw_code(self):
        record = {"new_severity": 2, "new_severity@OData.Community.Display.V1.FormattedValue": "Critical"}
        fields = crm_scrape._extract_all_fields(record, {}, set())
        self.assertEqual(fields[0]["value"], "Critical")

    def test_summary_fields_are_excluded_to_avoid_duplication(self):
        record = {"incidentid": "1", "title": "t", "ticketnumber": "T1", "description": "d"}
        fields = crm_scrape._extract_all_fields(record, {}, set())
        self.assertEqual(fields, [])

    def test_pure_plumbing_fields_are_excluded(self):
        record = {"versionnumber": 12345, "entityimage_url": "https://x/image"}
        fields = crm_scrape._extract_all_fields(record, {}, set())
        self.assertEqual(fields, [])

    def test_null_and_empty_values_are_excluded(self):
        record = {"new_a": None, "new_b": ""}
        fields = crm_scrape._extract_all_fields(record, {}, set())
        self.assertEqual(fields, [])

    def test_memo_field_html_is_stripped(self):
        record = {"new_internaldescription": "<div>line one</div><div>line two</div>"}
        fields = crm_scrape._extract_all_fields(record, {}, {"new_internaldescription"})
        self.assertNotIn("<div>", fields[0]["value"])
        self.assertIn("line one", fields[0]["value"])

    def test_html_looking_value_is_stripped_even_without_memo_metadata(self):
        # Metadata can fail to load entirely (see get_attribute_metadata) --
        # a heuristic HTML-tag check is the fallback so a memo field's HTML
        # doesn't leak into the brief unstripped just because metadata
        # wasn't available.
        record = {"new_internaldescription": "<p>hello</p>"}
        fields = crm_scrape._extract_all_fields(record, {}, set())
        self.assertNotIn("<p>", fields[0]["value"])

    def test_annotation_only_entries_are_not_emitted_as_their_own_field(self):
        record = {
            "new_severity": 2,
            "new_severity@OData.Community.Display.V1.FormattedValue": "Critical",
        }
        fields = crm_scrape._extract_all_fields(record, {}, set())
        self.assertEqual(len(fields), 1)


class GetAttributeMetadataTests(unittest.TestCase):
    def setUp(self):
        crm_scrape.reset_metadata_cache()

    def test_parses_labels_and_memo_fields_from_a_successful_response(self):
        page = FakePage("https://org.crm.dynamics.com/x", eval_result={
            "value": [
                {"LogicalName": "new_internaldescription",
                 "DisplayName": {"UserLocalizedLabel": {"Label": "Internal Description"}},
                 "AttributeTypeName": {"Value": "MemoType"}},
                {"LogicalName": "ticketnumber",
                 "DisplayName": {"UserLocalizedLabel": {"Label": "Ticket Number"}},
                 "AttributeTypeName": {"Value": "StringType"}},
            ]
        })
        labels, memo_fields = crm_scrape.get_attribute_metadata(page, "https://org.crm.dynamics.com")
        self.assertEqual(labels["new_internaldescription"], "Internal Description")
        self.assertEqual(labels["ticketnumber"], "Ticket Number")
        self.assertEqual(memo_fields, {"new_internaldescription"})

    def test_failure_degrades_to_empty_labels_rather_than_raising(self):
        page = FakePage("https://org.crm.dynamics.com/x", eval_result={"__error": "HTTP 403: forbidden"})
        labels, memo_fields = crm_scrape.get_attribute_metadata(page, "https://org.crm.dynamics.com")
        self.assertEqual(labels, {})
        self.assertEqual(memo_fields, set())

    def test_result_is_cached_per_origin(self):
        page = FakePage("https://org.crm.dynamics.com/x", eval_result={
            "value": [{"LogicalName": "a", "DisplayName": {"UserLocalizedLabel": {"Label": "A"}}}]
        })
        crm_scrape.get_attribute_metadata(page, "https://org.crm.dynamics.com")
        page._eval_result = {"value": []}  # would wipe labels if re-fetched
        labels, _ = crm_scrape.get_attribute_metadata(page, "https://org.crm.dynamics.com")
        self.assertEqual(labels["a"], "A")


class GetNotesTests(unittest.TestCase):
    def test_maps_and_strips_html_from_note_text(self):
        page = FakePage("https://x", eval_result={"value": [
            {"subject": "Repro", "notetext": "<div>works on my machine</div>", "createdon": "2026-08-01", "isdocument": False},
        ]})
        notes, truncated, error = crm_scrape.get_notes(page, "https://x", "id1")
        self.assertIsNone(error)
        self.assertFalse(truncated)
        self.assertEqual(notes[0]["subject"], "Repro")
        self.assertIn("works on my machine", notes[0]["text"])
        self.assertIsNone(notes[0]["filename"])

    def test_filename_only_kept_for_actual_documents(self):
        page = FakePage("https://x", eval_result={"value": [
            {"subject": "s", "notetext": None, "createdon": "d", "isdocument": True, "filename": "log.txt"},
        ]})
        notes, _, _ = crm_scrape.get_notes(page, "https://x", "id1")
        self.assertEqual(notes[0]["filename"], "log.txt")

    def test_hitting_the_cap_sets_truncated(self):
        page = FakePage("https://x", eval_result={"value": [{"subject": str(i)} for i in range(crm_scrape.NOTES_TOP)]})
        notes, truncated, _ = crm_scrape.get_notes(page, "https://x", "id1")
        self.assertTrue(truncated)

    def test_fetch_error_is_surfaced_not_raised(self):
        page = FakePage("https://x", eval_result={"__error": "HTTP 500"})
        notes, truncated, error = crm_scrape.get_notes(page, "https://x", "id1")
        self.assertEqual(notes, [])
        self.assertFalse(truncated)
        self.assertEqual(error, "HTTP 500")


class GetActivitiesTests(unittest.TestCase):
    def test_maps_activity_fields_preferring_formatted_status(self):
        page = FakePage("https://x", eval_result={"value": [
            {"subject": "Callback", "activitytypecode": "phonecall", "createdon": "d",
             "description": "<div>done</div>", "statuscode": 2,
             "statuscode@OData.Community.Display.V1.FormattedValue": "Completed"},
        ]})
        activities, truncated, error = crm_scrape.get_activities(page, "https://x", "id1")
        self.assertIsNone(error)
        self.assertFalse(truncated)
        self.assertEqual(activities[0]["status"], "Completed")
        self.assertIn("done", activities[0]["description"])

    def test_hitting_the_cap_sets_truncated(self):
        page = FakePage("https://x", eval_result={"value": [{"subject": str(i)} for i in range(crm_scrape.ACTIVITIES_TOP)]})
        _, truncated, _ = crm_scrape.get_activities(page, "https://x", "id1")
        self.assertTrue(truncated)

    def test_fetch_error_is_surfaced_not_raised(self):
        page = FakePage("https://x", eval_result={"__error": "HTTP 500"})
        activities, truncated, error = crm_scrape.get_activities(page, "https://x", "id1")
        self.assertEqual(activities, [])
        self.assertEqual(error, "HTTP 500")


class FindTabsTests(unittest.TestCase):
    def test_find_authenticated_tabs_filters_by_host_substring(self):
        pages = [FakePage("https://a.dynamics.com/x"), FakePage("https://other.example.com/y")]
        result = crm_scrape.find_authenticated_tabs(pages, ["dynamics.com"])
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


def _routes_for(case_value, metadata=None, notes=None, activities=None):
    """Builds a FakePage `routes` dict that answers each of _finish's
    fetches (the incident query itself, then metadata/notes/activities)
    distinctly by URL substring, defaulting the ones a test doesn't care
    about to an empty result."""
    return {
        "EntityDefinitions": metadata if metadata is not None else {"value": []},
        "annotations": notes if notes is not None else {"value": []},
        "activitypointers": activities if activities is not None else {"value": []},
        "incidents": case_value,
    }


class LookupByTicketTests(unittest.TestCase):
    def setUp(self):
        crm_scrape.reset_metadata_cache()

    def test_builds_the_expected_odata_filter_url_with_no_select(self):
        page = FakePage("https://org.crm.dynamics.com/main.aspx", routes=_routes_for({"value": []}))
        crm_scrape.lookup_by_ticket(page, "T123")
        first_call = page.eval_calls[0]
        self.assertIn("ticketnumber eq 'T123'", first_call)
        self.assertTrue(first_call.startswith("https://org.crm.dynamics.com/api/data/v9.2/incidents"))
        self.assertNotIn("$select", first_call)

    def test_a_single_quote_in_the_ticket_number_is_escaped_not_injected_raw(self):
        # Without escaping, a ticket number like "T1' or '1'='1" would break
        # out of the OData string literal -- confirms the doubling actually
        # happens in the constructed URL.
        page = FakePage("https://org.crm.dynamics.com/main.aspx", routes=_routes_for({"value": []}))
        crm_scrape.lookup_by_ticket(page, "T1' or '1'='1")
        self.assertIn("ticketnumber eq 'T1'' or ''1''=''1'", page.eval_calls[0])
        self.assertNotIn("'1'='1'", page.eval_calls[0])

    def test_respects_a_custom_ticket_field_name(self):
        page = FakePage("https://org.crm.dynamics.com/main.aspx", routes=_routes_for({"value": []}))
        crm_scrape.lookup_by_ticket(page, "T1", ticket_field="custom_ticketid")
        self.assertIn("custom_ticketid eq 'T1'", page.eval_calls[0])

    def test_fetch_error_on_the_main_query_is_surfaced_as_an_error_result(self):
        page = FakePage("https://org.crm.dynamics.com/main.aspx", eval_result={"__error": "HTTP 403: forbidden"})
        result = crm_scrape.lookup_by_ticket(page, "T1")
        self.assertEqual(result["error"], "HTTP 403: forbidden")

    def test_no_matching_case_is_a_clear_not_found_error_not_a_crash(self):
        page = FakePage("https://org.crm.dynamics.com/main.aspx", routes=_routes_for({"value": []}))
        result = crm_scrape.lookup_by_ticket(page, "T404")
        self.assertIn("No case found", result["error"])

    def test_returns_the_first_match_mapped_and_enriched_with_notes_and_activities(self):
        case = {"incidentid": "id1", "ticketnumber": "T1"}
        page = FakePage("https://org.crm.dynamics.com/main.aspx", routes=_routes_for(
            {"value": [case]},
            notes={"value": [{"subject": "n1"}]},
            activities={"value": [{"subject": "a1"}]},
        ))
        result = crm_scrape.lookup_by_ticket(page, "T1")
        self.assertEqual(result["ticket_number"], "T1")
        self.assertEqual(len(result["notes"]), 1)
        self.assertEqual(len(result["activities"]), 1)
        self.assertEqual(result["all_fields"], [])



if __name__ == "__main__":
    unittest.main()
