"""Guesses which repo(s) to suggest clone/branch commands for -- moved here
from case-brief (see case-brief/CLAUDE.md), which used to render this as its
own "Useful Commands" brief section. This tool is the one that actually
needs it (step 2, "Get set up", of the guide claude writes), so it's the one
that owns it now; case-brief's brief is just the facts.

Deliberately a standalone copy of the same logic, not an import -- same
"no shared imports" policy as lib/ado_api.py/lib/writer.py (see CLAUDE.md).
Fuzzy-matches the CRM customer name against ADO project (then repo) names --
there's no manual override; a confirmed hit from this run's own Azure DevOps
search always takes priority over a guess (see merge_confirmed_and_guessed).
Customer name comes from the already-rendered brief Markdown (see
case_guide.py's _extract_customer).
"""
import re
import sys
from difflib import SequenceMatcher


_CORP_SUFFIXES = re.compile(
    r"\b(a\.?\s*s\.?|s\.?\s*r\.?\s*o\.?|spol\.?|inc\.?|llc|ltd\.?|gmbh|sp\.?\s*z\s*o\.?\s*o\.?|corp\.?|co\.?)\b",
    re.IGNORECASE,
)


def _normalize_name(name):
    name = _CORP_SUFFIXES.sub("", name or "")
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _fuzzy_score(a, b):
    return SequenceMatcher(None, _normalize_name(a), _normalize_name(b)).ratio()


def best_fuzzy_match(name, candidates, threshold=0.5, min_lead=0.15):
    """Picks the single candidate whose normalized name best matches `name`,
    but only if it clearly beats the runner-up -- an ambiguous guess is
    worse than no guess, since it'd suggest the wrong repo silently."""
    if not candidates:
        return None
    scored = sorted(((c, _fuzzy_score(name, c)) for c in candidates), key=lambda t: -t[1])
    best, best_score = scored[0]
    runner_up_score = scored[1][1] if len(scored) > 1 else 0.0
    if best_score >= threshold and (best_score - runner_up_score) >= min_lead:
        return best, best_score
    return None


def _slugify(text, max_len=50):
    if not text:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


def branch_name(case_number, title):
    case_part = re.sub(r"[^\w.-]+", "_", str(case_number)).strip("_").replace("_", "-") or "unlabeled"
    slug = _slugify(title)
    return f"{case_part}-{slug}" if slug else case_part


def resolve_suggested_repos(ado_api, azure_cfg, customer):
    """Figures out which repo(s) to suggest clone/branch commands for, by
    fuzzy-matching the CRM customer name against ADO project (then repo)
    names. Auto-match results are tagged so the guide can flag them as a
    guess rather than a confirmed mapping -- there is no manual override;
    a confirmed hit from this run's own Azure DevOps search still takes
    priority over a guess for the same repo (see
    merge_confirmed_and_guessed).

    `ado_api` is passed in (rather than imported) so tests can hand this a
    fake without monkeypatching a module-level import.

    Returns a list of {project, repo, clone_url, source} dicts (possibly
    empty, possibly more than one if a matched project has several repos and
    none stands out as THE one).
    """
    org_url = azure_cfg.get("org_url")
    if not customer or not org_url:
        return []

    try:
        projects, _truncated = ado_api.list_projects(azure_cfg)
    except Exception as e:
        print(f"  Could not auto-match a project for repo suggestion: {e}", file=sys.stderr)
        return []

    match = best_fuzzy_match(customer, projects)
    if not match:
        return []
    project, score = match
    print(f"  Guessed ADO project '{project}' from customer '{customer}' (similarity {score:.2f}).")

    try:
        repos = ado_api.list_repos(azure_cfg, project)
    except Exception as e:
        print(f"  Could not list repos in guessed project '{project}': {e}", file=sys.stderr)
        return []
    if not repos:
        return []
    if len(repos) == 1:
        r = repos[0]
        return [{"project": project, "repo": r["name"], "clone_url": r.get("remoteUrl"), "source": "auto-match"}]

    repo_names = [r["name"] for r in repos]
    repo_match = best_fuzzy_match(customer, repo_names)
    if repo_match:
        r = next(r for r in repos if r["name"] == repo_match[0])
        return [{"project": project, "repo": r["name"], "clone_url": r.get("remoteUrl"), "source": "auto-match"}]

    # Project matched but no single repo stands out -- show all of them
    # rather than silently guessing one.
    return [{"project": project, "repo": r["name"], "clone_url": r.get("remoteUrl"), "source": "auto-match"} for r in repos]


def merge_confirmed_and_guessed(detail, guessed):
    """(project, repo) -> {clone_url, source}. A confirmed match (a branch/PR
    this run's own Azure DevOps search already found for this case) takes
    priority over a customer-name/config guess for the same repo -- setdefault
    only fills in what a confirmed hit didn't already cover."""
    repos = {}
    for item in list((detail or {}).get("branches", [])) + list((detail or {}).get("pull_requests", [])):
        if item.get("clone_url"):
            repos.setdefault((item["project"], item["repo"]), {"clone_url": item["clone_url"], "source": "ado-search"})
    for item in guessed or []:
        key = (item["project"], item["repo"])
        if key not in repos:
            repos[key] = {"clone_url": item.get("clone_url"), "source": item.get("source", "guess")}
    return repos


def format_suggested_repo(repos, branch):
    """Markdown block describing which repo(s)/branch to use -- fed into the
    prompt as its own section (see case_guide.py's PROMPT_TEMPLATE) rather
    than rendered as a final "Get set up" heading itself, since claude still
    writes that section's actual prose."""
    if not repos:
        return (
            "_No repo identified yet._\n\n"
            "```\n"
            "git clone <repo-url>\n"
            "cd <repo-folder>\n"
            f"git checkout -b {branch}\n"
            "```"
        )
    lines = []
    for (project, repo), info in repos.items():
        lines.append(f"**{project}/{repo}:**" + (" _(guessed from customer name — verify before using)_" if info["source"] == "auto-match" else ""))
        lines.append("")
        lines.append("```")
        if info.get("clone_url"):
            lines.append(f"git clone {info['clone_url']}")
        else:
            lines.append(f"git clone <clone-url-for-{project}/{repo}>")
        lines.append(f"cd {repo}")
        lines.append(f"git checkout -b {branch}")
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip()
