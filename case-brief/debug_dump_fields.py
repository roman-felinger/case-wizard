#!/usr/bin/env python3
"""One-off diagnostic: dump every raw field Dataverse actually returns for a
case, with NONE of case_brief's filtering/labeling applied.

Why this exists: case_brief.py's crm_scrape.lookup_by_ticket already fetches
the incident record with no $select (so Dataverse returns every attribute),
but a specific custom field -- e.g. an "Internal Description" field that's
only visible on the CRM form behind a toggle -- has been reported missing
from a generated brief. This script isolates the raw Dataverse response from
all of case_brief's later filtering (_IGNORE_FIELDS, _SUMMARY_FIELDS, the
empty-value skip, memo/HTML stripping) so we can tell whether:

  (a) the field IS in the raw API response and something downstream in
      lib/crm_scrape.py._extract_all_fields is dropping/hiding it, or
  (b) the field is NOT in the raw API response at all -- e.g. field-level
      security, it lives on a different entity, or it's a control type the
      Web API doesn't expose as a plain attribute.

Usage (from case-brief/, same setup as case_brief.py -- needs the automation
Chrome profile with a CRM tab open and signed in):

    python debug_dump_fields.py T2611845
    python debug_dump_fields.py T2611845 --grep intern      # only print keys containing "intern"
    python debug_dump_fields.py T2611845 --grep popis        # Czech: "popis" = "description"

Prints every key/value Dataverse returned for the matched incident, then a
second pass showing exactly which of those _extract_all_fields would keep vs.
drop and why -- so if the field IS present raw but missing from the brief,
this points at the exact filter responsible.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import browser, crm_scrape


def dump_raw_record(page, ticket_number, ticket_field):
    import re
    origin = re.match(r"(https?://[^/]+)", page.url).group(1)
    escaped = ticket_number.replace("'", "''")
    api_url = f"{origin}/api/data/v9.2/incidents?$filter={ticket_field} eq '{escaped}'&$top=1"
    result = page.evaluate(crm_scrape._FETCH_JS, api_url)
    if result.get("__error"):
        raise RuntimeError(result["__error"])
    values = result.get("value", [])
    if not values:
        raise RuntimeError(f"No case found with {ticket_field} = '{ticket_number}'.")
    return origin, values[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_number", help="CRM ticket number")
    parser.add_argument("--ticket-field", default="ticketnumber")
    parser.add_argument("--grep", default=None, help="Only print raw keys containing this substring (case-insensitive)")
    parser.add_argument("--chrome-port", type=int, default=9222)
    args = parser.parse_args()

    port, _ = browser.ensure_chrome({"debug_port": args.chrome_port}, visible=True)
    pw, pages = browser.get_pages(port)
    try:
        auth_tabs = crm_scrape.find_authenticated_tabs(pages, ["dynamics.com"])
        auth_tab = next((t for t in auth_tabs if crm_scrape.is_authenticated(t)), None)
        if not auth_tab:
            print("No authenticated CRM tab found -- open/sign into a CRM tab in the automation Chrome window first.", file=sys.stderr)
            sys.exit(1)

        origin, raw = dump_raw_record(auth_tab, args.case_number, args.ticket_field)
        labels, memo_fields = crm_scrape.get_attribute_metadata(auth_tab, origin)
    finally:
        browser.close(pw)

    print(f"\n=== RAW keys Dataverse returned for {args.case_number} ({len(raw)} total) ===")
    for key in sorted(raw.keys()):
        if args.grep and args.grep.lower() not in key.lower():
            continue
        print(f"  {key!r}: {raw[key]!r}")

    print(f"\n=== What lib/crm_scrape.py's _extract_all_fields would keep/drop ===")
    fields = crm_scrape._extract_all_fields(raw, labels, memo_fields)
    kept_logical = {f["logical_name"] for f in fields}
    for key in sorted(raw.keys()):
        if "@" in key:
            continue
        logical = key[1:-len("_value")] if key.startswith("_") and key.endswith("_value") else key
        if args.grep and args.grep.lower() not in logical.lower():
            continue
        if logical in crm_scrape._IGNORE_FIELDS:
            reason = "dropped: in _IGNORE_FIELDS"
        elif logical in crm_scrape._SUMMARY_FIELDS:
            reason = "dropped: in _SUMMARY_FIELDS (shown elsewhere in the brief)"
        elif logical in kept_logical:
            kept = next(f for f in fields if f["logical_name"] == logical)
            reason = f"KEPT as {kept['label']!r} = {kept['value']!r}"
        else:
            reason = "dropped: empty/None value"
        print(f"  {logical}: {reason}")

    print(f"\n=== Attribute metadata (labels) fetched for 'incident' entity ===")
    if args.grep:
        for logical, label in labels.items():
            if args.grep.lower() in logical.lower() or args.grep.lower() in label.lower():
                print(f"  {logical} -> {label!r} (memo: {logical in memo_fields})")
    else:
        print(f"  ({len(labels)} labels fetched -- pass --grep to filter)")


if __name__ == "__main__":
    main()
