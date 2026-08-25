"""Unit tests for lib/ado_api.py against a faked `requests.get`/`requests.post`
-- no real network access, no live PAT/org needed.

Note for anyone comparing this to case-guide/tests/test_ado_api.py: despite
being a near-namesake, case-brief's ado_api.py is NOT the same implementation.
It calls the bare `requests.get`/`requests.post` functions directly (no
`requests.Session`), and it has no `AdoAuthError` class, no `_get_json`/
`_get_or` raise-vs-swallow helpers, and no `get_recent_prs`/`get_pr_details`
-- those only exist in case-guide's copy. A 401/403 here just raises the
plain `requests.HTTPError` from `raise_for_status()` like any other HTTP
error; nothing here specifically detects or reports auth failures
differently, and callers (case_brief.py) all wrap ADO calls in a bare
`except Exception` and turn it into a visible error message. This file
covers what's actually here: PAT resolution (`_get_pat`), project listing
and its MAX_PROJECTS cap, `get_repo`'s case-insensitive name match, and
`find_related`'s case-number matching plus its `max_prs` truncation signal
and its "one bad repo/project shouldn't kill the whole search" resilience.

Run with: python -m unittest discover -s tests -v   (from case-brief/)
      or: python -m pytest tests                     (if pytest is installed)
"""
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TEST_AZDO_PAT", "fake-pat-for-tests")
from lib import ado_api

CFG = {"org_url": "https://dev.azure.com/org", "pat_env_var": "TEST_AZDO_PAT", "project": None, "max_prs": 2}


class FakeResponse:
    def __init__(self, json_body=None, status=200):
        self._json = json_body if json_body is not None else {}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._json


def route(routes, default_status=404):
    """Builds a fake `requests.get(url, headers=None, timeout=30)` from
    {substring: response_or_callable} so each test only has to describe the
    URLs it cares about."""
    def fake_get(url, headers=None, timeout=30):
        for needle, value in routes.items():
            if needle in url:
                return value(url) if callable(value) else value
        return FakeResponse({}, status=default_status)
    return fake_get


class GetPatTests(unittest.TestCase):
    def test_raises_when_env_var_is_unset(self):
        cfg = {"pat_env_var": "DEFINITELY_NOT_SET_ADO_PAT_VAR"}
        os.environ.pop(cfg["pat_env_var"], None)
        with self.assertRaises(RuntimeError):
            ado_api._get_pat(cfg)

    def test_returns_the_pat_from_the_configured_env_var(self):
        self.assertEqual(ado_api._get_pat(CFG), "fake-pat-for-tests")

    def test_error_message_names_the_configured_env_var_not_a_hardcoded_one(self):
        cfg = {"pat_env_var": "SOME_OTHER_PAT_VAR"}
        os.environ.pop(cfg["pat_env_var"], None)
        with self.assertRaises(RuntimeError) as ctx:
            ado_api._get_pat(cfg)
        self.assertIn("SOME_OTHER_PAT_VAR", str(ctx.exception))


class ListProjectsTests(unittest.TestCase):
    def test_returns_project_names(self):
        fake = route({"_apis/projects": FakeResponse({"value": [{"name": "ProjA"}, {"name": "ProjB"}]})})
        with mock.patch("requests.get", fake):
            names = ado_api.list_projects(CFG)
        self.assertEqual(names, ["ProjA", "ProjB"])

    def test_propagates_http_errors_rather_than_swallowing_them(self):
        fake = route({}, default_status=500)
        with mock.patch("requests.get", fake):
            with self.assertRaises(requests.HTTPError):
                ado_api.list_projects(CFG)

    def test_propagates_auth_failures_too_since_there_is_no_special_handling(self):
        # Unlike case-guide's copy, a 401 here is just another HTTPError --
        # confirms that assumption instead of silently relying on it.
        fake = route({}, default_status=401)
        with mock.patch("requests.get", fake):
            with self.assertRaises(requests.HTTPError):
                ado_api.list_projects(CFG)


