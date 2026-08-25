"""Unit tests for case_guide.py's security/correctness-sensitive pure-logic
pieces: the case-number sanitizer, the brief-lookup traversal guard and
ambiguous-match safety, and the config-comment stripper. Deliberately not
exhaustive over every formatting/rendering branch -- those are low-risk and
easy to eyeball manually; this file locks in the handful of things that
would otherwise fail silently and dangerously (path traversal, a wrong
guess presented as certain, a stray `_comment` leaking into a request dict).

Run with: python -m unittest discover -s tests   (from case-guide/)
      or: python -m pytest tests                 (if pytest is installed)
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import case_guide as cg
from shared import config as shared_config


class SanitizeCaseNumberTests(unittest.TestCase):
    def test_strips_path_separators_and_dots(self):
        self.assertEqual(cg._sanitize_case_number("../../../etc/T123"), "......etcT123")

    def test_leaves_a_normal_case_number_untouched(self):
        self.assertEqual(cg._sanitize_case_number("T2611845"), "T2611845")

    def test_dots_and_dashes_are_kept(self):
        self.assertEqual(cg._sanitize_case_number("T26-11.845"), "T26-11.845")


class FindBriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.brief_dir = self.tmp.name
        open(os.path.join(self.brief_dir, "case-T111.md"), "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_match(self):
        path = cg.find_brief(self.brief_dir, "T111")
        self.assertEqual(os.path.basename(path), "case-T111.md")

    def test_ambiguous_match_exits_rather_than_guessing(self):
        open(os.path.join(self.brief_dir, "case-T3330.md"), "w").close()
        open(os.path.join(self.brief_dir, "case-T3331.md"), "w").close()
        with self.assertRaises(SystemExit):
            cg.find_brief(self.brief_dir, "T333")

    def test_traversal_attempt_is_blocked(self):
        # A case number crafted to escape brief_dir must not resolve to
        # anything outside it, even if a same-named file exists elsewhere.
        outside = tempfile.NamedTemporaryFile(suffix=".md", delete=False)
        outside.close()
        try:
            case_number = "../" * 6 + os.path.splitext(os.path.basename(outside.name))[0]
            self.assertIsNone(cg.find_brief(self.brief_dir, case_number))
        finally:
            os.unlink(outside.name)


class FindExampleGuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, text, mtime_offset=0):
        path = os.path.join(self.output_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        if mtime_offset:
            stat = os.stat(path)
            os.utime(path, (stat.st_atime, stat.st_mtime + mtime_offset))
        return path

    def test_none_on_first_guide_ever(self):
        self._write("case-T1-for-dummies.md", "current case's own leftover, if any")
        result = cg.find_example_guide(self.output_dir, "case-T1-for-dummies.md")
        self.assertIsNone(result)

    def test_none_when_output_dir_does_not_exist_yet(self):
        result = cg.find_example_guide(os.path.join(self.output_dir, "missing"), "case-T1-for-dummies.md")
        self.assertIsNone(result)

    def test_picks_most_recent_excluding_current_case(self):
        self._write("case-T1-for-dummies.md", "older", mtime_offset=-100)
        self._write("case-T2-for-dummies.md", "newest", mtime_offset=0)
        self._write("case-T3-for-dummies.md", "current run's own target", mtime_offset=100)
        result = cg.find_example_guide(self.output_dir, "case-T3-for-dummies.md")
        self.assertEqual(result, "newest")

    def test_count_joins_multiple_most_recent(self):
        self._write("case-T1-for-dummies.md", "oldest", mtime_offset=-200)
        self._write("case-T2-for-dummies.md", "middle", mtime_offset=-100)
        self._write("case-T3-for-dummies.md", "newest", mtime_offset=0)
        result = cg.find_example_guide(self.output_dir, "case-T4-for-dummies.md", count=2)
        self.assertEqual(result, "newest\n\n---\n\nmiddle")

    def test_zero_count_disables(self):
        self._write("case-T1-for-dummies.md", "irrelevant")
        result = cg.find_example_guide(self.output_dir, "case-T2-for-dummies.md", count=0)
        self.assertIsNone(result)


class StripCommentsTests(unittest.TestCase):
    def test_removes_any_underscore_prefixed_key(self):
        cfg = {
            "_comment": "top",
            "azure_devops": {"_comment": "x", "_other_meta": "y", "org_url": None},
            "claude": {"_comment": "z"},
        }
        cleaned = shared_config.strip_comments(cfg)
        self.assertNotIn("_comment", cleaned)
        self.assertNotIn("_comment", cleaned["azure_devops"])
        self.assertNotIn("_other_meta", cleaned["azure_devops"])
        self.assertEqual(cleaned["azure_devops"]["org_url"], None)


class TruncateTests(unittest.TestCase):
    def test_text_under_the_limit_passes_through_unchanged(self):
        self.assertEqual(cg._truncate("hello", 10), "hello")

    def test_text_exactly_at_the_limit_passes_through_unchanged(self):
        self.assertEqual(cg._truncate("hello", 5), "hello")

    def test_text_over_the_limit_is_capped_with_a_visible_truncation_note(self):
        result = cg._truncate("hello world", 5, label="test detail")
        self.assertTrue(result.startswith("hello"))
        self.assertIn("truncated", result)
        self.assertIn("6 more character(s) of test detail omitted", result)

    def test_a_falsy_limit_disables_truncation(self):
        long_text = "x" * 1000
        self.assertEqual(cg._truncate(long_text, None), long_text)
        self.assertEqual(cg._truncate(long_text, 0), long_text)


class FormatAdoDetailTests(unittest.TestCase):
    def test_no_incomplete_note_when_the_search_fully_succeeded(self):
        detail = {
            "branches": [{"project": "P", "repo": "R", "branch": "b", "commits": []}],
            "pull_requests": [],
            "warnings": [],
        }
        result = cg.format_ado_detail(detail, None)
        self.assertNotIn("may be incomplete", result)

    def test_folds_a_partial_search_warning_into_a_visible_note(self):
        detail = {
            "branches": [{"project": "P", "repo": "R", "branch": "b", "commits": []}],
            "pull_requests": [],
            "warnings": ["some PRs weren't checked"],
        }
        result = cg.format_ado_detail(detail, None)
        self.assertIn("may be incomplete", result)
        self.assertIn("Some PRs weren't checked.", result)

    def test_a_capped_search_that_found_nothing_still_says_so_rather_than_claiming_a_clean_search(self):
        detail = {"branches": [], "pull_requests": [], "warnings": ["the org has more than 50 projects"]}
        result = cg.format_ado_detail(detail, None)
        self.assertIn("No related branches or pull requests found", result)
        self.assertIn("the org has more than 50 projects", result)

    def test_a_hard_ado_error_is_reported_distinctly_from_a_clean_empty_search(self):
        result = cg.format_ado_detail(None, "Azure DevOps rejected the request (401)")
        self.assertIn("Could not fetch live Azure DevOps detail", result)
        self.assertNotIn("No related branches or pull requests found", result)


class FormatExampleGuideTests(unittest.TestCase):
    def test_none_yields_a_placeholder_saying_no_example_exists_yet(self):
        result = cg.format_example_guide(None)
        self.assertIn("first one", result)

    def test_existing_text_passes_through_unchanged(self):
        text = "# Case T1 for Dummies\nsome content"
        self.assertEqual(cg.format_example_guide(text), text)


class GatherAdoDetailAuthErrorTests(unittest.TestCase):
    """gather_ado_detail must surface AdoAuthError as an explicit,
    distinguishable error -- never as a plain (empty-looking) result that
    format_ado_detail would render as "nothing found", which is a very
    different claim from "couldn't search because the PAT is bad"."""

    def test_an_auth_error_finding_related_work_surfaces_as_an_explicit_error(self):
        cfg = {"azure_devops": {"org_url": "https://dev.azure.com/org"}}
        with mock.patch.object(cg.ado_api, "open_session", return_value=mock.Mock()), \
             mock.patch.object(
                 cg.ado_api, "find_related",
                 side_effect=cg.ado_api.AdoAuthError("Azure DevOps rejected the request (401)"),
             ):
            detail, error = cg.gather_ado_detail(cfg, "T1")
        self.assertIsNone(detail)
        self.assertIn("401", error)
        rendered = cg.format_ado_detail(detail, error)
        self.assertIn("Could not fetch live Azure DevOps detail", rendered)
        self.assertNotIn("No related branches or pull requests found", rendered)

    def test_an_auth_error_during_per_branch_enrichment_also_surfaces_as_an_explicit_error(self):
        cfg = {"azure_devops": {"org_url": "https://dev.azure.com/org"}}
        branch = {"project": "P", "repo": "R", "branch": "b"}
        with mock.patch.object(cg.ado_api, "open_session", return_value=mock.Mock()), \
             mock.patch.object(cg.ado_api, "find_related", return_value=([branch], [], [])), \
             mock.patch.object(
                 cg.ado_api, "get_branch_commits",
                 side_effect=cg.ado_api.AdoAuthError("Azure DevOps rejected the request (403)"),
             ):
            detail, error = cg.gather_ado_detail(cfg, "T1")
        self.assertIsNone(detail)
        self.assertIn("403", error)


class ResolveExtraArgsTests(unittest.TestCase):
    """_resolve_extra_args is the one exception to "CLI flags always win"
    (see CLAUDE.md): --no-claude-extra-args has to be able to express "zero
    extra args" even though a plain argparse append flag can only ever add,
    never subtract -- worth locking in since getting this backwards would
    silently keep a discouraged/stale config flag (e.g. a permission-mode
    override) alive on a run that explicitly asked to drop it."""

    def _args(self, no_claude_extra_args, claude_args):
        return mock.Mock(no_claude_extra_args=no_claude_extra_args, claude_args=claude_args)

    def test_no_extra_args_flag_with_nothing_explicit_yields_an_empty_list(self):
        cfg = {"claude": {"extra_args": ["--from-config"]}}
        args = self._args(no_claude_extra_args=True, claude_args=None)
        self.assertEqual(cg._resolve_extra_args(args, cfg), [])

    def test_no_extra_args_flag_still_honors_an_explicit_claude_arg(self):
        cfg = {"claude": {"extra_args": ["--from-config"]}}
        args = self._args(no_claude_extra_args=True, claude_args=["--explicit"])
        self.assertEqual(cg._resolve_extra_args(args, cfg), ["--explicit"])

    def test_without_the_flag_and_no_explicit_arg_config_extra_args_are_used(self):
        cfg = {"claude": {"extra_args": ["--from-config"]}}
        args = self._args(no_claude_extra_args=False, claude_args=None)
        self.assertEqual(cg._resolve_extra_args(args, cfg), ["--from-config"])

    def test_an_explicit_claude_arg_overrides_config_extra_args(self):
        cfg = {"claude": {"extra_args": ["--from-config"]}}
        args = self._args(no_claude_extra_args=False, claude_args=["--explicit"])
        self.assertEqual(cg._resolve_extra_args(args, cfg), ["--explicit"])


class AddGuessWarningTests(unittest.TestCase):
    """_add_guess_warning is the code-level guarantee that a fuzzy-matched
    (unconfirmed) repo suggestion gets flagged in the actual written guide
    -- not left to chance on claude's own rewrite of the Get Set Up section
    keeping format_suggested_repo's inline "(guessed...)" annotation."""

    GUIDE = "# Case T1 for Dummies\n\n## What this case is about\nSomething.\n"

    def test_no_warning_when_nothing_was_guessed(self):
        confirmed = {("P", "R"): {"clone_url": "https://x", "source": "ado-search"}}
        self.assertEqual(cg._add_guess_warning(self.GUIDE, confirmed), self.GUIDE)

    def test_no_warning_when_no_repo_was_suggested_at_all(self):
        self.assertEqual(cg._add_guess_warning(self.GUIDE, {}), self.GUIDE)
        self.assertEqual(cg._add_guess_warning(self.GUIDE, None), self.GUIDE)

    def test_warning_inserted_right_after_the_title_when_a_repo_was_guessed(self):
        guessed = {("P", "R"): {"clone_url": "https://x", "source": "auto-match"}}
        result = cg._add_guess_warning(self.GUIDE, guessed)
        lines = result.split("\n")
        self.assertEqual(lines[0], "# Case T1 for Dummies")
        self.assertIn("guessed, not confirmed", lines[2])
        # The rest of claude's guide must still be there, untouched.
        self.assertIn("## What this case is about", result)
        self.assertIn("Something.", result)

    def test_warning_still_applies_when_only_one_of_several_repos_was_guessed(self):
        mixed = {
            ("P", "R1"): {"clone_url": "https://x", "source": "ado-search"},
            ("P", "R2"): {"clone_url": "https://y", "source": "auto-match"},
        }
        result = cg._add_guess_warning(self.GUIDE, mixed)
        self.assertIn("guessed, not confirmed", result)

    def test_handles_a_guide_with_no_newline_at_all(self):
        result = cg._add_guess_warning("just one line", {("P", "R"): {"source": "auto-match"}})
        self.assertIn("just one line", result)
        self.assertIn("guessed, not confirmed", result)


