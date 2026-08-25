"""Azure DevOps lookups via a self-service PAT -- same approach as
case-brief's own lib/ado_api.py (no admin app registration needed), but
kept as an independent copy here rather than importing across projects.

find_related mirrors case-brief's search (branches/PRs whose name/title/
description contains the case number) so this tool can re-run it fresh;
get_branch_commits/get_pr_details go one level deeper than case-brief does
-- commit messages, changed files, review comments -- since that's exactly
the context a "for dummies" guide needs to describe what related work
already attempted. get_recent_prs is unrelated to the case itself -- a
shallow sample of the project's other recent PRs, purely so a guide can
match this team's actual branch/review/naming conventions instead of
guessing.

Every request in this module goes through one requests.Session (built once
by open_session, threaded through as the `session` argument) instead of a
fresh connection -- and a fresh PAT lookup/header encode -- per call. The
independent per-repo/per-branch/per-PR fetches inside find_related and
gather_ado_detail (case_guide.py) run through a small thread pool rather
than one at a time, since they don't depend on each other.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from shared.ado_auth import auth_header as _auth_header, get_pat as _get_pat_by_env

# The PAT env var name never actually varies -- not worth a config setting.
PAT_ENV_VAR = "AZDO_PAT"
DEFAULT_MAX_PRS = 50
MAX_PROJECTS = 50
MAX_WORKERS = 8


class AdoAuthError(RuntimeError):
    """Azure DevOps rejected the request (401/403) -- kept distinct from a
    generic request failure so callers don't silently treat an expired or
    under-scoped PAT as "this really has no matching branches/PRs"."""


def open_session():
    """One requests.Session with the auth header set once -- pass this into
    every call in a run instead of letting each one build its own header
    and open its own connection."""
    session = requests.Session()
    session.headers.update(_auth_header(_get_pat_by_env(PAT_ENV_VAR)))
    return session


def _get_json(url, session, timeout=30):
    """GET url and return its parsed JSON body. Raises AdoAuthError on a
    401/403 (distinct from any other failure -- see the class docstring),
    or requests.RequestException/HTTPError for anything else, for callers
    that want a failure to propagate (see _get_or for the opposite,
    best-effort policy)."""
    resp = session.get(url, timeout=timeout)
    if resp.status_code in (401, 403):
        raise AdoAuthError(
            f"Azure DevOps rejected the request ({resp.status_code}) -- "
            "check that the configured PAT is still valid and has the right scopes."
        )
    resp.raise_for_status()
    return resp.json()


def _get_or(url, session, default, timeout=30):
    """Same as _get_json, but returns `default` instead of raising on a
    generic request/HTTP failure -- the shared shape behind this module's
    several best-effort lookups (a repo that's disabled or a PR with no
    iterations yet shouldn't abort the whole search, just yield nothing for
    that one piece). An AdoAuthError is NOT swallowed here -- an expired
    PAT is a systemic problem, not a "this one item is missing" one, so it
    still propagates to the caller."""
    try:
        return _get_json(url, session, timeout=timeout)
    except AdoAuthError:
        raise
    except requests.RequestException:
        return default


def list_projects(cfg, session=None):
    """(project_names, truncated) -- truncated is True if the org has more
    than MAX_PROJECTS projects, since $top caps what comes back with no
    other signal that anything was left out."""
    session = session or open_session()
    org_url = cfg["org_url"].rstrip("/")
    data = _get_json(f"{org_url}/_apis/projects?api-version=7.1&$top={MAX_PROJECTS}", session)
    names = [p["name"] for p in data.get("value", [])]
    return names, len(names) >= MAX_PROJECTS


def _resolve_projects(cfg, session):
    project = cfg.get("project")
    if project:
        return [project], False
    projects, truncated = list_projects(cfg, session=session)
    print(f"  No project configured -- searching all {len(projects)} project(s) in the org.")
    return projects, truncated


def list_repos(cfg, project, session=None):
    session = session or open_session()
    org_url = cfg["org_url"].rstrip("/")
    data = _get_json(f"{org_url}/{project}/_apis/git/repositories?api-version=7.1", session)
    return data.get("value", [])


def get_repo(cfg, project, repo_name, session=None):
    """A single named repo's info (including its clone URL), or None if it
    doesn't exist / isn't visible with this PAT -- used by
    lib/repo_suggest.py to resolve a clone URL for a customer-name guess,
    same as case-brief's own get_repo."""
    for repo in list_repos(cfg, project, session=session):
        if repo["name"].lower() == repo_name.lower():
            return repo
    return None