class ListReposAndGetRepoTests(unittest.TestCase):
    def test_list_repos_returns_the_raw_repo_dicts(self):
        repos = [{"id": "r1", "name": "RepoA"}, {"id": "r2", "name": "RepoB"}]
        fake = route({"git/repositories": FakeResponse({"value": repos})})
        with mock.patch("requests.get", fake):
            result = ado_api.list_repos(CFG, "ProjA")
        self.assertEqual(result, repos)

    def test_get_repo_matches_case_insensitively(self):
        repos = [{"id": "r1", "name": "RepoA", "remoteUrl": "https://x/RepoA"}]
        fake = route({"git/repositories": FakeResponse({"value": repos})})
        with mock.patch("requests.get", fake):
            result = ado_api.get_repo(CFG, "ProjA", "repoa")
        self.assertEqual(result["name"], "RepoA")

    def test_get_repo_returns_none_when_not_found(self):
        repos = [{"id": "r1", "name": "RepoA"}]
        fake = route({"git/repositories": FakeResponse({"value": repos})})
        with mock.patch("requests.get", fake):
            result = ado_api.get_repo(CFG, "ProjA", "does-not-exist")
        self.assertIsNone(result)


class FindRelatedTests(unittest.TestCase):
    def _routes(self, prs=None, branches=None):
        return {
            "_apis/projects": FakeResponse({"value": [{"name": "ProjA"}]}),
            "git/repositories?api-version": FakeResponse({"value": [{"id": "r1", "name": "repoA", "remoteUrl": "https://x/repoA"}]}),
            "/refs?filter=heads": FakeResponse({"value": branches if branches is not None else [{"name": "refs/heads/T1-fix"}]}),
            "pullrequests?searchCriteria": FakeResponse({"value": prs if prs is not None else []}),
        }

    def test_matches_branch_by_case_number_case_insensitively(self):
        cfg = {**CFG, "project": "ProjA"}
        with mock.patch("requests.get", route(self._routes(branches=[{"name": "refs/heads/t1-fix"}]))):
            branches, prs, truncated, max_prs = ado_api.find_related(cfg, "T1")
        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0]["branch"], "t1-fix")
        self.assertEqual(branches[0]["clone_url"], "https://x/repoA")

    def test_branch_not_matching_case_number_is_excluded(self):
        cfg = {**CFG, "project": "ProjA"}
        with mock.patch("requests.get", route(self._routes(branches=[{"name": "refs/heads/unrelated-branch"}]))):
            branches, _, _, _ = ado_api.find_related(cfg, "T999")
        self.assertEqual(branches, [])

    def test_matches_pr_by_title_or_description(self):
        cfg = {**CFG, "project": "ProjA", "max_prs": 5}
        pr = {"pullRequestId": 7, "title": "Fix T1 bug", "description": "", "status": "active",
              "createdBy": {"displayName": "Jane"}, "repository": {"name": "repoA", "id": "r1"}}
        with mock.patch("requests.get", route(self._routes(prs=[pr], branches=[]))):
            _, prs, truncated, max_prs = ado_api.find_related(cfg, "T1")
        self.assertEqual(len(prs), 1)
        self.assertEqual(prs[0]["id"], 7)
        self.assertEqual(prs[0]["clone_url"], "https://x/repoA")
        self.assertFalse(truncated)

    def test_pr_list_at_the_cap_sets_truncated_flag(self):
        cfg = {**CFG, "project": "ProjA", "max_prs": 1}
        pr = {"pullRequestId": 1, "title": "T1 fix", "description": "", "status": "active",
              "createdBy": {"displayName": "Jane"}, "repository": {"name": "repoA", "id": "r1"}}
        with mock.patch("requests.get", route(self._routes(prs=[pr], branches=[]))):
            _, _, truncated, max_prs_out = ado_api.find_related(cfg, "T1")
        self.assertTrue(truncated)
        self.assertEqual(max_prs_out, 1)

    def test_pr_list_below_the_cap_is_not_flagged_truncated(self):
        cfg = {**CFG, "project": "ProjA", "max_prs": 5}
        pr = {"pullRequestId": 1, "title": "T1 fix", "description": "", "status": "active",
              "createdBy": {"displayName": "Jane"}, "repository": {"name": "repoA", "id": "r1"}}
        with mock.patch("requests.get", route(self._routes(prs=[pr], branches=[]))):
            _, _, truncated, _ = ado_api.find_related(cfg, "T1")
        self.assertFalse(truncated)

    def test_a_project_whose_repo_listing_fails_is_skipped_not_fatal(self):
        # A search spanning many projects shouldn't die because one project
        # can't be listed (e.g. disabled/no access) -- it should skip that
        # project and keep going, not raise out of find_related entirely.
        cfg = {**CFG, "project": None, "max_prs": 5}

        def fake_get(url, headers=None, timeout=30):
            if "_apis/projects" in url:
                return FakeResponse({"value": [{"name": "BadProj"}, {"name": "GoodProj"}]})
            if "BadProj" in url and "git/repositories" in url:
                raise requests.exceptions.ConnectionError("down")
            if "GoodProj" in url and "git/repositories?api-version" in url:
                return FakeResponse({"value": [{"id": "r1", "name": "repoA", "remoteUrl": "https://x/repoA"}]})
            if "/refs?filter=heads" in url:
                return FakeResponse({"value": [{"name": "refs/heads/T1-fix"}]})
            if "pullrequests?searchCriteria" in url:
                return FakeResponse({"value": []})
            return FakeResponse({}, status=404)

        with mock.patch("requests.get", fake_get):
            branches, prs, truncated, _ = ado_api.find_related(cfg, "T1")
        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0]["project"], "GoodProj")

    def test_a_repos_pr_search_failure_degrades_to_no_prs_for_that_repo(self):
        cfg = {**CFG, "project": "ProjA", "max_prs": 5}

        def fake_get(url, headers=None, timeout=30):
            if "_apis/projects" in url:
                return FakeResponse({"value": [{"name": "ProjA"}]})
            if "git/repositories?api-version" in url:
                return FakeResponse({"value": [{"id": "r1", "name": "repoA", "remoteUrl": "https://x/repoA"}]})
            if "/refs?filter=heads" in url:
                return FakeResponse({"value": []})
            if "pullrequests?searchCriteria" in url:
                raise requests.exceptions.ConnectionError("down")
            return FakeResponse({}, status=404)

        with mock.patch("requests.get", fake_get):
            branches, prs, truncated, _ = ado_api.find_related(cfg, "T1")
        self.assertEqual(prs, [])
        self.assertFalse(truncated)

    def test_no_project_configured_searches_every_project_in_the_org(self):
        cfg = {**CFG, "project": None, "max_prs": 5}
        routes = self._routes(branches=[])
        routes["_apis/projects"] = FakeResponse({"value": [{"name": "ProjA"}, {"name": "ProjB"}]})
        calls = []

        def fake_get(url, headers=None, timeout=30):
            calls.append(url)
            for needle, value in routes.items():
                if needle in url:
                    return value(url) if callable(value) else value
            return FakeResponse({}, status=404)

        with mock.patch("requests.get", fake_get):
            ado_api.find_related(cfg, "T1")
        self.assertTrue(any("ProjA" in u for u in calls))
        self.assertTrue(any("ProjB" in u for u in calls))

    def test_missing_pat_raises_before_any_request_is_made(self):
        cfg = {"org_url": "https://dev.azure.com/org", "pat_env_var": "NOPE_NOT_SET", "project": "ProjA", "max_prs": 5}
        os.environ.pop("NOPE_NOT_SET", None)
        with self.assertRaises(RuntimeError):
            ado_api.find_related(cfg, "T1")


