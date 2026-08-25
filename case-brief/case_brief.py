#!/usr/bin/env python3
"""Compile a support case's context into one Markdown brief opened in VS Code.

Default flow needs no admin-approved app registration at all:
  - CRM case: if you pass a ticket number, it's looked up directly via the
    CRM API using ANY already-open, logged-in CRM tab as the auth bridge --
    you don't need to find/open the specific case yourself. Omit the ticket
    number and it'll auto-detect from a case you already have open instead.
  - Azure DevOps: related branches and PRs, via the real REST API using a
    self-service PAT (no admin approval needed for that one). Resolved
    directly from any ADO link already found in the CRM case (fast --
    one API call each). Only falls back to a full org-wide branch/PR
    search (slow on large orgs) if nothing was linked directly, and only
    when you opt in with --search-ado.

config.json is optional -- every setting in it has a sensible default and
can also be set with a command-line flag (which takes priority over the
config file). Run with -h to see them all.

Examples:
    python case_brief.py T2611845                  # look up this case directly
    python case_brief.py T2611845 --skip-ado
    python case_brief.py                           # auto-detect from an already-open CRM case tab
    python case_brief.py T2611845 --org-url https://dev.azure.com/myorg --project MyProject
    python case_brief.py --demo                    # no browser/APIs, sample data
"""
import argparse
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from shared.console import enable_utf8_console

enable_utf8_console()  # this script prints Unicode; see shared/console.py

from lib import ado_api, browser, crm_scrape, report
from lib.report import DEFAULT_PROMOTED_FIELDS
from lib.progress import progress, progress_success, progress_error, Phase
from shared.config import deep_merge, strip_comments

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
    },
    "ticket_field": "ticketnumber",
    "azure_devops": {
        "org_url": None,
        "project": None,
        "pat_env_var": "AZDO_PAT",
        "search_fields": ["System.Title", "System.Description"],
        "max_prs": ado_api.DEFAULT_MAX_PRS,
        # Off by default: find_related's org-wide branch/PR search is slow
        # (every repo's every branch, in every project) and is only a
        # fallback now -- see run_ado_lookup / ado_api.parse_direct_references.
        "broad_search": False,
    },
    "output_dir": "./case-briefs",
    "open_in_vscode": True,
    # CRM fields (by logical_name) shown as their own proper subsection right
    # after Description, instead of buried in the "Other CRM Fields" dump at
    # the bottom -- see lib/report.py::build_markdown. Org-specific custom
    # fields; override in config.json if yours differ.
    "crm_promoted_fields": list(DEFAULT_PROMOTED_FIELDS),
}


def load_config(path=CONFIG_PATH):
    """Starts from DEFAULTS, layers config.json over it if present. Nothing
    here is required -- config.json existing at all is optional, and every
    field can also be set via a command-line flag (see apply_cli_overrides),
    which wins over both."""
    cfg = copy.deepcopy(DEFAULTS)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            deep_merge(cfg, json.load(f))
    return strip_comments(cfg)


def apply_cli_overrides(cfg, args):
    if args.org_url:
        cfg["azure_devops"]["org_url"] = args.org_url
    if args.project:
        cfg["azure_devops"]["project"] = args.project
    if args.pat_env_var:
        cfg["azure_devops"]["pat_env_var"] = args.pat_env_var
    if args.max_prs is not None:
        cfg["azure_devops"]["max_prs"] = args.max_prs
    if args.search_ado:
        cfg["azure_devops"]["broad_search"] = True
    if args.ticket_field:
        cfg["ticket_field"] = args.ticket_field
    if args.crm_host:
        cfg["url_patterns"]["crm_host_contains"] = args.crm_host
    if args.chrome_profile_dir:
        cfg["chrome"]["profile_dir"] = args.chrome_profile_dir
    if args.chrome_port:
        cfg["chrome"]["debug_port"] = args.chrome_port
    if args.output_dir:
        cfg["output_dir"] = args.output_dir
    return cfg


