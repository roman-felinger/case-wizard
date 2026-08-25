"""Azure DevOps lookups via a self-service PAT: branches and pull requests
directly referenced from a CRM case.

CRM notes/description/custom fields often already contain an actual link a
support engineer pasted while working the case -- if one's there,
parse_direct_references finds it and get_pull_request/get_branch resolve it
with exactly one API call each.

There is no broader org-wide search. This tool only ever talks to one org
(ORG_URL below), so a "list every branch in every repo, in every project"
fallback added a lot of complexity (a project cap, a per-project PR cap,
"one bad repo shouldn't kill the whole search" resilience) for a case that
was rarely worth it in practice -- a case that never mentions its own work
either doesn't have any yet, or is faster to ask the person who worked it
about than to brute-force search for.
"""
import os
import re
import sys
from urllib.parse import quote, unquote

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from shared.ado_auth import auth_header as _auth_header, get_pat as _get_pat_by_env

# This tool only ever talks to one Azure DevOps org and one PAT env var --
# never actually varies, so not worth a config setting or CLI flag.
ORG_URL = "https://dev.azure.com/artexis"
PAT_ENV_VAR = "AZDO_PAT"

# Matches an Azure DevOps PR or branch link pasted into CRM (description,
# a note, a custom field -- anywhere free text ends up). Both link shapes
# share the same .../{project}/_git/{repo} prefix and only differ in the
# tail, so one regex covers both rather than running two full passes.
_ADO_LINK_RE = re.compile(
    r"https?://(?:dev\.azure\.com/(?P<org1>[^/\s]+)|(?P<org2>[^./\s]+)\.visualstudio\.com)"
    r"/(?P<project>[^/\s]+)/_git/(?P<repo>[^/\s?]+)"
    r"(?:/pullrequest/(?P<pr_id>\d+)|\?(?:[^\s\"'<>]*[?&])?version=GB(?P<branch>[^&\s\"'<>]+))",
    re.IGNORECASE,
)


def _get_pat():
    return _get_pat_by_env(PAT_ENV_VAR)


def list_repos(project):
    pat = _get_pat()
    url = f"{ORG_URL.rstrip('/')}/{project}/_apis/git/repositories?api-version=7.1"
    resp = requests.get(url, headers=_auth_header(pat), timeout=30)
    resp.raise_for_status()
    return resp.json().get("value", [])


def get_repo(project, repo_name):
    """A single named repo's info (including its clone URL), or None if it
    doesn't exist / isn't visible with this PAT. Used to resolve a clone URL
    for a directly-referenced PR/branch."""
    for repo in list_repos(project):
        if repo["name"].lower() == repo_name.lower():
            return repo
    return None


def _org_name(org_url):
    """'https://dev.azure.com/myorg' or 'https://myorg.visualstudio.com' -> 'myorg'."""
    if not org_url:
        return None
    m = re.match(
        r"https?://(?:dev\.azure\.com/(?P<a>[^/\s]+)|(?P<b>[^./\s]+)\.visualstudio\.com)",
        org_url.rstrip("/") + "/",
    )
    if not m:
        return None
    return m.group("a") or m.group("b")


def parse_direct_references(text):
    """Scans arbitrary text (CRM description/notes/activities/custom
    fields) for actual Azure DevOps PR/branch links -- the same links a
    person would click, e.g. pasted by a support engineer while working
    the case. Only links pointing at ORG_URL are trusted; a link into a
    different org can't be resolved with this PAT anyway, and could just as
    easily be a customer's own unrelated org mentioned in the text.

    Returns (pr_refs, branch_refs), each a de-duplicated list of dicts
    ({project, repo, id} / {project, repo, branch}) ready to hand straight
    to get_pull_request/get_branch.
    """
    if not text:
        return [], []
    org_name = _org_name(ORG_URL)
    if not org_name:
        return [], []

    pr_refs, branch_refs = [], []
    seen_pr, seen_branch = set(), set()
    for m in _ADO_LINK_RE.finditer(text):
        org = m.group("org1") or m.group("org2")
        if not org or org.lower() != org_name.lower():
            continue
        project = unquote(m.group("project"))
        repo = unquote(m.group("repo"))

        if m.group("pr_id"):
            key = (project.lower(), repo.lower(), m.group("pr_id"))
            if key in seen_pr:
                continue
            seen_pr.add(key)
            pr_refs.append({"project": project, "repo": repo, "id": int(m.group("pr_id"))})
        elif m.group("branch"):
            branch = unquote(m.group("branch"))
            key = (project.lower(), repo.lower(), branch.lower())
            if key in seen_branch:
                continue
            seen_branch.add(key)
            branch_refs.append({"project": project, "repo": repo, "branch": branch})

    return pr_refs, branch_refs


def get_pull_request(project, pr_id):
    """Fetches exactly one PR by id -- resolved from a link already found in
    the CRM case via parse_direct_references."""
    pat = _get_pat()
    org_url = ORG_URL.rstrip("/")
    url = f"{org_url}/{project}/_apis/git/pullrequests/{pr_id}?api-version=7.1"
    resp = requests.get(url, headers=_auth_header(pat), timeout=30)
    resp.raise_for_status()
    pr = resp.json()

    repo_name = pr["repository"]["name"]
    repo_info = get_repo(project, repo_name)
    return {
        "project": project,
        "id": pr["pullRequestId"],
        "repo": repo_name,
        "title": pr.get("title"),
        "status": pr.get("status"),
        "created_by": (pr.get("createdBy") or {}).get("displayName"),
        "url": f"{org_url}/{project}/_git/{repo_name}/pullrequest/{pr['pullRequestId']}",
        "clone_url": (repo_info or {}).get("remoteUrl"),
    }


def get_branch(project, repo, branch_name):
    """Fetches exactly one branch by name -- resolved from a link already
    found in the CRM case via parse_direct_references. Returns None if the
    repo or the branch itself doesn't exist (e.g. already deleted/merged),
    rather than raising -- a stale link in a CRM note shouldn't fail the
    whole brief."""
    repo_info = get_repo(project, repo)
    if not repo_info:
        return None

    pat = _get_pat()
    org_url = ORG_URL.rstrip("/")
    url = (
        f"{org_url}/{project}/_apis/git/repositories/{repo_info['id']}/refs"
        f"?filter=heads/{quote(branch_name, safe='')}&api-version=7.1"
    )
    resp = requests.get(url, headers=_auth_header(pat), timeout=30)
    resp.raise_for_status()

    target = f"refs/heads/{branch_name}"
    match = next((r for r in resp.json().get("value", []) if r["name"] == target), None)
    if not match:
        return None
    return {
        "project": project,
        "repo": repo_info["name"],
        "branch": branch_name,
        "url": f"{org_url}/{project}/_git/{repo_info['name']}?version=GB{quote(branch_name, safe='')}",
        "clone_url": repo_info.get("remoteUrl"),
    }
