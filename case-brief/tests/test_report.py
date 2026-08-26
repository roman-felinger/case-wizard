"""Unit tests for lib/report.py, the Markdown brief builder.

Uses plain dict/list inputs -- no real CRM/ADO data needed, since by the
time anything reaches report.py it's already just dicts and lists (see
CLAUDE.md: "CRM and ADO results are plain dicts/lists by the time they
reach [report.py], with no formatting logic living in the scrapers
themselves"). Focus is on the things that would silently produce a
misleading brief rather than an ugly one: missing/empty sections must say so
explicitly rather than rendering blank, and an ado_error must suppress stale
branch/PR content instead of showing both.
Deliberately not exhaustive over exact Markdown wording/spacing -- that's
low-risk and easy to eyeball via `--demo`.

Run with: python -m unittest discover -s tests -v   (from case-brief/)
      or: python -m pytest tests                     (if pytest is installed)
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import report


class SafeNameTests(unittest.TestCase):
    def test_safe_name_replaces_unsafe_characters(self):
        self.assertEqual(report._safe_name("T26/11:845?"), "T26_11_845")

    def test_safe_name_falls_back_to_unlabeled_for_empty_string(self):
        self.assertEqual(report._safe_name(""), "unlabeled")


class BuildMarkdownMinimalInputTests(unittest.TestCase):
    def test_minimal_input_does_not_crash_and_notes_every_empty_section(self):
        md = report.build_markdown("T1", [], [], [])
        self.assertIn("# Case T1", md)
        self.assertIn("No CRM case data", md)
        # Nothing to report at all (no branches, no PRs, no CRM related
        # links, no Helpdesk link) -- one combined line naming all of them,
        # not a separate "not found" line per category.
        self.assertIn("_No branches, pull requests, related links, and a Helpdesk link found for this case._", md)

    def test_ado_error_suppresses_branch_and_pr_listing(self):
        branches = [{"project": "P", "repo": "R", "branch": "b", "url": "u"}]
        prs = [{"project": "P", "repo": "R", "id": 1, "title": "t", "status": "active", "created_by": "x", "url": "u"}]
        md = report.build_markdown("T1", [], branches, prs, ado_error="PAT missing")
        self.assertIn("Could not query Azure DevOps: PAT missing", md)
        # Even though branches/prs are non-empty, they must not be printed
        # alongside an error -- that would present a broken search as a
        # confirmed "these are the only results" listing.
        self.assertNotIn("[P/R: b]", md)
        self.assertNotIn("!1", md)
        # An error already explains the empty section -- branches/pull
        # requests must not also show up as "missing" in the combined line.
        self.assertIn("_No related links and a Helpdesk link found for this case._", md)
        self.assertNotIn("branches", md)
        self.assertNotIn("pull requests", md)


class BuildMarkdownCrmSectionTests(unittest.TestCase):
    def test_crm_error_result_is_flagged_with_a_warning_not_rendered_as_a_case(self):
        crm_results = [{"error": "No authenticated CRM tab found.", "url": "https://x"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("No authenticated CRM tab found.", md)

    def test_successful_crm_case_renders_its_fields(self):
        crm_results = [{
            "title": "Posting error", "ticket_number": "T1", "customer": "Contoso",
            "owner": "Jane", "priority": "High", "status": "Active",
            "created_on": "2026-08-01", "description": "Something broke.",
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("Posting error", md)
        self.assertIn("Contoso", md)
        self.assertIn("Something broke.", md)

    def test_missing_optional_crm_fields_render_as_an_em_dash_not_crash(self):
        crm_results = [{"ticket_number": "T1"}]  # everything else missing
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("—", md)

    def test_extra_fields_beyond_the_curated_summary_are_rendered(self):
        # This is the whole point of "get everything" -- a field crm_scrape
        # found that isn't part of the curated summary (e.g. an org's own
        # internal-only custom field) must show up in the brief, even if
        # it's not one of the specially-promoted fields (see
        # BuildMarkdownPromotedFieldsTests) -- just in the "Other CRM
        # Fields" catch-all instead of its own subsection.
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "new_internaldescription", "label": "Internal Description", "value": "agents only"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("**Internal Description** (`new_internaldescription`): agents only", md)

    def test_no_extra_fields_omits_the_other_crm_fields_heading(self):
        crm_results = [{"ticket_number": "T1", "all_fields": []}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertNotIn("Other CRM Fields", md)

    def test_notes_are_rendered_with_subject_and_text(self):
        crm_results = [{"ticket_number": "T1", "notes": [{"subject": "Repro", "text": "Reproduced locally.", "created_on": "2026-08-01"}]}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("Repro", md)
        self.assertIn("Reproduced locally.", md)

    def test_no_notes_says_so_explicitly(self):
        # Folded into Details' one combined "missing" line rather than its
        # own "**Notes:**" header + "no notes" line -- see
        # test_a_case_with_nothing_in_details_states_it_all_in_one_line.
        crm_results = [{"ticket_number": "T1"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("notes", md)
        self.assertNotIn("**Notes:**", md)

    def test_notes_error_is_shown_instead_of_a_blank_section(self):
        crm_results = [{"ticket_number": "T1", "notes_error": "HTTP 403"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("Could not load notes: HTTP 403", md)

    def test_notes_truncated_note_appears_only_when_flagged(self):
        crm_results = [{"ticket_number": "T1", "notes": [{"subject": "n"}], "notes_truncated": True}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("Only the most recent notes are shown", md)

    def test_activities_are_rendered_with_type_and_description(self):
        crm_results = [{"ticket_number": "T1", "activities": [
            {"type": "phonecall", "subject": "Callback", "status": "Completed", "description": "Confirmed the repro."},
        ]}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("phonecall", md)
        self.assertIn("Confirmed the repro.", md)

    def test_no_activities_says_so_explicitly(self):
        # Folded into Details' one combined "missing" line rather than its
        # own "**Activity Timeline:**" header + "no activities" line.
        crm_results = [{"ticket_number": "T1"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("activity timeline entries", md)
        self.assertNotIn("**Activity Timeline:**", md)

    def test_activities_error_is_shown_instead_of_a_blank_section(self):
        crm_results = [{"ticket_number": "T1", "activities_error": "HTTP 500"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("Could not load the activity timeline: HTTP 500", md)


class BuildMarkdownDetailsSectionTests(unittest.TestCase):
    """Description, promoted fields, Notes, and Activity Timeline are all
    grouped under one "## Details" heading, right after "## Related Links"
    -- see build_markdown."""

    def test_details_heading_comes_after_related_links_and_before_description(self):
        crm_results = [{"ticket_number": "T1", "description": "Something broke."}]
        md = report.build_markdown("T1", crm_results, [], [])
        related_idx = md.index("## Related Links")
        details_idx = md.index("## Details")
        description_idx = md.index("**Description:**")
        self.assertLess(related_idx, details_idx)
        self.assertLess(details_idx, description_idx)

    def test_a_case_with_nothing_in_details_states_it_all_in_one_line(self):
        # Everything optional in Details (both promoted fields, Notes,
        # Activity Timeline) missing at once -- one combined line naming
        # all four, not four separate "not found"/"(not filled in)" lines.
        crm_results = [{"ticket_number": "T1"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn(
            "_No Dodatečný veřejný popis, Interní popis & poznámky, notes, "
            "and activity timeline entries found for this case._", md)
        self.assertNotIn("_(not filled in)_", md)
        self.assertNotIn("**Notes:**", md)
        self.assertNotIn("**Activity Timeline:**", md)

    def test_details_heading_appears_once_per_rendered_case(self):
        crm_results = [
            {"ticket_number": "T1", "title": "Case One"},
            {"ticket_number": "T2", "title": "Case Two"},
        ]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertEqual(md.count("## Details"), 2)


class BuildMarkdownRelatedLinksTests(unittest.TestCase):
    """Covers "## Related Links": Azure DevOps branches/PRs resolved from a
    direct reference in the CRM case, the Dev tab's "Related links" grid
    (see crm_scrape.get_related_links), and the case's Helpdesk link, all
    combined into one section -- see report._related_links_lines."""

    def test_a_related_link_renders_as_a_markdown_link_with_status_and_date(self):
        crm_results = [{"ticket_number": "T1", "related_links": [
            {"name": "PR 20216 ✅ (CU-BTECH)", "url": "https://dev.azure.com/o/P/_git/R/pullrequest/20216",
             "status": "Active", "created_on": "2026-08-13T11:18:01Z"},
        ]}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("## Related Links", md)
        self.assertIn("[PR 20216 ✅ (CU-BTECH)](https://dev.azure.com/o/P/_git/R/pullrequest/20216)", md)
        self.assertIn("Active", md)
        self.assertIn("2026-08-13T11:18:01Z", md)

    def test_a_link_with_no_name_falls_back_to_the_url_as_the_label(self):
        crm_results = [{"ticket_number": "T1", "related_links": [{"name": None, "url": "https://dev.azure.com/x"}]}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("[https://dev.azure.com/x](https://dev.azure.com/x)", md)

    def test_related_links_error_is_shown_instead_of_the_list(self):
        crm_results = [{"ticket_number": "T1", "related_links_error": "HTTP 403"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("Could not load linked Azure DevOps items: HTTP 403", md)
        # The error already explains why nothing is listed -- "related
        # links" must not also show up as "missing" in the combined line.
        self.assertIn("_No branches, pull requests, and a Helpdesk link found for this case._", md)

    def test_nothing_found_at_all_is_stated_in_one_combined_line(self):
        crm_results = [{"ticket_number": "T1", "related_links": []}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("_No branches, pull requests, related links, and a Helpdesk link found for this case._", md)

    def test_helpdesk_link_renders_as_the_last_entry(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_helpdesklink", "label": "Helpdesk link",
                             "value": "https://artexhelpdesk.powerappsportals.com/support/edit-case/?id=1"}],
            "related_links": [{"name": "PR 1", "url": "https://dev.azure.com/o/P/_git/R/pullrequest/1"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("[Helpdesk link](https://artexhelpdesk.powerappsportals.com/support/edit-case/?id=1)", md)
        # Must come after the CRM related link -- "last member".
        self.assertLess(md.index("[PR 1]"), md.index("[Helpdesk link]"))
        # Present, so it must not also show up as "missing" in the combined line.
        self.assertIn("_No branches and pull requests found for this case._", md)

    def test_helpdesk_link_is_excluded_from_other_crm_fields(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_helpdesklink", "label": "Helpdesk link", "value": "https://x"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertNotIn("Other CRM Fields", md)  # the only field present was promoted into Related Links

    def test_helpdesk_link_missing_value_does_not_render_or_crash(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_helpdesklink", "label": "Helpdesk link", "value": None}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertNotIn("Helpdesk link]", md)
        self.assertIn("_No branches, pull requests, related links, and a Helpdesk link found for this case._", md)

    def test_ado_branches_and_prs_are_not_duplicated_across_multiple_cases(self):
        # Branches/PRs are whole-run, not per-case -- must appear only once
        # even though "## Related Links" itself renders once per case.
        branches = [{"project": "P", "repo": "R", "branch": "b", "url": "u"}]
        crm_results = [
            {"ticket_number": "T1", "title": "Case One"},
            {"ticket_number": "T2", "title": "Case Two"},
        ]
        md = report.build_markdown("T1", crm_results, branches, [])
        self.assertEqual(md.count("[P/R: b]"), 1)
        self.assertEqual(md.count("## Related Links"), 2)


class BuildMarkdownPromotedFieldsTests(unittest.TestCase):
    """Covers promoted_fields: specific CRM custom fields (matched by
    logical_name) get their own proper subsection right after Description,
    instead of being buried in the "Other CRM Fields" catch-all at the very
    bottom of the brief -- see report.py's module docstring / DEFAULT_PROMOTED_FIELDS."""

    def test_a_promoted_field_not_populated_on_the_case_is_named_in_the_combined_missing_line(self):
        # crm_scrape._extract_all_fields drops None/"" values entirely, so
        # an unfilled promoted field is simply absent from all_fields -- it
        # must still be named explicitly (using the field's documented
        # Czech label as a fallback -- there's no metadata-sourced label
        # available for a field that wasn't returned) in Details' combined
        # "missing" line, rather than silently vanishing from the brief.
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_internaldescriptionandnotes",
                             "label": "Interní popis & poznámky", "value": "internal notes"}],
            "notes": [{"subject": "n"}],
            "activities": [{"type": "call"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("_No Dodatečný veřejný popis found for this case._", md)
        self.assertNotIn("Interní popis & poznámky found for this case", md)

    def test_a_promoted_field_gets_its_own_subsection_after_description(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_internaldescriptionandnotes",
                             "label": "Interní popis & poznámky", "value": "internal analysis notes"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("**Interní popis & poznámky:**\n\ninternal analysis notes", md)

    def test_a_promoted_field_is_not_also_duplicated_in_the_other_crm_fields_section(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_internaldescriptionandnotes",
                             "label": "Interní popis & poznámky", "value": "internal analysis notes"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertNotIn("Other CRM Fields", md)  # the only field present was promoted, nothing leftover

    def test_non_promoted_fields_are_pushed_to_the_bottom_other_crm_fields_section(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "new_randomfield", "label": "Random Field", "value": "some value"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("## Other CRM Fields", md)
        # Must come after the case's own details -- "pull down ... to the bottom of the brief".
        self.assertGreater(md.index("## Other CRM Fields"), md.index("### "))
        # logical_name is shown alongside the label so a future promoted-field
        # pick doesn't require guessing it (see report.py's leftover rendering).
        self.assertIn("**Random Field** (`new_randomfield`): some value", md)

    def test_default_promoted_fields_put_the_public_description_before_the_internal_one(self):
        # The secondary/public description reads like a continuation of the
        # normal Description field, so it belongs right after it and before
        # the internal-only one -- see report.DEFAULT_PROMOTED_FIELDS.
        crm_results = [{
            "ticket_number": "T1",
            "description": "Customer-visible summary.",
            "all_fields": [
                {"logical_name": "art_internaldescriptionandnotes",
                 "label": "Interní popis & poznámky", "value": "internal notes"},
                {"logical_name": "art_additionalpublicdescription",
                 "label": "Dodatečný veřejný popis", "value": "public follow-up"},
            ],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertLess(md.index("Customer-visible summary."), md.index("Dodatečný veřejný popis"))
        self.assertLess(md.index("Dodatečný veřejný popis"), md.index("Interní popis & poznámky"))

    def test_custom_promoted_fields_param_overrides_the_default(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "new_randomfield", "label": "Random Field", "value": "some value"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [], promoted_fields=["new_randomfield"])
        self.assertIn("**Random Field:**\n\nsome value", md)
        self.assertNotIn("Other CRM Fields", md)

    def test_multiple_cases_with_leftover_fields_are_labeled_in_the_bottom_section(self):
        crm_results = [
            {"ticket_number": "T1", "title": "Case One",
             "all_fields": [{"logical_name": "new_a", "label": "A", "value": "1"}]},
            {"ticket_number": "T2", "title": "Case Two",
             "all_fields": [{"logical_name": "new_b", "label": "B", "value": "2"}]},
        ]
        md = report.build_markdown("T1", crm_results, [], [])
        other_section = md[md.index("## Other CRM Fields"):]
        # Each case's title appears again as its own subheading within the
        # bottom section (on top of its own heading up in CRM Case(s)) --
        # a single-case brief skips this subheading entirely (see the
        # non-promoted-field test above), it's only needed to disambiguate
        # which case a leftover field came from once there's more than one.
        self.assertIn("### Case One", other_section)
        self.assertIn("### Case Two", other_section)
        self.assertIn("**A** (`new_a`): 1", other_section)
        self.assertIn("**B** (`new_b`): 2", other_section)


class BuildMarkdownAdoNoteTests(unittest.TestCase):
    def test_ado_note_is_shown_when_present(self):
        md = report.build_markdown("T1", [], [], [],
                                    ado_note="Resolved 1/1 Azure DevOps reference(s) found directly in the CRM case.")
        self.assertIn("Resolved 1/1 Azure DevOps reference", md)

    def test_ado_note_is_omitted_when_none(self):
        md = report.build_markdown("T1", [], [], [], ado_note=None)
        self.assertNotIn("_None_", md)

    def test_ado_error_suppresses_the_note_too(self):
        md = report.build_markdown("T1", [], [], [], ado_error="PAT missing", ado_note="should not show")
        self.assertNotIn("should not show", md)


class BuildMarkdownRelatedLinksPlacementTests(unittest.TestCase):
    """"## Related Links" is deliberately pulled up next to a case's
    at-a-glance details (Ticket #/Customer/.../Created) rather than buried
    after Description/Notes/Activity Timeline -- see build_markdown."""

    def test_related_links_section_comes_right_after_the_details_and_before_the_details_heading(self):
        crm_results = [{"ticket_number": "T1", "description": "Something broke."}]
        md = report.build_markdown("T1", crm_results, [], [])
        created_idx = md.index("**Created:**")
        related_idx = md.index("## Related Links")
        details_idx = md.index("## Details")
        self.assertLess(created_idx, related_idx)
        self.assertLess(related_idx, details_idx)

    def test_related_links_section_still_renders_when_no_crm_case_was_found(self):
        md = report.build_markdown("T1", [], [], [])
        self.assertIn("## Related Links", md)

    def test_related_links_section_still_renders_when_every_crm_result_errored(self):
        crm_results = [{"error": "No authenticated CRM tab found.", "url": "https://x"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("## Related Links", md)


class WriteAndOpenTests(unittest.TestCase):
    def test_writes_the_markdown_to_a_sanitized_filename_under_output_dir(self):
        # _safe_name deliberately keeps dots (case numbers like "T26-11.845"
        # need them) so ".." can still appear as a substring of the filename
        # -- what actually matters is that path separators are stripped, so
        # the result is always one filename directly inside output_dir and
        # can never escape it as a nested/relative path.
        with tempfile.TemporaryDirectory() as d:
            path = report.write_and_open("content", d, "T1/../2")
            self.assertTrue(os.path.exists(path))
            self.assertEqual(os.path.dirname(os.path.abspath(path)), os.path.abspath(d))
            basename = os.path.basename(path)
            self.assertNotIn("/", basename)
            self.assertNotIn("\\", basename)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "content")

    def test_creates_output_dir_if_missing(self):
        with tempfile.TemporaryDirectory() as d:
            nested = os.path.join(d, "not-yet-created")
            path = report.write_and_open("content", nested, "T1")
            self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
