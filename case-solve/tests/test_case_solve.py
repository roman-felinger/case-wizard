"""Unit tests for case_solve.py's pure-logic pieces and CLI wiring: the
config deep-merge precedence (DEFAULTS -> config.json -> CLI flags via
apply_cli_overrides), the guide-lookup traversal guard and ambiguous-match
safety (mirrors case-guide's FindBriefTests pattern), repo-URL extraction
from freeform guide text, repo-name extraction across GitHub/ADO/GitLab URL
shapes, and filename sanitization.

case-solve is interactive-only -- no --yes/--ignore-readiness escape hatch
of any kind (removed 2026-08-26; the user didn't want either). Every main()
test below that reaches the repo-URL/confirmation prompts drives them
through a scripted builtins.input, proving the interactive path is always
taken rather than skipped.

Deliberately not exhaustive over the full happy-path pipeline (workspace
setup -> implement -> verify -> commit -> report) -- that orchestration is
covered piecemeal in the per-module test files (test_workspace.py,
test_implementer.py, etc.) and end-to-end only by `--show-plan`/`--dry-run`
manual runs against a real repo, per case-solve/CLAUDE.md. Low-risk print
formatting is skipped in favor of eyeballing real output.

Run with: python -m unittest discover -s tests -v   (from case-solve/)
"""
import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import case_solve as cs


