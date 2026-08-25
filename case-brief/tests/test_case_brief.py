"""Unit tests for case_brief.py's pure-logic pieces: run_ado_lookup's
direct-reference resolution and _collect_reference_text's text-flattening.

Deliberately not exhaustive over every CLI flag or every branch of
build_parser/main -- those are low-risk plumbing, easily eyeballed with
`--demo`-style manual runs. There is no config file at all here (org URL,
CRM ticket field/host pattern, Chrome profile -- all fixed constants; see
case_brief.py's module docstring), so there's no config-merge precedence
left to test the way case-guide/case-solve still have.

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
    def test_no_direct_reference_found_returns_empty_with_a_note(self):
        branches, prs, ado_error, ado_note = cb.run_ado_lookup([])
        self.assertEqual((branches, prs), ([], []))
        self.assertIsNone(ado_error)
        self.assertIn("No direct Azure DevOps link found", ado_note)

    def test_direct_reference_found_resolves_it(self):
        crm_results = [{"description": "https://dev.azure.com/myorg/P/_git/R/pullrequest/5"}]
        pr = {"project": "P", "id": 5, "repo": "R", "title": "t", "status": "active",
              "created_by": "x", "url": "u", "clone_url": None}
        with mock.patch.object(cb.ado_api, "get_pull_request", return_value=pr) as get_pr, \
             mock.patch.object(cb.ado_api, "parse_direct_references",
                                return_value=([{"project": "P", "repo": "R", "id": 5}], [])):
            branches, prs, ado_error, ado_note = cb.run_ado_lookup(crm_results)
        get_pr.assert_called_once_with("P", 5)
        self.assertEqual(prs, [pr])
        self.assertIsNone(ado_error)
        self.assertIn("Resolved 1/1", ado_note)

    def test_a_failed_direct_reference_is_reported_in_the_note_not_raised(self):
        crm_results = [{"description": "https://dev.azure.com/myorg/P/_git/R/pullrequest/5"}]
        with mock.patch.object(cb.ado_api, "get_pull_request", side_effect=RuntimeError("404")), \
             mock.patch.object(cb.ado_api, "parse_direct_references",
                                return_value=([{"project": "P", "repo": "R", "id": 5}], [])):
            branches, prs, ado_error, ado_note = cb.run_ado_lookup(crm_results)
        self.assertEqual(prs, [])
        self.assertIsNone(ado_error)
        self.assertIn("0/1", ado_note)
        self.assertIn("1 could not be resolved", ado_note)


if __name__ == "__main__":
    unittest.main()
