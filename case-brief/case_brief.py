#!/usr/bin/env python3
"""Compile a support case's context into one Markdown brief opened in VS Code.

Default flow needs no admin-approved app registration at all:
  - CRM case: looked up directly via the Dataverse Web API by ticket number,
    authenticated via OAuth (Entra ID) device-code sign-in -- the first run
    opens an interactive sign-in prompt (a URL + a one-time code, no browser
    automation profile), every run after that is silent (see
    lib/dataverse_auth.py for why no admin app registration is needed here).
  - Azure DevOps: related branches and PRs, via the real REST API using a
    self-service PAT (no admin approval needed for that one). Resolved
    directly from any ADO link already found in the CRM case (fast -- one
    API call each). There is no broader org-wide search -- see
    lib/ado_api.py's module docstring for why.

The org URL, PAT env var, CRM ticket field, and output directory are all
fixed (see the constants below) -- this tool only ever talks to one org and
one CRM, so making any of that configurable added surface nobody ever
actually needed to touch. There is no config.json at all -- every setting
here is either a CLI flag or a fixed constant. Run with -h to see the flags.

Examples:
    python case_brief.py T2611845                  # look up this case directly
    python case_brief.py --demo                    # no API calls, sample data
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from shared.console import enable_utf8_console

enable_utf8_console()  # this script prints Unicode; see shared/console.py

from lib import ado_api, crm_scrape, dataverse_auth, report
from lib.dataverse_page import DataverseApiPage
from lib.progress import progress, progress_success, progress_error

HERE = os.path.dirname(os.path.abspath(__file__))

# This tool only ever talks to one Dynamics 365 org, so none of this
# actually varies -- not worth a config file or CLI flag. (Azure DevOps's
# own org URL/PAT env var equivalents live in lib/ado_api.py.)
TICKET_FIELD = "ticketnumber"
# Also the Dataverse OAuth resource identifier (see lib/dataverse_auth.py).
CRM_ORIGIN = "https://artex-crm.crm4.dynamics.com"
OUTPUT_DIR = "./briefs"


def _collect_reference_text(crm_results):
    """Flattens every bit of text case-brief pulled from CRM -- title,
    description, every extra field crm_scrape.py found, every note, every
    activity -- into one blob to scan for direct Azure DevOps PR/branch
    links (see ado_api.parse_direct_references). Errors and non-string
    values are skipped rather than raising: this is a best-effort scan,
    not something that should ever fail the brief.

    Deliberately does NOT include the Dev tab's own "Related links" grid
    (crm_scrape.get_related_links) -- report.py renders those directly
    from the CRM data already (see report._related_links_lines), so
    scanning them here too would just mean resolving them via the ADO API
    only to immediately discard the result as a duplicate (see
    run_ado_lookup/_related_link_refs, which excludes anything already
    covered by related_links from what this function's callers resolve --
    covering a related link pasted redundantly into a note or field too,
    not just the grid entry itself).
    """
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


def _related_link_refs(crm_results):
    """(pr_refs, branch_refs) already covered by the CRM case form's own
    Dev-tab "Related links" grid (see crm_scrape.get_related_links) --
    parsed from just those entries' URLs the same way
    ado_api.parse_direct_references parses everything else, so
    run_ado_lookup can exclude them from its own resolved branches/pull_requests.

    Without this, the same PR/branch gets linked twice in the rendered
    brief: once via report.py's own related_links rendering (the raw CRM
    grid entry), and again via this module's direct-reference resolution
    -- a related link's URL is itself part of the text
    _collect_reference_text scans, so it always also turns up as a "direct
    reference" in its own right.
    """
    urls = []
    for c in crm_results or []:
        if c.get("error"):
            continue
        for rl in c.get("related_links") or []:
            url = rl.get("url")
            if isinstance(url, str):
                urls.append(url)
    return ado_api.parse_direct_references("\n".join(urls))


def run_ado_lookup(crm_results):
    """Finds branches/PRs referenced directly in the CRM case (resolved
    directly, a couple of targeted API calls each, via
    ado_api.parse_direct_references). There is no broader
    org-wide search -- see lib/ado_api.py's module docstring for why --
    so if the case doesn't already link its own work, this comes back
    empty rather than searching for it.

    Anything already covered by CRM's own Dev-tab related links grid (see
    _related_link_refs) is excluded before resolving -- report.py renders
    those directly from the CRM data already, so resolving and listing
    them again here would link the same PR/branch twice. Matched by
    (project, id) for PRs -- Azure DevOps PR ids are unique org-wide, and
    matching on repo too is unreliable here: the CRM-stored related-link
    URL and the one resolved via the ADO API can represent the same repo
    with a different string (a repo GUID vs. its human-readable name) --
    and by (project, branch) for branches, for the same reason.

    Returns (branches, pull_requests, ado_error, ado_note). ado_note is None
    when nothing was found in the text scan -- report.py's "## Related
    Links" section already says so generically (covering CRM's own Dev-tab
    related links and the Helpdesk link too, not just this text scan) once
    it's seen the combined result come up empty, so there's no need for a
    redundant, ADO-specific "nothing found" message here.

    A single failed reference is caught and counted per-item (folded into
    `ado_note`, see below) rather than raised, so this function itself
    never actually returns a non-None `ado_error` -- that slot in the
    return tuple only ever gets populated by `main`'s own try/except around
    the call to this function, for a failure this function didn't already
    handle (e.g. `ado_api.parse_direct_references` itself raising). Always
    runs, never optional -- see main()'s call site.
    """
    ref_text = _collect_reference_text(crm_results)
    pr_refs, branch_refs = ado_api.parse_direct_references(ref_text)

    related_pr_refs, related_branch_refs = _related_link_refs(crm_results)
    related_pr_keys = {(r["project"].lower(), r["id"]) for r in related_pr_refs}
    related_branch_keys = {(r["project"].lower(), r["branch"].lower()) for r in related_branch_refs}
    pr_refs = [r for r in pr_refs if (r["project"].lower(), r["id"]) not in related_pr_keys]
    branch_refs = [r for r in branch_refs if (r["project"].lower(), r["branch"].lower()) not in related_branch_keys]

    if not (pr_refs or branch_refs):
        return [], [], None, None

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
    demo_incident_id = "00000000-0000-0000-0000-0000000000aa"
    crm_results = [{
        "title": "Posting error in Sales Invoice",
        "ticket_number": case_number or "12345",
        "id": demo_incident_id,
        # Shows off the case's own CRM record deep link (see
        # crm_scrape._to_result / report._related_links_lines) -- the first
        # entry in "## Related Links".
        "url": f"{CRM_ORIGIN}/main.aspx?appid={crm_scrape.CRM_APP_ID}&forceUCI=1"
               f"&pagetype=entityrecord&etn=incident&id={demo_incident_id}",
        "customer": "Contoso s.r.o.",
        "owner": "Jane Doe",
        "priority": "High",
        "status": "In Progress",
        "created_on": "2026-08-18T09:12:00Z",
        "description": "Customer reports the invoicing module throws a dimension error when posting invoice 103042.",
        # Shows off crm_scrape.py's "get everything" fields -- what used to
        # be silently dropped by a curated $select list, e.g. an org's own
        # internal-only custom field. Uses the real logical names
        # (art_descriptionadditionalpublic/art_internaldescriptionandnotes,
        # see report.DEFAULT_PROMOTED_FIELDS) so --demo actually exercises
        # both promoted-field-under-Description paths, in their real order,
        # instead of just landing in "Other CRM Fields" like a made-up
        # field name would.
        "all_fields": [
            {"logical_name": "art_descriptionadditionalpublic", "label": "Dodatečný veřejný popis",
             "value": "Public-facing summary: invoice posting is delayed while we investigate a dimension error."},
            {"logical_name": "art_internaldescriptionandnotes", "label": "Interní popis & poznámky",
             "value": "Looks like the dimension default was cleared during the last data import -- check DIM-4021 before escalating."},
            # The case's own Helpdesk portal link -- promoted into "##
            # Related Links" as its own entry (see report.HELPDESK_LINK_FIELD),
            # not rendered as a text block like the two fields above.
            {"logical_name": "art_helpdesklink", "label": "Helpdesk link",
             "value": "https://artexhelpdesk.powerappsportals.com/support/edit-case/?id=00000000-0000-0000-0000-000000000000"},
            {"logical_name": "caseorigincode", "label": "Origin", "value": "Phone"},
            {"logical_name": "resolvebydate", "label": "Resolve By", "value": "2026-08-25T09:12:00Z"},
        ],
        "notes": [
            {"subject": "Repro steps confirmed", "created_on": "2026-08-19T10:03:00Z",
             "text": "Reproduced on a copy of the customer's database. Fails only when the dimension default is missing.", "filename": None},
            # Shows off attachment content (2026-08-26) -- a small text-like
            # attachment (see crm_scrape._fetch_inlinable_attachments) gets
            # inlined as a fenced code block right in the brief, not just
            # named. An image attachment would instead be saved next to the
            # brief and linked with a Markdown image tag (see
            # report.collect_attachments) -- not shown here since --demo
            # never calls crm_scrape at all, so there's no real file to save.
            {"subject": "Error log attached", "created_on": "2026-08-19T11:15:00Z", "text": None,
             "filename": "error.log", "mimetype": "text/plain", "filesize": 128,
             "attachment": {"kind": "text", "content": "2026-08-19 11:12:03 ERROR DimensionDefaultMissing (invoice 103042)", "truncated": False}},
        ],
        "notes_truncated": False, "notes_error": None,
        "activities": [
            {"type": "phonecall", "subject": "Callback re: invoice 103042", "status": "Completed",
             "created_on": "2026-08-18T14:00:00Z", "description": "Confirmed the customer can reproduce it consistently."},
        ],
        "activities_truncated": False, "activities_error": None,
        # Shows off the Dev tab's "Related links" grid (a PR attached
        # directly in CRM, not just pasted into free text -- see
        # crm_scrape.get_related_links). A *different* PR (#88) than the
        # demo branches/pull_requests below (#91) -- on purpose: those two
        # sections must never show the same PR twice (see
        # run_ado_lookup/_related_link_refs, which excludes anything
        # related_links already covers from what gets resolved into
        # branches/pull_requests). --demo bypasses run_ado_lookup entirely
        # (no real API calls), so unlike a real run this dedup doesn't run
        # here -- these two lists are just kept deliberately non-
        # overlapping by hand instead, so the demo doesn't visually
        # reintroduce the very duplication that dedup exists to prevent.
        "related_links": [
            {"name": "PR 88 ✅ (CU-DEMO)",
             "url": "https://dev.azure.com/example/proj/_git/invoicing-service/pullrequest/88",
             "status": "Active", "created_on": "2026-08-18T09:20:00Z"},
        ],
        "related_links_error": None,
    }]
    branches = [
        {"project": "proj", "repo": "invoicing-service", "branch": "feature/12345-dimension-fix",
         "url": "https://dev.azure.com/example/proj/_git/invoicing-service?version=GBfeature/12345-dimension-fix",
         "clone_url": "https://dev.azure.com/example/proj/_git/invoicing-service"},
    ]
    pull_requests = [
        {"project": "proj", "id": 91, "repo": "invoicing-service", "title": "Add dimension default fallback (12345)",
         "status": "active", "created_by": "Jane Doe",
         "url": "https://dev.azure.com/example/proj/_git/invoicing-service/pullrequest/91",
         "clone_url": "https://dev.azure.com/example/proj/_git/invoicing-service"},
    ]
    return crm_results, branches, pull_requests


def run_crm_lookup(case_number):
    """CRM lookup via the real Dataverse Web API over an OAuth (Entra ID)
    access token (see lib/dataverse_auth.py). Reuses crm_scrape.py
    completely unchanged: the only thing new is DataverseApiPage, which
    answers crm_scrape's `page` interface (`.url` / `.evaluate(js, arg)`)
    over `requests` + the token instead of an in-page browser fetch.

    Deliberately does NOT retry or degrade on failure -- an expired/blocked
    token or a permissions error needs to surface as a clear error (see
    lib/dataverse_auth.py's DataverseAuthError and CLAUDE.md's Dataverse
    API section for what to do about it).
    """
    token = dataverse_auth.get_access_token()
    page = DataverseApiPage(CRM_ORIGIN, token)
    print(f"Looking up case {case_number} via the Dataverse Web API (OAuth)...")
    return [crm_scrape.lookup_by_ticket(page, case_number, TICKET_FIELD)]


def list_relevant_cases():
    """Every currently-unassigned CRM case (crm_scrape.list_new_cases), via
    the same OAuth-authenticated Dataverse connection as run_crm_lookup.
    Used by case-getter (../case-getter/case_getter.py) to find work to
    brief/guide -- case-brief's own CLI never calls this, it only ever
    looks up one case by ticket number.

    Returns (cases, error, truncated) -- see crm_scrape.list_new_cases.
    """
    token = dataverse_auth.get_access_token()
    page = DataverseApiPage(CRM_ORIGIN, token)
    return crm_scrape.list_new_cases(page)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="case_brief.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("case_number", nargs="?", help="CRM ticket number (required unless --demo is used)")

    modes = parser.add_argument_group("modes")
    modes.add_argument("--demo", action="store_true", help="Use sample data, no network/API calls")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # case_number is only optional for --demo (fake data) -- the real
    # lookup always needs a ticket number. There is no ADO-only mode: ADO
    # results here are resolved from direct references found *in* the CRM
    # case text (see run_ado_lookup/_collect_reference_text), so without a
    # CRM lookup there is nothing to scan and the brief would always come
    # back empty -- skipping CRM was never actually a usable "ADO-only"
    # mode, just a flag that silently produced nothing.
    if not args.demo and not args.case_number:
        parser.error("case_number is required (pass a ticket number, or use --demo)")

    crm_results, branches, pull_requests, ado_error, ado_note = [], [], [], None, None

    try:
        if args.demo:
            progress("Loading demo data...", status="running")
            crm_results, branches, pull_requests = demo_data(args.case_number)
            progress_success("Demo data loaded")
        else:
            progress("Signing in to Dataverse (OAuth)...", status="running")
            crm_results = run_crm_lookup(args.case_number)
            progress_success("CRM data extracted", f"Found {len(crm_results)} cases")

            progress("Looking for direct Azure DevOps references in CRM...", status="running")
            try:
                branches, pull_requests, ado_error, ado_note = run_ado_lookup(crm_results)
            except Exception as e:
                # Always runs, never optional -- but must never take the
                # whole brief down with it. An expired/under-scoped PAT or
                # some other ADO-side failure here still means a CRM-only
                # brief gets written (with the failure noted in "## Related
                # Links" via ado_error), not a run that dies with nothing
                # written at all.
                branches, pull_requests, ado_error, ado_note = [], [], str(e), None
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
        # Image attachments only -- text ones are already inlined directly
        # into `markdown` above (see report._note_attachment_lines).
        attachments = report.collect_attachments(case_number, crm_results)
        progress_success("Brief markdown built")

        progress("Writing to file...", status="running")
        path = report.write_and_open(
            markdown,
            os.path.join(HERE, OUTPUT_DIR),
            case_number,
            attachments=attachments,
        )
        progress_success("Brief complete", f"Written to {path}")

    except Exception as e:
        progress_error("Brief generation failed", str(e))
        raise


if __name__ == "__main__":
    main()
