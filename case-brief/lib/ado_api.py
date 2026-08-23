"""Azure DevOps lookups via a self-service PAT: branches and pull requests
related to a case number.

If config.json's azure_devops.project is left unset, this searches EVERY
project in the org rather than making you know which one holds the relevant
repo -- convenient, but slower and more API calls the more projects you have
(capped at MAX_PROJECTS as a safety net for very large orgs).

There's no server-side full-text search for branches/PRs the way WIQL gives
us for work items, so this fetches candidates (all repos' branches, recent
PRs per project) and filters client-side for the case number appearing in
the name/title/description. The PR search per project is capped at
DEFAULT_MAX_PRS most recent (override via azure_devops.max_prs in
config.json), since there's no way to ask the API for "PRs from all time"
cheaply.
"""
import base64
import os

import requests

DEFAULT_MAX_PRS = 50
MAX_PROJECTS = 50


def _auth_header(pat):
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def _get_pat(cfg):
    pat = os.environ.get(cfg["pat_env_var"])
    if not pat:
        raise RuntimeError(
            f"Azure DevOps PAT not found. Set env var {cfg['pat_env_var']} "
            "(create one at https://dev.azure.com/{org}/_usersSettings/tokens)."
        )
    return pat


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


def find_work_items(cfg, case_number):
    """Kept for the --api fallback / in case work items become relevant
    again -- not used by the default flow (see find_related).
    Unlike that, this needs a specific project configured."""
    pat = _get_pat(cfg)
    org_url = cfg["org_url"].rstrip("/")
    project = cfg["project"]
    fields = cfg.get("search_fields", ["System.Title", "System.Description"])
    clauses = " OR ".join([f"[{f}] CONTAINS '{case_number}'" for f in fields])

    wiql = {
        "query": (
            "SELECT [System.Id], [System.Title], [System.State], [System.WorkItemType] "
            f"FROM WorkItems WHERE [System.TeamProject] = '{project}' AND ({clauses}) "
            "ORDER BY [System.ChangedDate] DESC"
        )
    }
    wiql_url = f"{org_url}/{project}/_apis/wit/wiql?api-version=7.1"
    resp = requests.post(wiql_url, headers=_auth_header(pat), json=wiql, timeout=30)
    resp.raise_for_status()
    ids = [str(item["id"]) for item in resp.json().get("workItems", [])][:20]
    if not ids:
        return []

    items_url = (
        f"{org_url}/_apis/wit/workitems?ids={','.join(ids)}"
        "&fields=System.Title,System.State,System.WorkItemType,System.ChangedDate"
        "&api-version=7.1"
    )
    resp = requests.get(items_url, headers=_auth_header(pat), timeout=30)
    resp.raise_for_status()

    results = []
    for wi in resp.json().get("value", []):
        f = wi["fields"]
        results.append({
            "id": wi["id"],
            "url": f"{org_url}/{project}/_workitems/edit/{wi['id']}",
            "type": f.get("System.WorkItemType"),
            "title": f.get("System.Title"),
            "state": f.get("System.State"),
            "changed_on": f.get("System.ChangedDate"),
        })
    return results
