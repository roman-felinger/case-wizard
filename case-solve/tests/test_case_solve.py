"""Unit tests for case_solve.py's pure-logic pieces and CLI wiring: the
config deep-merge precedence (DEFAULTS -> config.json -> CLI flags via
apply_cli_overrides), the guide-lookup traversal guard and ambiguous-match
safety (mirrors case-guide's FindBriefTests pattern), repo-URL extraction
from freeform guide text, repo-name extraction across GitHub/ADO/GitLab URL
shapes, and filename sanitization.

The highest-value coverage here is the `--yes` non-interactive path added
this session: case_solve.main() must NEVER call input() when --yes is set,
whether a repo is given explicitly, falls back to a guide-extracted
suggestion, or (with neither) exits with a clear error instead of hanging.
We prove "never calls input()" by patching builtins.input to raise if
invoked at all, not just by checking the return value.

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
        solves_dir=None,
        show_plan=False,
        no_implement=False,
        dry_run=False,
        yes=False,
        skip_tests=False,
        skip_lint=False,
        skip_build=False,
        guide_dir=None,
        config=str(cs.CONFIG_PATH),
        no_open=False,
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
        self.assertNotIn("repo", cfg)  # never set unless --repo given

    def test_repo_flag_sets_repo_key(self):
        cfg = cs.load_config(Path("this-file-does-not-exist.json"))
        cs.apply_cli_overrides(cfg, _args(repo="https://github.com/org/repo.git"))
        self.assertEqual(cfg["repo"], "https://github.com/org/repo.git")

    def test_guide_dir_and_solves_dir_flags(self):
        cfg = cs.load_config(Path("this-file-does-not-exist.json"))
        cs.apply_cli_overrides(cfg, _args(guide_dir="/g", solves_dir="/s"))
        self.assertEqual(cfg["guide_dir"], "/g")
        self.assertEqual(cfg["solves_dir"], "/s")

    def test_skip_flags_flip_the_corresponding_run_booleans_to_false(self):
        cfg = cs.load_config(Path("this-file-does-not-exist.json"))
        cs.apply_cli_overrides(
            cfg, _args(skip_tests=True, skip_lint=True, skip_build=True, no_open=True)
        )
        self.assertFalse(cfg["run_tests"])
        self.assertFalse(cfg["run_lint"])
        self.assertFalse(cfg["run_build"])
        self.assertFalse(cfg["open_in_vscode"])

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

    def test_full_chain_default_then_config_then_cli(self):
        # guide_dir: default -> config.json overrides -> CLI overrides again.
        self._write_config({"guide_dir": "/from-config"})
        cfg = cs.load_config(self.config_path)
        self.assertEqual(cfg["guide_dir"], "/from-config")
        cs.apply_cli_overrides(cfg, _args(guide_dir="/from-cli"))
        self.assertEqual(cfg["guide_dir"], "/from-cli")  # CLI wins here


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
        self.assertEqual(
            cs.extract_repo_name("https://dev.azure.com/acme/Proj/_git/widgets"), "widgets"
        )

    def test_gitlab_url(self):
        self.assertEqual(cs.extract_repo_name("https://gitlab.com/acme/widgets.git"), "widgets")


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
        self.assertEqual(cs.guide_filename("T1"), "case-T1-for-dummies.md")
        self.assertEqual(cs.guide_filename("../T1"), "case-.._T1-for-dummies.md")


class FindGuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.guide_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name):
        open(os.path.join(self.guide_dir, name), "w").close()

    def test_exact_match(self):
        self._write("case-T2611845-for-dummies.md")
        path = cs.find_guide("T2611845", self.guide_dir)
        self.assertEqual(os.path.basename(str(path)), "case-T2611845-for-dummies.md")

    def test_substring_fallback_when_no_exact_match(self):
        self._write("case-T2611845-for-dummies.md")
        path = cs.find_guide("T261", self.guide_dir)  # not an exact filename
        self.assertEqual(os.path.basename(str(path)), "case-T2611845-for-dummies.md")

    def test_ambiguous_substring_match_exits_rather_than_guessing(self):
        self._write("case-T3330-for-dummies.md")
        self._write("case-T3331-for-dummies.md")
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
            dir=parent, suffix="-for-dummies.md", prefix="case-ESCAPED", delete=False
        )
        outside.close()
        try:
            case_number = "../" + os.path.basename(outside.name)
            with self.assertRaises(SystemExit):
                cs.find_guide(case_number, self.guide_dir)
        finally:
            os.unlink(outside.name)


class YesFlagNonInteractiveTests(unittest.TestCase):
    """The --yes flag exists specifically so a non-interactive caller (e.g.
    case-wizard's Streamlit UI running this as a subprocess) never hangs on
    input(). Each test patches builtins.input to raise AssertionError if
    called at all -- proving it, not just checking outcomes."""

    def _run_main(self, argv, guide_text, input_mock=None):
        fake_guide_path = Path("case-guides") / "case-T1-for-dummies.md"
        mock_workspace = mock.Mock(repo_dir="C:/fake/repo", branch_name="case/T1")
        mock_wm_instance = mock.Mock()
        mock_wm_instance.setup.return_value = mock_workspace
        mock_wm_cls = mock.Mock(return_value=mock_wm_instance)

        if input_mock is None:
            input_mock = mock.Mock(
                side_effect=AssertionError("input() must never be called under --yes")
            )

        with mock.patch.object(sys, "argv", ["case_solve.py"] + argv), \
             mock.patch("case_solve.shutil.which", side_effect=lambda name: "/usr/bin/claude" if name == "claude" else None), \
             mock.patch("case_solve.find_guide", return_value=fake_guide_path), \
             mock.patch("case_solve.read_guide", return_value=guide_text), \
             mock.patch("lib.workspace.WorkspaceManager", mock_wm_cls), \
             mock.patch("builtins.input", input_mock):
            result = cs.main()
        return result, mock_wm_cls, input_mock

    def test_yes_with_explicit_repo_never_calls_input(self):
        result, mock_wm_cls, input_mock = self._run_main(
            ["T1", "--yes", "--repo", "https://github.com/acme/widgets.git", "--no-implement"],
            guide_text="No clone instructions here.",
        )
        self.assertEqual(result, 0)
        input_mock.assert_not_called()
        _, kwargs = mock_wm_cls.call_args
        self.assertEqual(kwargs["repo_url"], "https://github.com/acme/widgets.git")

    def test_yes_falls_back_to_guide_suggested_repo_when_no_repo_flag(self):
        guide_text = "## Get set up\n\ngit clone https://github.com/acme/fallback.git\n"
        result, mock_wm_cls, input_mock = self._run_main(
            ["T1", "--yes", "--no-implement"],
            guide_text=guide_text,
        )
        self.assertEqual(result, 0)
        input_mock.assert_not_called()
        _, kwargs = mock_wm_cls.call_args
        self.assertEqual(kwargs["repo_url"], "https://github.com/acme/fallback.git")

    def test_yes_without_repo_or_suggestion_raises_system_exit(self):
        fake_guide_path = Path("case-guides") / "case-T1-for-dummies.md"
        input_mock = mock.Mock(
            side_effect=AssertionError("input() must never be called under --yes")
        )
        with mock.patch.object(
            sys, "argv", ["case_solve.py", "T1", "--yes", "--no-implement"]
        ), mock.patch(
            "case_solve.shutil.which", side_effect=lambda name: "/usr/bin/claude" if name == "claude" else None
        ), mock.patch(
            "case_solve.find_guide", return_value=fake_guide_path
        ), mock.patch(
            "case_solve.read_guide", return_value="No clone instructions anywhere."
        ), mock.patch(
            "builtins.input", input_mock
        ):
            with self.assertRaises(SystemExit) as ctx:
                cs.main()
        self.assertIn("--yes requires --repo", str(ctx.exception))
        input_mock.assert_not_called()

    def test_without_yes_the_interactive_path_still_prompts_as_before(self):
        # Contrast case: confirms we didn't accidentally remove the
        # interactive path while adding --yes. input() IS expected here.
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


if __name__ == "__main__":
    unittest.main()
