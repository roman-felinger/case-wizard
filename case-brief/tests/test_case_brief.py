"""Unit tests for case_brief.py's pure-logic pieces: run_ado_lookup's
direct-reference resolution and _collect_reference_text's text-flattening.

Deliberately not exhaustive over every CLI flag or every branch of
build_parser/main -- those are low-risk plumbing, easily eyeballed with
`--demo`-style manual runs. There is no config file at all here (org URL,
CRM ticket field, Dataverse OAuth client/authority -- all fixed constants;
see case_brief.py's module docstring), so there's no config-merge
precedence left to test the way case-guide/case-solve still have.

Run with: python -m unittest discover -s tests -v   (from case-brief/)
      or: python -m pytest tests                     (if pytest is installed)
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import case_brief as cb


class CollectReferenceTextTests(unittest.TestCase):
    def test_gathers_title_description_extra_fields_notes_and_activities(self):
        crm_results = [{
            "title": "T", "description": "D",
            "all_fields": [{"value": "F"}],
            "notes": [{"subject": "NS", "text": "NT"}],
            "activities": [{"subject": "AS", "description": "AD"}],
        }]
        text = cb._collect_reference_text(crm_results)
        for expected in ("T", "D", "F", "NS", "NT", "AS", "AD"):
            self.assertIn(expected, text)

    def test_does_not_gather_related_links(self):
        # The Dev tab's own "Related links" grid (see
        # crm_scrape.get_related_links) is deliberately NOT part of this
        # scan -- report.py renders those directly from the CRM data
        # already, so scanning them here too would just mean resolving
        # them via the ADO API only to immediately discard the result as a
        # duplicate. See run_ado_lookup/_related_link_refs, which excludes
        # anything already covered by related_links a different way --
        # from the related_links data itself, not this text blob.
        crm_results = [{"related_links": [
            {"name": "PR 20216 ✅ (CU-BTECH)", "url": "https://dev.azure.com/o/P/_git/R/pullrequest/20216"},
        ]}]
        text = cb._collect_reference_text(crm_results)
        self.assertNotIn("PR 20216 ✅ (CU-BTECH)", text)
        self.assertNotIn("https://dev.azure.com/o/P/_git/R/pullrequest/20216", text)

    def test_error_result_is_skipped(self):
        crm_results = [{"error": "boom", "url": "https://x"}]
        self.assertEqual(cb._collect_reference_text(crm_results), "")

    def test_non_string_values_do_not_crash(self):
        crm_results = [{"title": None, "all_fields": [{"value": 123}], "notes": [{"subject": None}]}]
        self.assertEqual(cb._collect_reference_text(crm_results), "")

    def test_empty_or_none_input_returns_empty_string(self):
        self.assertEqual(cb._collect_reference_text([]), "")
        self.assertEqual(cb._collect_reference_text(None), "")


class RunAdoLookupTests(unittest.TestCase):
    def test_no_direct_reference_found_returns_empty_with_no_note(self):
        # No ADO-specific "nothing found" message here -- report.py's "##
        # Related Links" section says so generically once it's seen the
        # combined result (ADO refs + CRM related links + Helpdesk link)
        # come up empty, so a redundant note isn't needed.
        branches, prs, ado_error, ado_note = cb.run_ado_lookup([])
        self.assertEqual((branches, prs), ([], []))
        self.assertIsNone(ado_error)
        self.assertIsNone(ado_note)

    @staticmethod
    def _parse_one_pr_unless_empty(text):
        # Stand-in for ado_api.parse_direct_references: run_ado_lookup
        # calls the real function twice -- once over the full reference
        # text, once (via _related_link_refs) over just the related-links
        # URLs -- so a flat return_value would make both calls return the
        # same ref and the dedup logic would then filter it out against
        # itself. Empty input (the related-links scan, when a test's
        # crm_results has none) must come back empty; non-empty input (the
        # main scan) returns the one fixed PR ref.
        if not text:
            return [], []
        return [{"project": "P", "repo": "R", "id": 5}], []

    def test_direct_reference_found_resolves_it(self):
        crm_results = [{"description": "https://dev.azure.com/myorg/P/_git/R/pullrequest/5"}]
        pr = {"project": "P", "id": 5, "repo": "R", "title": "t", "status": "active",
              "created_by": "x", "url": "u", "clone_url": None}
        with mock.patch.object(cb.ado_api, "get_pull_request", return_value=pr) as get_pr, \
             mock.patch.object(cb.ado_api, "parse_direct_references",
                                side_effect=self._parse_one_pr_unless_empty):
            branches, prs, ado_error, ado_note = cb.run_ado_lookup(crm_results)
        get_pr.assert_called_once_with("P", 5)
        self.assertEqual(prs, [pr])
        self.assertIsNone(ado_error)
        self.assertIn("Resolved 1/1", ado_note)

    def test_a_failed_direct_reference_is_reported_in_the_note_not_raised(self):
        crm_results = [{"description": "https://dev.azure.com/myorg/P/_git/R/pullrequest/5"}]
        with mock.patch.object(cb.ado_api, "get_pull_request", side_effect=RuntimeError("404")), \
             mock.patch.object(cb.ado_api, "parse_direct_references",
                                side_effect=self._parse_one_pr_unless_empty):
            branches, prs, ado_error, ado_note = cb.run_ado_lookup(crm_results)
        self.assertEqual(prs, [])
        self.assertIsNone(ado_error)
        self.assertIn("0/1", ado_note)
        self.assertIn("1 could not be resolved", ado_note)

    def test_a_pr_already_covered_by_related_links_is_excluded_and_not_resolved(self):
        # The same PR pasted into the description (or mentioned anywhere
        # else the text scan covers) as well as attached in CRM's own
        # Dev-tab related links grid -- report.py already renders it via
        # related_links, so it must not also turn up here (that would link
        # the same PR twice in the rendered brief) -- and, since it's
        # getting excluded either way, must not even be resolved via the
        # ADO API (a wasted call otherwise). Uses the real ado_api.ORG_URL
        # org ("artexis") rather than a mocked parse_direct_references,
        # since the exclusion logic itself is what's under test here.
        crm_results = [{
            "description": "https://dev.azure.com/artexis/P/_git/R/pullrequest/5",
            "related_links": [{"name": "PR 5", "url": "https://dev.azure.com/artexis/P/_git/R/pullrequest/5"}],
        }]
        with mock.patch.object(cb.ado_api, "get_pull_request") as get_pr:
            branches, prs, ado_error, ado_note = cb.run_ado_lookup(crm_results)
        get_pr.assert_not_called()
        self.assertEqual((branches, prs), ([], []))
        self.assertIsNone(ado_note)

    def test_a_pr_not_covered_by_related_links_is_still_resolved(self):
        # A related link covering a *different* PR must not suppress this
        # one -- only an exact (project, id) match is excluded.
        crm_results = [{
            "description": "https://dev.azure.com/artexis/P/_git/R/pullrequest/5",
            "related_links": [{"name": "PR 9", "url": "https://dev.azure.com/artexis/P/_git/R/pullrequest/9"}],
        }]
        pr = {"project": "P", "id": 5, "repo": "R", "title": "t", "status": "active",
              "created_by": "x", "url": "u", "clone_url": None}
        with mock.patch.object(cb.ado_api, "get_pull_request", return_value=pr) as get_pr:
            branches, prs, ado_error, ado_note = cb.run_ado_lookup(crm_results)
        get_pr.assert_called_once_with("P", 5)
        self.assertEqual(prs, [pr])


if __name__ == "__main__":
    unittest.main()