def _collect_reference_text(crm_results):
    """Flattens every bit of text case-brief pulled from CRM -- title,
    description, every extra field crm_scrape.py found, every note, every
    activity -- into one blob to scan for direct Azure DevOps PR/branch
    links (see ado_api.parse_direct_references). Errors and non-string
    values are skipped rather than raising: this is a best-effort scan,
    not something that should ever fail the brief."""
    parts = []
    for c in crm_results or []:
        if c.get("error"):
            continue
        for key in ("title", "description"):
            v = c.get(key)
            if isinstance(v, str):
                parts.append(v)
        for f in c.get("all_fields") or []:
            v = f.get("value")
            if isinstance(v, str):
                parts.append(v)
        for n in c.get("notes") or []:
            for key in ("subject", "text"):
                v = n.get(key)
                if isinstance(v, str):
                    parts.append(v)
        for a in c.get("activities") or []:
            for key in ("subject", "description"):
                v = a.get(key)
                if isinstance(v, str):
                    parts.append(v)
    return "\n".join(parts)


def run_ado_lookup(cfg, args, crm_results):
    """Finds branches/PRs related to the case. Prefers direct links already
    present in the CRM case (one API call each, via
    ado_api.parse_direct_references) over the old org-wide brute-force
    search (find_related), which only runs now as an opt-in fallback
    (--search-ado / azure_devops.broad_search) since it can be very slow on
    orgs with many projects/repos.

    Returns (branches, pull_requests, ado_error, ado_note, prs_truncated, max_prs).
    """
    azure_cfg = cfg["azure_devops"]
    max_prs = azure_cfg.get("max_prs", ado_api.DEFAULT_MAX_PRS)

    if not azure_cfg["org_url"]:
        return [], [], "no Azure DevOps org URL configured -- set azure_devops.org_url in config.json or pass --org-url", None, False, max_prs

    ref_text = _collect_reference_text(crm_results)
    pr_refs, branch_refs = ado_api.parse_direct_references(azure_cfg, ref_text)

    if pr_refs or branch_refs:
        branches, pull_requests = [], []
        resolved = failed = 0
        for ref in pr_refs:
            try:
                pull_requests.append(ado_api.get_pull_request(azure_cfg, ref["project"], ref["repo"], ref["id"]))
                resolved += 1
            except Exception as e:
                failed += 1
                print(f"  Could not resolve PR {ref['project']}/{ref['repo']} !{ref['id']} (linked from CRM): {e}", file=sys.stderr)
        for ref in branch_refs:
            try:
                b = ado_api.get_branch(azure_cfg, ref["project"], ref["repo"], ref["branch"])
            except Exception as e:
                b = None
                print(f"  Could not resolve branch {ref['project']}/{ref['repo']}/{ref['branch']} (linked from CRM): {e}", file=sys.stderr)
            if b:
                branches.append(b)
                resolved += 1
            else:
                failed += 1
                if b is None:
                    print(f"  Branch {ref['project']}/{ref['repo']}/{ref['branch']} (linked from CRM) not found in Azure DevOps -- deleted/merged?", file=sys.stderr)

        total = len(pr_refs) + len(branch_refs)
        ado_note = f"Resolved {resolved}/{total} Azure DevOps reference(s) found directly in the CRM case (no org-wide search needed)."
        if failed:
            ado_note += f" {failed} could not be resolved -- see console."
        return branches, pull_requests, None, ado_note, False, max_prs

    if not azure_cfg.get("broad_search"):
        note = "No direct Azure DevOps link found in the CRM case; org-wide search skipped (pass --search-ado to run it, but it can be slow)."
        return [], [], None, note, False, max_prs

    case_for_search = args.case_number or (crm_results[0].get("ticket_number") if crm_results and not crm_results[0].get("error") else None)
    if not case_for_search:
        return [], [], "no case number given and none found in an open CRM tab", None, False, max_prs

    try:
        branches, pull_requests, prs_truncated, max_prs = ado_api.find_related(azure_cfg, case_for_search)
        return branches, pull_requests, None, "Found via a full org-wide search (--search-ado) -- no direct link was found in the CRM case.", prs_truncated, max_prs
    except Exception as e:
        return [], [], str(e), None, False, max_prs


