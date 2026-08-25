#!/usr/bin/env python3
"""Compile a support case's context into one Markdown brief opened in VS Code.

Default flow needs no admin-approved app registration at all:
  - CRM case: if you pass a ticket number, it's looked up directly via the
    CRM API using ANY already-open, logged-in CRM tab as the auth bridge --
    you don't need to find/open the specific case yourself. Omit the ticket
    number and it'll auto-detect from a case you already have open instead.
  - Azure DevOps: related branches and PRs, via the real REST API using a
    self-service PAT (no admin approval needed for that one). Resolved
    directly from any ADO link already found in the CRM case (fast -- one
    API call each). There is no broader org-wide search -- see
    lib/ado_api.py's module docstring for why.

The org URL, PAT env var, CRM ticket field, CRM host pattern, output
directory, and Chrome profile/port are all fixed (see the constants below)
-- this tool only ever talks to one org, one CRM, and its own dedicated
Chrome profile, so making any of that configurable added surface nobody
ever actually needed to touch. There is no config.json at all -- every
setting here is either a CLI flag or a fixed constant. Run with -h to see
the flags.

Examples:
    python case_brief.py T2611845                  # look up this case directly
    python case_brief.py T2611845 --skip-ado
    python case_brief.py                           # auto-detect from an already-open CRM case tab
    python case_brief.py --demo                    # no browser/APIs, sample data
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from shared.console import enable_utf8_console

enable_utf8_console()  # this script prints Unicode; see shared/console.py

from lib import ado_api, browser, crm_scrape, report
from lib.progress import progress, progress_success, progress_error

HERE = os.path.dirname(os.path.abspath(__file__))

# This tool only ever talks to one Dynamics 365 org via its own dedicated
# Chrome automation profile, so none of this actually varies -- not worth a
# config file or CLI flag. (Azure DevOps's own org URL/PAT env var
# equivalents live in lib/ado_api.py.) If chrome.exe isn't found
# automatically, set CHROME_CFG["executable"] below to its full path.
TICKET_FIELD = "ticketnumber"
CRM_HOST_CONTAINS = ["dynamics.com"]
OUTPUT_DIR = "./case-briefs"
CHROME_CFG = {
    "profile_dir": "./chrome-automation-profile",
    "debug_port": 9222,
    "executable": None,
}


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


def run_ado_lookup(crm_results):
    """Finds branches/PRs referenced directly in the CRM case (one API call
    each, via ado_api.parse_direct_references). There is no broader
    org-wide search -- see lib/ado_api.py's module docstring for why --
    so if the case doesn't already link its own work, this comes back
    empty rather than searching for it.

    Returns (branches, pull_requests, ado_error, ado_note).
    """
    ref_text = _collect_reference_text(crm_results)
    pr_refs, branch_refs = ado_api.parse_direct_references(ref_text)

    if not (pr_refs or branch_refs):
        return [], [], None, "No direct Azure DevOps link found in the CRM case."

    branches, pull_requests = [], []
    resolved = failed = 0
    for ref in pr_refs:
        try:
            pull_requests.append(ado_api.get_pull_request(ref["project"], ref["id"]))
            resolved += 1
        except Exception as e:
            failed += 1
            print(f"  Could not resolve PR {ref['project']}/{ref['repo']} !{ref['id']} (linked from CRM): {e}", file=sys.stderr)
    for ref in branch_refs:
        try:
            b = ado_api.get_branch(ref["project"], ref["repo"], ref["branch"])
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
    ado_note = f"Resolved {resolved}/{total} Azure DevOps reference(s) found directly in the CRM case."
    if failed:
        ado_note += f" {failed} could not be resolved -- see console."
    return branches, pull_requests, None, ado_note


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


def run_browser_scrape(case_number=None, keep_browser_open=False):
    port, _ = browser.ensure_chrome(CHROME_CFG)

    def ready(pages):
        if case_number:
            return any(crm_scrape.is_authenticated(t) for t in crm_scrape.find_authenticated_tabs(pages, CRM_HOST_CONTAINS))
        return bool(crm_scrape.find_case_tabs(pages, CRM_HOST_CONTAINS))

    if case_number:
        message = "Waiting for you to sign into CRM in the automation Chrome window (any page there is fine)..."
    else:
        message = "Waiting for a CRM case tab to be open in the automation Chrome window..."

    browser.wait_until_ready(port, ready, message)

    pw, pages = browser.get_pages(port)
    try:
        if case_number:
            auth_tabs = crm_scrape.find_authenticated_tabs(pages, CRM_HOST_CONTAINS)
            auth_tab = next((t for t in auth_tabs if crm_scrape.is_authenticated(t)), None)
            if not auth_tab:
                crm_results = [{"error": "No authenticated CRM tab found.", "url": ""}]
            else:
                print(f"Looking up case {case_number} via the CRM API (using an already-open CRM tab for auth)...")
                crm_results = [crm_scrape.lookup_by_ticket(auth_tab, case_number, TICKET_FIELD)]
        else:
            crm_tabs = crm_scrape.find_case_tabs(pages, CRM_HOST_CONTAINS)
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
        browser.close_chrome_window(CHROME_CFG)

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
        help="Don't close the automation Chrome window when done (default: close it).",
    )

    return parser


def main():
    args = build_parser().parse_args()

    crm_results, branches, pull_requests, ado_error, ado_note = [], [], [], None, None

    try:
        if args.demo:
            progress("Loading demo data...", status="running")
            crm_results, branches, pull_requests = demo_data(args.case_number)
            progress_success("Demo data loaded")
        else:
            if not args.skip_browser:
                progress("Connecting to automation Chrome window...", status="running")
                crm_results = run_browser_scrape(
                    case_number=args.case_number,
                    keep_browser_open=args.keep_browser_open,
                )
                progress_success("CRM data extracted", f"Found {len(crm_results)} cases")

            if not args.skip_ado:
                progress("Looking for direct Azure DevOps references in CRM...", status="running")
                branches, pull_requests, ado_error, ado_note = run_ado_lookup(crm_results)
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
        )
        progress_success("Brief markdown built")

        progress("Writing to file...", status="running")
        path = report.write_and_open(
            markdown,
            os.path.join(HERE, OUTPUT_DIR),
            case_number,
            open_in_vscode=not args.no_open,
        )
        progress_success("Brief complete", f"Written to {path}")

    except Exception as e:
        progress_error("Brief generation failed", str(e))
        raise


if __name__ == "__main__":
    main()