def _args(**overrides):
    """Build an argparse.Namespace with case_solve's CLI defaults, overridden
    by keyword. Mirrors what build_parser().parse_args() would produce."""
    base = dict(
        case_number="T1",
        repo=None,
        show_plan=False,
        no_implement=False,
        dry_run=False,
        skip_tests=False,
        skip_lint=False,
        skip_build=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


class ApplyCliOverridesTests(unittest.TestCase):
    """CLI flags are the last stage of the merge -- each one should touch
    exactly its own config key and leave everything else alone."""

    def test_no_flags_leaves_defaults_untouched(self):
        cfg = cs.load_config(Path("this-file-does-not-exist.json"))
        before = json.loads(json.dumps(cfg))  # deep copy via round-trip
        cs.apply_cli_overrides(cfg, _args())
        self.assertEqual(cfg, before)

    def test_skip_flags_flip_the_corresponding_run_booleans_to_false(self):
        cfg = cs.load_config(Path("this-file-does-not-exist.json"))
        cs.apply_cli_overrides(
            cfg, _args(skip_tests=True, skip_lint=True, skip_build=True)
        )
        self.assertFalse(cfg["run_tests"])
        self.assertFalse(cfg["run_lint"])
        self.assertFalse(cfg["run_build"])

    def test_skip_flags_false_do_not_flip_booleans_back_to_true(self):
        # apply_cli_overrides only ever sets False when the skip flag is
        # present; it must never re-assert the default True itself, or a
        # config.json override to False could never be honored.
        cfg = cs.load_config(Path("this-file-does-not-exist.json"))
        cfg["run_tests"] = False
        cs.apply_cli_overrides(cfg, _args(skip_tests=False))
        self.assertFalse(cfg["run_tests"])


class ConfigMergePrecedenceTests(unittest.TestCase):
    """DEFAULTS -> config.json -> CLI flags. Each stage must be able to
    override the previous one; earlier stages must not leak back through."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_config(self, data):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_missing_config_file_falls_back_to_defaults_only(self):
        cfg = cs.load_config(self.config_path)  # never written
        self.assertEqual(cfg, cs.DEFAULTS)

    def test_config_json_overrides_a_default_scalar(self):
        self._write_config({"run_lint": False})
        cfg = cs.load_config(self.config_path)
        self.assertFalse(cfg["run_lint"])
        self.assertTrue(cfg["run_tests"])  # untouched default survives

    def test_config_json_deep_merges_nested_dict_without_clobbering_siblings(self):
        self._write_config({"claude": {"model": "opus"}})
        cfg = cs.load_config(self.config_path)
        self.assertEqual(cfg["claude"]["model"], "opus")
        self.assertEqual(cfg["claude"]["agent"], "case-solver")  # sibling default kept

    def test_config_json_comments_are_stripped_before_use(self):
        self._write_config({"_comment": "docs", "claude": {"_comment": "x", "model": "haiku"}})
        cfg = cs.load_config(self.config_path)
        self.assertNotIn("_comment", cfg)
        self.assertNotIn("_comment", cfg["claude"])
        self.assertEqual(cfg["claude"]["model"], "haiku")

    def test_cli_flag_wins_over_config_json_value(self):
        self._write_config({"run_tests": True})
        cfg = cs.load_config(self.config_path)
        cs.apply_cli_overrides(cfg, _args(skip_tests=True))
        self.assertFalse(cfg["run_tests"])  # CLI beats config.json

    def test_config_json_value_survives_when_no_cli_flag_given(self):
        self._write_config({"run_build": False})
        cfg = cs.load_config(self.config_path)
        cs.apply_cli_overrides(cfg, _args())  # no --skip-build
        self.assertFalse(cfg["run_build"])  # config.json value, not the True default


class CheckReadinessTests(unittest.TestCase):
    """Own copy of case-guide's _READINESS_RE (see case_guide.py's
    "Readiness check") -- these lock in the same "Yes/missing == ready,
    No == blocked" contract case_guide.py's own PROMPT_TEMPLATE establishes."""

    def test_explicit_yes_is_ready(self):
        text = "# Case T1\n\n**Ready for Implementation:** Yes\n\nMore guide text."
        self.assertEqual(cs.check_readiness(text), (True, None))

    def test_explicit_no_is_not_ready_and_captures_the_reason(self):
        text = "# Case T1\n\n**Ready for Implementation:** No -- waiting on customer reply\n"
        self.assertEqual(
            cs.check_readiness(text), (False, "waiting on customer reply")
        )

    def test_no_without_a_reason_still_reports_not_ready(self):
        text = "**Ready for Implementation:** No\n"
        ready, reason = cs.check_readiness(text)
        self.assertFalse(ready)
        self.assertIsNone(reason)

    def test_missing_marker_defaults_to_ready(self):
        # An older guide, or claude dropped the line -- case-guide's own
        # write_and_open already warns about this; case-solve doesn't
        # additionally hard-block on it.
        text = "# Case T1\n\nJust a guide with no readiness line at all."
        self.assertEqual(cs.check_readiness(text), (True, None))

    def test_marker_far_past_the_scan_window_is_treated_as_missing(self):
        # Mirrors case-guide's own text[:1000] loose-check window.
        text = "x" * 1000 + "\n**Ready for Implementation:** No -- too late\n"
        self.assertEqual(cs.check_readiness(text), (True, None))

    def test_match_is_case_insensitive_on_yes_no(self):
        self.assertEqual(
            cs.check_readiness("**Ready for Implementation:** yes\n"), (True, None)
        )
        ready, _ = cs.check_readiness("**Ready for Implementation:** no -- reason\n")
        self.assertFalse(ready)


class ExtractRepoSuggestionTests(unittest.TestCase):
    def test_extracts_github_url(self):
        text = "## Get set up\n\n```\ngit clone https://github.com/acme/widgets.git\n```\n"
        self.assertEqual(cs.extract_repo_suggestion(text), "https://github.com/acme/widgets.git")

    def test_extracts_azure_devops_url(self):
        text = "Run: git clone https://dev.azure.com/acme/Proj/_git/widgets"
        self.assertEqual(
            cs.extract_repo_suggestion(text), "https://dev.azure.com/acme/Proj/_git/widgets"
        )

    def test_extracts_gitlab_url(self):
        text = "git clone https://gitlab.com/acme/widgets.git"
        self.assertEqual(cs.extract_repo_suggestion(text), "https://gitlab.com/acme/widgets.git")

    def test_strips_trailing_period_from_sentence_punctuation(self):
        text = "Clone the repo: git clone https://github.com/acme/widgets.git."
        self.assertEqual(cs.extract_repo_suggestion(text), "https://github.com/acme/widgets.git")

    def test_returns_none_when_guide_has_no_git_clone_line(self):
        text = "This guide has no clone instructions at all."
        self.assertIsNone(cs.extract_repo_suggestion(text))

    def test_returns_none_for_unrecognized_host_even_with_a_clone_line(self):
        # Known limitation of the substring heuristic: only github/dev.azure/
        # gitlab are recognized, so a real clone URL on another host is
        # silently missed rather than extracted. Locking in current
        # behavior, not endorsing it.
        text = "git clone https://bitbucket.org/acme/widgets.git"
        self.assertIsNone(cs.extract_repo_suggestion(text))

    def test_uses_first_matching_line_when_multiple_present(self):
        text = (
            "git clone https://github.com/acme/first.git\n"
            "git clone https://github.com/acme/second.git\n"
        )
        self.assertEqual(cs.extract_repo_suggestion(text), "https://github.com/acme/first.git")