def demo_data(case_number):
    crm_results = [{
        "title": "Posting error in Sales Invoice",
        "ticket_number": case_number or "12345",
        "customer": "Contoso s.r.o.",
        "owner": "Jane Doe",
        "priority": "High",
        "status": "In Progress",
        "created_on": "2026-08-18T09:12:00Z",
        "description": "Customer reports the invoicing module throws a dimension error when posting invoice 103042.",
        # Shows off crm_scrape.py's "get everything" fields -- what used to
        # be silently dropped by a curated $select list, e.g. an org's own
        # internal-only custom field.
        "all_fields": [
            {"logical_name": "new_internaldescription", "label": "Internal Description",
             "value": "Looks like the dimension default was cleared during the last data import -- check DIM-4021 before escalating."},
            {"logical_name": "caseorigincode", "label": "Origin", "value": "Phone"},
            {"logical_name": "resolvebydate", "label": "Resolve By", "value": "2026-08-25T09:12:00Z"},
        ],
        "notes": [
            {"subject": "Repro steps confirmed", "created_on": "2026-08-19T10:03:00Z",
             "text": "Reproduced on a copy of the customer's database. Fails only when the dimension default is missing.", "filename": None},
        ],
        "notes_truncated": False, "notes_error": None,
        "activities": [
            {"type": "phonecall", "subject": "Callback re: invoice 103042", "status": "Completed",
             "created_on": "2026-08-18T14:00:00Z", "description": "Confirmed the customer can reproduce it consistently."},
        ],
        "activities_truncated": False, "activities_error": None,
    }]
    branches = [
        {"project": "proj", "repo": "invoicing-service", "branch": "feature/12345-dimension-fix",
         "url": "https://dev.azure.com/example/proj/_git/invoicing-service?version=GBfeature/12345-dimension-fix",
         "clone_url": "https://dev.azure.com/example/proj/_git/invoicing-service"},
    ]
    pull_requests = [
        {"project": "proj", "id": 88, "repo": "invoicing-service", "title": "Fix dimension check on partial posting (12345)",
         "status": "active", "created_by": "Jane Doe",
         "url": "https://dev.azure.com/example/proj/_git/invoicing-service/pullrequest/88",
         "clone_url": "https://dev.azure.com/example/proj/_git/invoicing-service"},
    ]
    return crm_results, branches, pull_requests