class ExtractFromBriefTests(unittest.TestCase):
    """case-brief's lib/report.py always renders a case's title as the first
    "### " heading and its customer right after it as a "- **Customer:**
    ..." bullet -- see this project's CLAUDE.md ("no shared imports... a
    filesystem contract only") for why this project parses that back out of
    the finished brief instead of importing case-brief's own code."""

    BRIEF = (
        "# Case T1\n\n"
        "### Posting error in Sales Invoice\n"
        "- **Ticket #:** T1\n"
        "- **Customer:** Contoso s.r.o.\n"
        "- **Owner:** Jane\n"
    )

    def test_extracts_the_case_title(self):
        self.assertEqual(cg._extract_case_title(self.BRIEF), "Posting error in Sales Invoice")

    def test_extracts_the_customer(self):
        self.assertEqual(cg._extract_customer(self.BRIEF), "Contoso s.r.o.")

    def test_missing_title_returns_none(self):
        self.assertIsNone(cg._extract_case_title("# Case T1\n\nno heading here"))

    def test_missing_customer_returns_none(self):
        self.assertIsNone(cg._extract_customer("### Title\n- **Ticket #:** T1\n"))

    def test_em_dash_placeholder_customer_is_treated_as_missing(self):
        # report.py renders a missing customer as "- **Customer:** —", not
        # an empty string -- that placeholder must not be treated as a real
        # customer name to fuzzy-match against.
        brief = "### Title\n- **Customer:** —\n"
        self.assertIsNone(cg._extract_customer(brief))


if __name__ == "__main__":
    unittest.main()
