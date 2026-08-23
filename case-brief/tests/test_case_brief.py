"""Unit tests for case_brief.py's pure-logic, security/correctness-sensitive
pieces: the config merge order (DEFAULTS -> config.json -> CLI flags,
apply_cli_overrides/load_config), find_customer_repo's substring matching,
and resolve_suggested_repos' fuzzy auto-match -- especially
_best_fuzzy_match's ambiguity guard, which exists specifically so a case
with two similarly-named candidate projects/repos never gets a silently
wrong repo suggested with the same confidence as a real match.

Deliberately not exhaustive over every CLI flag or every branch of
build_parser/main -- those are low-risk plumbing, easily eyeballed with
`--demo --show-prompt`-style manual runs. This file locks in the handful of
things that would otherwise fail silently and misleadingly: a CLI flag that
should win over config.json but doesn't (or vice versa), a config-merge that
clobbers a whole sub-dict instead of merging it, and a fuzzy match that
looks confident but is actually a coin flip between two candidates.

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
    apply_cli_overrides/resolve_suggested_repos reads, defaulting to the
    "flag not passed" value (None/False) unless overridden."""
    defaults = dict(
        case_number=None, demo=False, skip_ado=False, skip_browser=False,
        with_bc=False, no_open=False, org_url=None, project=None, max_prs=None,
        pat_env_var=None, repo=None, ticket_field=None, crm_host=None,
        bc_host=None, chrome_profile_dir=None, chrome_port=None, output_dir=None,
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


class FindCustomerRepoTests(unittest.TestCase):
    def test_case_insensitive_substring_match(self):
        cfg = {"customer_repo_map": [{"customer_contains": "Contoso", "project": "P1", "repo": "R1"}]}
        rule = cb.find_customer_repo(cfg, "CONTOSO s.r.o.")
        self.assertEqual(rule["project"], "P1")

    def test_no_match_returns_none(self):
        cfg = {"customer_repo_map": [{"customer_contains": "Contoso", "project": "P1", "repo": "R1"}]}
        self.assertIsNone(cb.find_customer_repo(cfg, "Fabrikam"))

    def test_empty_customer_name_returns_none_without_crashing(self):
        cfg = {"customer_repo_map": [{"customer_contains": "Contoso", "project": "P1", "repo": "R1"}]}
        self.assertIsNone(cb.find_customer_repo(cfg, None))
        self.assertIsNone(cb.find_customer_repo(cfg, ""))

    def test_missing_customer_repo_map_key_returns_none(self):
        self.assertIsNone(cb.find_customer_repo({}, "Contoso"))


class BestFuzzyMatchTests(unittest.TestCase):
    def test_clear_winner_is_returned(self):
        result = cb._best_fuzzy_match("Contoso Ltd", ["Contoso", "Fabrikam", "Northwind"])
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Contoso")

    def test_ambiguous_top_two_candidates_refuses_to_guess(self):
        # Two candidates that normalize to something equally close to the
        # target must NOT produce a confident-looking single answer --
        # guessing wrong here would silently point someone at the wrong repo.
        result = cb._best_fuzzy_match("Contoso", ["Contoso Corp", "Contoso Inc"])
        self.assertIsNone(result)

    def test_top_two_within_min_lead_refuses_to_guess_even_without_a_tie(self):
        # Not a literal tie -- just too close together (lead < min_lead) --
        # must still be treated as ambiguous rather than picking the higher one.
        result = cb._best_fuzzy_match("Northwind Traders", ["Northwind", "Northwind Trading Co"])
        self.assertIsNone(result)

    def test_below_threshold_returns_none_even_as_the_best_of_a_bad_set(self):
        result = cb._best_fuzzy_match("Zzyzx Corp", ["Contoso", "Fabrikam"])
        self.assertIsNone(result)

    def test_empty_candidate_list_returns_none(self):
        self.assertIsNone(cb._best_fuzzy_match("Contoso", []))

    def test_single_candidate_only_needs_to_clear_the_threshold(self):
        # With no runner-up, min_lead can't disqualify it -- score alone decides.
        result = cb._best_fuzzy_match("Contoso", ["Contoso"])
        self.assertEqual(result[0], "Contoso")


class ResolveSuggestedReposTests(unittest.TestCase):
    def _cfg(self, org_url="https://dev.azure.com/org", customer_repo_map=None):
        cfg = copy.deepcopy(cb.DEFAULTS)
        cfg["azure_devops"]["org_url"] = org_url
        cfg["customer_repo_map"] = customer_repo_map or []
        return cfg

    def test_cli_repo_flag_takes_priority_over_everything_else(self):
        cfg = self._cfg(customer_repo_map=[{"customer_contains": "acme", "project": "PX", "repo": "RX"}])
        args = make_args(repo="ProjA/repoA")
        crm_results = [{"customer": "Acme Corp"}]
        with mock.patch.object(cb.ado_api, "get_repo", return_value={"name": "repoA", "remoteUrl": "https://x/repoA"}):
            result = cb.resolve_suggested_repos(cfg, args, crm_results)
        self.assertEqual(result, [{"project": "ProjA", "repo": "repoA", "clone_url": "https://x/repoA", "source": "cli"}])

    def test_malformed_repo_flag_is_ignored_and_falls_through_to_next_priority(self):
        # No "/" in --repo can't be split into project/repo -- rather than
        # crashing or silently returning nothing, it should warn and fall
        # through to the next source (customer_repo_map here).
        cfg = self._cfg(customer_repo_map=[{"customer_contains": "acme", "project": "PMap", "repo": "RMap"}])
        args = make_args(repo="not-a-project-slash-repo")
        crm_results = [{"customer": "Acme Corp"}]
        with mock.patch.object(cb.ado_api, "get_repo", return_value=None):
            result = cb.resolve_suggested_repos(cfg, args, crm_results)
        self.assertEqual(result, [{"project": "PMap", "repo": "RMap", "clone_url": None, "source": "customer_repo_map"}])

    def test_customer_repo_map_used_when_no_repo_flag(self):
        cfg = self._cfg(customer_repo_map=[{"customer_contains": "acme", "project": "PMap", "repo": "RMap"}])
        args = make_args()
        crm_results = [{"customer": "Acme Corp"}]
        with mock.patch.object(cb.ado_api, "get_repo", return_value={"name": "RMap", "remoteUrl": "https://x/RMap"}):
            result = cb.resolve_suggested_repos(cfg, args, crm_results)
        self.assertEqual(result[0]["source"], "customer_repo_map")

    def test_no_crm_results_returns_empty_list(self):
        cfg = self._cfg()
        args = make_args()
        self.assertEqual(cb.resolve_suggested_repos(cfg, args, []), [])

    def test_crm_error_result_returns_empty_list(self):
        cfg = self._cfg()
        args = make_args()
        crm_results = [{"error": "No authenticated CRM tab found.", "url": ""}]
        self.assertEqual(cb.resolve_suggested_repos(cfg, args, crm_results), [])

    def test_no_org_url_skips_auto_match_and_returns_empty(self):
        cfg = self._cfg(org_url=None)
        args = make_args()
        crm_results = [{"customer": "Acme Corp"}]
        self.assertEqual(cb.resolve_suggested_repos(cfg, args, crm_results), [])

    def test_ambiguous_repo_within_a_matched_project_lists_all_rather_than_guessing(self):
        cfg = self._cfg()
        args = make_args()
        crm_results = [{"customer": "Acme Corp"}]
        repos = [{"name": "Acme Corp Billing", "remoteUrl": "https://x/billing"},
                 {"name": "Acme Corp Legacy", "remoteUrl": "https://x/legacy"}]
        with mock.patch.object(cb.ado_api, "list_projects", return_value=["Acme Corp"]), \
             mock.patch.object(cb.ado_api, "list_repos", return_value=repos):
            result = cb.resolve_suggested_repos(cfg, args, crm_results)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(r["source"] == "auto-match" for r in result))

    def test_single_repo_in_matched_project_is_returned_directly(self):
        cfg = self._cfg()
        args = make_args()
        crm_results = [{"customer": "Acme Corp"}]
        repos = [{"name": "acme-billing", "remoteUrl": "https://x/billing"}]
        with mock.patch.object(cb.ado_api, "list_projects", return_value=["Acme Corp"]), \
             mock.patch.object(cb.ado_api, "list_repos", return_value=repos):
            result = cb.resolve_suggested_repos(cfg, args, crm_results)
        self.assertEqual(result, [{"project": "Acme Corp", "repo": "acme-billing", "clone_url": "https://x/billing", "source": "auto-match"}])

    def test_project_listing_failure_degrades_to_empty_list_not_a_crash(self):
        cfg = self._cfg()
        args = make_args()
        crm_results = [{"customer": "Acme Corp"}]
        with mock.patch.object(cb.ado_api, "list_projects", side_effect=RuntimeError("boom")):
            result = cb.resolve_suggested_repos(cfg, args, crm_results)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
