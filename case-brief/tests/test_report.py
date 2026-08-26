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


class SanitizeFreetextForMarkdownTests(unittest.TestCase):
    """_sanitize_freetext_for_markdown fixes two real, observed failure
    modes in CRM freetext (description/notes/activities/promoted fields) --
    see the function's own docstring."""

    def test_nbsp_only_line_becomes_a_real_blank_line(self):
        # CRM's own blank-paragraph marker (U+00A0) doesn't read as a
        # paragraph break to Markdown -- normalized to an actual empty line.
        text = "First paragraph.\n\xa0\nSecond paragraph."
        out = report._sanitize_freetext_for_markdown(text)
        self.assertEqual(out, "First paragraph.\n\nSecond paragraph.")

    def test_a_lone_dash_line_is_escaped_so_it_cannot_become_a_setext_heading(self):
        # A paragraph immediately followed by a dashes-only line would
        # otherwise render as one giant <h1>/<h2> instead of a paragraph
        # plus a divider -- this happened for real with a description
        # ending in a lone "--" line.
        text = "Some paragraph text\n--"
        out = report._sanitize_freetext_for_markdown(text)
        self.assertEqual(out, "Some paragraph text\n\\--")

    def test_a_lone_equals_line_is_escaped_too(self):
        text = "Some paragraph text\n===="
        out = report._sanitize_freetext_for_markdown(text)
        self.assertEqual(out, "Some paragraph text\n\\====")

    def test_a_heading_marker_line_is_escaped(self):
        text = "# Not actually a heading"
        out = report._sanitize_freetext_for_markdown(text)
        self.assertEqual(out, "\\# Not actually a heading")

    def test_ordinary_text_passes_through_unchanged(self):
        text = "Just a normal paragraph with - a dash in the middle."
        self.assertEqual(report._sanitize_freetext_for_markdown(text), text)

    def test_none_and_empty_string_pass_through_unchanged(self):
        self.assertIsNone(report._sanitize_freetext_for_markdown(None))
        self.assertEqual(report._sanitize_freetext_for_markdown(""), "")


