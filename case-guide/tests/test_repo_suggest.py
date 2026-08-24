"""Unit tests for lib/repo_suggest.py -- the repo/branch suggestion logic
moved here from case-brief (see case-brief/CLAUDE.md and this project's
CLAUDE.md). Mirrors case-brief's own former test coverage for the same
logic: find_customer_repo's substring matching, and
best_fuzzy_match/resolve_suggested_repos' fuzzy auto-match -- especially
best_fuzzy_match's ambiguity guard, which exists specifically so a case with
two similarly-named candidate projects/repos never gets a silently wrong
repo suggested with the same confidence as a real match.

resolve_suggested_repos takes an `ado_api` module/stand-in as its first
argument (rather than importing lib.ado_api itself) specifically so these
tests can hand it a lightweight fake instead of monkeypatching a module
attribute -- see FakeAdoApi below.

Run with: python -m unittest discover -s tests   (from case-guide/)
      or: python -m pytest tests                 (if pytest is installed)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import repo_suggest


class FakeAdoApi:
    """Stand-in for lib.ado_api exposing just what resolve_suggested_repos
    calls, each overridable per test via a constructor kwarg (a callable, or
    an exception instance to be raised)."""

    def __init__(self, list_projects=None, list_repos=None, get_repo=None):
        self._list_projects = list_projects
        self._list_repos = list_repos
        self._get_repo = get_repo

    def list_projects(self, cfg):
        if isinstance(self._list_projects, Exception):
            raise self._list_projects
        return self._list_projects(cfg) if callable(self._list_projects) else self._list_projects

    def list_repos(self, cfg, project):
        if isinstance(self._list_repos, Exception):
            raise self._list_repos
        return self._list_repos(cfg, project) if callable(self._list_repos) else self._list_repos

    def get_repo(self, cfg, project, repo_name):
        if isinstance(self._get_repo, Exception):
            raise self._get_repo
        return self._get_repo(cfg, project, repo_name) if callable(self._get_repo) else self._get_repo


class FindCustomerRepoTests(unittest.TestCase):
    def test_case_insensitive_substring_match(self):
        rule = repo_suggest.find_customer_repo(
            [{"customer_contains": "Contoso", "project": "P1", "repo": "R1"}], "CONTOSO s.r.o.")
        self.assertEqual(rule["project"], "P1")

    def test_no_match_returns_none(self):
        self.assertIsNone(repo_suggest.find_customer_repo(
            [{"customer_contains": "Contoso", "project": "P1", "repo": "R1"}], "Fabrikam"))

    def test_empty_customer_name_returns_none_without_crashing(self):
        rules = [{"customer_contains": "Contoso", "project": "P1", "repo": "R1"}]
        self.assertIsNone(repo_suggest.find_customer_repo(rules, None))
        self.assertIsNone(repo_suggest.find_customer_repo(rules, ""))

    def test_missing_customer_repo_map_returns_none(self):
        self.assertIsNone(repo_suggest.find_customer_repo(None, "Contoso"))
        self.assertIsNone(repo_suggest.find_customer_repo([], "Contoso"))


class BestFuzzyMatchTests(unittest.TestCase):
    def test_clear_winner_is_returned(self):
        result = repo_suggest.best_fuzzy_match("Contoso Ltd", ["Contoso", "Fabrikam", "Northwind"])
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Contoso")

    def test_ambiguous_top_two_candidates_refuses_to_guess(self):
        result = repo_suggest.best_fuzzy_match("Contoso", ["Contoso Corp", "Contoso Inc"])
        self.assertIsNone(result)

    def test_top_two_within_min_lead_refuses_to_guess_even_without_a_tie(self):
        result = repo_suggest.best_fuzzy_match("Northwind Traders", ["Northwind", "Northwind Trading Co"])
        self.assertIsNone(result)

    def test_below_threshold_returns_none_even_as_the_best_of_a_bad_set(self):
        result = repo_suggest.best_fuzzy_match("Zzyzx Corp", ["Contoso", "Fabrikam"])
        self.assertIsNone(result)

    def test_empty_candidate_list_returns_none(self):
        self.assertIsNone(repo_suggest.best_fuzzy_match("Contoso", []))

    def test_single_candidate_only_needs_to_clear_the_threshold(self):
        result = repo_suggest.best_fuzzy_match("Contoso", ["Contoso"])
        self.assertEqual(result[0], "Contoso")


class BranchNameTests(unittest.TestCase):
    def test_combines_case_and_slug(self):
        self.assertEqual(repo_suggest.branch_name("T123", "Fix the bug"), "T123-fix-the-bug")

    def test_falls_back_to_case_number_alone_without_a_title(self):
        self.assertEqual(repo_suggest.branch_name("T123", None), "T123")


class ResolveSuggestedReposTests(unittest.TestCase):
    def _azure_cfg(self, org_url="https://dev.azure.com/org"):
        return {"org_url": org_url}

    def test_repo_override_takes_priority_over_everything_else(self):
        api = FakeAdoApi(get_repo={"name": "repoA", "remoteUrl": "https://x/repoA"})
        customer_repo_map = [{"customer_contains": "acme", "project": "PX", "repo": "RX"}]
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), customer_repo_map, "ProjA/repoA", "Acme Corp")
        self.assertEqual(result, [{"project": "ProjA", "repo": "repoA", "clone_url": "https://x/repoA", "source": "cli"}])

    def test_malformed_repo_override_is_ignored_and_falls_through_to_next_priority(self):
        api = FakeAdoApi(get_repo=None)
        customer_repo_map = [{"customer_contains": "acme", "project": "PMap", "repo": "RMap"}]
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), customer_repo_map, "not-a-project-slash-repo", "Acme Corp")
        self.assertEqual(result, [{"project": "PMap", "repo": "RMap", "clone_url": None, "source": "customer_repo_map"}])

    def test_customer_repo_map_used_when_no_repo_override(self):
        api = FakeAdoApi(get_repo={"name": "RMap", "remoteUrl": "https://x/RMap"})
        customer_repo_map = [{"customer_contains": "acme", "project": "PMap", "repo": "RMap"}]
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), customer_repo_map, None, "Acme Corp")
        self.assertEqual(result[0]["source"], "customer_repo_map")

    def test_no_customer_returns_empty_list(self):
        api = FakeAdoApi()
        self.assertEqual(repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), [], None, None), [])

    def test_no_org_url_skips_auto_match_and_returns_empty(self):
        api = FakeAdoApi()
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(org_url=None), [], None, "Acme Corp")
        self.assertEqual(result, [])

    def test_ambiguous_repo_within_a_matched_project_lists_all_rather_than_guessing(self):
        repos = [{"name": "Acme Corp Billing", "remoteUrl": "https://x/billing"},
                 {"name": "Acme Corp Legacy", "remoteUrl": "https://x/legacy"}]
        api = FakeAdoApi(list_projects=(["Acme Corp"], False), list_repos=repos)
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), [], None, "Acme Corp")
        self.assertEqual(len(result), 2)
        self.assertTrue(all(r["source"] == "auto-match" for r in result))

    def test_single_repo_in_matched_project_is_returned_directly(self):
        repos = [{"name": "acme-billing", "remoteUrl": "https://x/billing"}]
        api = FakeAdoApi(list_projects=(["Acme Corp"], False), list_repos=repos)
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), [], None, "Acme Corp")
        self.assertEqual(result, [{"project": "Acme Corp", "repo": "acme-billing", "clone_url": "https://x/billing", "source": "auto-match"}])

    def test_project_listing_failure_degrades_to_empty_list_not_a_crash(self):
        api = FakeAdoApi(list_projects=RuntimeError("boom"))
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), [], None, "Acme Corp")
        self.assertEqual(result, [])


class MergeConfirmedAndGuessedTests(unittest.TestCase):
    def test_confirmed_ado_match_takes_priority_over_a_guessed_suggestion_for_the_same_repo(self):
        detail = {"branches": [{"project": "P", "repo": "R", "clone_url": "https://confirmed"}], "pull_requests": []}
        guessed = [{"project": "P", "repo": "R", "clone_url": "https://guessed", "source": "auto-match"}]
        repos = repo_suggest.merge_confirmed_and_guessed(detail, guessed)
        self.assertEqual(repos[("P", "R")]["clone_url"], "https://confirmed")

    def test_guessed_suggestion_used_when_nothing_confirmed(self):
        guessed = [{"project": "P", "repo": "R", "clone_url": "https://guessed", "source": "auto-match"}]
        repos = repo_suggest.merge_confirmed_and_guessed(None, guessed)
        self.assertEqual(repos[("P", "R")], {"clone_url": "https://guessed", "source": "auto-match"})

    def test_no_detail_and_no_guess_is_empty(self):
        self.assertEqual(repo_suggest.merge_confirmed_and_guessed(None, []), {})


class FormatSuggestedRepoTests(unittest.TestCase):
    def test_no_repos_shows_the_generic_tip(self):
        text = repo_suggest.format_suggested_repo({}, "T1-fix")
        self.assertIn("No repo identified yet", text)
        self.assertIn("git checkout -b T1-fix", text)
        self.assertIn("customer_repo_map", text)

    def test_guessed_repo_is_labeled_as_a_guess(self):
        repos = {("P", "R"): {"clone_url": "https://x", "source": "auto-match"}}
        text = repo_suggest.format_suggested_repo(repos, "T1-fix")
        self.assertIn("guessed from customer name", text)

    def test_confirmed_repo_is_not_labeled_as_a_guess(self):
        repos = {("P", "R"): {"clone_url": "https://x", "source": "ado-search"}}
        text = repo_suggest.format_suggested_repo(repos, "T1-fix")
        self.assertNotIn("guessed from customer name", text)
        self.assertIn("git clone https://x", text)


if __name__ == "__main__":
    unittest.main()
