#!/usr/bin/env python3
"""Compile a support case's context into one Markdown brief opened in VS Code.

Default flow needs no admin-approved app registration at all:
  - CRM case: if you pass a ticket number, it's looked up directly via the
    CRM API using ANY already-open, logged-in CRM tab as the auth bridge --
    you don't need to find/open the specific case yourself. Omit the ticket
    number and it'll auto-detect from a case you already have open instead.
  - Azure DevOps: related branches and PRs (matched by the case number
    appearing in the name/title/description, searched across every project
    in the org unless you set one) via the real REST API using a
    self-service PAT (no admin approval needed for that one).
  - Business Central: off by default (--with-bc to enable) while its
    scraping selector is still being worked out -- see lib/bc_scrape.py.

config.json is optional -- every setting in it has a sensible default and
can also be set with a command-line flag (which takes priority over the
config file). Run with -h to see them all.

Examples:
    python case_brief.py T2611845                  # look up this case directly
    python case_brief.py T2611845 --skip-ado
    python case_brief.py                           # auto-detect from an already-open CRM case tab
    python case_brief.py T2611845 --with-bc
    python case_brief.py T2611845 --org-url https://dev.azure.com/myorg --project MyProject
    python case_brief.py --demo                    # no browser/APIs, sample data
"""
import argparse
import copy
import difflib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ado_api, browser, bc_scrape, crm_scrape, report

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

DEFAULTS = {
    "chrome": {
        "profile_dir": "./chrome-automation-profile",
        "debug_port": 9222,
        "executable": None,
    },
    "url_patterns": {
        "crm_host_contains": ["dynamics.com"],
        "bc_host": "businesscentral.dynamics.com",
    },
    "ticket_field": "ticketnumber",
    "azure_devops": {
        "org_url": None,
        "project": None,
        "pat_env_var": "AZDO_PAT",
        "search_fields": ["System.Title", "System.Description"],
        "max_prs": ado_api.DEFAULT_MAX_PRS,
    },
    "output_dir": "./case-briefs",
    "open_in_vscode": True,
    "customer_repo_map": [],
}


def _deep_merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path=CONFIG_PATH):
    """Starts from DEFAULTS, layers config.json over it if present. Nothing
    here is required -- config.json existing at all is optional, and every
    field can also be set via a command-line flag (see apply_cli_overrides),
    which wins over both."""
    cfg = copy.deepcopy(DEFAULTS)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            _deep_merge(cfg, json.load(f))
    return cfg


def apply_cli_overrides(cfg, args):
    if args.org_url:
        cfg["azure_devops"]["org_url"] = args.org_url
    if args.project:
        cfg["azure_devops"]["project"] = args.project
    if args.pat_env_var:
        cfg["azure_devops"]["pat_env_var"] = args.pat_env_var
    if args.max_prs is not None:
        cfg["azure_devops"]["max_prs"] = args.max_prs
    if args.ticket_field:
        cfg["ticket_field"] = args.ticket_field
    if args.crm_host:
        cfg["url_patterns"]["crm_host_contains"] = args.crm_host
    if args.bc_host:
        cfg["url_patterns"]["bc_host"] = args.bc_host
    if args.chrome_profile_dir:
        cfg["chrome"]["profile_dir"] = args.chrome_profile_dir
    if args.chrome_port:
        cfg["chrome"]["debug_port"] = args.chrome_port
    if args.output_dir:
        cfg["output_dir"] = args.output_dir
    return cfg


def find_customer_repo(cfg, customer_name):
    """Looks up customer_repo_map in config.json for a rule whose
    customer_contains matches (case-insensitive substring) the CRM case's
    customer name. Returns the matching rule dict ({customer_contains,
    project, repo}) or None."""
    if not customer_name:
        return None
    haystack = customer_name.lower()
    for rule in cfg.get("customer_repo_map", []):
        needle = rule.get("customer_contains", "").lower()
        if needle and needle in haystack:
            return rule
    return None


_CORP_SUFFIXES = re.compile(
    r"\b(a\.?\s*s\.?|s\.?\s*r\.?\s*o\.?|spol\.?|inc\.?|llc|ltd\.?|gmbh|sp\.?\s*z\s*o\.?\s*o\.?|corp\.?|co\.?)\b",
    re.IGNORECASE,
)


