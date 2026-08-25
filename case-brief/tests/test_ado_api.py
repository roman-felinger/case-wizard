"""Unit tests for lib/ado_api.py against a faked `requests.get` -- no real
network access, no live PAT/org needed.

Note for anyone comparing this to case-guide/tests/test_ado_api.py: despite
being a near-namesake, case-brief's ado_api.py is NOT the same
implementation. It calls the bare `requests.get` function directly (no
`requests.Session`), and it has no `AdoAuthError` class, no `_get_json`/
`_get_or` raise-vs-swallow helpers, no org-wide search, and no
`get_pr_details` -- that only exists in case-guide's copy.
A 401/403 here just raises the plain `requests.HTTPError` from
`raise_for_status()` like any other HTTP error; nothing here specifically
detects or reports auth failures differently, and callers (case_brief.py)
all wrap ADO calls in a bare `except Exception` and turn it into a visible
error message.

This tool only ever talks to one Azure DevOps org and PAT env var
(ado_api.ORG_URL / ado_api.PAT_ENV_VAR, module constants, not config) --
tests that need a specific org/PAT set patch those constants directly via
`mock.patch.object(ado_api, "ORG_URL", ...)` rather than passing a cfg dict.

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

ORG_URL = "https://dev.azure.com/org"


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


def _with_org(url):
    return mock.patch.object(ado_api, "ORG_URL", url)


def _with_pat_env(env_var):
    return mock.patch.object(ado_api, "PAT_ENV_VAR", env_var)


class GetPatTests(unittest.TestCase):
    def test_raises_when_env_var_is_unset(self):
        os.environ.pop("DEFINITELY_NOT_SET_ADO_PAT_VAR", None)
        with _with_pat_env("DEFINITELY_NOT_SET_ADO_PAT_VAR"):
            with self.assertRaises(RuntimeError):
                ado_api._get_pat()

    def test_returns_the_pat_from_the_configured_env_var(self):
        with _with_pat_env("TEST_AZDO_PAT"):
            self.assertEqual(ado_api._get_pat(), "fake-pat-for-tests")

    def test_error_message_names_the_configured_env_var_not_a_hardcoded_one(self):
        os.environ.pop("SOME_OTHER_PAT_VAR", None)
        with _with_pat_env("SOME_OTHER_PAT_VAR"):
            with self.assertRaises(RuntimeError) as ctx:
                ado_api._get_pat()
        self.assertIn("SOME_OTHER_PAT_VAR", str(ctx.exception))


class ListReposAndGetRepoTests(unittest.TestCase):
    def test_list_repos_returns_the_raw_repo_dicts(self):
        repos = [{"id": "r1", "name": "RepoA"}, {"id": "r2", "name": "RepoB"}]
        fake = route({"git/repositories": FakeResponse({"value": repos})})
        with _with_org(ORG_URL), _with_pat_env("TEST_AZDO_PAT"), mock.patch("requests.get", fake):
            result = ado_api.list_repos("ProjA")
        self.assertEqual(result, repos)

    def test_get_repo_matches_case_insensitively(self):
        repos = [{"id": "r1", "name": "RepoA", "remoteUrl": "https://x/RepoA"}]
        fake = route({"git/repositories": FakeResponse({"value": repos})})
        with _with_org(ORG_URL), _with_pat_env("TEST_AZDO_PAT"), mock.patch("requests.get", fake):
            result = ado_api.get_repo("ProjA", "repoa")
        self.assertEqual(result["name"], "RepoA")

    def test_get_repo_returns_none_when_not_found(self):
        repos = [{"id": "r1", "name": "RepoA"}]
        fake = route({"git/repositories": FakeResponse({"value": repos})})
        with _with_org(ORG_URL), _with_pat_env("TEST_AZDO_PAT"), mock.patch("requests.get", fake):
            result = ado_api.get_repo("ProjA", "does-not-exist")
        self.assertIsNone(result)


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
    def test_finds_a_pull_request_link(self):
        text = "See https://dev.azure.com/myorg/MyProject/_git/my-repo/pullrequest/123 for the fix."
        with _with_org("https://dev.azure.com/myorg"):
            prs, branches = ado_api.parse_direct_references(text)
        self.assertEqual(prs, [{"project": "MyProject", "repo": "my-repo", "id": 123}])
        self.assertEqual(branches, [])

    def test_finds_a_branch_link(self):
        text = "Working on https://dev.azure.com/myorg/MyProject/_git/my-repo?version=GBfeature%2Ffix-123"
        with _with_org("https://dev.azure.com/myorg"):
            prs, branches = ado_api.parse_direct_references(text)
        self.assertEqual(branches, [{"project": "MyProject", "repo": "my-repo", "branch": "feature/fix-123"}])
        self.assertEqual(prs, [])

    def test_finds_a_visualstudio_com_style_link(self):
        text = "https://myorg.visualstudio.com/MyProject/_git/my-repo/pullrequest/9"
        with _with_org("https://myorg.visualstudio.com"):
            prs, _ = ado_api.parse_direct_references(text)
        self.assertEqual(prs, [{"project": "MyProject", "repo": "my-repo", "id": 9}])

    def test_ignores_a_link_pointing_at_a_different_org(self):
        text = "https://dev.azure.com/someoneelseorg/MyProject/_git/my-repo/pullrequest/123"
        with _with_org("https://dev.azure.com/myorg"):
            prs, branches = ado_api.parse_direct_references(text)
        self.assertEqual(prs, [])
        self.assertEqual(branches, [])

    def test_deduplicates_the_same_link_seen_twice(self):
        text = ("https://dev.azure.com/myorg/MyProject/_git/my-repo/pullrequest/123 "
                "and again https://dev.azure.com/myorg/MyProject/_git/my-repo/pullrequest/123")
        with _with_org("https://dev.azure.com/myorg"):
            prs, _ = ado_api.parse_direct_references(text)
        self.assertEqual(len(prs), 1)

    def test_no_org_url_configured_returns_empty_without_crashing(self):
        with _with_org(None):
            prs, branches = ado_api.parse_direct_references("https://dev.azure.com/myorg/P/_git/R/pullrequest/1")
        self.assertEqual(prs, [])
        self.assertEqual(branches, [])

    def test_empty_text_returns_empty_without_crashing(self):
        with _with_org("https://dev.azure.com/myorg"):
            self.assertEqual(ado_api.parse_direct_references(""), ([], []))
            self.assertEqual(ado_api.parse_direct_references(None), ([], []))


class GetPullRequestTests(unittest.TestCase):
    def test_fetches_a_single_pr_by_id_and_resolves_its_clone_url(self):
        pr = {"pullRequestId": 7, "title": "Fix T1 bug", "status": "active",
              "createdBy": {"displayName": "Jane"}, "repository": {"name": "repoA", "id": "r1"}}
        routes = {
            "pullrequests/7": FakeResponse(pr),
            "git/repositories": FakeResponse({"value": [{"id": "r1", "name": "repoA", "remoteUrl": "https://x/repoA"}]}),
        }
        with _with_org(ORG_URL), _with_pat_env("TEST_AZDO_PAT"), mock.patch("requests.get", route(routes)):
            result = ado_api.get_pull_request("ProjA", 7)
        self.assertEqual(result["id"], 7)
        self.assertEqual(result["repo"], "repoA")
        self.assertEqual(result["clone_url"], "https://x/repoA")
        self.assertIn("/ProjA/_git/repoA/pullrequest/7", result["url"])

    def test_propagates_http_errors_rather_than_swallowing_them(self):
        with _with_org(ORG_URL), _with_pat_env("TEST_AZDO_PAT"), mock.patch("requests.get", route({}, default_status=404)):
            with self.assertRaises(requests.HTTPError):
                ado_api.get_pull_request("ProjA", 999)


class GetBranchTests(unittest.TestCase):
    def test_fetches_a_single_branch_by_name(self):
        routes = {
            "git/repositories?api-version": FakeResponse({"value": [{"id": "r1", "name": "repoA", "remoteUrl": "https://x/repoA"}]}),
            "/refs?filter=heads": FakeResponse({"value": [{"name": "refs/heads/feature/fix-123"}]}),
        }
        with _with_org(ORG_URL), _with_pat_env("TEST_AZDO_PAT"), mock.patch("requests.get", route(routes)):
            result = ado_api.get_branch("ProjA", "repoA", "feature/fix-123")
        self.assertEqual(result["branch"], "feature/fix-123")
        self.assertEqual(result["clone_url"], "https://x/repoA")

    def test_returns_none_when_the_repo_does_not_exist(self):
        with _with_org(ORG_URL), _with_pat_env("TEST_AZDO_PAT"), \
             mock.patch("requests.get", route({"git/repositories?api-version": FakeResponse({"value": []})})):
            result = ado_api.get_branch("ProjA", "does-not-exist", "main")
        self.assertIsNone(result)

    def test_returns_none_when_the_branch_does_not_exist_rather_than_raising(self):
        # A stale link in a CRM note (branch since deleted/merged) shouldn't
        # fail the whole brief.
        routes = {
            "git/repositories?api-version": FakeResponse({"value": [{"id": "r1", "name": "repoA", "remoteUrl": "https://x/repoA"}]}),
            "/refs?filter=heads": FakeResponse({"value": []}),
        }
        with _with_org(ORG_URL), _with_pat_env("TEST_AZDO_PAT"), mock.patch("requests.get", route(routes)):
            result = ado_api.get_branch("ProjA", "repoA", "long-gone-branch")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