def _branches_in_repo(org_url, project, repo, needle, session):
    """Branches in one repo whose name contains the case number -- split
    out of find_related so the per-repo fetches (independent of each
    other) can run through a thread pool instead of one at a time."""
    refs_url = f"{org_url}/{project}/_apis/git/repositories/{repo['id']}/refs?filter=heads/&api-version=7.1"
    # A repo we can't list refs for (disabled, no access) just contributes
    # no branches rather than killing the whole search.
    refs = _get_or(refs_url, session, default={}).get("value", [])
    found = []
    for ref in refs:
        name = ref["name"].replace("refs/heads/", "")
        if needle in name.lower():
            found.append({
                "project": project,
                "repo": repo["name"],
                "branch": name,
                "url": f"{org_url}/{project}/_git/{repo['name']}?version=GB{requests.utils.quote(name, safe='')}",
                "clone_url": repo.get("remoteUrl"),
            })
    return found


def find_related(cfg, case_number, session=None):
    """Branches and PRs, across every searched project, whose name/title/
    description contains the case number (case-insensitive). Returns
    (branches, pull_requests, warnings) -- warnings is a list of
    human-readable strings describing any part of the search that may be
    incomplete (an org-wide project-listing cap, a per-project PR-listing
    cap, ...), empty if nothing was capped.

    Prints progress per project -- a search spanning many projects can take
    a while, and silence for a minute-plus reads as "stuck" even when it's
    just working through the list. Projects are searched one at a time (so
    that progress output stays in a sane order); the repos within each
    project are fetched concurrently, since they don't depend on each other.
    """
    session = session or open_session()
    org_url = cfg["org_url"].rstrip("/")
    max_prs = DEFAULT_MAX_PRS
    needle = case_number.lower()
    projects, projects_truncated = _resolve_projects(cfg, session)
    total = len(projects)

    warnings = []
    if projects_truncated:
        warnings.append(
            f"the org has more than {MAX_PROJECTS} projects -- only the first {MAX_PROJECTS} were searched"
        )

    branches = []
    pull_requests = []
    prs_truncated = False

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for i, project in enumerate(projects, 1):
            try:
                repos = list_repos(cfg, project, session=session)
            except requests.RequestException as e:
                print(f"  [{i}/{total}] {project}: could not list repos ({e}) -- skipping")
                continue

            repo_by_id = {r["id"]: r for r in repos}

            branch_hits = 0
            for found in pool.map(lambda repo: _branches_in_repo(org_url, project, repo, needle, session), repos):
                branches.extend(found)
                branch_hits += len(found)

            pr_url = (
                f"{org_url}/{project}/_apis/git/pullrequests"
                f"?searchCriteria.status=all&$top={max_prs}&api-version=7.1"
            )
            prs = _get_or(pr_url, session, default={}).get("value", [])
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

    if prs_truncated:
        warnings.append(
            f"the pull request search only checked the {max_prs} most recently updated PRs per "
            "project -- an older matching PR could exist but wasn't checked"
        )

    return branches, pull_requests, warnings