def _normalize_name(name):
    name = _CORP_SUFFIXES.sub("", name or "")
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _fuzzy_score(a, b):
    return difflib.SequenceMatcher(None, _normalize_name(a), _normalize_name(b)).ratio()


def _best_fuzzy_match(name, candidates, threshold=0.5, min_lead=0.15):
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


def resolve_suggested_repos(cfg, args, crm_results):
    """Figures out which repo(s) to suggest clone/branch commands for --
    even when the Azure DevOps search found no branches/PRs yet (a brand
    new case has none, which is exactly when this is most useful).

    Priority: --repo flag > customer_repo_map entry > auto-matching the CRM
    customer name against ADO project (then repo) names by fuzzy string
    similarity. Auto-match results are tagged so the report can flag them
    as a guess rather than a confirmed mapping.

    Returns a list of {project, repo, clone_url, source} dicts (possibly
    empty, possibly more than one if a matched project has several repos
    and none stands out as THE one).
    """
    azure_cfg = cfg["azure_devops"]
    org_url = azure_cfg["org_url"]

    def resolve_one(project, repo_name, source):
        if not org_url:
            return [{"project": project, "repo": repo_name, "clone_url": None, "source": source}]
        try:
            repo_info = ado_api.get_repo(azure_cfg, project, repo_name)
        except Exception as e:
            print(f"  Could not resolve repo {project}/{repo_name}: {e}", file=sys.stderr)
            return [{"project": project, "repo": repo_name, "clone_url": None, "source": source}]
        if not repo_info:
            print(f"  Repo {project}/{repo_name} not found (check customer_repo_map / --repo)", file=sys.stderr)
            return [{"project": project, "repo": repo_name, "clone_url": None, "source": source}]
        return [{"project": project, "repo": repo_info["name"], "clone_url": repo_info.get("remoteUrl"), "source": source}]

    if args.repo:
        if "/" not in args.repo:
            print(f"  --repo should be PROJECT/REPO, got {args.repo!r} -- ignoring", file=sys.stderr)
        else:
            project, repo_name = args.repo.split("/", 1)
            return resolve_one(project, repo_name, "cli")

    if not crm_results or crm_results[0].get("error"):
        return []
    customer = crm_results[0].get("customer")
    if not customer:
        return []

    rule = find_customer_repo(cfg, customer)
    if rule:
        return resolve_one(rule.get("project"), rule.get("repo"), "customer_repo_map")

    if not org_url:
        return []

    try:
        projects = ado_api.list_projects(azure_cfg)
    except Exception as e:
        print(f"  Could not auto-match a project for repo suggestion: {e}", file=sys.stderr)
        return []

    match = _best_fuzzy_match(customer, projects)
    if not match:
        return []
    project, score = match
    print(f"  Guessed ADO project '{project}' from customer '{customer}' (similarity {score:.2f}) -- "
          f"override with --repo or customer_repo_map if wrong.")

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
    repo_match = _best_fuzzy_match(customer, repo_names)
    if repo_match:
        r = next(r for r in repos if r["name"] == repo_match[0])
        return [{"project": project, "repo": r["name"], "clone_url": r.get("remoteUrl"), "source": "auto-match"}]

    # Project matched but no single repo stands out -- show all of them
    # rather than silently guessing one.
    return [{"project": project, "repo": r["name"], "clone_url": r.get("remoteUrl"), "source": "auto-match"} for r in repos]


def demo_data(case_number):
    crm_results = [{
        "title": "Posting error in Sales Invoice",
        "ticket_number": case_number or "12345",
        "customer": "Contoso s.r.o.",
        "owner": "Jane Doe",
        "priority": "High",
        "status": "In Progress",
        "created_on": "2026-08-18T09:12:00Z",
        "description": "Customer reports Codeunit 80 throws a dimension error when posting invoice 103042.",
    }]
    branches = [
        {"project": "proj", "repo": "bc-extensions", "branch": "feature/12345-dimension-fix",
         "url": "https://dev.azure.com/example/proj/_git/bc-extensions?version=GBfeature/12345-dimension-fix",
         "clone_url": "https://dev.azure.com/example/proj/_git/bc-extensions"},
    ]
    pull_requests = [
        {"project": "proj", "id": 88, "repo": "bc-extensions", "title": "Fix dimension check on partial posting (12345)",
         "status": "active", "created_by": "Jane Doe",
         "url": "https://dev.azure.com/example/proj/_git/bc-extensions/pullrequest/88",
         "clone_url": "https://dev.azure.com/example/proj/_git/bc-extensions"},
    ]
    bc_results = [{
        "url": "https://businesscentral.dynamics.com/.../card",
        "page_title": "Sales Invoice 103042",
        "fields": [
            {"label": "No.", "value": "103042"},
            {"label": "Customer Name", "value": "Contoso s.r.o."},
            {"label": "Posting Date", "value": "2026-08-19"},
        ],
    }]
    return crm_results, branches, pull_requests, bc_results