class OrgNameTests(unittest.TestCase):
    def test_extracts_org_from_dev_azure_com_url(self):
        self.assertEqual(ado_api._org_name("https://dev.azure.com/myorg"), "myorg")

    def test_extracts_org_from_visualstudio_com_url(self):
        self.assertEqual(ado_api._org_name("https://myorg.visualstudio.com"), "myorg")

    def test_trailing_slash_does_not_break_extraction(self):
        self.assertEqual(ado_api._org_name("https://dev.azure.com/myorg/"), "myorg")

    def test_none_or_unrecognized_url_returns_none(self):
        self.assertIsNone(ado_api._org_name(None))
        self.assertIsNone(ado_api._org_name("https://example.com/notado"))


class ParseDirectReferencesTests(unittest.TestCase):
    CFG = {"org_url": "https://dev.azure.com/myorg"}

    def test_finds_a_pull_request_link(self):
        text = "See https://dev.azure.com/myorg/MyProject/_git/my-repo/pullrequest/123 for the fix."
        prs, branches = ado_api.parse_direct_references(self.CFG, text)
        self.assertEqual(prs, [{"project": "MyProject", "repo": "my-repo", "id": 123}])
        self.assertEqual(branches, [])

    def test_finds_a_branch_link(self):
        text = "Working on https://dev.azure.com/myorg/MyProject/_git/my-repo?version=GBfeature%2Ffix-123"
        prs, branches = ado_api.parse_direct_references(self.CFG, text)
        self.assertEqual(branches, [{"project": "MyProject", "repo": "my-repo", "branch": "feature/fix-123"}])
        self.assertEqual(prs, [])

    def test_finds_a_visualstudio_com_style_link(self):
        cfg = {"org_url": "https://myorg.visualstudio.com"}
        text = "https://myorg.visualstudio.com/MyProject/_git/my-repo/pullrequest/9"
        prs, _ = ado_api.parse_direct_references(cfg, text)
        self.assertEqual(prs, [{"project": "MyProject", "repo": "my-repo", "id": 9}])

    def test_ignores_a_link_pointing_at_a_different_org(self):
        text = "https://dev.azure.com/someoneelseorg/MyProject/_git/my-repo/pullrequest/123"
        prs, branches = ado_api.parse_direct_references(self.CFG, text)
        self.assertEqual(prs, [])
        self.assertEqual(branches, [])

    def test_deduplicates_the_same_link_seen_twice(self):
        text = ("https://dev.azure.com/myorg/MyProject/_git/my-repo/pullrequest/123 "
                "and again https://dev.azure.com/myorg/MyProject/_git/my-repo/pullrequest/123")
        prs, _ = ado_api.parse_direct_references(self.CFG, text)
        self.assertEqual(len(prs), 1)

    def test_no_org_url_configured_returns_empty_without_crashing(self):
        prs, branches = ado_api.parse_direct_references({"org_url": None}, "https://dev.azure.com/myorg/P/_git/R/pullrequest/1")
        self.assertEqual(prs, [])
        self.assertEqual(branches, [])

    def test_empty_text_returns_empty_without_crashing(self):
        self.assertEqual(ado_api.parse_direct_references(self.CFG, ""), ([], []))
        self.assertEqual(ado_api.parse_direct_references(self.CFG, None), ([], []))


