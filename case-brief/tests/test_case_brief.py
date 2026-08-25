"""Unit tests for case_brief.py's pure-logic, security/correctness-sensitive
pieces: the config merge order (DEFAULTS -> config.json -> CLI flags,
apply_cli_overrides/load_config, now just the Chrome profile) and
run_ado_lookup's direct-reference resolution.

Deliberately not exhaustive over every CLI flag or every branch of
build_parser/main -- those are low-risk plumbing, easily eyeballed with
`--demo`-style manual runs. This file locks in the handful of things that
would otherwise fail silently and misleadingly: a CLI flag that should win
over config.json but doesn't (or vice versa), a config-merge that clobbers a
whole sub-dict instead of merging it, and a direct ADO reference that
resolves (or fails to) correctly.

Run with: python -m unittest discover -s tests -v   (from case-brief/)
      or: python -m pytest tests                     (if pytest is installed)
"""
import copy
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import case_brief as cb


def make_args(**overrides):
    """A minimal argparse.Namespace stand-in with every field
    apply_cli_overrides reads, defaulting to the "flag not passed" value
    (None/False) unless overridden."""
    defaults = dict(
        case_number=None, demo=False, skip_ado=False, skip_browser=False,
        no_open=False, chrome_profile_dir=None, chrome_port=None,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


class LoadConfigTests(unittest.TestCase):
    def test_defaults_used_when_config_file_is_absent(self):
        missing_path = os.path.join(tempfile.gettempdir(), "definitely-does-not-exist-cb.json")
        cfg = cb.load_config(missing_path)
        self.assertEqual(cfg, cb.DEFAULTS)
        # Make sure it's a real copy, not the live DEFAULTS dict itself --
        # mutating cfg must never leak back into DEFAULTS for the next call.
        cfg["chrome"]["profile_dir"] = "changed"
        self.assertNotEqual(cb.DEFAULTS["chrome"]["profile_dir"], "changed")

    def test_config_json_overrides_only_the_keys_it_sets(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"chrome": {"debug_port": 9999}}')
            cfg = cb.load_config(path)
        self.assertEqual(cfg["chrome"]["debug_port"], 9999)
        # Sibling keys in the same sub-dict must survive the merge untouched --
        # a naive `cfg[key] = value` on the whole "chrome" dict would have
        # wiped these out instead of merging one level deeper.
        self.assertEqual(cfg["chrome"]["profile_dir"], cb.DEFAULTS["chrome"]["profile_dir"])
        self.assertEqual(cfg["chrome"]["executable"], cb.DEFAULTS["chrome"]["executable"])


class ApplyCliOverridesTests(unittest.TestCase):
    def test_cli_flags_win_over_config_json_values(self):
        cfg = copy.deepcopy(cb.DEFAULTS)
        cfg["chrome"]["profile_dir"] = "./from-config"
        args = make_args(chrome_profile_dir="./from-cli", chrome_port=9999)
        cb.apply_cli_overrides(cfg, args)
        self.assertEqual(cfg["chrome"]["profile_dir"], "./from-cli")
        self.assertEqual(cfg["chrome"]["debug_port"], 9999)

    def test_unset_cli_flags_leave_config_values_alone(self):
        cfg = copy.deepcopy(cb.DEFAULTS)
        cfg["chrome"]["profile_dir"] = "./from-config"
        args = make_args()  # nothing passed on the CLI
        cb.apply_cli_overrides(cfg, args)
        self.assertEqual(cfg["chrome"]["profile_dir"], "./from-config")


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
