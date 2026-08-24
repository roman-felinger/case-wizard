#!/usr/bin/env python3
"""One-off diagnostic: automatically finds which Dataverse Web API call the
CRM case FORM makes to populate a custom panel/subgrid (e.g. the "Dev" tab's
"Související odkazy" / "Related links" list showing linked Azure DevOps PRs)
-- instead of manually hunting through DevTools' Network tab.

Why this exists: case_brief.py's crm_scrape.py only reads the incident
record itself, its notes (annotations), and its activity timeline
(activitypointers). A case can have other data -- shown in the CRM UI via a
custom subgrid/PCF control bound to some OTHER entity -- that none of those
three cover. This script reloads the case page you already have open,
captures every Dataverse Web API (/api/data/v9.*/) response fired during
that reload (which includes whatever custom control populates that panel),
and flags any whose response body actually contains an Azure DevOps URL or
the word "pullrequest" -- i.e., the exact API call we're hunting for.

Usage (from case-brief/, same setup as case_brief.py -- needs the automation
Chrome profile with the case already open and signed in, ideally with the
panel/tab that shows the PR links actually visible/expanded so it's forced
to load during the reload):

    python debug_capture_pr_links.py
    python debug_capture_pr_links.py --wait 12       # slow-loading PCF controls
    python debug_capture_pr_links.py --grep azure     # custom search term instead of the PR-link default
    python debug_capture_pr_links.py --all            # dump every non-noise api/data call, not just PR-flagged ones

Prints, for each flagged response: the request URL (this IS the entity set /
endpoint case_brief.py would need to call directly) and the response body
(pretty-printed if it's JSON) so you can see the entity/field shape too.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import browser, crm_scrape

# Endpoints case_brief.py already knows about -- not interesting here even
# though they're real Web API traffic, since we're hunting for what's NOT
# already covered by crm_scrape.py's incident/annotation/activitypointer reads.
_KNOWN_NOISE = ("/api/data/v9", )  # refined below (still shown under --all, just deprioritized)
_KNOWN_ENTITY_NOISE = ("incidents", "annotations", "activitypointers", "$metadata", "entitydefinitions")

DEFAULT_GREP_TERMS = ("dev.azure.com", "visualstudio.com", "pullrequest", "pull_request", "/_git/")


def capture_api_calls(page, wait_seconds):
    calls = []

    def on_response(resp):
        url = resp.url
        if "/api/data/v9" not in url:
            return
        body = None
        try:
            body = resp.text()
        except Exception as e:
            body = f"<could not read body: {e}>"
        calls.append({"url": url, "status": resp.status, "body": body})

    page.on("response", on_response)
    print(f"Reloading {page.url} to capture every Web API call it makes...")
    page.reload(wait_until="networkidle")
    # networkidle fires on the base page load -- custom PCF controls/subgrids
    # (exactly what we're hunting for) often fetch their own data a beat
    # later, so keep listening a bit longer.
    time.sleep(wait_seconds)
    page.remove_listener("response", on_response)
    return calls


def is_known_noise(url):
    low = url.lower()
    return any(e in low for e in _KNOWN_ENTITY_NOISE)


def matches_grep(call, terms):
    haystack = (call["url"] + " " + (call["body"] or "")).lower()
    return any(t.lower() in haystack for t in terms)


def pretty(body):
    try:
        return json.dumps(json.loads(body), indent=2, ensure_ascii=False)[:4000]
    except (json.JSONDecodeError, TypeError):
        return (body or "")[:2000]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chrome-port", type=int, default=9222)
    parser.add_argument("--wait", type=float, default=8, help="Extra seconds to keep listening after the page reports networkidle (default: 8)")
    parser.add_argument("--grep", action="append", dest="grep_terms", help="Custom term(s) to flag on, repeatable (default: Azure DevOps URL/PR patterns)")
    parser.add_argument("--all", action="store_true", help="Also print every other non-noise api/data call, not just flagged ones")
    args = parser.parse_args()
    grep_terms = args.grep_terms or list(DEFAULT_GREP_TERMS)

    port, _ = browser.ensure_chrome({"debug_port": args.chrome_port}, visible=True)
    pw, pages = browser.get_pages(port)
    try:
        auth_tabs = crm_scrape.find_authenticated_tabs(pages, ["dynamics.com"])
        page = next((t for t in auth_tabs if crm_scrape.is_authenticated(t)), None)
        if not page:
            print("No authenticated CRM tab found -- open the case (with the panel you care about visible) in the automation Chrome window first.", file=sys.stderr)
            sys.exit(1)

        calls = capture_api_calls(page, args.wait)
    finally:
        browser.close(pw)

    flagged = [c for c in calls if not is_known_noise(c["url"]) and matches_grep(c, grep_terms)]
    other = [c for c in calls if not is_known_noise(c["url"]) and c not in flagged]

    print(f"\n=== {len(calls)} total api/data call(s) captured ===")

    if flagged:
        print(f"\n=== {len(flagged)} call(s) matching {grep_terms} -- this is likely what you need ===")
        for c in flagged:
            print(f"\n--- {c['status']} {c['url']} ---")
            print(pretty(c["body"]))
    else:
        print(f"\nNo call matched {grep_terms}. Either the panel didn't reload in time (try --wait 15), "
              f"or it doesn't go through the Web API the way expected (e.g. a Power Automate/plugin-rendered "
              f"iframe) -- see the full list below and eyeball it, or re-run with --all.")

    if args.all or not flagged:
        print(f"\n=== {len(other)} other non-noise api/data call(s) (urls only; add --all body dump not included here to keep this short) ===")
        for c in other:
            print(f"  {c['status']} {c['url']}")


if __name__ == "__main__":
    main()