def run_browser_scrape(cfg, case_number=None, keep_browser_open=False):
    chrome_cfg = cfg["chrome"]
    crm_host = cfg["url_patterns"]["crm_host_contains"]

    port, _ = browser.ensure_chrome(chrome_cfg)

    def ready(pages):
        if case_number:
            return any(crm_scrape.is_authenticated(t) for t in crm_scrape.find_authenticated_tabs(pages, crm_host))
        return bool(crm_scrape.find_case_tabs(pages, crm_host))

    if case_number:
        message = "Waiting for you to sign into CRM in the automation Chrome window (any page there is fine)..."
    else:
        message = "Waiting for a CRM case tab to be open in the automation Chrome window..."

    browser.wait_until_ready(port, ready, message)

    pw, pages = browser.get_pages(port)
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
    finally:
        browser.close(pw)

    # Remember this URL so the next cold launch (e.g. after you closed the
    # window) reopens it automatically instead of leaving you to retype it.
    last_urls = browser.load_last_urls()
    if crm_results and not crm_results[0].get("error"):
        last_urls["crm"] = crm_results[0]["url"]
    if last_urls:
        browser.save_last_urls(last_urls)

    if not keep_browser_open:
        print("Closing the automation Chrome window...")
        browser.close_chrome_window(chrome_cfg)

    return crm_results


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
    modes.add_argument("--skip-browser", action="store_true", help="Skip CRM browser scraping entirely (Azure DevOps only)")
    modes.add_argument("--no-open", action="store_true", help="Don't open the result in VS Code")
    modes.add_argument(
        "--keep-browser-open", action="store_true",
        help="Don't close the automation Chrome window when done (default: close it). "
             "Use this when something else - e.g. case-wizard's own dashboard - is using that same window.",
    )

    ado = parser.add_argument_group("azure devops (override config.json's azure_devops.*)")
    ado.add_argument("--org-url", metavar="URL", help="Azure DevOps org URL, e.g. https://dev.azure.com/myorg")
    ado.add_argument("--project", metavar="NAME", help="Restrict the search to one project (default: search every project in the org)")
    ado.add_argument("--max-prs", type=int, metavar="N", help=f"Most recent PRs to search per project (default: {ado_api.DEFAULT_MAX_PRS})")
    ado.add_argument("--pat-env-var", metavar="NAME", help="Environment variable holding the Azure DevOps PAT (default: AZDO_PAT)")
    ado.add_argument(
        "--search-ado", action="store_true",
        help="Fall back to a full org-wide branch/PR search when no direct Azure DevOps link is found in the "
             "CRM case (default: off -- can be slow on orgs with many projects/repos)",
    )

    crm = parser.add_argument_group("crm (override config.json's top-level and url_patterns.* settings)")
    crm.add_argument("--ticket-field", metavar="NAME", help="CRM field name for the ticket number (default: ticketnumber)")
    crm.add_argument("--crm-host", metavar="HOST", action="append", help="Substring matched against CRM tab URLs (default: dynamics.com); repeatable")

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

    crm_results, branches, pull_requests, ado_error, ado_note, prs_truncated, max_prs = (
        [], [], [], None, None, False, ado_api.DEFAULT_MAX_PRS
    )

    try:
        if args.demo:
            progress("Loading demo data...", status="running")
            crm_results, branches, pull_requests = demo_data(args.case_number)
            progress_success("Demo data loaded")
        else:
            if not args.skip_browser:
                progress("Connecting to automation Chrome window...", status="running")
                crm_results = run_browser_scrape(
                    cfg, case_number=args.case_number,
                    keep_browser_open=args.keep_browser_open,
                )
                progress_success("CRM data extracted", f"Found {len(crm_results)} cases")

            if not args.skip_ado:
                progress("Looking for direct Azure DevOps references in CRM...", status="running")
                branches, pull_requests, ado_error, ado_note, prs_truncated, max_prs = run_ado_lookup(cfg, args, crm_results)
                if ado_error:
                    progress_error("Azure DevOps lookup failed", ado_error)
                else:
                    progress_success("Azure DevOps lookup complete", ado_note or f"Found {len(branches)} branches, {len(pull_requests)} PRs")

        case_number = args.case_number
        if not case_number and crm_results and not crm_results[0].get("error"):
            case_number = crm_results[0].get("ticket_number")
        case_number = case_number or "unlabeled"

        progress("Building markdown brief...", status="running")
        markdown = report.build_markdown(
            case_number, crm_results, branches, pull_requests,
            ado_error=ado_error, ado_note=ado_note,
            prs_truncated=prs_truncated, max_prs=max_prs,
            promoted_fields=cfg.get("crm_promoted_fields"),
        )
        progress_success("Brief markdown built")

        progress("Writing to file...", status="running")
        path = report.write_and_open(
            markdown,
            os.path.join(HERE, cfg["output_dir"]),
            case_number,
            open_in_vscode=cfg["open_in_vscode"] and not args.no_open,
        )
        progress_success("Brief complete", f"Written to {path}")

    except Exception as e:
        progress_error("Brief generation failed", str(e))
        raise


if __name__ == "__main__":
    main()
