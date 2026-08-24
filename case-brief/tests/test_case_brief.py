"""Unit tests for case_brief.py's pure-logic, security/correctness-sensitive
pieces: the config merge order (DEFAULTS -> config.json -> CLI flags,
apply_cli_overrides/load_config) and run_ado_lookup's direct-reference vs.
broad-search branching.

Deliberately not exhaustive over every CLI flag or every branch of
build_parser/main -- those are low-risk plumbing, easily eyeballed with
`--demo --show-prompt`-style manual runs. This file locks in the handful of
things that would otherwise fail silently and misleadingly: a CLI flag that
should win over config.json but doesn't (or vice versa), a config-merge that
clobbers a whole sub-dict instead of merging it, and a direct ADO reference
that should skip the (slow, opt-in) broad search but doesn't.

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
        no_open=False, org_url=None, project=None, max_prs=None,
        pat_env_var=None, ticket_field=None, crm_host=None,
        chrome_profile_dir=None, chrome_port=None, output_dir=None,
        search_ado=False,
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
        cfg["output_dir"] = "changed"
        self.assertNotEqual(cb.DEFAULTS["output_dir"], "changed")

    def test_config_json_overrides_only_the_keys_it_sets(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"azure_devops": {"org_url": "https://dev.azure.com/acme"}}')
            cfg = cb.load_config(path)
        self.assertEqual(cfg["azure_devops"]["org_url"], "https://dev.azure.com/acme")
        # Sibling keys in the same sub-dict must survive the merge untouched --
        # a naive `cfg[key] = value` on the whole "azure_devops" dict would
        # have wiped these out instead of merging one level deeper.
        self.assertEqual(cfg["azure_devops"]["pat_env_var"], "AZDO_PAT")
        self.assertEqual(cfg["azure_devops"]["max_prs"], cb.ado_api.DEFAULT_MAX_PRS)
        self.assertEqual(cfg["chrome"], cb.DEFAULTS["chrome"])

    def test_top_level_scalar_override(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"output_dir": "./somewhere-else", "open_in_vscode": false}')
            cfg = cb.load_config(path)
        self.assertEqual(cfg["output_dir"], "./somewhere-else")
        self.assertFalse(cfg["open_in_vscode"])


class ApplyCliOverridesTests(unittest.TestCase):
    def test_cli_flags_win_over_config_json_values(self):
        cfg = copy.deepcopy(cb.DEFAULTS)
        cfg["azure_devops"]["org_url"] = "https://dev.azure.com/from-config"
        args = make_args(org_url="https://dev.azure.com/from-cli", project="FromCli")
        cb.apply_cli_overrides(cfg, args)
        self.assertEqual(cfg["azure_devops"]["org_url"], "https://dev.azure.com/from-cli")
        self.assertEqual(cfg["azure_devops"]["project"], "FromCli")

    def test_unset_cli_flags_leave_config_values_alone(self):
        cfg = copy.deepcopy(cb.DEFAULTS)
        cfg["azure_devops"]["org_url"] = "https://dev.azure.com/from-config"
        cfg["output_dir"] = "./configured-output"
        args = make_args()  # nothing passed on the CLI
        cb.apply_cli_overrides(cfg, args)
        self.assertEqual(cfg["azure_devops"]["org_url"], "https://dev.azure.com/from-config")
        self.assertEqual(cfg["output_dir"], "./configured-output")

    def test_max_prs_zero_is_honored_not_treated_as_unset(self):
        # max_prs is deliberately checked with `is not None` rather than
        # truthiness (unlike the other overrides) specifically so --max-prs 0
        # can be set at all; a plain `if args.max_prs:` would silently ignore
        # this and keep the configured default instead.
        cfg = copy.deepcopy(cb.DEFAULTS)
        args = make_args(max_prs=0)
        cb.apply_cli_overrides(cfg, args)
        self.assertEqual(cfg["azure_devops"]["max_prs"], 0)

    def test_max_prs_none_leaves_configured_value_untouched(self):
        cfg = copy.deepcopy(cb.DEFAULTS)
        cfg["azure_devops"]["max_prs"] = 25
        args = make_args(max_prs=None)
        cb.apply_cli_overrides(cfg, args)
        self.assertEqual(cfg["azure_devops"]["max_prs"], 25)

    def test_crm_host_list_flag_replaces_rather_than_appends_to_config(self):
        cfg = copy.deepcopy(cb.DEFAULTS)
        cfg["url_patterns"]["crm_host_contains"] = ["dynamics.com"]
        args = make_args(crm_host=["mycrm.example.com"])
        cb.apply_cli_overrides(cfg, args)
        self.assertEqual(cfg["url_patterns"]["crm_host_contains"], ["mycrm.example.com"])

    def test_search_ado_flag_turns_on_broad_search(self):
        cfg = copy.deepcopy(cb.DEFAULTS)
        self.assertFalse(cfg["azure_devops"]["broad_search"])
        args = make_args(search_ado=True)
        cb.apply_cli_overrides(cfg, args)
        self.assertTrue(cfg["azure_devops"]["broad_search"])

    def test_search_ado_not_passed_leaves_broad_search_off(self):
        cfg = copy.deepcopy(cb.DEFAULTS)
        args = make_args()
        cb.apply_cli_overrides(cfg, args)
        self.assertFalse(cfg["azure_devops"]["broad_search"])


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
    def _cfg(self, **azure_overrides):
        cfg = copy.deepcopy(cb.DEFAULTS)
        cfg["azure_devops"]["org_url"] = "https://dev.azure.com/myorg"
        cfg["azure_devops"].update(azure_overrides)
        return cfg

    def test_no_org_url_configured_is_an_error(self):
        cfg = copy.deepcopy(cb.DEFAULTS)
        args = make_args()
        branches, prs, ado_error, ado_note, truncated, max_prs = cb.run_ado_lookup(cfg, args, [])
        self.assertIn("no Azure DevOps org URL configured", ado_error)
        self.assertEqual((branches, prs), ([], []))

    def test_direct_reference_found_resolves_it_and_skips_the_broad_search(self):
        cfg = self._cfg()
        args = make_args()
        crm_results = [{"description": "https://dev.azure.com/myorg/P/_git/R/pullrequest/5"}]
        pr = {"project": "P", "id": 5, "repo": "R", "title": "t", "status": "active",
              "created_by": "x", "url": "u", "clone_url": None}
        with mock.patch.object(cb.ado_api, "get_pull_request", return_value=pr) as get_pr, \
             mock.patch.object(cb.ado_api, "find_related") as find_related:
            branches, prs, ado_error, ado_note, truncated, max_prs = cb.run_ado_lookup(cfg, args, crm_results)
        get_pr.assert_called_once_with(cfg["azure_devops"], "P", "R", 5)
        find_related.assert_not_called()
        self.assertEqual(prs, [pr])
        self.assertIsNone(ado_error)
        self.assertIn("Resolved 1/1", ado_note)

    def test_no_direct_reference_and_broad_search_disabled_skips_the_search(self):
        cfg = self._cfg(broad_search=False)
        args = make_args()
        with mock.patch.object(cb.ado_api, "find_related") as find_related:
            branches, prs, ado_error, ado_note, truncated, max_prs = cb.run_ado_lookup(cfg, args, [])
        find_related.assert_not_called()
        self.assertEqual((branches, prs), ([], []))
        self.assertIn("org-wide search skipped", ado_note)

    def test_no_direct_reference_and_broad_search_enabled_falls_back_to_find_related(self):
        cfg = self._cfg(broad_search=True)
        args = make_args(case_number="T1")
        with mock.patch.object(cb.ado_api, "find_related", return_value=([{"b": 1}], [{"p": 1}], False, 50)) as find_related:
            branches, prs, ado_error, ado_note, truncated, max_prs = cb.run_ado_lookup(cfg, args, [])
        find_related.assert_called_once_with(cfg["azure_devops"], "T1")
        self.assertEqual(branches, [{"b": 1}])
        self.assertEqual(prs, [{"p": 1}])
        self.assertIn("full org-wide search", ado_note)

    def test_broad_search_enabled_but_no_case_number_available_is_an_error(self):
        cfg = self._cfg(broad_search=True)
        args = make_args()
        with mock.patch.object(cb.ado_api, "find_related") as find_related:
            branches, prs, ado_error, ado_note, truncated, max_prs = cb.run_ado_lookup(cfg, args, [])
        find_related.assert_not_called()
        self.assertIn("no case number given", ado_error)

    def test_a_failed_direct_reference_is_reported_in_the_note_not_raised(self):
        cfg = self._cfg()
        args = make_args()
        crm_results = [{"description": "https://dev.azure.com/myorg/P/_git/R/pullrequest/5"}]
        with mock.patch.object(cb.ado_api, "get_pull_request", side_effect=RuntimeError("404")):
            branches, prs, ado_error, ado_note, truncated, max_prs = cb.run_ado_lookup(cfg, args, crm_results)
        self.assertEqual(prs, [])
        self.assertIsNone(ado_error)
        self.assertIn("0/1", ado_note)
        self.assertIn("1 could not be resolved", ado_note)


if __name__ == "__main__":
    unittest.main()