class ExtractRepoNameTests(unittest.TestCase):
    def test_github_url(self):
        self.assertEqual(cs.extract_repo_name("https://github.com/acme/widgets"), "widgets")

    def test_github_url_with_git_suffix(self):
        self.assertEqual(cs.extract_repo_name("https://github.com/acme/widgets.git"), "widgets")

    def test_github_url_with_trailing_slash(self):
        self.assertEqual(cs.extract_repo_name("https://github.com/acme/widgets/"), "widgets")

    def test_azure_devops_url(self):
        # A meaningfully deeper path than GitHub's (org/project/_git/repo,
        # not just org/repo) -- the one other host shape this function's
        # own docstring calls out by name.
        self.assertEqual(
            cs.extract_repo_name("https://dev.azure.com/acme/Proj/_git/widgets"), "widgets"
        )


class SafeNameAndGuideFilenameTests(unittest.TestCase):
    def test_normal_case_number_is_untouched(self):
        self.assertEqual(cs._safe_name("T2611845"), "T2611845")

    def test_path_separators_become_underscores(self):
        self.assertEqual(cs._safe_name("../../etc/T1"), ".._.._etc_T1")

    def test_dots_and_dashes_are_preserved(self):
        self.assertEqual(cs._safe_name("T26-11.845"), "T26-11.845")

    def test_empty_or_fully_unsafe_text_falls_back_to_unlabeled(self):
        self.assertEqual(cs._safe_name(""), "unlabeled")
        self.assertEqual(cs._safe_name("!!!"), "unlabeled")

    def test_guide_filename_uses_the_sanitized_name(self):
        self.assertEqual(cs.guide_filename("T1"), "guide-T1.md")
        self.assertEqual(cs.guide_filename("../T1"), "guide-.._T1.md")


class FindGuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.guide_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name):
        open(os.path.join(self.guide_dir, name), "w").close()

    def test_exact_match(self):
        self._write("guide-T2611845.md")
        path = cs.find_guide("T2611845", self.guide_dir)
        self.assertEqual(os.path.basename(str(path)), "guide-T2611845.md")

    def test_substring_fallback_when_no_exact_match(self):
        self._write("guide-T2611845.md")
        path = cs.find_guide("T261", self.guide_dir)  # not an exact filename
        self.assertEqual(os.path.basename(str(path)), "guide-T2611845.md")

    def test_ambiguous_substring_match_exits_rather_than_guessing(self):
        self._write("guide-T3330.md")
        self._write("guide-T3331.md")
        with self.assertRaises(SystemExit):
            cs.find_guide("T333", self.guide_dir)

    def test_no_match_exits_with_a_helpful_message(self):
        with self.assertRaises(SystemExit) as ctx:
            cs.find_guide("T999", self.guide_dir)
        self.assertIn("Guide not found", str(ctx.exception))

    def test_traversal_attempt_cannot_escape_guide_dir(self):
        # A case number crafted to escape guide_dir via ../ must not resolve
        # to anything outside it -- _safe_name turns "/" into "_", so the
        # glob pattern can only ever match files inside guide_dir itself.
        # An unrelated file sitting one level up must never be found.
        parent = os.path.dirname(self.guide_dir)
        outside = tempfile.NamedTemporaryFile(
            dir=parent, suffix=".md", prefix="guide-ESCAPED", delete=False
        )
        outside.close()
        try:
            case_number = "../" + os.path.basename(outside.name)
            with self.assertRaises(SystemExit):
                cs.find_guide(case_number, self.guide_dir)
        finally:
            os.unlink(outside.name)


