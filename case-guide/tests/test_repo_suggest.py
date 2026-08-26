"""Unit tests for lib/repo_suggest.py -- the repo/branch suggestion logic
moved here from case-brief (see case-brief/CLAUDE.md and this project's
CLAUDE.md): best_fuzzy_match/resolve_suggested_repos' fuzzy auto-match,
especially best_fuzzy_match's ambiguity guard, which exists specifically so
a case with two similarly-named candidate projects/repos never gets a
silently wrong repo suggested with the same confidence as a real match.

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

    def __init__(self, list_projects=None, list_repos=None):
        self._list_projects = list_projects
        self._list_repos = list_repos

    def list_projects(self, cfg):
        if isinstance(self._list_projects, Exception):
            raise self._list_projects
        return self._list_projects(cfg) if callable(self._list_projects) else self._list_projects

    def list_repos(self, cfg, project):
        if isinstance(self._list_repos, Exception):
            raise self._list_repos
        return self._list_repos(cfg, project) if callable(self._list_repos) else self._list_repos


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

    def test_czech_corp_suffixes_are_ignored_when_matching(self):
        # This codebase's own CRM data uses Czech legal-entity suffixes
        # (see test_case_guide.py's ExtractFromBriefTests, "Contoso s.r.o.")
        # -- a bug in that branch of _CORP_SUFFIXES would silently make a
        # real customer name score worse than it should.
        result = repo_suggest.best_fuzzy_match("Contoso s.r.o.", ["Contoso", "Fabrikam"])
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Contoso")
        self.assertEqual(result[1], 1.0)  # normalized names are an exact match

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

    def test_no_customer_returns_empty_list(self):
        api = FakeAdoApi()
        self.assertEqual(repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), None), [])

    def test_no_org_url_skips_auto_match_and_returns_empty(self):
        api = FakeAdoApi()
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(org_url=None), "Acme Corp")
        self.assertEqual(result, [])

    def test_ambiguous_repo_within_a_matched_project_lists_all_rather_than_guessing(self):
        repos = [{"name": "Acme Corp Billing", "remoteUrl": "https://x/billing"},
                 {"name": "Acme Corp Legacy", "remoteUrl": "https://x/legacy"}]
        api = FakeAdoApi(list_projects=(["Acme Corp"], False), list_repos=repos)
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), "Acme Corp")
        self.assertEqual(len(result), 2)
        self.assertTrue(all(r["source"] == "auto-match" for r in result))

    def test_single_repo_in_matched_project_is_returned_directly(self):
        repos = [{"name": "acme-billing", "remoteUrl": "https://x/billing"}]
        api = FakeAdoApi(list_projects=(["Acme Corp"], False), list_repos=repos)
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), "Acme Corp")
        self.assertEqual(result, [{"project": "Acme Corp", "repo": "acme-billing", "clone_url": "https://x/billing", "source": "auto-match"}])

    def test_project_listing_failure_degrades_to_empty_list_not_a_crash(self):
        api = FakeAdoApi(list_projects=RuntimeError("boom"))
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), "Acme Corp")
        self.assertEqual(result, [])

    def test_repo_listing_failure_after_a_matched_project_degrades_to_empty_list(self):
        # Same degrade-to-[] behavior as the project-listing failure above,
        # one call later -- a repo-listing failure after a project was
        # already matched must not crash either.
        api = FakeAdoApi(list_projects=(["Acme Corp"], False), list_repos=RuntimeError("boom"))
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), "Acme Corp")
        self.assertEqual(result, [])

    def test_matched_project_with_zero_repos_returns_empty_list(self):
        api = FakeAdoApi(list_projects=(["Acme Corp"], False), list_repos=[])
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), "Acme Corp")
        self.assertEqual(result, [])

    def test_a_repo_name_that_clearly_matches_the_customer_is_picked_over_its_siblings(self):
        # Distinct from test_single_repo_in_matched_project_is_returned_directly
        # (only one repo exists at all) and
        # test_ambiguous_repo_within_a_matched_project_lists_all_rather_than_guessing
        # (no repo stands out) -- this is the third, real branch: several
        # repos in the matched project, but one of them clearly fuzzy-matches
        # the customer name on its own.
        repos = [{"name": "acme-billing", "remoteUrl": "https://x/billing"},
                 {"name": "unrelated-tool", "remoteUrl": "https://x/unrelated"}]
        api = FakeAdoApi(list_projects=(["Acme Corp"], False), list_repos=repos)
        result = repo_suggest.resolve_suggested_repos(api, self._azure_cfg(), "Acme Corp")
        self.assertEqual(result, [{"project": "Acme Corp", "repo": "acme-billing",
                                    "clone_url": "https://x/billing", "source": "auto-match"}])


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


class AnyGuessedTests(unittest.TestCase):
    def test_true_when_any_entry_is_an_auto_match(self):
        repos = {("P", "R"): {"clone_url": "https://x", "source": "auto-match"}}
        self.assertTrue(repo_suggest.any_guessed(repos))

    def test_false_when_every_entry_is_confirmed(self):
        repos = {("P", "R"): {"clone_url": "https://x", "source": "ado-search"}}
        self.assertFalse(repo_suggest.any_guessed(repos))

    def test_true_when_mixed(self):
        repos = {
            ("P", "R1"): {"clone_url": "https://x", "source": "ado-search"},
            ("P", "R2"): {"clone_url": "https://y", "source": "auto-match"},
        }
        self.assertTrue(repo_suggest.any_guessed(repos))

    def test_false_when_empty_or_none(self):
        self.assertFalse(repo_suggest.any_guessed({}))
        self.assertFalse(repo_suggest.any_guessed(None))


class FormatSuggestedRepoTests(unittest.TestCase):
    def test_no_repos_shows_the_generic_placeholder(self):
        text = repo_suggest.format_suggested_repo({}, "T1-fix")
        self.assertIn("No repo identified yet", text)
        self.assertIn("git checkout -b T1-fix", text)

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