def get_recent_prs(cfg, project, exclude_ids=(), top=5, session=None):
    """A lightweight sample of this project's other recent completed PRs --
    not case-specific, just a style/convention reference so a guide can
    ground its setup/ship advice in how this team actually works (what
    branch PRs here target, who typically reviews, how branch names/titles
    are actually formatted) instead of generic guesses. Deliberately shallow
    compared to get_pr_details: title/branch/reviewers only, straight off
    the same list response find_related already fetches -- no per-PR follow-
    up request.

    Over-fetches by len(exclude_ids) so filtering out the case's own
    matched PR(s) (already shown elsewhere as this case's related work)
    still leaves `top` PRs behind where possible; best-effort only, not
    guaranteed to backfill if several of the top hits are excluded.
    """
    session = session or open_session()
    org_url = cfg["org_url"].rstrip("/")
    fetch_top = top + len(exclude_ids)
    url = (
        f"{org_url}/{project}/_apis/git/pullrequests"
        f"?searchCriteria.status=completed&$top={fetch_top}&api-version=7.1"
    )
    prs = _get_or(url, session, default={}).get("value", [])

    result = []
    for pr in prs:
        if pr["pullRequestId"] in exclude_ids:
            continue
        result.append({
            "id": pr["pullRequestId"],
            "title": pr.get("title"),
            "repo": pr["repository"]["name"],
            "created_by": (pr.get("createdBy") or {}).get("displayName"),
            "source_branch": pr.get("sourceRefName", "").replace("refs/heads/", ""),
            "target_branch": pr.get("targetRefName", "").replace("refs/heads/", ""),
            "reviewers": [r.get("displayName") for r in pr.get("reviewers", []) if r.get("displayName")],
        })
        if len(result) >= top:
            break
    return result


def get_branch_commits(cfg, project, repo_name, branch_name, max_commits=15, session=None):
    """Recent commit messages on a branch -- find_related only gives the
    branch name, not what's actually in it."""
    session = session or open_session()
    org_url = cfg["org_url"].rstrip("/")
    url = (
        f"{org_url}/{project}/_apis/git/repositories/{requests.utils.quote(repo_name, safe='')}/commits"
        f"?searchCriteria.itemVersion.version={requests.utils.quote(branch_name, safe='')}"
        f"&searchCriteria.itemVersion.versionType=branch&$top={max_commits}&api-version=7.1"
    )
    data = _get_or(url, session, default={})
    return [c["comment"].splitlines()[0] for c in data.get("value", []) if c.get("comment")]


def get_pr_details(cfg, project, repo_name, pr_id, max_commits=20, max_files=40, max_comments=15, session=None):
    """Depth on a single PR beyond find_related's summary (title/status/
    url): commit messages, changed file paths from its latest iteration,
    and non-system review comments -- so a guide can describe concretely
    what a related PR changed and whether it looks finished, stuck in
    review, or abandoned.

    Best-effort: any of the three lookups failing (e.g. a PR with no
    iterations yet) just yields nothing for that piece rather than
    aborting the whole lookup. An AdoAuthError still propagates, though --
    see _get_or.
    """
    session = session or open_session()
    org_url = cfg["org_url"].rstrip("/")
    repo = requests.utils.quote(repo_name, safe="")
    base = f"{org_url}/{project}/_apis/git/repositories/{repo}/pullrequests/{pr_id}"

    # Each of these three is already bounded at the source -- $top on the
    # commits query, an explicit slice on changed files -- so only comments
    # (never capped while being built) needs a cap at the end.
    commits_data = _get_or(f"{base}/commits?api-version=7.1&$top={max_commits}", session, default={})
    commits = [c["comment"].splitlines()[0] for c in commits_data.get("value", []) if c.get("comment")]

    files = []
    iterations = _get_or(f"{base}/iterations?api-version=7.1", session, default={}).get("value", [])
    if iterations:
        latest_id = iterations[-1]["id"]
        changes = _get_or(f"{base}/iterations/{latest_id}/changes?api-version=7.1", session, default={})
        for change in changes.get("changeEntries", [])[:max_files]:
            path = (change.get("item") or {}).get("path")
            if path:
                files.append(f"{change.get('changeType', '?')}: {path}")

    comments = []
    threads = _get_or(f"{base}/threads?api-version=7.1", session, default={}).get("value", [])
    for thread in threads:
        for c in thread.get("comments", []):
            content = (c.get("content") or "").strip()
            if content and c.get("commentType") != "system":
                author = (c.get("author") or {}).get("displayName", "?")
                comments.append(f"{author}: {content}")

    return {"commits": commits, "files": files, "comments": comments[:max_comments]}