class PromptForRepoTests(unittest.TestCase):
    def test_returns_typed_url(self):
        with mock.patch("builtins.input", return_value="https://github.com/acme/typed.git"):
            self.assertEqual(cs.prompt_for_repo(), "https://github.com/acme/typed.git")

    def test_empty_input_falls_back_to_suggestion(self):
        with mock.patch("builtins.input", return_value=""):
            self.assertEqual(
                cs.prompt_for_repo("https://github.com/acme/suggested.git"),
                "https://github.com/acme/suggested.git",
            )

    def test_reprompts_until_non_empty_when_no_suggestion(self):
        answers = iter(["", "", "https://github.com/acme/eventually.git"])
        with mock.patch("builtins.input", side_effect=lambda prompt="": next(answers)):
            self.assertEqual(cs.prompt_for_repo(), "https://github.com/acme/eventually.git")


class ConfirmBeforeImplementingTests(unittest.TestCase):
    def test_yes_returns_true(self):
        with mock.patch("builtins.input", return_value="yes"):
            self.assertTrue(
                cs.confirm_before_implementing("T1", "https://github.com/acme/widgets.git", "case/T1")
            )

    def test_no_returns_false(self):
        with mock.patch("builtins.input", return_value="no"):
            self.assertFalse(
                cs.confirm_before_implementing("T1", "https://github.com/acme/widgets.git", "case/T1")
            )

    def test_reprompts_on_unrecognized_input(self):
        answers = iter(["maybe", "y"])
        with mock.patch("builtins.input", side_effect=lambda prompt="": next(answers)):
            self.assertTrue(
                cs.confirm_before_implementing("T1", "https://github.com/acme/widgets.git", "case/T1")
            )


class InteractivePathTests(unittest.TestCase):
    """case-solve is interactive-only -- no --yes/--ignore-readiness escape
    hatch of any kind (removed 2026-08-26). Every main() run resolves the
    repo URL and confirms before making changes via input(); these drive
    that sequence with a scripted builtins.input rather than skipping it."""

    def _run_main(self, argv, guide_text, input_mock):
        fake_guide_path = Path("guides") / "guide-T1.md"
        mock_workspace = mock.Mock(repo_dir="C:/fake/repo", branch_name="case/T1")
        mock_wm_instance = mock.Mock()
        mock_wm_instance.setup.return_value = mock_workspace
        mock_wm_cls = mock.Mock(return_value=mock_wm_instance)

        with mock.patch.object(sys, "argv", ["case_solve.py"] + argv), \
             mock.patch("case_solve.shutil.which", side_effect=lambda name: "/usr/bin/claude" if name == "claude" else None), \
             mock.patch("case_solve.find_guide", return_value=fake_guide_path), \
             mock.patch("case_solve.read_guide", return_value=guide_text), \
             mock.patch("lib.workspace.WorkspaceManager", mock_wm_cls), \
             mock.patch("builtins.input", input_mock):
            result = cs.main()
        return result, mock_wm_cls, input_mock

    def test_repo_flag_given_still_asks_for_confirmation(self):
        input_mock = mock.Mock(return_value="yes")
        result, mock_wm_cls, input_mock = self._run_main(
            ["T1", "--repo", "https://github.com/acme/widgets.git", "--no-implement"],
            guide_text="No clone instructions here.",
            input_mock=input_mock,
        )
        self.assertEqual(result, 0)
        input_mock.assert_called_once()  # --repo given, so only the confirmation prompt fires
        _, kwargs = mock_wm_cls.call_args
        self.assertEqual(kwargs["repo_url"], "https://github.com/acme/widgets.git")

    def test_no_repo_flag_prompts_for_one_then_confirms(self):
        answers = iter(["https://github.com/acme/typed.git", "yes"])
        input_mock = mock.Mock(side_effect=lambda prompt="": next(answers))
        result, mock_wm_cls, _ = self._run_main(
            ["T1", "--no-implement"],
            guide_text="No clone instructions here.",
            input_mock=input_mock,
        )
        self.assertEqual(result, 0)
        self.assertEqual(input_mock.call_count, 2)
        _, kwargs = mock_wm_cls.call_args
        self.assertEqual(kwargs["repo_url"], "https://github.com/acme/typed.git")

    def test_declining_confirmation_stops_before_workspace_setup(self):
        input_mock = mock.Mock(return_value="no")
        result, mock_wm_cls, _ = self._run_main(
            ["T1", "--repo", "https://github.com/acme/widgets.git", "--no-implement"],
            guide_text="irrelevant",
            input_mock=input_mock,
        )
        self.assertEqual(result, 1)
        mock_wm_cls.assert_not_called()