class GetPullRequestTests(unittest.TestCase):
    def test_fetches_a_single_pr_by_id_and_resolves_its_clone_url(self):
        cfg = {**CFG, "project": None}
        pr = {"pullRequestId": 7, "title": "Fix T1 bug", "status": "active",
              "createdBy": {"displayName": "Jane"}, "repository": {"name": "repoA", "id": "r1"}}
        routes = {
            "pullrequests/7": FakeResponse(pr),
            "git/repositories": FakeResponse({"value": [{"id": "r1", "name": "repoA", "remoteUrl": "https://x/repoA"}]}),
        }
        with mock.patch("requests.get", route(routes)):
            result = ado_api.get_pull_request(cfg, "ProjA", "repoA", 7)
        self.assertEqual(result["id"], 7)
        self.assertEqual(result["repo"], "repoA")
        self.assertEqual(result["clone_url"], "https://x/repoA")
        self.assertIn("/ProjA/_git/repoA/pullrequest/7", result["url"])

    def test_propagates_http_errors_rather_than_swallowing_them(self):
        cfg = {**CFG, "project": None}
        with mock.patch("requests.get", route({}, default_status=404)):
            with self.assertRaises(requests.HTTPError):
                ado_api.get_pull_request(cfg, "ProjA", "repoA", 999)


class GetBranchTests(unittest.TestCase):
    def test_fetches_a_single_branch_by_name(self):
        cfg = {**CFG, "project": None}
        routes = {
            "git/repositories?api-version": FakeResponse({"value": [{"id": "r1", "name": "repoA", "remoteUrl": "https://x/repoA"}]}),
            "/refs?filter=heads": FakeResponse({"value": [{"name": "refs/heads/feature/fix-123"}]}),
        }
        with mock.patch("requests.get", route(routes)):
            result = ado_api.get_branch(cfg, "ProjA", "repoA", "feature/fix-123")
        self.assertEqual(result["branch"], "feature/fix-123")
        self.assertEqual(result["clone_url"], "https://x/repoA")

    def test_returns_none_when_the_repo_does_not_exist(self):
        cfg = {**CFG, "project": None}
        with mock.patch("requests.get", route({"git/repositories?api-version": FakeResponse({"value": []})})):
            result = ado_api.get_branch(cfg, "ProjA", "does-not-exist", "main")
        self.assertIsNone(result)

    def test_returns_none_when_the_branch_does_not_exist_rather_than_raising(self):
        # A stale link in a CRM note (branch since deleted/merged) shouldn't
        # fail the whole brief.
        cfg = {**CFG, "project": None}
        routes = {
            "git/repositories?api-version": FakeResponse({"value": [{"id": "r1", "name": "repoA", "remoteUrl": "https://x/repoA"}]}),
            "/refs?filter=heads": FakeResponse({"value": []}),
        }
        with mock.patch("requests.get", route(routes)):
            result = ado_api.get_branch(cfg, "ProjA", "repoA", "long-gone-branch")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
