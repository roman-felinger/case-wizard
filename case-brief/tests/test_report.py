"""Unit tests for lib/report.py, the Markdown brief builder.

Uses plain dict/list inputs -- no real CRM/ADO data needed, since by the
time anything reaches report.py it's already just dicts and lists (see
CLAUDE.md: "CRM and ADO results are plain dicts/lists by the time they
reach [report.py], with no formatting logic living in the scrapers
themselves"). Focus is on the things that would silently produce a
misleading brief rather than an ugly one: missing/empty sections must say so
explicitly rather than rendering blank, an ado_error must suppress stale
branch/PR content instead of showing both, and `write_and_open` must never
let a missing/failing `code` executable stop the brief from being written.
Deliberately not exhaustive over exact Markdown wording/spacing -- that's
low-risk and easy to eyeball via `--demo`.

Run with: python -m unittest discover -s tests -v   (from case-brief/)
      or: python -m pytest tests                     (if pytest is installed)
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

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
        self.assertIn("No CRM case tab found open", md)
        self.assertIn("No matching branches found", md)
        self.assertIn("No matching pull requests found", md)

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

    def test_prs_truncated_note_appears_only_when_flagged(self):
        md_truncated = report.build_markdown("T1", [], [], [{"project": "P", "repo": "R", "id": 1, "title": "t",
                                                              "status": "active", "created_by": "x", "url": "u"}],
                                              prs_truncated=True, max_prs=50)
        self.assertIn("Only searched the 50 most recent pull requests", md_truncated)
        md_not_truncated = report.build_markdown("T1", [], [], [], prs_truncated=False)
        self.assertNotIn("Only searched", md_not_truncated)


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
        self.assertIn("**Internal Description:** agents only", md)

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
        crm_results = [{"ticket_number": "T1"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("No notes on this case", md)

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
        crm_results = [{"ticket_number": "T1"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("No activities recorded on this case", md)

    def test_activities_error_is_shown_instead_of_a_blank_section(self):
        crm_results = [{"ticket_number": "T1", "activities_error": "HTTP 500"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("Could not load the activity timeline: HTTP 500", md)


class BuildMarkdownPromotedFieldsTests(unittest.TestCase):
    """Covers promoted_fields: specific CRM custom fields (matched by
    logical_name) get their own proper subsection right after Description,
    instead of being buried in the "Other CRM Fields" catch-all at the very
    bottom of the brief -- see report.py's module docstring / DEFAULT_PROMOTED_FIELDS."""

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
        self.assertIn("**Random Field:** some value", md)

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
        self.assertIn("**A:** 1", other_section)
        self.assertIn("**B:** 2", other_section)


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


class BuildMarkdownAdoSectionPlacementTests(unittest.TestCase):
    """The Azure DevOps section is deliberately pulled up next to a case's
    at-a-glance details (Ticket #/Customer/.../Created) rather than buried
    after Description/Notes/Activity Timeline -- see build_markdown."""

    def test_ado_section_comes_right_after_the_details_and_before_description(self):
        crm_results = [{"ticket_number": "T1", "description": "Something broke."}]
        md = report.build_markdown("T1", crm_results, [], [])
        created_idx = md.index("**Created:**")
        ado_idx = md.index("## Azure DevOps")
        description_idx = md.index("**Description:**")
        self.assertLess(created_idx, ado_idx)
        self.assertLess(ado_idx, description_idx)

    def test_ado_section_still_renders_when_no_crm_case_was_found(self):
        md = report.build_markdown("T1", [], [], [])
        self.assertIn("## Azure DevOps", md)

    def test_ado_section_still_renders_when_every_crm_result_errored(self):
        crm_results = [{"error": "No authenticated CRM tab found.", "url": "https://x"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("## Azure DevOps", md)

    def test_ado_section_appears_only_once_with_multiple_cases(self):
        crm_results = [
            {"ticket_number": "T1", "title": "Case One"},
            {"ticket_number": "T2", "title": "Case Two"},
        ]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertEqual(md.count("## Azure DevOps"), 1)


class WriteAndOpenTests(unittest.TestCase):
    def test_writes_the_markdown_to_a_sanitized_filename_under_output_dir(self):
        # _safe_name deliberately keeps dots (case numbers like "T26-11.845"
        # need them) so ".." can still appear as a substring of the filename
        # -- what actually matters is that path separators are stripped, so
        # the result is always one filename directly inside output_dir and
        # can never escape it as a nested/relative path.
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("shared.editor.subprocess.run") as run_mock:
                path = report.write_and_open("content", d, "T1/../2", open_in_vscode=False)
            run_mock.assert_not_called()
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
            with mock.patch("shared.editor.subprocess.run"):
                path = report.write_and_open("content", nested, "T1", open_in_vscode=False)
            self.assertTrue(os.path.exists(path))

    def test_open_in_vscode_true_invokes_subprocess_run(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("shared.editor.shutil.which", return_value="C:/fake/code.cmd"), \
                 mock.patch("shared.editor.subprocess.run") as run_mock:
                report.write_and_open("content", d, "T1", open_in_vscode=True)
            run_mock.assert_called_once()

    def test_missing_code_executable_does_not_prevent_the_file_from_being_written(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("shared.editor.shutil.which", return_value=None):
                path = report.write_and_open("content", d, "T1", open_in_vscode=True)
            self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