class BuildMarkdownMinimalInputTests(unittest.TestCase):
    def test_minimal_input_does_not_crash_and_notes_every_empty_section(self):
        md = report.build_markdown("T1", [], [], [])
        self.assertIn("# Case T1", md)
        self.assertIn("No CRM case data", md)
        # No CRM related links found (the only category ever reported
        # "missing" -- see BuildMarkdownRelatedLinksTests' class
        # docstring: branches/PRs and the Helpdesk link are never reported
        # as missing, even when genuinely absent).
        self.assertIn("_No linked Azure DevOps items found for this case._", md)

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
        # Branches/PRs are never reported as "missing" (see
        # BuildMarkdownRelatedLinksTests' class docstring), error or not --
        # only related_links is.
        self.assertIn("_No linked Azure DevOps items found for this case._", md)
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
        # BuildMarkdownPromotedFieldsTests) -- just in the "Other
        # Populated CRM Fields" catch-all instead of its own subsection.
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "new_internaldescription", "label": "Internal Description", "value": "agents only"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("**Internal Description** (`new_internaldescription`): agents only", md)

    def test_no_extra_fields_omits_the_other_crm_fields_heading(self):
        crm_results = [{"ticket_number": "T1", "all_fields": []}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertNotIn("Other Populated CRM Fields", md)

    def test_notes_are_rendered_with_subject_and_text(self):
        crm_results = [{"ticket_number": "T1", "notes": [{"subject": "Repro", "text": "Reproduced locally.", "created_on": "2026-08-01"}]}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("Repro", md)
        self.assertIn("Reproduced locally.", md)

    def test_notes_error_is_shown_instead_of_a_blank_section(self):
        crm_results = [{"ticket_number": "T1", "notes_error": "HTTP 403"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("Could not load notes: HTTP 403", md)

    def test_notes_truncated_note_appears_only_when_flagged(self):
        crm_results = [{"ticket_number": "T1", "notes": [{"subject": "n"}], "notes_truncated": True}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("Only the most recent notes are shown", md)

    def test_text_attachment_is_inlined_as_a_code_block(self):
        crm_results = [{"ticket_number": "T1", "notes": [{
            "id": "a1", "subject": "s", "text": None, "filename": "error.log", "filesize": 42,
            "attachment": {"kind": "text", "content": "boom at line 12", "truncated": False},
        }]}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("error.log", md)
        self.assertIn("```\nboom at line 12\n```", md)

    def test_truncated_text_attachment_says_so(self):
        crm_results = [{"ticket_number": "T1", "notes": [{
            "id": "a1", "subject": "s", "text": None, "filename": "big.log",
            "attachment": {"kind": "text", "content": "partial...", "truncated": True},
        }]}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("attachment truncated", md)

    def test_image_attachment_renders_a_relative_markdown_image_link_not_a_data_uri(self):
        crm_results = [{"ticket_number": "T1", "notes": [{
            "id": "a1b2c3d4e5", "subject": "s", "text": None, "filename": "screenshot.png",
            "attachment": {"kind": "image", "bytes": b"\x89PNG..."},
        }]}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("![screenshot.png](attachments/T1/a1b2c3d4-screenshot.png)", md)
        self.assertNotIn("base64", md)  # no inline data URI -- see report._note_attachment_lines

    def test_attachment_too_large_or_wrong_type_is_named_only(self):
        # Same as behavior before this feature existed -- filename (+ size,
        # now that it's known) with no content, pointing back to CRM.
        crm_results = [{"ticket_number": "T1", "notes": [{
            "id": "a1", "subject": "s", "text": None, "filename": "dump.zip", "filesize": 5_000_000,
            "attachment": None,
        }]}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("dump.zip", md)
        self.assertIn("not included in this brief", md)
        self.assertNotIn("```", md)

    def test_activities_are_rendered_with_type_and_description(self):
        crm_results = [{"ticket_number": "T1", "activities": [
            {"type": "phonecall", "subject": "Callback", "status": "Completed", "description": "Confirmed the repro."},
        ]}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("phonecall", md)
        self.assertIn("Confirmed the repro.", md)

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
        # Everything optional in Details (Description, both promoted
        # fields, Notes, Activity Timeline) missing at once -- one combined
        # line naming all five, not five separate "not found"/"(not filled
        # in)"/"_(none)_" lines.
        crm_results = [{"ticket_number": "T1"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn(
            "_No Description, Additional Public Description, Internal Description, Notes, "
            "and Activity Timeline found for this case._", md)
        self.assertNotIn("_(not filled in)_", md)
        self.assertNotIn("_(none)_", md)
        self.assertNotIn("**Description:**", md)
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
    """Covers "## Related Links": the case's own CRM record link and its
    Helpdesk link first -- both always available on a real case -- then
    the optional, may-or-may-not-exist stuff: the Dev tab's "Related
    links" grid (see crm_scrape.get_related_links), and finally Azure
    DevOps branches/PRs resolved from a direct reference found elsewhere
    in the CRM case (already deduplicated against the Dev-tab grid by
    case_brief.py before it gets here -- see case_brief.py's own tests)
    -- all combined into one section, in that order -- see
    report._related_links_lines."""

    def test_the_case_link_renders_first_then_the_helpdesk_link(self):
        crm_results = [{
            "ticket_number": "T1",
            "url": "https://artex-crm.crm4.dynamics.com/main.aspx?appid=x&forceUCI=1&pagetype=entityrecord&etn=incident&id=1",
            "related_links": [{"name": "PR 1", "url": "https://dev.azure.com/o/P/_git/R/pullrequest/1"}],
            "all_fields": [{"logical_name": "art_helpdesklink", "label": "Helpdesk link", "value": "https://x"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        case_url = ("https://artex-crm.crm4.dynamics.com/main.aspx?appid=x&forceUCI=1"
                    "&pagetype=entityrecord&etn=incident&id=1")
        self.assertIn(f"Case link: [{case_url}]({case_url})", md)
        # Case link, then Helpdesk link -- both always available on a real
        # case -- ahead of the optional Dev-tab related link.
        related_idx = md.index("## Related Links")
        self.assertLess(md.index("Case link:", related_idx), md.index("Helpdesk link:"))
        self.assertLess(md.index("Helpdesk link:"), md.index("PR 1:"))

    def test_a_missing_case_url_is_not_counted_as_missing(self):
        # Unlike the Dev-tab links/branches/PRs, the case's own link isn't
        # an optional related resource -- so its absence must never show
        # up in the combined "missing" line.
        crm_results = [{"ticket_number": "T1"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertNotIn("Case link", md)
        self.assertNotIn("a case link", md)

    def test_a_related_link_renders_with_a_plain_text_label_and_the_url_as_the_hyperlink(self):
        # Unlike the ADO-resolved branches/PRs below it in the section, a
        # related link's label is plain text and the URL itself is the
        # hyperlink -- same convention as the Helpdesk link, and readable/
        # copyable without clicking through. Status/created-on are
        # deliberately not shown -- CRM's own snapshot from whenever the
        # link was attached, not refreshed since, unlike the ADO section.
        crm_results = [{"ticket_number": "T1", "related_links": [
            {"name": "PR 20216 ✅ (CU-BTECH)", "url": "https://dev.azure.com/o/P/_git/R/pullrequest/20216",
             "status": "Active", "created_on": "2026-08-13T11:18:01Z"},
        ]}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("## Related Links", md)
        self.assertIn(
            "- PR 20216 ✅ (CU-BTECH): [https://dev.azure.com/o/P/_git/R/pullrequest/20216]"
            "(https://dev.azure.com/o/P/_git/R/pullrequest/20216)", md)
        self.assertNotIn("Active", md)
        self.assertNotIn("2026-08-13T11:18:01Z", md)

    def test_a_link_with_no_name_falls_back_to_the_url_as_the_label(self):
        crm_results = [{"ticket_number": "T1", "related_links": [{"name": None, "url": "https://dev.azure.com/x"}]}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("- https://dev.azure.com/x: [https://dev.azure.com/x](https://dev.azure.com/x)", md)

    def test_related_links_error_is_shown_instead_of_the_list(self):
        crm_results = [{"ticket_number": "T1", "related_links_error": "HTTP 403"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("Could not load linked Azure DevOps items: HTTP 403", md)
        # The error already explains why nothing is listed -- "linked
        # Azure DevOps items" must not also show up as "missing" in the
        # combined line. Nothing else (case link, Helpdesk link, branches/
        # PRs) is ever reported missing at all (see the class docstring),
        # so with the only trackable category errored out, no "missing"
        # line is emitted at all. Sliced to "## Related Links" only --
        # "## Details" has its own, unrelated combined "missing" line.
        related_section = md[md.index("## Related Links"):md.index("## Details")]
        self.assertNotIn("found for this case", related_section)

    def test_nothing_found_at_all_is_stated_in_one_combined_line(self):
        # Only related_links is ever reported missing -- branches/PRs
        # aren't (even genuinely empty, see the class docstring), and
        # case link/Helpdesk link never are.
        crm_results = [{"ticket_number": "T1", "related_links": []}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("_No linked Azure DevOps items found for this case._", md)

    def test_helpdesk_link_renders_before_related_links_and_ado(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_helpdesklink", "label": "Helpdesk link",
                             "value": "https://artexhelpdesk.powerappsportals.com/support/edit-case/?id=1"}],
            "related_links": [{"name": "PR 1", "url": "https://dev.azure.com/o/P/_git/R/pullrequest/1"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        # Label is plain text, not the hyperlink -- the URL itself is.
        self.assertIn("Helpdesk link: [https://artexhelpdesk.powerappsportals.com/support/edit-case/?id=1]"
                       "(https://artexhelpdesk.powerappsportals.com/support/edit-case/?id=1)", md)
        # Helpdesk link -- always available -- comes before the optional
        # Dev-tab related link, and before the (here empty) ADO
        # branches/PRs block -- see the class docstring for the order.
        self.assertLess(md.index("Helpdesk link:"), md.index("PR 1:"))
        # Branches/PRs genuinely empty here, but that's never reported as
        # "missing" -- see the class docstring. Sliced to "## Related
        # Links" only -- "## Details" has its own, unrelated combined
        # "missing" line.
        related_section = md[md.index("## Related Links"):md.index("## Details")]
        self.assertNotIn("found for this case", related_section)

    def test_helpdesk_link_is_excluded_from_other_crm_fields(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_helpdesklink", "label": "Helpdesk link", "value": "https://x"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertNotIn("Other Populated CRM Fields", md)  # the only field present was promoted into Related Links

    def test_helpdesk_link_missing_value_does_not_render_or_crash(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_helpdesklink", "label": "Helpdesk link", "value": None}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertNotIn("Helpdesk link:", md)
        # Absence of the Helpdesk link is never reported as "missing" --
        # see the class docstring -- so only related_links shows up.
        self.assertIn("_No linked Azure DevOps items found for this case._", md)

    def test_helpdesk_link_label_is_plain_text_and_the_url_itself_is_the_hyperlink(self):
        # Unlike the ADO-resolved branches/PRs (label as the hyperlink),
        # the Helpdesk link's own label is plain text and the URL is both
        # the hyperlink's target *and* its visible text -- so it's
        # clickable and still readable/copyable without clicking through.
        # Same convention as the related-links bullets above it.
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_helpdesklink", "label": "Helpdesk link",
                             "value": "https://artexhelpdesk.powerappsportals.com/support/edit-case/?id=1"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn(
            "Helpdesk link: [https://artexhelpdesk.powerappsportals.com/support/edit-case/?id=1]"
            "(https://artexhelpdesk.powerappsportals.com/support/edit-case/?id=1)", md)
        self.assertNotIn("[Helpdesk link]", md)

    def test_a_helpdesk_link_with_no_other_related_links_does_not_read_as_contradictory(self):
        # Regression: a case with only a Helpdesk link (no ADO branches/
        # PRs/Dev-tab grid entries) must not say "No ... related links ...
        # found" right below a Helpdesk link bullet -- that reads as
        # self-contradictory, since the Helpdesk link IS a related link.
        # The Dev-tab-grid-specific "missing" category is named distinctly
        # ("linked Azure DevOps items") so this never happens.
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_helpdesklink", "label": "Helpdesk link",
                             "value": "https://artexhelpdesk.powerappsportals.com/support/edit-case/?id=1"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("Helpdesk link:", md)
        self.assertNotIn("related links found for this case", md)
        self.assertIn("_No linked Azure DevOps items found for this case._", md)

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

    def test_no_branches_or_pull_requests_never_states_a_not_found_line(self):
        # Regression: a case genuinely having no branches/PRs isn't worth
        # a dedicated "not found" callout every time (unlike related_links,
        # which still gets one) -- see the class docstring. Must hold even
        # with everything else present, and even with an ado_note.
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_helpdesklink", "label": "Helpdesk link", "value": "https://x"}],
            "related_links": [{"name": "PR 1", "url": "https://dev.azure.com/o/P/_git/R/pullrequest/1"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [],
                                    ado_note="Resolved 0/0 Azure DevOps reference(s) found directly in the CRM case.")
        self.assertNotIn("branches", md)
        self.assertNotIn("pull requests", md)
        # Sliced to "## Related Links" only -- "## Details" has its own,
        # unrelated combined "missing" line.
        related_section = md[md.index("## Related Links"):md.index("## Details")]
        self.assertNotIn("found for this case", related_section)


class BuildMarkdownPromotedFieldsTests(unittest.TestCase):
    """Covers promoted_fields: specific CRM custom fields (matched by
    logical_name) get their own proper subsection right after Description,
    instead of being buried in the "Other Populated CRM Fields" catch-all at the very
    bottom of the brief -- see report.py's module docstring / DEFAULT_PROMOTED_FIELDS."""

    def test_a_promoted_field_not_populated_on_the_case_is_named_in_the_combined_missing_line(self):
        # crm_scrape._extract_all_fields drops None/"" values entirely, so
        # an unfilled promoted field is simply absent from all_fields -- it
        # must still be named explicitly (using the field's fixed English
        # label -- there's no metadata-sourced label available for a field
        # that wasn't returned) in Details' combined "missing" line, rather
        # than silently vanishing from the brief.
        crm_results = [{
            "ticket_number": "T1",
            "description": "Something broke.",
            "all_fields": [{"logical_name": "art_internaldescriptionandnotes",
                             "label": "Interní popis & poznámky", "value": "internal notes"}],
            "notes": [{"subject": "n"}],
            "activities": [{"type": "call"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("_No Additional Public Description found for this case._", md)
        self.assertNotIn("Internal Description found for this case", md)

    def test_a_promoted_field_gets_its_own_subsection_after_description(self):
        # The header uses the fixed English label, overriding whatever
        # (Czech, on this org) label the CRM metadata call returned.
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_internaldescriptionandnotes",
                             "label": "Interní popis & poznámky", "value": "internal analysis notes"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("**Internal Description:**\n\ninternal analysis notes", md)
        self.assertNotIn("Interní popis & poznámky", md)

    def test_a_promoted_field_is_not_also_duplicated_in_the_other_crm_fields_section(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_internaldescriptionandnotes",
                             "label": "Interní popis & poznámky", "value": "internal analysis notes"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertNotIn("Other Populated CRM Fields", md)  # the only field present was promoted, nothing leftover

    def test_non_promoted_fields_are_pushed_to_the_bottom_other_crm_fields_section(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "new_randomfield", "label": "Random Field", "value": "some value"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("## Other Populated CRM Fields", md)
        # Must come after the case's own details -- "pull down ... to the bottom of the brief".
        self.assertGreater(md.index("## Other Populated CRM Fields"), md.index("### "))
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
                {"logical_name": "art_descriptionadditionalpublic",
                 "label": "Dodatečný veřejný popis", "value": "public follow-up"},
            ],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertLess(md.index("Customer-visible summary."), md.index("Additional Public Description"))
        self.assertLess(md.index("Additional Public Description"), md.index("Internal Description"))

    def test_custom_promoted_fields_param_overrides_the_default(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "new_randomfield", "label": "Random Field", "value": "some value"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [], promoted_fields=["new_randomfield"])
        self.assertIn("**Random Field:**\n\nsome value", md)
        self.assertNotIn("Other Populated CRM Fields", md)

    def test_multiple_cases_with_leftover_fields_are_labeled_in_the_bottom_section(self):
        crm_results = [
            {"ticket_number": "T1", "title": "Case One",
             "all_fields": [{"logical_name": "new_a", "label": "A", "value": "1"}]},
            {"ticket_number": "T2", "title": "Case Two",
             "all_fields": [{"logical_name": "new_b", "label": "B", "value": "2"}]},
        ]
        md = report.build_markdown("T1", crm_results, [], [])
        other_section = md[md.index("## Other Populated CRM Fields"):]
        # Each case's title appears again as its own subheading within the
        # bottom section (on top of its own heading up in CRM Case(s)) --
        # a single-case brief skips this subheading entirely (see the
        # non-promoted-field test above), it's only needed to disambiguate
        # which case a leftover field came from once there's more than one.
        self.assertIn("### Case One", other_section)
        self.assertIn("### Case Two", other_section)
        self.assertIn("**A** (`new_a`): 1", other_section)
        self.assertIn("**B** (`new_b`): 2", other_section)


class BuildMarkdownEstimatesAndTotalsTests(unittest.TestCase):
    """Covers "## Estimates & Totals": a fixed curated set of exactly four
    fields off the case form's own "Estimate & Totals" widget -- Estimate,
    Billable Hours, Non-Billable Hours, Total Hours, in that display order
    -- matched by label (not logical_name, since these org rollup fields'
    logical names aren't known ahead of time) via
    report._classify_estimate_field/_ESTIMATE_FIELD_MATCHERS. Everything
    else the widget doesn't show (an approver lookup, price, a rollup's
    own "(stav)"/"(datum poslední aktualizace)" metadata) is left alone --
    not specially dropped, just not pulled into this section, so it still
    lands in "Other Populated CRM Fields" like any other uncurated field. No
    explanatory blurb and no `logical_name` per bullet -- this section is
    meant to be skimmed, not used to hunt for a field worth promoting."""

    def test_all_four_fields_render_in_fixed_display_order(self):
        # Real labels from the case form's "Estimate & Totals" widget --
        # note the word order differs from what EntityDefinitions metadata
        # returns for the same fields elsewhere in this test class
        # ("Celkem fakturované hodiny" etc.) -- both must match.
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [
                {"logical_name": "a", "label": "Nefakturované hodiny celkem", "value": "0,00"},
                {"logical_name": "b", "label": "Hodiny celkem", "value": "2,00"},
                {"logical_name": "c", "label": "Odhad", "value": "3,00"},
                {"logical_name": "d", "label": "Fakturované hodiny celkem", "value": "2,00"},
            ],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        section = md[md.index("## Estimates & Totals"):]
        self.assertIn(
            "- **Estimate:** 3,00\n"
            "- **Billable Hours:** 2,00\n"
            "- **Non-Billable Hours:** 0,00\n"
            "- **Total Hours:** 2,00",
            section)
        self.assertNotIn("Other Populated CRM Fields", md)  # nothing left over once all four are pulled out

    def test_matches_the_metadata_label_word_order_too(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [
                {"logical_name": "a", "label": "Celkem fakturované hodiny", "value": "1,50"},
                {"logical_name": "b", "label": "Celkem nefakturované hodiny", "value": "0,00"},
            ],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        section = md[md.index("## Estimates & Totals"):]
        self.assertIn("**Billable Hours:** 1,50", section)
        self.assertIn("**Non-Billable Hours:** 0,00", section)

    def test_no_explanatory_blurb_and_no_logical_name_shown(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "art_totalbillablehours",
                             "label": "Celkem fakturované hodiny", "value": "1,50"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        section = md[md.index("## Estimates & Totals"):]
        self.assertNotIn("art_totalbillablehours", section)
        self.assertNotIn("low priority to read", section)

    def test_all_four_always_render_even_when_only_one_field_is_present(self):
        # A field crm_scrape never returned at all (dropped upstream as
        # empty/None -- see crm_scrape._extract_all_fields) must still get
        # its own line here, as an em dash -- not silently vanish from the
        # section just because this case never had it filled in.
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "a", "label": "Odhad", "value": "3,00"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        section = md[md.index("## Estimates & Totals"):]
        self.assertIn("**Estimate:** 3,00", section)
        self.assertIn("**Billable Hours:** —", section)
        self.assertIn("**Non-Billable Hours:** —", section)
        self.assertIn("**Total Hours:** —", section)

    def test_rollup_metadata_suffixed_fields_are_not_matched(self):
        # A rollup field's own calculation-status/last-run-date
        # sub-fields -- metadata about the value, not the value itself --
        # must not be picked up as if they were the real Billable Hours
        # field, and must not suppress the real one either.
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [
                {"logical_name": "a", "label": "Total Billable Hours (stav)", "value": "1"},
                {"logical_name": "b", "label": "Total price (datum poslední aktualizace)",
                 "value": "26.08.2026 7:09"},
                {"logical_name": "c", "label": "Celkem fakturované hodiny", "value": "1,50"},
            ],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        section = md[md.index("## Estimates & Totals"):md.index("## Other Populated CRM Fields")]
        self.assertIn("**Billable Hours:** 1,50", section)
        self.assertNotIn("(stav)", section)
        self.assertNotIn("aktualizace", section)
        # The two metadata fields, not matching any category, fall
        # through to "Other Populated CRM Fields" like any other uncurated field.
        other_section = md[md.index("## Other Populated CRM Fields"):]
        self.assertIn("Total Billable Hours (stav)", other_section)
        self.assertIn("Total price (datum poslední aktualizace)", other_section)

    def test_unrelated_fields_are_not_pulled_in_and_still_land_in_other_crm_fields(self):
        # Kilometers/price/dispatch counts/an approver lookup -- real
        # fields the widget doesn't show as one of the four totals --
        # must not be swept into "## Estimates & Totals" just for
        # mentioning "celkem"/"total" in passing.
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [
                {"logical_name": "a", "label": "Celkem kilometrů", "value": "0,00"},
                {"logical_name": "b", "label": "Cena celkem", "value": "0,00"},
                {"logical_name": "c", "label": "Celkem výjezdů", "value": "0,00"},
                {"logical_name": "d", "label": "Odhad schválen", "value": "Jane Doe"},
                {"logical_name": "e", "label": "Odhad", "value": "3,00"},
            ],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        section = md[md.index("## Estimates & Totals"):md.index("## Other Populated CRM Fields")]
        self.assertIn("**Estimate:** 3,00", section)
        self.assertNotIn("kilometrů", section)
        self.assertNotIn("Cena celkem", section)
        self.assertNotIn("výjezdů", section)
        self.assertNotIn("Odhad schválen", section)
        other_section = md[md.index("## Other Populated CRM Fields"):]
        self.assertIn("Celkem kilometrů", other_section)
        self.assertIn("Cena celkem", other_section)
        self.assertIn("Celkem výjezdů", other_section)
        self.assertIn("Odhad schválen", other_section)

    def test_section_is_placed_right_before_other_crm_fields(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [
                {"logical_name": "a", "label": "Odhad", "value": "3,00"},
                {"logical_name": "b", "label": "Random Field", "value": "some value"},
            ],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        estimates_idx = md.index("## Estimates & Totals")
        other_idx = md.index("## Other Populated CRM Fields")
        self.assertLess(estimates_idx, other_idx)

    def test_no_matching_fields_omits_the_heading(self):
        crm_results = [{
            "ticket_number": "T1",
            "all_fields": [{"logical_name": "a", "label": "Random Field", "value": "some value"}],
        }]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertNotIn("Estimates & Totals", md)


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


class ModifiedOnMarkerTests(unittest.TestCase):
    """report.build_markdown's hidden staleness marker -- read back by
    case-getter (see its own is_stale/_brief_modified_on) to tell whether
    the CRM case has changed since this brief was written."""

    def test_marker_is_stamped_when_modified_on_is_present(self):
        crm_results = [{"ticket_number": "T1", "modified_on": "2026-08-20T10:00:00Z"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertIn("<!-- case-brief:crm-modified-on=2026-08-20T10:00:00Z -->", md)

    def test_no_marker_when_modified_on_is_missing(self):
        crm_results = [{"ticket_number": "T1"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertNotIn("crm-modified-on", md)

    def test_an_errored_case_result_is_never_used_for_the_marker(self):
        crm_results = [{"error": "boom", "modified_on": "should-never-appear"}]
        md = report.build_markdown("T1", crm_results, [], [])
        self.assertNotIn("should-never-appear", md)


class CollectAttachmentsTests(unittest.TestCase):
    def test_collects_only_image_attachments(self):
        crm_results = [{"ticket_number": "T1", "notes": [
            {"id": "a1b2c3d4", "filename": "screenshot.png", "attachment": {"kind": "image", "bytes": b"PNG"}},
            {"id": "a5b6c7d8", "filename": "notes.txt", "attachment": {"kind": "text", "content": "x", "truncated": False}},
            {"id": "a9b0c1d2", "filename": "dump.zip", "attachment": None},
        ]}]
        attachments = report.collect_attachments("T1", crm_results)
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["relative_path"], "attachments/T1/a1b2c3d4-screenshot.png")
        self.assertEqual(attachments[0]["bytes"], b"PNG")

    def test_errored_crm_results_are_skipped(self):
        crm_results = [{"error": "boom", "notes": [
            {"id": "a1", "filename": "x.png", "attachment": {"kind": "image", "bytes": b"x"}},
        ]}]
        self.assertEqual(report.collect_attachments("T1", crm_results), [])

    def test_no_attachments_returns_an_empty_list(self):
        crm_results = [{"ticket_number": "T1", "notes": [{"id": "a1", "subject": "s", "text": "t"}]}]
        self.assertEqual(report.collect_attachments("T1", crm_results), [])


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

    def test_attachments_are_written_alongside_the_brief(self):
        with tempfile.TemporaryDirectory() as d:
            attachments = [{"relative_path": "attachments/T1/a1-screenshot.png", "bytes": b"\x89PNG..."}]
            report.write_and_open("content", d, "T1", attachments=attachments)
            att_path = os.path.join(d, "attachments", "T1", "a1-screenshot.png")
            self.assertTrue(os.path.exists(att_path))
            with open(att_path, "rb") as f:
                self.assertEqual(f.read(), b"\x89PNG...")

    def test_no_attachments_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as d:
            path = report.write_and_open("content", d, "T1")  # attachments defaults to None
            self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
