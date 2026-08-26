"""Renders the collected case data into a Markdown brief."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from shared.safe_name import safe_name as _safe_name


_MD_BLOCK_TRIGGER = re.compile(r"^(#{1,6}(\s|$)|[=\-_*]+$|>|```|~~~)")


def _sanitize_freetext_for_markdown(text):
    """Neutralize freeform text (e.g. a CRM ticket description) so it
    always renders as plain paragraphs, regardless of what a support
    agent typed or how CRM's rich-text-to-plain-text conversion
    punctuated it.

    Fixes two real, observed failure modes:
    1. CRM's blank-paragraph markers often come through as U+00A0
       (non-breaking space) rather than a truly empty line, which
       Markdown does NOT treat as a paragraph break - the whole
       run of text stays one unbroken paragraph.
    2. If that unbroken paragraph is then immediately followed by a line
       that's just dashes/equals (a support agent's own divider, or
       leftover HTML), Markdown reads it as a Setext heading underline
       and renders the *entire* paragraph as one giant <h1>/<h2> - this
       happened for real with a description ending in a lone "--" line.
    """
    if not text:
        return text
    out = []
    for line in text.split("\n"):
        # Anything left over is a paragraph break in spirit - normalize
        # to a real blank line so Markdown treats it as one. Explicit
        # chars, not str.strip()'s default: Python's default strip()
        # already treats \xa0 as whitespace (str.isspace() is True for
        # it), which would make an nbsp-only line strip down to "" and
        # get missed by an `if stripped:` check done *after* stripping.
        if not line.strip("\xa0 \t\r"):
            out.append("")
            continue
        stripped = line.strip()
        if _MD_BLOCK_TRIGGER.match(stripped):
            line = "\\" + stripped
        out.append(line)
    return "\n".join(out)


# Custom CRM fields surfaced as their own proper subsection right after
# Description, in this order, instead of getting buried in the generic
# "Other CRM Fields" dump at the bottom -- see build_markdown's
# `promoted_fields` param. Matched by logical_name (stable across a field's
# display label changing). Fixed here, not configurable -- case-brief has
# no config file (see case_brief.py's module docstring); a caller that
# needs a different set can still pass its own `promoted_fields` directly.
DEFAULT_PROMOTED_FIELDS = [
    "art_additionalpublicdescription",  # "Dodatečný veřejný popis" -- secondary/public
                                         # description; right after Description, before
                                         # the internal one
    "art_internaldescriptionandnotes",  # "Interní popis & poznámky"
]

# The case's own Helpdesk portal link. Rendered as the last entry in the
# "## Related Links" section (see _related_links_lines) rather than as one
# more text block under DEFAULT_PROMOTED_FIELDS -- it's a link, not prose --
# but still excluded from the "Other CRM Fields" catch-all the same way
# DEFAULT_PROMOTED_FIELDS is (see build_markdown).
HELPDESK_LINK_FIELD = "art_helpdesklink"

# Friendly labels for DEFAULT_PROMOTED_FIELDS, used only as a fallback when
# the field wasn't populated on this case (so it's missing from all_fields
# entirely -- crm_scrape._extract_all_fields drops None/"" values -- and
# there's no metadata-sourced label to fall back on). Keeps the "not filled
# in" line human-readable instead of printing the raw logical_name.
_PROMOTED_FIELD_FALLBACK_LABELS = {
    "art_additionalpublicdescription": "Dodatečný veřejný popis",
    "art_internaldescriptionandnotes": "Interní popis & poznámky",
}


def _join_and(items):
    """"a", "a and b", "a, b, and c" -- for folding several missing members
    of a section into one combined sentence instead of one line each."""
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _related_links_lines(ado_error, ado_note, branches, pull_requests,
                          related_links=None, related_links_error=None, helpdesk_link=None,
                          include_ado=True):
    """The '## Related Links' section's lines -- everything that points at
    outside work tied to this case: Azure DevOps branches/PRs resolved from
    a direct reference found in the CRM case, the case form's own Dev-tab
    "Related links" grid, and finally the case's own Helpdesk portal link
    (`helpdesk_link`, an optional {"label", "value"} dict -- see
    HELPDESK_LINK_FIELD), in that order, Helpdesk link last.

    Whatever was actually found (in any category) is listed as its own
    bullet; whichever categories came up empty (with no error -- an error
    already explains itself) are folded into one combined "_No X, Y, and Z
    found for this case._" line at the end, rather than a separate "not
    found" line per category.

    `include_ado` gates just the branches/PRs category. It's whole-run, not
    per-case (see build_markdown's `ado_rendered`) -- False skips rendering
    it a second time for a later case rather than reporting the *global*
    search's absence of branches/PRs as if it were empty for that case too.
    """
    lines = ["## Related Links"]
    missing = []

    if include_ado:
        if ado_error:
            lines.append(f"_Could not query Azure DevOps: {ado_error}_")
        else:
            if ado_note:
                lines.append(f"_{ado_note}_")
            for b in branches or []:
                lines.append(f"- [{b['project']}/{b['repo']}: {b['branch']}]({b['url']})")
            for pr in pull_requests or []:
                lines.append(f"- [{pr['project']}/{pr['repo']} !{pr['id']}]({pr['url']}) — {pr.get('title')} ({pr.get('status')}, by {pr.get('created_by') or '—'})")
            if not branches:
                missing.append("branches")
            if not pull_requests:
                missing.append("pull requests")

    if related_links_error:
        lines.append(f"_Could not load linked Azure DevOps items: {related_links_error}_")
    else:
        for link in related_links or []:
            label = link.get("name") or link.get("url") or "(unnamed link)"
            line = f"- [{label}]({link['url']})" if link.get("url") else f"- {label}"
            extra = " — ".join(x for x in [link.get("status"), link.get("created_on")] if x)
            if extra:
                line += f" ({extra})"
            lines.append(line)
        if not related_links:
            missing.append("related links")

    if helpdesk_link and helpdesk_link.get("value"):
        lines.append(f"- [{helpdesk_link.get('label') or 'Helpdesk link'}]({helpdesk_link['value']})")
    else:
        missing.append("a Helpdesk link")

    if missing:
        lines.append(f"_No {_join_and(missing)} found for this case._")

    return lines


def build_markdown(case_number, crm_results, branches, pull_requests,
                    ado_error=None, ado_note=None, promoted_fields=None):
    if promoted_fields is None:
        promoted_fields = DEFAULT_PROMOTED_FIELDS

    lines = [f"# Case {case_number}", ""]
    leftover_by_case = []  # [(case, [field, ...]), ...] -- rendered at the bottom, see below
    # branches/pull_requests are whole-run, not per-case -- attach them to
    # the first case's own "## Related Links" section rather than repeating
    # (or orphaning) them.
    ado_rendered = False

    if not crm_results:
        lines.append("_No CRM case data (CRM lookup was skipped or returned nothing)._")
    for c in crm_results:
        if c.get("error"):
            lines.append(f"- ⚠️ {c['error']} ({c.get('url')})")
            continue
        lines.append(f"### {c.get('title') or c.get('ticket_number') or c.get('id')}")
        lines.append(f"- **Ticket #:** {c.get('ticket_number') or '—'}")
        lines.append(f"- **Customer:** {c.get('customer') or '—'}")
        lines.append(f"- **Owner:** {c.get('owner') or '—'}")
        lines.append(f"- **Priority:** {c.get('priority') or '—'}")
        lines.append(f"- **Status:** {c.get('status') or '—'}")
        lines.append(f"- **Created:** {c.get('created_on') or '—'}")
        lines.append("")

        all_fields = c.get("all_fields") or []
        by_logical_name = {f["logical_name"]: f for f in all_fields}
        helpdesk_field = by_logical_name.get(HELPDESK_LINK_FIELD)

        # Pulled up here (right after the at-a-glance details, before the
        # wall of Description/Notes/Activity Timeline text in "## Details"
        # below) rather than buried after it.
        lines.extend(_related_links_lines(
            ado_error, ado_note, branches, pull_requests,
            related_links=c.get("related_links"),
            related_links_error=c.get("related_links_error"),
            helpdesk_link=helpdesk_field,
            include_ado=not ado_rendered,
        ))
        lines.append("")
        ado_rendered = True

        lines.append("## Details")
        lines.append("")
        lines.append("**Description:**")
        lines.append("")
        lines.append(_sanitize_freetext_for_markdown(c.get("description")) or "_(none)_")
        lines.append("")

        # Whichever of these optional Details members (promoted fields,
        # Notes, Activity Timeline) are actually empty (not errored -- an
        # error already explains itself) get folded into one combined "_No
        # X, Y, and Z found for this case._" line at the end of Details,
        # rather than a separate "(not filled in)"/"No notes on this
        # case."/"No activities recorded on this case." line each.
        missing_details = []

        for logical_name in promoted_fields:
            f = by_logical_name.get(logical_name)
            if f:
                lines.append(f"**{f['label']}:**")
                lines.append("")
                lines.append(_sanitize_freetext_for_markdown(str(f["value"])) or "_(none)_")
                lines.append("")
            else:
                missing_details.append(_PROMOTED_FIELD_FALLBACK_LABELS.get(logical_name, logical_name))

        # Helpdesk link is promoted into "## Related Links" above, not
        # rendered as a text block here -- excluded the same way
        # promoted_fields is, so it doesn't also show up in "Other CRM
        # Fields" at the bottom.
        excluded_fields = set(promoted_fields) | {HELPDESK_LINK_FIELD}
        leftover = [f for f in all_fields if f["logical_name"] not in excluded_fields]
        if leftover:
            leftover_by_case.append((c, leftover))

        if c.get("notes_error"):
            lines.append("**Notes:**")
            lines.append("")
            lines.append(f"_Could not load notes: {c['notes_error']}_")
            lines.append("")
        elif c.get("notes"):
            lines.append("**Notes:**")
            lines.append("")
            for n in c["notes"]:
                header = " — ".join(x for x in [n.get("created_on"), n.get("subject")] if x)
                lines.append(f"- {header or '(untitled note)'}")
                if n.get("text"):
                    lines.append("")
                    lines.append(_sanitize_freetext_for_markdown(n["text"]))
                if n.get("filename"):
                    lines.append(f"  _(attachment: {n['filename']})_")
                lines.append("")
            if c.get("notes_truncated"):
                lines.append("_Only the most recent notes are shown -- older ones were omitted._")
            lines.append("")
        else:
            missing_details.append("notes")

        if c.get("activities_error"):
            lines.append("**Activity Timeline:**")
            lines.append("")
            lines.append(f"_Could not load the activity timeline: {c['activities_error']}_")
            lines.append("")
        elif c.get("activities"):
            lines.append("**Activity Timeline:**")
            lines.append("")
            for a in c["activities"]:
                header = " — ".join(x for x in [a.get("created_on"), a.get("type"), a.get("subject")] if x)
                if a.get("status"):
                    header += f" ({a['status']})"
                lines.append(f"- {header or '(untitled activity)'}")
                if a.get("description"):
                    lines.append("")
                    lines.append(_sanitize_freetext_for_markdown(a["description"]))
                lines.append("")
            if c.get("activities_truncated"):
                lines.append("_Only the most recent activities are shown -- older ones were omitted._")
            lines.append("")
        else:
            missing_details.append("activity timeline entries")

        if missing_details:
            lines.append(f"_No {_join_and(missing_details)} found for this case._")
            lines.append("")
    lines.append("")

    # Fallback for when no case was actually rendered above (no CRM tab
    # open, or every crm_result errored) -- the section still needs to show
    # up somewhere rather than silently vanishing.
    if not ado_rendered:
        lines.extend(_related_links_lines(ado_error, ado_note, branches, pull_requests))
        lines.append("")

    if leftover_by_case:
        lines.append("## Other CRM Fields")
        lines.append("_Every other populated CRM field not already surfaced above -- uncurated, for the rare case "
                      "it has what you need. Each field's `logical_name` is shown so you can find one worth "
                      "promoting (see report.DEFAULT_PROMOTED_FIELDS) without having to guess it._")
        lines.append("")
        multiple_cases = len(leftover_by_case) > 1
        for c, leftover in leftover_by_case:
            if multiple_cases:
                lines.append(f"### {c.get('title') or c.get('ticket_number') or c.get('id')}")
            for f in leftover:
                lines.append(f"- **{f['label']}** (`{f['logical_name']}`): "
                              f"{_sanitize_freetext_for_markdown(str(f['value']))}")
            lines.append("")

    return "\n".join(lines)


def write_and_open(markdown, output_dir, case_number):
    os.makedirs(output_dir, exist_ok=True)
    filename = f"case-{_safe_name(case_number)}.md"
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)

    return path