def run_browser_scrape(cfg, case_number=None, include_bc=False):
    chrome_cfg = cfg["chrome"]
    crm_host = cfg["url_patterns"]["crm_host_contains"]
    bc_host = cfg["url_patterns"]["bc_host"]

    port, _ = browser.ensure_chrome(chrome_cfg)

    def crm_ready(pages):
        if case_number:
            return any(crm_scrape.is_authenticated(t) for t in crm_scrape.find_authenticated_tabs(pages, crm_host))
        return bool(crm_scrape.find_case_tabs(pages, crm_host))

    def ready(pages):
        if not crm_ready(pages):
            return False
        return not include_bc or bool(bc_scrape.find_bc_tabs(pages, bc_host))

    if case_number:
        message = "Waiting for you to sign into CRM in the automation Chrome window (any page there is fine)..."
    else:
        message = "Waiting for a CRM case tab to be open in the automation Chrome window..."
    if include_bc:
        message += " Also waiting for a Business Central tab to be open."

    browser.wait_until_ready(port, ready, message)

    pw, pages = browser.get_pages(port)
    bc_results = []
    try:
        if case_number:
            ticket_field = cfg["ticket_field"]
            auth_tabs = crm_scrape.find_authenticated_tabs(pages, crm_host)
            auth_tab = next((t for t in auth_tabs if crm_scrape.is_authenticated(t)), None)
            if not auth_tab:
                crm_results = [{"error": "No authenticated CRM tab found.", "url": ""}]
            else:
                print(f"Looking up case {case_number} via the CRM API (using an already-open CRM tab for auth)...")
                crm_results = [crm_scrape.lookup_by_ticket(auth_tab, case_number, ticket_field)]
        else:
            crm_tabs = crm_scrape.find_case_tabs(pages, crm_host)
            print(f"Found {len(crm_tabs)} CRM case tab(s) open.")
            crm_results = [crm_scrape.extract(p) for p in crm_tabs]

        if include_bc:
            bc_tabs = bc_scrape.find_bc_tabs(pages, bc_host)
            print(f"Found {len(bc_tabs)} Business Central tab(s) open.")
            bc_results = [bc_scrape.extract(p) for p in bc_tabs]
    finally:
        browser.close(pw)

    # Remember these URLs so the next cold launch (e.g. after you closed the
    # window) reopens them automatically instead of leaving you to retype them.
    last_urls = browser.load_last_urls()
    if crm_results and not crm_results[0].get("error"):
        last_urls["crm"] = crm_results[0]["url"]
    if bc_results:
        last_urls["bc"] = bc_results[0]["url"]
    if last_urls:
        browser.save_last_urls(last_urls)

    print("Closing the automation Chrome window...")
    browser.close_chrome_window(chrome_cfg)

    return crm_results, bc_results


