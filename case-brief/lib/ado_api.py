"""Azure DevOps lookups via a self-service PAT: branches and pull requests
related to a case number.

Two ways to find them, in order of preference:

  - Direct (parse_direct_references + get_pull_request/get_branch): CRM
    notes/description/custom fields often already contain an actual link a
    support engineer pasted while working the case. If one's there, this
    resolves it with exactly one API call -- no searching required. This is
    the fast path and, by default, the *only* path (see case_brief.py).

  - Broad search (find_related, opt-in via --search-ado /
    azure_devops.broad_search): when nothing was linked directly, falls
    back to fetching candidates (all repos' branches, recent PRs per
    project, across every project if azure_devops.project is unset) and
    filtering client-side for the case number appearing in the
    name/title/description -- there's no server-side full-text search for
    branches/PRs the way WIQL gives us for work items. This is the
    expensive path: an org with many projects/repos means many API calls,
    which is exactly why it's no longer the default. The PR search per
    project is capped at DEFAULT_MAX_PRS most recent (override via
    azure_devops.max_prs), since there's no way to ask the API for "PRs
    from all time" cheaply. Projects searched are capped at MAX_PROJECTS as
    a safety net for very large orgs.
"""
import os
import re
import sys
from urllib.parse import quote, unquote

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from shared.ado_auth import auth_header as _auth_header, get_pat as _get_pat_by_env

DEFAULT_MAX_PRS = 50
MAX_PROJECTS = 50

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


def _get_pat(cfg):
    return _get_pat_by_env(cfg["pat_env_var"])


def list_projects(cfg):
    pat = _get_pat(cfg)
    org_url = cfg["org_url"].rstrip("/")
    url = f"{org_url}/_apis/projects?api-version=7.1&$top={MAX_PROJECTS}"
    resp = requests.get(url, headers=_auth_header(pat), timeout=30)
    resp.raise_for_status()
    return [p["name"] for p in resp.json().get("value", [])]


def _resolve_projects(cfg):
    project = cfg.get("project")
    if project:
        return [project]
    projects = list_projects(cfg)
    print(f"  No project configured -- searching all {len(projects)} project(s) in the org.")
    return projects


def list_repos(cfg, project):
    pat = _get_pat(cfg)
    org_url = cfg["org_url"].rstrip("/")
    url = f"{org_url}/{project}/_apis/git/repositories?api-version=7.1"
    resp = requests.get(url, headers=_auth_header(pat), timeout=30)
    resp.raise_for_status()
    return resp.json().get("value", [])


def get_repo(cfg, project, repo_name):
    """A single named repo's info (including its clone URL), or None if it
    doesn't exist / isn't visible with this PAT. Used to suggest clone/branch
    commands for a customer's known repo even when nothing's branched off it
    yet for this case -- which is exactly the case where it matters most."""
    for repo in list_repos(cfg, project):
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


def parse_direct_references(cfg, text):
    """Scans arbitrary text (CRM description/notes/activities/custom
    fields) for actual Azure DevOps PR/branch links -- the same links a
    person would click, e.g. pasted by a support engineer while working
    the case. Only links pointing at *this* org (azure_devops.org_url) are
    trusted; a link into a different org can't be resolved with this PAT
    anyway, and could just as easily be a customer's own unrelated org
    mentioned in the text.

    Returns (pr_refs, branch_refs), each a de-duplicated list of dicts
    ({project, repo, id} / {project, repo, branch}) ready to hand straight
    to get_pull_request/get_branch. This is the fast path that replaces an
    org-wide brute-force search when the case already says exactly where
    to look.
    """
    if not text:
        return [], []
    org_name = _org_name(cfg.get("org_url"))
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


def get_pull_request(cfg, project, repo, pr_id):
    """Fetches exactly one PR by id -- the targeted counterpart to
    find_related's 'search every PR in every project' path, used when a
    CRM note/field already links straight to it."""
    pat = _get_pat(cfg)
    org_url = cfg["org_url"].rstrip("/")
    url = f"{org_url}/{project}/_apis/git/pullrequests/{pr_id}?api-version=7.1"
    resp = requests.get(url, headers=_auth_header(pat), timeout=30)
    resp.raise_for_status()
    pr = resp.json()

    repo_name = pr["repository"]["name"]
    repo_info = get_repo(cfg, project, repo_name)
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