class ReadinessGateTests(unittest.TestCase):
    """The social readiness gate must stop main() before it even asks for a
    repo -- there's no point setting up a workspace for work a developer
    can't start yet -- and there's no flag to bypass it (--ignore-readiness
    was removed 2026-08-26; see NoBypassFlagTests below). Each not-ready
    test patches builtins.input to raise if called at all, proving the gate
    stops the run before any interactive prompt."""

    NOT_READY_TEXT = (
        "# Case T1\n\n**Ready for Implementation:** No -- waiting on customer reply\n\n"
        "## Before You Start -- Social Steps\n\n1. Ask the customer to confirm X.\n"
    )

    def _run_main(self, argv, guide_text, input_mock=None):
        fake_guide_path = Path("guides") / "guide-T1.md"
        mock_wm_cls = mock.Mock()
        if input_mock is None:
            input_mock = mock.Mock(
                side_effect=AssertionError("input() must never be called once the gate stops the run")
            )
        with mock.patch.object(sys, "argv", ["case_solve.py"] + argv), \
             mock.patch("case_solve.shutil.which", side_effect=lambda name: "/usr/bin/claude" if name == "claude" else None), \
             mock.patch("case_solve.find_guide", return_value=fake_guide_path), \
             mock.patch("case_solve.read_guide", return_value=guide_text), \
             mock.patch("lib.workspace.WorkspaceManager", mock_wm_cls), \
             mock.patch("builtins.input", input_mock):
            result = cs.main()
        return result, mock_wm_cls, input_mock

    def test_not_ready_guide_stops_before_workspace_setup(self):
        result, mock_wm_cls, input_mock = self._run_main(
            ["T1", "--repo", "https://github.com/acme/widgets.git"],
            guide_text=self.NOT_READY_TEXT,
        )
        self.assertEqual(result, 1)
        mock_wm_cls.assert_not_called()
        input_mock.assert_not_called()

    def test_ready_guide_is_unaffected(self):
        input_mock = mock.Mock(return_value="yes")
        result, mock_wm_cls, _ = self._run_main(
            ["T1", "--repo", "https://github.com/acme/widgets.git", "--no-implement"],
            guide_text="**Ready for Implementation:** Yes\n",
            input_mock=input_mock,
        )
        self.assertEqual(result, 0)
        mock_wm_cls.assert_called_once()


class NoBypassFlagTests(unittest.TestCase):
    """Locks in that --yes and --ignore-readiness are gone entirely (removed
    2026-08-26 at the user's request) -- not just unused, genuinely absent
    from the parser, so neither can be typed by mistake and silently do
    nothing."""

    def test_yes_is_not_a_recognized_flag(self):
        with self.assertRaises(SystemExit):
            cs.build_parser().parse_args(["T1", "--yes"])

    def test_ignore_readiness_is_not_a_recognized_flag(self):
        with self.assertRaises(SystemExit):
            cs.build_parser().parse_args(["T1", "--ignore-readiness"])