def build_parser():
    parser = argparse.ArgumentParser(
        prog="case_brief.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("case_number", nargs="?", help="CRM ticket number (optional -- auto-detected from an open CRM tab if omitted)")

    modes = parser.add_argument_group("modes")
    modes.add_argument("--demo", action="store_true", help="Use sample data, no network/browser/API calls")
    modes.add_argument("--skip-ado", action="store_true", help="Don't search Azure DevOps")
    modes.add_argument("--skip-browser", action="store_true", help="Skip CRM/BC browser scraping entirely (Azure DevOps only)")
    modes.add_argument("--with-bc", action="store_true", help="Also scrape an open Business Central tab (off by default)")
    modes.add_argument("--no-open", action="store_true", help="Don't open the result in VS Code")

    ado = parser.add_argument_group("azure devops (override config.json's azure_devops.*)")
    ado.add_argument("--org-url", metavar="URL", help="Azure DevOps org URL, e.g. https://dev.azure.com/myorg")
    ado.add_argument("--project", metavar="NAME", help="Restrict the search to one project (default: search every project in the org)")
    ado.add_argument("--max-prs", type=int, metavar="N", help=f"Most recent PRs to search per project (default: {ado_api.DEFAULT_MAX_PRS})")
    ado.add_argument("--pat-env-var", metavar="NAME", help="Environment variable holding the Azure DevOps PAT (default: AZDO_PAT)")
    ado.add_argument("--repo", metavar="PROJECT/REPO", help="Repo to suggest clone/branch commands for, e.g. MyProject/my-repo (overrides customer_repo_map; shown even with no matching branches/PRs)")

    crm = parser.add_argument_group("crm / business central (override config.json's top-level and url_patterns.* settings)")
    crm.add_argument("--ticket-field", metavar="NAME", help="CRM field name for the ticket number (default: ticketnumber)")
    crm.add_argument("--crm-host", metavar="HOST", action="append", help="Substring matched against CRM tab URLs (default: dynamics.com); repeatable")
    crm.add_argument("--bc-host", metavar="HOST", help="Substring matched against Business Central tab URLs (default: businesscentral.dynamics.com)")

    chrome = parser.add_argument_group("chrome (override config.json's chrome.*)")
    chrome.add_argument("--chrome-profile-dir", metavar="DIR", help="Dedicated Chrome profile directory (default: ./chrome-automation-profile)")
    chrome.add_argument("--chrome-port", type=int, metavar="PORT", help="Chrome remote-debugging port (default: 9222)")

    misc = parser.add_argument_group("misc")
    misc.add_argument("--config", metavar="PATH", default=CONFIG_PATH, help="Path to config.json (default: ./config.json)")
    misc.add_argument("--output-dir", metavar="DIR", help="Where to write the brief (default: ./case-briefs)")

    return parser


def main():
    args = build_parser().parse_args()
    cfg = load_config(args.config)
    apply_cli_overrides(cfg, args)

    crm_results, branches, pull_requests, bc_results, ado_error, prs_truncated, max_prs = (
        [], [], [], [], None, False, ado_api.DEFAULT_MAX_PRS
    )

    if args.demo:
        crm_results, branches, pull_requests, bc_results = demo_data(args.case_number)
    else:
        if not args.skip_browser:
            print("Connecting to the automation Chrome window...")
            crm_results, bc_results = run_browser_scrape(cfg, case_number=args.case_number, include_bc=args.with_bc)

        if not args.skip_ado:
            if not cfg["azure_devops"]["org_url"]:
                ado_error = "no Azure DevOps org URL configured -- set azure_devops.org_url in config.json or pass --org-url"
            else:
                print("Searching Azure DevOps...")
                case_for_search = args.case_number or (crm_results[0].get("ticket_number") if crm_results and not crm_results[0].get("error") else None)
                if not case_for_search:
                    ado_error = "no case number given and none found in an open CRM tab"
                else:
                    try:
                        branches, pull_requests, prs_truncated, max_prs = ado_api.find_related(cfg["azure_devops"], case_for_search)
                    except Exception as e:
                        ado_error = str(e)
                        print(f"  Azure DevOps lookup failed: {e}", file=sys.stderr)

    case_number = args.case_number
    if not case_number and crm_results and not crm_results[0].get("error"):
        case_number = crm_results[0].get("ticket_number")
    case_number = case_number or "unlabeled"

    suggested_repos = []
    if not args.demo:
        suggested_repos = resolve_suggested_repos(cfg, args, crm_results)

    markdown = report.build_markdown(
        case_number, crm_results, branches, pull_requests, bc_results,
        ado_error=ado_error, include_bc=args.with_bc or args.demo,
        prs_truncated=prs_truncated, max_prs=max_prs, suggested_repos=suggested_repos,
    )
    path = report.write_and_open(
        markdown,
        os.path.join(HERE, cfg["output_dir"]),
        case_number,
        open_in_vscode=cfg["open_in_vscode"] and not args.no_open,
    )
    print(f"\nBrief written to {path}")


if __name__ == "__main__":
    main()
