"""Unit tests for lib/ado_api.py against a faked requests.Session -- no
real network access, no live PAT/org needed. Covers the raise-vs-swallow
policy split (_get_json/_get_or), the distinct AdoAuthError path, the
project/PR truncation signals, and get_pr_details' capping behavior.

Run with: python -m unittest discover -s tests   (from case-guide/)
      or: python -m pytest tests                 (if pytest is installed)
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
    """Builds a fake `Session.get(self, url, timeout)` from {substring:
    response_or_callable} so each test only has to describe the URLs it
    cares about."""
    def fake_get(self, url, timeout=30):
        for needle, value in routes.items():
            if needle in url:
                return value(url) if callable(value) else value
        return FakeResponse({}, status=default_status)
    return fake_get


class GetJsonAndGetOrTests(unittest.TestCase):
    def test_get_json_raises_generic_http_error(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse({}, status=500)
        with self.assertRaises(requests.HTTPError):
            ado_api._get_json("http://x", session)

    def test_get_json_raises_ado_auth_error_on_401(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse({}, status=401)
        with self.assertRaises(ado_api.AdoAuthError):
            ado_api._get_json("http://x", session)

    def test_get_json_raises_ado_auth_error_on_403(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse({}, status=403)
        with self.assertRaises(ado_api.AdoAuthError):
            ado_api._get_json("http://x", session)

    def test_get_json_returns_body_on_success(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse({"value": [1, 2]})
        self.assertEqual(ado_api._get_json("http://x", session), {"value": [1, 2]})

    def test_get_or_returns_default_on_generic_failure(self):
        session = mock.Mock()
        session.get.side_effect = requests.exceptions.ConnectionError("down")
        self.assertEqual(ado_api._get_or("http://x", session, default={"value": []}), {"value": []})

    def test_get_or_reraises_auth_error_instead_of_swallowing(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse({}, status=401)
        with self.assertRaises(ado_api.AdoAuthError):
            ado_api._get_or("http://x", session, default={})


class ListProjectsTests(unittest.TestCase):
    def test_truncated_at_the_cap(self):
        many = [{"name": f"P{i}"} for i in range(ado_api.MAX_PROJECTS)]
        fake = route({"_apis/projects": FakeResponse({"value": many})})
        with mock.patch.object(requests.Session, "get", fake):
            names, truncated = ado_api.list_projects(CFG)
        self.assertEqual(len(names), ado_api.MAX_PROJECTS)
        self.assertTrue(truncated)

    def test_propagates_on_failure(self):
        fake = route({}, default_status=500)
        with mock.patch.object(requests.Session, "get", fake):
            with self.assertRaises(requests.HTTPError):
                ado_api.list_projects(CFG)


class FindRelatedTests(unittest.TestCase):
    def _routes(self, pr_count=1):
        prs = [{
            "pullRequestId": i, "title": f"Fix T1 #{i}", "description": "", "status": "active",
            "createdBy": {"displayName": "Jane"}, "repository": {"name": "repoA", "id": "r1"},
        } for i in range(pr_count)]
        return {
            "_apis/projects": FakeResponse({"value": [{"name": "ProjA"}]}),
            "git/repositories?api-version": FakeResponse({"value": [{"id": "r1", "name": "repoA", "remoteUrl": "https://x/repoA"}]}),
            "/refs?filter=heads": FakeResponse({"value": [{"name": "refs/heads/T1-fix"}]}),
            "pullrequests?searchCriteria": FakeResponse({"value": prs}),
        }

    def test_happy_path_no_warnings(self):
        cfg = {**CFG, "project": "ProjA", "max_prs": 5}
        with mock.patch.object(requests.Session, "get", route(self._routes(pr_count=1))):
            branches, prs, warnings = ado_api.find_related(cfg, "T1")
        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0]["branch"], "T1-fix")
        self.assertEqual(len(prs), 1)
        self.assertEqual(warnings, [])

    def test_pr_search_truncation_warning(self):
        cfg = {**CFG, "project": "ProjA", "max_prs": 1}
        with mock.patch.object(requests.Session, "get", route(self._routes(pr_count=1))):
            _, _, warnings = ado_api.find_related(cfg, "T1")
        self.assertEqual(len(warnings), 1)
        self.assertIn("most recently updated PRs", warnings[0])

    def test_project_cap_warning_when_no_project_configured(self):
        cfg = {**CFG, "project": None, "max_prs": 5}
        many_projects = FakeResponse({"value": [{"name": f"P{i}"} for i in range(ado_api.MAX_PROJECTS)]})
        routes = self._routes(pr_count=1)
        routes["_apis/projects"] = many_projects
        with mock.patch.object(requests.Session, "get", route(routes)):
            _, _, warnings = ado_api.find_related(cfg, "T1")
        self.assertTrue(any("more than" in w for w in warnings))

    def test_auth_error_propagates_out_of_find_related(self):
        cfg = {**CFG, "project": "ProjA"}
        with mock.patch.object(requests.Session, "get", route({}, default_status=401)):
            with self.assertRaises(ado_api.AdoAuthError):
                ado_api.find_related(cfg, "T1")


class GetRecentPrsTests(unittest.TestCase):
    def _pr(self, i, reviewers=None):
        return {
            "pullRequestId": i, "title": f"Fix #{i}",
            "repository": {"name": "repoA"},
            "createdBy": {"displayName": "Jane"},
            "sourceRefName": f"refs/heads/T{i}-fix",
            "targetRefName": "refs/heads/test",
            "reviewers": [{"displayName": r} for r in (reviewers or ["Bob"])],
        }

    def test_excludes_given_ids_and_respects_top(self):
        prs = [self._pr(i) for i in range(5, 0, -1)]  # ids 5,4,3,2,1, most-recent-first
        routes = {"pullrequests?searchCriteria": FakeResponse({"value": prs})}
        with mock.patch.object(requests.Session, "get", route(routes)):
            result = ado_api.get_recent_prs(CFG, "ProjA", exclude_ids={5, 3}, top=2)
        self.assertEqual([pr["id"] for pr in result], [4, 2])

    def test_maps_fields_from_the_list_response(self):
        prs = [self._pr(1, reviewers=["Alice", "[Team]\\Admins"])]
        routes = {"pullrequests?searchCriteria": FakeResponse({"value": prs})}
        with mock.patch.object(requests.Session, "get", route(routes)):
            result = ado_api.get_recent_prs(CFG, "ProjA", top=5)
        self.assertEqual(result, [{
            "id": 1, "title": "Fix #1", "repo": "repoA", "created_by": "Jane",
            "source_branch": "T1-fix", "target_branch": "test",
            "reviewers": ["Alice", "[Team]\\Admins"],
        }])

    def test_degrades_to_empty_list_on_request_failure(self):
        routes = {}  # everything 404s via the default_status
        with mock.patch.object(requests.Session, "get", route(routes)):
            result = ado_api.get_recent_prs(CFG, "ProjA", top=5)
        self.assertEqual(result, [])

    def test_auth_error_propagates(self):
        with mock.patch.object(requests.Session, "get", route({}, default_status=401)):
            with self.assertRaises(ado_api.AdoAuthError):
                ado_api.get_recent_prs(CFG, "ProjA", top=5)


class GetPrDetailsTests(unittest.TestCase):
    def test_caps_comments_but_not_commits_or_files_a_second_time(self):
        commits = FakeResponse({"value": [{"comment": f"c{i}\nextra"} for i in range(3)]})
        iterations = FakeResponse({"value": [{"id": 1}, {"id": 2}]})
        changes = FakeResponse({"changeEntries": [{"changeType": "edit", "item": {"path": f"/f{i}.py"}} for i in range(3)]})
        threads = FakeResponse({"value": [{"comments": [
            {"content": f"comment {i}", "commentType": "text", "author": {"displayName": "Bob"}}
            for i in range(5)
        ]}]})
        routes = {
            "/commits?api-version": commits,
            "/iterations?api-version": iterations,
            "/iterations/2/changes": changes,
            "/threads?api-version": threads,
        }
        with mock.patch.object(requests.Session, "get", route(routes)):
            detail = ado_api.get_pr_details(CFG, "ProjA", "repoA", 9, max_commits=3, max_files=3, max_comments=2)
        self.assertEqual(detail["commits"], ["c0", "c1", "c2"])
        self.assertEqual(detail["files"], ["edit: /f0.py", "edit: /f1.py", "edit: /f2.py"])
        self.assertEqual(len(detail["comments"]), 2)  # capped from 5 down to max_comments

    def test_missing_iterations_yields_no_files_without_crashing(self):
        routes = {
            "/commits?api-version": FakeResponse({"value": []}),
            "/iterations?api-version": FakeResponse({"value": []}),
            "/threads?api-version": FakeResponse({"value": []}),
        }
        with mock.patch.object(requests.Session, "get", route(routes)):
            detail = ado_api.get_pr_details(CFG, "ProjA", "repoA", 9)
        self.assertEqual(detail, {"commits": [], "files": [], "comments": []})

    def test_a_failed_sub_fetch_degrades_to_empty_for_that_piece_only(self):
        def failing_commits(url):
            raise requests.exceptions.ConnectionError("down")
        routes = {
            "/commits?api-version": failing_commits,
            "/iterations?api-version": FakeResponse({"value": [{"id": 1}]}),
            "/iterations/1/changes": FakeResponse({"changeEntries": [{"changeType": "add", "item": {"path": "/a.py"}}]}),
            "/threads?api-version": FakeResponse({"value": []}),
        }
        with mock.patch.object(requests.Session, "get", route(routes)):
            detail = ado_api.get_pr_details(CFG, "ProjA", "repoA", 9)
        self.assertEqual(detail["commits"], [])  # degraded, not raised
        self.assertEqual(detail["files"], ["add: /a.py"])  # unaffected


if __name__ == "__main__":
    unittest.main()
