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
import json
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
        open(os.path.join(self.brief_dir, "brief-T111.md"), "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_match(self):
        path = cg.find_brief(self.brief_dir, "T111")
        self.assertEqual(os.path.basename(path), "brief-T111.md")

    def test_ambiguous_match_exits_rather_than_guessing(self):
        open(os.path.join(self.brief_dir, "brief-T3330.md"), "w").close()
        open(os.path.join(self.brief_dir, "brief-T3331.md"), "w").close()
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
        self._write("case-T1.md", "current case's own leftover, if any")
        result = cg.find_example_guide(self.output_dir, "case-T1.md")
        self.assertIsNone(result)

    def test_none_when_output_dir_does_not_exist_yet(self):
        result = cg.find_example_guide(os.path.join(self.output_dir, "missing"), "case-T1.md")
        self.assertIsNone(result)

    def test_picks_most_recent_excluding_current_case(self):
        self._write("case-T1.md", "older", mtime_offset=-100)
        self._write("case-T2.md", "newest", mtime_offset=0)
        self._write("case-T3.md", "current run's own target", mtime_offset=100)
        result = cg.find_example_guide(self.output_dir, "case-T3.md")
        self.assertEqual(result, "newest")

    def test_count_joins_multiple_most_recent(self):
        self._write("case-T1.md", "oldest", mtime_offset=-200)
        self._write("case-T2.md", "middle", mtime_offset=-100)
        self._write("case-T3.md", "newest", mtime_offset=0)
        result = cg.find_example_guide(self.output_dir, "case-T4.md", count=2)
        self.assertEqual(result, "newest\n\n---\n\nmiddle")

    def test_zero_count_disables(self):
        self._write("case-T1.md", "irrelevant")
        result = cg.find_example_guide(self.output_dir, "case-T2.md", count=0)
        self.assertIsNone(result)


class LoadConfigTests(unittest.TestCase):
    """DEFAULTS -> config.json (deep-merged, _comment stripped) -- the
    actual load_config integration, not just deep_merge/strip_comments as
    standalone units (see StripCommentsTests below for the latter)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.tmp.name, "config.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, data):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_missing_config_file_falls_back_to_defaults_only(self):
        cfg = cg.load_config(os.path.join(self.tmp.name, "nonexistent.json"))
        self.assertEqual(cfg, cg.DEFAULTS)

    def test_config_json_deep_merges_into_nested_defaults_without_clobbering_siblings(self):
        self._write({"azure_devops": {"org_url": "https://dev.azure.com/acme"}})
        cfg = cg.load_config(self.config_path)
        self.assertEqual(cfg["azure_devops"]["org_url"], "https://dev.azure.com/acme")
        self.assertIsNone(cfg["azure_devops"]["project"])  # sibling default kept
        self.assertEqual(cfg["claude"]["agent"], "case-guide-writer")  # untouched branch kept

    def test_comment_keys_are_stripped_through_the_real_load_path(self):
        self._write({"_comment": "docs", "claude": {"_comment": "x", "model": "opus"}})
        cfg = cg.load_config(self.config_path)
        self.assertNotIn("_comment", cfg)
        self.assertNotIn("_comment", cfg["claude"])
        self.assertEqual(cfg["claude"]["model"], "opus")


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
        text = "# Case T1\nsome content"
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


class GatherAdoDetailDegradeTests(unittest.TestCase):
    """The actual point of _enrich_branch/_enrich_pr -- a non-auth failure
    enriching one branch/PR must not sink the whole (possibly concurrent)
    pass, unlike the hard-fail AdoAuthError cases above."""

    def test_no_org_url_configured_returns_a_clear_error_without_searching(self):
        cfg = {"azure_devops": {"org_url": None}}
        with mock.patch.object(cg.ado_api, "open_session") as open_session:
            detail, error = cg.gather_ado_detail(cfg, "T1")
        open_session.assert_not_called()
        self.assertIsNone(detail)
        self.assertIn("no Azure DevOps org URL configured", error)

    def test_a_branch_enrichment_failure_still_returns_the_branch_with_a_warning(self):
        cfg = {"azure_devops": {"org_url": "https://dev.azure.com/org"}}
        branch = {"project": "P", "repo": "R", "branch": "b"}
        with mock.patch.object(cg.ado_api, "open_session", return_value=mock.Mock()), \
             mock.patch.object(cg.ado_api, "find_related", return_value=([branch], [], [])), \
             mock.patch.object(cg.ado_api, "get_branch_commits", side_effect=RuntimeError("HTTP 500")):
            detail, error = cg.gather_ado_detail(cfg, "T1")
        self.assertIsNone(error)
        self.assertEqual(len(detail["branches"]), 1)
        self.assertEqual(detail["branches"][0]["commits"], [])
        self.assertTrue(any("couldn't fetch commits" in w for w in detail["warnings"]))

    def test_a_pr_enrichment_failure_still_returns_the_pr_with_a_warning(self):
        cfg = {"azure_devops": {"org_url": "https://dev.azure.com/org"}}
        pr = {"project": "P", "repo": "R", "id": 5}
        with mock.patch.object(cg.ado_api, "open_session", return_value=mock.Mock()), \
             mock.patch.object(cg.ado_api, "find_related", return_value=([], [pr], [])), \
             mock.patch.object(cg.ado_api, "get_pr_details", side_effect=RuntimeError("HTTP 500")):
            detail, error = cg.gather_ado_detail(cfg, "T1")
        self.assertIsNone(error)
        self.assertEqual(len(detail["pull_requests"]), 1)
        self.assertEqual(detail["pull_requests"][0]["commits"], [])
        self.assertTrue(any("couldn't fetch detail for PR" in w for w in detail["warnings"]))

    def test_successful_enrichment_merges_commits_and_pr_extras_in(self):
        cfg = {"azure_devops": {"org_url": "https://dev.azure.com/org"}}
        branch = {"project": "P", "repo": "R", "branch": "b"}
        pr = {"project": "P", "repo": "R", "id": 5}
        with mock.patch.object(cg.ado_api, "open_session", return_value=mock.Mock()), \
             mock.patch.object(cg.ado_api, "find_related", return_value=([branch], [pr], [])), \
             mock.patch.object(cg.ado_api, "get_branch_commits", return_value=["c1"]), \
             mock.patch.object(cg.ado_api, "get_pr_details", return_value={"files": ["f1"], "comments": []}):
            detail, error = cg.gather_ado_detail(cfg, "T1")
        self.assertIsNone(error)
        self.assertEqual(detail["branches"][0]["commits"], ["c1"])
        self.assertEqual(detail["pull_requests"][0]["files"], ["f1"])
        self.assertEqual(detail["warnings"], [])


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

    GUIDE = "# Case T1\n\n## What this case is about\nSomething.\n"

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
        self.assertEqual(lines[0], "# Case T1")
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


class BuildPromptDifficultyRubricTests(unittest.TestCase):
    """build_prompt must always inline the fixed DIFFICULTY_RUBRIC and the
    instruction to use it -- this is what keeps difficulty ratings
    comparable across separate claude calls/cases (see DIFFICULTY_RUBRIC's
    own docstring-equivalent comment in PROMPT_TEMPLATE)."""

    def _prompt(self):
        return cg.build_prompt("T1", "brief text", "suggested repo", "ado detail", "example guide")

    def test_the_fixed_rubric_bands_are_present_verbatim(self):
        prompt = self._prompt()
        self.assertIn(cg.DIFFICULTY_RUBRIC, prompt)
        self.assertIn("1  -- Trivial", prompt)
        self.assertIn("10 -- Highest", prompt)

    def test_rubric_has_an_n_a_band_for_non_dev_task_cases(self):
        # An automated/informational notification (e.g. a BC "environment
        # updated" e-mail) or pure triage/closure case has no dev work to
        # size at all -- forcing it onto the 1-10 scale used to produce
        # inconsistent 1s and 9s for the exact same kind of case.
        self.assertIn("N/A", cg.DIFFICULTY_RUBRIC)
        self.assertIn("Not a dev task", cg.DIFFICULTY_RUBRIC)

    def test_instructs_claude_that_n_a_is_a_valid_difficulty_value(self):
        prompt = self._prompt()
        self.assertIn("**Implementation Difficulty:** N/A", prompt)
        self.assertIn("do NOT force", prompt)

    def test_instructs_claude_to_output_a_difficulty_line(self):
        prompt = self._prompt()
        self.assertIn("**Implementation Difficulty:** X/10", prompt)
        self.assertIn("don't invent your own scale", prompt)

    def test_instructs_claude_to_output_a_readiness_line(self):
        prompt = self._prompt()
        self.assertIn("**Ready for Implementation:** Yes", prompt)
        self.assertIn("Before You Start -- Social Steps", prompt)

    def test_difficulty_is_marked_required_with_no_exceptions(self):
        # The instruction that used to just ask for the line now says
        # explicitly that it's mandatory -- including for a trivial
        # triage/closure case, the exact shape that was slipping through.
        prompt = self._prompt()
        self.assertIn("REQUIRED", prompt)
        self.assertIn("no exceptions", prompt)

    def test_difficulty_comes_immediately_after_readiness_before_social_steps(self):
        # The ordering conflict this closes: readiness (step 2) and
        # difficulty (step 3) used to both claim "right after the summary,"
        # leaving claude to decide whether Social Steps or the difficulty
        # line came second -- a guide with a long Social Steps section
        # could then push the difficulty line out past a naive early-text
        # sanity check. Now the prompt is explicit that both status lines
        # are a back-to-back pair, with Social Steps (if any) after both.
        prompt = self._prompt()
        self.assertIn("back-to-back pair", prompt)
        self.assertIn("never between them", prompt)

    def test_status_lines_are_instructed_before_the_summary_not_after(self):
        # Moved even earlier than the original fix: the two required status
        # lines now go before "What this case is about" entirely, not just
        # before the Social Steps section -- so a long case summary can
        # never push them down either.
        prompt = self._prompt()
        self.assertLess(prompt.index("**Ready for Implementation:** Yes"), prompt.index("**What this case is about**"))
        self.assertLess(prompt.index("**Implementation Difficulty:** X/10"), prompt.index("**What this case is about**"))

    def test_closing_reminder_calls_out_both_required_lines(self):
        # A final, recency-favoring reminder just before the "output only
        # the guide" instruction -- belt-and-suspenders on top of the
        # step-by-step instructions above.
        prompt = self._prompt()
        self.assertIn("Before you finish", prompt)
        self.assertIn("**Ready for Implementation:**", prompt.split("Before you finish")[1])
        self.assertIn("**Implementation Difficulty:**", prompt.split("Before you finish")[1])


class LooksLikeGuideTests(unittest.TestCase):
    """Same warn-only pattern as HasDifficultyRatingTests/HasReadinessMarkerTests
    below -- a loose sanity check that claude's output is the guide itself,
    not a refusal or stray preamble."""

    def test_true_for_a_leading_heading_mentioning_the_case_number(self):
        text = "# Case T2611845\n\n## What this case is about\nSomething.\n"
        self.assertTrue(cg._looks_like_guide(text, "T2611845"))

    def test_false_when_there_is_no_leading_heading_at_all(self):
        text = "Sure, here's the guide for T2611845:\n\n## What this case is about\n"
        self.assertFalse(cg._looks_like_guide(text, "T2611845"))

    def test_false_when_the_case_number_never_appears_at_all(self):
        text = "# Implementation Guide\n\nSomething about a different case entirely.\n"
        self.assertFalse(cg._looks_like_guide(text, "T2611845"))

    def test_matching_is_case_insensitive(self):
        text = "# case t2611845\n"
        self.assertTrue(cg._looks_like_guide(text, "T2611845"))

    def test_a_case_number_past_the_first_200_characters_does_not_count(self):
        text = "# " + ("x" * 250) + " T2611845\n"
        self.assertFalse(cg._looks_like_guide(text, "T2611845"))


class HasDifficultyRatingTests(unittest.TestCase):
    def test_true_when_the_expected_line_is_present(self):
        text = "# Case T1\n\n## What this case is about\nSomething.\n\n**Implementation Difficulty:** 4/10 -- small, one module.\n"
        self.assertTrue(cg._has_difficulty_rating(text))

    def test_false_when_missing_entirely(self):
        text = "# Case T1\n\n## What this case is about\nSomething.\n"
        self.assertFalse(cg._has_difficulty_rating(text))

    def test_false_for_a_number_not_shaped_like_x_of_10(self):
        text = "# Case T1\n\nThis case affects 4 customers.\n"
        self.assertFalse(cg._has_difficulty_rating(text))

    def test_matches_regardless_of_which_of_the_ten_bands(self):
        text = "**Implementation Difficulty:** 10/10 -- architecture-level.\n"
        self.assertTrue(cg._has_difficulty_rating(text))

    def test_matches_n_a_for_a_non_dev_task_case(self):
        # An automated notification/pure-triage case is a legitimate N/A,
        # not a missing rating -- see DIFFICULTY_RUBRIC's own N/A entry.
        text = "**Implementation Difficulty:** N/A -- automated environment-update notification, nothing to develop.\n"
        self.assertTrue(cg._has_difficulty_rating(text))

    def test_true_even_when_the_line_lands_past_the_first_1000_characters(self):
        # A real bug: a verbose case summary, or a "Before You Start --
        # Social Steps" section ahead of it, can easily push a perfectly
        # correctly written line past an arbitrary early cutoff -- a false
        # negative here used to make ensure_difficulty_rating splice in a
        # second, duplicate line right next to the real one.
        text = "# Case T1\n\n" + ("Filler. " * 200) + "\n\n**Implementation Difficulty:** 4/10 -- small.\n"
        self.assertGreater(len(text), 1000)
        self.assertTrue(cg._has_difficulty_rating(text))


class InsertDifficultyRatingTests(unittest.TestCase):
    LINE = "**Implementation Difficulty:** 4/10 -- small, one module."

    def test_inserted_right_after_the_readiness_line_when_present(self):
        guide = "# Case T1\n\n**Ready for Implementation:** Yes\n\n## What this case is about\nSomething.\n"
        result = cg._insert_difficulty_rating(guide, self.LINE)
        lines = result.split("\n")
        self.assertEqual(lines[2], "**Ready for Implementation:** Yes")
        self.assertEqual(lines[3], self.LINE)
        self.assertIn("## What this case is about", result)

    def test_inserted_right_after_the_title_when_no_readiness_line(self):
        guide = "# Case T1\n\n## What this case is about\nSomething.\n"
        result = cg._insert_difficulty_rating(guide, self.LINE)
        lines = result.split("\n")
        self.assertEqual(lines[0], "# Case T1")
        self.assertEqual(lines[2], self.LINE)
        self.assertIn("## What this case is about", result)

    def test_handles_a_guide_with_no_newline_at_all(self):
        result = cg._insert_difficulty_rating("just one line", self.LINE)
        self.assertIn("just one line", result)
        self.assertIn(self.LINE, result)


class EnsureDifficultyRatingTests(unittest.TestCase):
    """ensure_difficulty_rating is the code-level guarantee that a guide
    ends up with a parseable difficulty line -- the same pattern
    _add_guess_warning already uses for the repo-guess warning, applied
    here via a small, targeted retry call instead of trusting claude
    followed the main prompt's instruction."""

    GUIDE = "# Case T1\n\n## What this case is about\nSomething.\n"

    def test_already_present_short_circuits_without_calling_claude(self):
        guide = self.GUIDE + "\n**Implementation Difficulty:** 4/10 -- small.\n"
        with mock.patch.object(cg, "call_claude") as call_claude:
            result = cg.ensure_difficulty_rating(guide)
        call_claude.assert_not_called()
        self.assertEqual(result, guide)

    def test_a_usable_retry_response_gets_spliced_in(self):
        response = "**Implementation Difficulty:** 6/10 -- multiple files, real logic."
        with mock.patch.object(cg, "call_claude", return_value=response) as call_claude:
            result = cg.ensure_difficulty_rating(self.GUIDE)
        call_claude.assert_called_once()
        self.assertTrue(cg._has_difficulty_rating(result))
        self.assertIn(response, result)

    def test_an_n_a_retry_response_is_accepted_too(self):
        response = "**Implementation Difficulty:** N/A -- automated notification, nothing to develop."
        with mock.patch.object(cg, "call_claude", return_value=response) as call_claude:
            result = cg.ensure_difficulty_rating(self.GUIDE)
        call_claude.assert_called_once()
        self.assertTrue(cg._has_difficulty_rating(result))
        self.assertIn(response, result)

    def test_a_bad_first_attempt_is_retried(self):
        responses = ["sorry, I can't help with that", "**Implementation Difficulty:** 3/10 -- one file."]
        with mock.patch.object(cg, "call_claude", side_effect=responses) as call_claude:
            result = cg.ensure_difficulty_rating(self.GUIDE, attempts=2)
        self.assertEqual(call_claude.call_count, 2)
        self.assertTrue(cg._has_difficulty_rating(result))

    def test_every_attempt_failing_leaves_the_guide_unchanged_rather_than_blocking(self):
        with mock.patch.object(cg, "call_claude", return_value="no usable line here") as call_claude:
            result = cg.ensure_difficulty_rating(self.GUIDE, attempts=2)
        self.assertEqual(call_claude.call_count, 2)
        self.assertEqual(result, self.GUIDE)
        self.assertFalse(cg._has_difficulty_rating(result))

    def test_the_retry_prompt_inlines_the_fixed_rubric(self):
        with mock.patch.object(cg, "call_claude", return_value="") as call_claude:
            cg.ensure_difficulty_rating(self.GUIDE, attempts=1)
        prompt = call_claude.call_args[0][0]
        self.assertIn(cg.DIFFICULTY_RUBRIC, prompt)
        self.assertIn(self.GUIDE.strip(), prompt)


class HasReadinessMarkerTests(unittest.TestCase):
    def test_true_for_yes(self):
        text = "# Case T1\n\n**Ready for Implementation:** Yes\n"
        self.assertTrue(cg._has_readiness_marker(text))

    def test_true_for_no_with_reason(self):
        text = "# Case T1\n\n**Ready for Implementation:** No -- waiting on customer reply\n"
        self.assertTrue(cg._has_readiness_marker(text))

    def test_false_when_missing_entirely(self):
        text = "# Case T1\n\n## What this case is about\nSomething.\n"
        self.assertFalse(cg._has_readiness_marker(text))

    def test_true_even_when_the_line_lands_past_the_first_1000_characters(self):
        text = "# Case T1\n\n" + ("Filler. " * 200) + "\n\n**Ready for Implementation:** Yes\n"
        self.assertGreater(len(text), 1000)
        self.assertTrue(cg._has_readiness_marker(text))


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