class MainModeFlagsTests(unittest.TestCase):
    """--show-plan and --dry-run both reach further into main() than
    --no-implement (which every other main()-level test in this file stops
    at) -- --show-plan must call generate_plan() and stop there without
    touching implement/verify/commit/report; --dry-run must call implement()
    but then skip Verifier/Committer entirely, unlike a normal run."""

    def _run_main(self, argv, guide_text="**Ready for Implementation:** Yes\n"):
        fake_guide_path = Path("guides") / "guide-T1.md"
        mock_workspace = mock.Mock(
            repo_dir="C:/fake/repo", branch_name="case/T1", case_dir=Path("C:/fake/case_dir"),
        )
        mock_wm_instance = mock.Mock()
        mock_wm_instance.setup.return_value = mock_workspace
        mock_wm_cls = mock.Mock(return_value=mock_wm_instance)

        mock_implementer_instance = mock.Mock()
        mock_implementer_instance.generate_plan.return_value = "1. Do the thing."
        mock_implementer_instance.implement.return_value = ["change one"]
        mock_implementer_cls = mock.Mock(return_value=mock_implementer_instance)

        mock_verifier_cls = mock.Mock()
        mock_committer_cls = mock.Mock()
        mock_committer_cls.return_value.commit_changes.return_value = ["commit one"]
        mock_report_cls = mock.Mock()
        mock_report_cls.return_value.generate.return_value = Path("C:/fake/case_dir/VERIFICATION_CHECKLIST.md")

        with mock.patch.object(sys, "argv", ["case_solve.py"] + argv), \
             mock.patch("case_solve.shutil.which", side_effect=lambda name: "/usr/bin/claude" if name == "claude" else None), \
             mock.patch("case_solve.find_guide", return_value=fake_guide_path), \
             mock.patch("case_solve.read_guide", return_value=guide_text), \
             mock.patch("lib.workspace.WorkspaceManager", mock_wm_cls), \
             mock.patch("lib.implementer.Implementer", mock_implementer_cls), \
             mock.patch("lib.verifier.Verifier", mock_verifier_cls), \
             mock.patch("lib.committer.Committer", mock_committer_cls), \
             mock.patch("lib.report.ReportGenerator", mock_report_cls), \
             mock.patch("builtins.input", return_value="yes"):
            # --repo is always given in this class's argv, so the only
            # interactive prompt reached is the confirmation -- "yes" covers it.
            result = cs.main()
        return result, mock_implementer_instance, mock_verifier_cls, mock_committer_cls, mock_report_cls

    def test_show_plan_prints_the_plan_and_stops_before_implementing_anything(self):
        result, implementer, verifier_cls, committer_cls, report_cls = self._run_main(
            ["T1", "--repo", "https://github.com/acme/widgets.git", "--show-plan"]
        )
        self.assertEqual(result, 0)
        implementer.generate_plan.assert_called_once()
        implementer.implement.assert_not_called()
        verifier_cls.assert_not_called()
        committer_cls.assert_not_called()
        report_cls.assert_not_called()

    def test_dry_run_implements_but_skips_verify_commit_and_reports_no_results(self):
        result, implementer, verifier_cls, committer_cls, report_cls = self._run_main(
            ["T1", "--repo", "https://github.com/acme/widgets.git", "--dry-run"]
        )
        self.assertEqual(result, 0)
        implementer.implement.assert_called_once()
        verifier_cls.assert_not_called()
        committer_cls.assert_not_called()
        report_cls.assert_called_once()
        _, kwargs = report_cls.call_args
        self.assertIsNone(kwargs["test_results"])
        self.assertEqual(kwargs["commits"], [])

    def test_normal_run_implements_verifies_and_commits(self):
        # Contrast case: confirms --dry-run's skip is opt-in, not the
        # default behavior.
        result, implementer, verifier_cls, committer_cls, report_cls = self._run_main(
            ["T1", "--repo", "https://github.com/acme/widgets.git"]
        )
        self.assertEqual(result, 0)
        implementer.implement.assert_called_once()
        verifier_cls.assert_called_once()
        committer_cls.assert_called_once()
        report_cls.assert_called_once()


class ClaudeNotFoundTests(unittest.TestCase):
    def test_missing_claude_cli_exits_before_looking_for_a_guide(self):
        with mock.patch.object(sys, "argv", ["case_solve.py", "T1"]), \
             mock.patch("case_solve.shutil.which", return_value=None), \
             mock.patch("case_solve.find_guide") as find_guide:
            with self.assertRaises(SystemExit) as ctx:
                cs.main()
        self.assertIn("claude CLI not found", str(ctx.exception))
        find_guide.assert_not_called()


if __name__ == "__main__":
    unittest.main()
