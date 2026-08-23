"""Unit tests for lib/report.py, the Markdown brief builder.

Uses plain dict/list inputs -- no real CRM/ADO/BC data needed, since by the
time anything reaches report.py it's already just dicts and lists (see
CLAUDE.md: "CRM, ADO, and BC results are plain dicts/lists by the time they
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


class SafeNameAndSlugifyTests(unittest.TestCase):
    def test_safe_name_replaces_unsafe_characters(self):
        self.assertEqual(report._safe_name("T26/11:845?"), "T26_11_845")

    def test_safe_name_falls_back_to_unlabeled_for_empty_string(self):
        self.assertEqual(report._safe_name(""), "unlabeled")

    def test_slugify_lowercases_and_truncates(self):
        long_title = "Posting Error In Sales Invoice With A Very Long Title Indeed"
        slug = report._slugify(long_title, max_len=20)
        self.assertLessEqual(len(slug), 20)
        self.assertEqual(slug, slug.lower())
        self.assertFalse(slug.endswith("-"))

    def test_slugify_empty_title_returns_empty_string(self):
        self.assertEqual(report._slugify(""), "")
        self.assertEqual(report._slugify(None), "")

    def test_branch_name_combines_case_and_slug(self):
        self.assertEqual(report._branch_name("T123", "Fix the bug"), "T123-fix-the-bug")

    def test_branch_name_falls_back_to_case_number_alone_without_a_title(self):
        self.assertEqual(report._branch_name("T123", None), "T123")


class BuildMarkdownMinimalInputTests(unittest.TestCase):
    def test_minimal_input_does_not_crash_and_notes_every_empty_section(self):
        md = report.build_markdown("T1", [], [], [], [], include_bc=False)
        self.assertIn("# Case T1", md)
        self.assertIn("No CRM case tab found open", md)
        self.assertIn("No matching branches found", md)
        self.assertIn("No matching pull requests found", md)
        self.assertIn("Skipped for this brief", md)  # BC section, include_bc=False
        self.assertIn("No repo identified yet", md)

    def test_ado_error_suppresses_branch_and_pr_listing(self):
        branches = [{"project": "P", "repo": "R", "branch": "b", "url": "u"}]
        prs = [{"project": "P", "repo": "R", "id": 1, "title": "t", "status": "active", "created_by": "x", "url": "u"}]
        md = report.build_markdown("T1", [], branches, prs, [], ado_error="PAT missing", include_bc=False)
        self.assertIn("Could not query Azure DevOps: PAT missing", md)
        # Even though branches/prs are non-empty, they must not be printed
        # alongside an error -- that would present a broken search as a
        # confirmed "these are the only results" listing.
        self.assertNotIn("[P/R: b]", md)
        self.assertNotIn("!1", md)

    def test_prs_truncated_note_appears_only_when_flagged(self):
        md_truncated = report.build_markdown("T1", [], [], [{"project": "P", "repo": "R", "id": 1, "title": "t",
                                                              "status": "active", "created_by": "x", "url": "u"}],
                                              [], include_bc=False, prs_truncated=True, max_prs=50)
        self.assertIn("Only searched the 50 most recent pull requests", md_truncated)
        md_not_truncated = report.build_markdown("T1", [], [], [], [], include_bc=False, prs_truncated=False)
        self.assertNotIn("Only searched", md_not_truncated)


class BuildMarkdownCrmSectionTests(unittest.TestCase):
    def test_crm_error_result_is_flagged_with_a_warning_not_rendered_as_a_case(self):
        crm_results = [{"error": "No authenticated CRM tab found.", "url": "https://x"}]
        md = report.build_markdown("T1", crm_results, [], [], [], include_bc=False)
        self.assertIn("No authenticated CRM tab found.", md)

    def test_successful_crm_case_renders_its_fields(self):
        crm_results = [{
            "title": "Posting error", "ticket_number": "T1", "customer": "Contoso",
            "owner": "Jane", "priority": "High", "status": "Active",
            "created_on": "2026-08-01", "description": "Something broke.",
        }]
        md = report.build_markdown("T1", crm_results, [], [], [], include_bc=False)
        self.assertIn("Posting error", md)
        self.assertIn("Contoso", md)
        self.assertIn("Something broke.", md)

    def test_missing_optional_crm_fields_render_as_an_em_dash_not_crash(self):
        crm_results = [{"ticket_number": "T1"}]  # everything else missing
        md = report.build_markdown("T1", crm_results, [], [], [], include_bc=False)
        self.assertIn("—", md)


class BuildMarkdownBcSectionTests(unittest.TestCase):
    def test_bc_included_but_no_tabs_found_says_so(self):
        md = report.build_markdown("T1", [], [], [], [], include_bc=True)
        self.assertIn("No Business Central tab found open", md)

    def test_bc_fields_are_rendered_as_a_list(self):
        bc_results = [{"url": "https://bc", "page_title": "Sales Invoice", "fields": [{"label": "No.", "value": "103042"}]}]
        md = report.build_markdown("T1", [], [], [], bc_results, include_bc=True)
        self.assertIn("Sales Invoice", md)
        self.assertIn("**No.:** 103042", md)

    def test_bc_raw_text_fallback_used_only_when_no_fields_matched(self):
        bc_results = [{"url": "https://bc", "page_title": "Page", "fields": [], "raw_text": "dump of visible text"}]
        md = report.build_markdown("T1", [], [], [], bc_results, include_bc=True)
        self.assertIn("dumping visible page text instead", md)
        self.assertIn("dump of visible text", md)


class BuildMarkdownRepoSuggestionTests(unittest.TestCase):
    def test_confirmed_ado_match_takes_priority_over_a_guessed_suggestion_for_the_same_repo(self):
        branches = [{"project": "P", "repo": "R", "branch": "b", "url": "u", "clone_url": "https://confirmed"}]
        suggested = [{"project": "P", "repo": "R", "clone_url": "https://guessed", "source": "auto-match"}]
        md = report.build_markdown("T1", [], branches, [], [], include_bc=False, suggested_repos=suggested)
        self.assertIn("git clone https://confirmed", md)
        self.assertNotIn("https://guessed", md)

    def test_guessed_repo_is_labeled_as_a_guess(self):
        suggested = [{"project": "P", "repo": "R", "clone_url": "https://guessed", "source": "auto-match"}]
        md = report.build_markdown("T1", [], [], [], [], include_bc=False, suggested_repos=suggested)
        self.assertIn("guessed from customer name", md)

    def test_customer_repo_map_suggestion_is_not_labeled_as_a_guess(self):
        suggested = [{"project": "P", "repo": "R", "clone_url": "https://x", "source": "customer_repo_map"}]
        md = report.build_markdown("T1", [], [], [], [], include_bc=False, suggested_repos=suggested)
        self.assertNotIn("guessed from customer name", md)


class WriteAndOpenTests(unittest.TestCase):
    def test_writes_the_markdown_to_a_sanitized_filename_under_output_dir(self):
        # _safe_name deliberately keeps dots (case numbers like "T26-11.845"
        # need them) so ".." can still appear as a substring of the filename
        # -- what actually matters is that path separators are stripped, so
        # the result is always one filename directly inside output_dir and
        # can never escape it as a nested/relative path.
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("lib.report.subprocess.run") as run_mock:
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
            with mock.patch("lib.report.subprocess.run"):
                path = report.write_and_open("content", nested, "T1", open_in_vscode=False)
            self.assertTrue(os.path.exists(path))

    def test_open_in_vscode_true_invokes_subprocess_run(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("lib.report.subprocess.run") as run_mock:
                report.write_and_open("content", d, "T1", open_in_vscode=True)
            run_mock.assert_called_once()

    def test_missing_code_executable_does_not_prevent_the_file_from_being_written(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("lib.report.subprocess.run", side_effect=FileNotFoundError):
                path = report.write_and_open("content", d, "T1", open_in_vscode=True)
            self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