def get_branch(cfg, project, repo, branch_name):
    """Fetches exactly one branch by name -- the targeted counterpart to
    find_related's 'list every ref in every repo' path. Returns None if the
    repo or the branch itself doesn't exist (e.g. already deleted/merged),
    rather than raising -- a stale link in a CRM note shouldn't fail the
    whole brief."""
    repo_info = get_repo(cfg, project, repo)
    if not repo_info:
        return None

    pat = _get_pat(cfg)
    org_url = cfg["org_url"].rstrip("/")
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


def find_related(cfg, case_number):
    """Branches and PRs, across every searched project, whose name/title/
    description contains the case number (case-insensitive). Returns
    (branches, pull_requests, prs_truncated, max_prs).

    Prints progress per project -- a search spanning many projects can take
    a while, and silence for a minute-plus reads as "stuck" even when it's
    just working through the list.
    """
    pat = _get_pat(cfg)
    org_url = cfg["org_url"].rstrip("/")
    max_prs = cfg.get("max_prs", DEFAULT_MAX_PRS)
    needle = case_number.lower()
    projects = _resolve_projects(cfg)
    total = len(projects)

    branches = []
    pull_requests = []
    prs_truncated = False

    for i, project in enumerate(projects, 1):
        try:
            repos = list_repos(cfg, project)
        except requests.RequestException as e:
            print(f"  [{i}/{total}] {project}: could not list repos ({e}) -- skipping")
            continue

        repo_by_id = {r["id"]: r for r in repos}

        branch_hits = 0
        for repo in repos:
            url = f"{org_url}/{project}/_apis/git/repositories/{repo['id']}/refs?filter=heads/&api-version=7.1"
            try:
                resp = requests.get(url, headers=_auth_header(pat), timeout=30)
                resp.raise_for_status()
            except requests.RequestException:
                continue  # a repo we can't list (e.g. disabled, no access) shouldn't kill the whole search
            for ref in resp.json().get("value", []):
                name = ref["name"].replace("refs/heads/", "")
                if needle in name.lower():
                    branch_hits += 1
                    branches.append({
                        "project": project,
                        "repo": repo["name"],
                        "branch": name,
                        "url": f"{org_url}/{project}/_git/{repo['name']}?version=GB{requests.utils.quote(name, safe='')}",
                        "clone_url": repo.get("remoteUrl"),
                    })

        pr_url = (
            f"{org_url}/{project}/_apis/git/pullrequests"
            f"?searchCriteria.status=all&$top={max_prs}&api-version=7.1"
        )
        try:
            resp = requests.get(pr_url, headers=_auth_header(pat), timeout=30)
            resp.raise_for_status()
            prs = resp.json().get("value", [])
        except requests.RequestException:
            prs = []
        if len(prs) >= max_prs:
            prs_truncated = True

        pr_hits = 0
        for pr in prs:
            haystack = f"{pr.get('title', '')} {pr.get('description', '')}".lower()
            if needle in haystack:
                pr_hits += 1
                repo_name = pr["repository"]["name"]
                pull_requests.append({
                    "project": project,
                    "id": pr["pullRequestId"],
                    "repo": repo_name,
                    "title": pr.get("title"),
                    "status": pr.get("status"),
                    "created_by": (pr.get("createdBy") or {}).get("displayName"),
                    "url": f"{org_url}/{project}/_git/{repo_name}/pullrequest/{pr['pullRequestId']}",
                    "clone_url": repo_by_id.get(pr["repository"]["id"], {}).get("remoteUrl"),
                })

        print(f"  [{i}/{total}] {project}: {len(repos)} repo(s) -- {branch_hits} matching branch(es), {pr_hits} matching PR(s)")

    return branches, pull_requests, prs_truncated, max_prs
