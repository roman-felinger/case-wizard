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


class FindWorkItemsTests(unittest.TestCase):
    def test_maps_fields_from_the_work_item_batch_response(self):
        cfg = {**CFG, "project": "ProjA", "search_fields": ["System.Title"]}
        wiql_result = FakeResponse({"workItems": [{"id": 42}]})
        items_result = FakeResponse({"value": [{
            "id": 42,
            "fields": {
                "System.Title": "Fix the thing",
                "System.State": "Active",
                "System.WorkItemType": "Bug",
                "System.ChangedDate": "2026-08-01T00:00:00Z",
            },
        }]})
        with mock.patch("requests.post", return_value=wiql_result), \
             mock.patch("requests.get", return_value=items_result):
            result = ado_api.find_work_items(cfg, "T1")
        self.assertEqual(result, [{
            "id": 42, "url": "https://dev.azure.com/org/ProjA/_workitems/edit/42",
            "type": "Bug", "title": "Fix the thing", "state": "Active",
            "changed_on": "2026-08-01T00:00:00Z",
        }])

    def test_no_matching_work_items_short_circuits_without_a_second_request(self):
        cfg = {**CFG, "project": "ProjA"}
        wiql_result = FakeResponse({"workItems": []})
        with mock.patch("requests.post", return_value=wiql_result), \
             mock.patch("requests.get") as get_mock:
            result = ado_api.find_work_items(cfg, "T1")
        self.assertEqual(result, [])
        get_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
