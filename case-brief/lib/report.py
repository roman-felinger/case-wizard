"""Renders the collected case data into a Markdown brief."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from shared.editor import open_in_editor
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
# display label changing), overridable via config.json's
# `crm_promoted_fields` (case_brief.py's DEFAULTS).
DEFAULT_PROMOTED_FIELDS = [
    "art_internaldescriptionandnotes",  # "Interní popis & poznámky"
    "art_additionalpublicdescription",  # "Dodatečný veřejný popis"
]


def _ado_section_lines(ado_error, ado_note, branches, pull_requests):
    """The '## Azure DevOps' section's lines, as its own helper so
    build_markdown can slot it in right after a case's core details (see the
    "pulled up to the details" placement below) instead of building it
    inline exactly where it prints."""
    lines = ["## Azure DevOps — Related Branches & Pull Requests"]
    if ado_error:
        lines.append(f"_Could not query Azure DevOps: {ado_error}_")
        return lines
    if ado_note:
        lines.append(f"_{ado_note}_")
        lines.append("")
    lines.append("**Branches:**")
    if not branches:
        lines.append("_No matching branches found._")
    else:
        for b in branches:
            lines.append(f"- [{b['project']}/{b['repo']}: {b['branch']}]({b['url']})")
    lines.append("")
    lines.append("**Pull requests:**")
    if not pull_requests:
        lines.append("_No matching pull requests found._")
    else:
        for pr in pull_requests:
            lines.append(f"- [{pr['project']}/{pr['repo']} !{pr['id']}]({pr['url']}) — {pr.get('title')} ({pr.get('status')}, by {pr.get('created_by') or '—'})")
    return lines


def build_markdown(case_number, crm_results, branches, pull_requests,
                    ado_error=None, ado_note=None, promoted_fields=None):
    if promoted_fields is None:
        promoted_fields = DEFAULT_PROMOTED_FIELDS

    lines = [f"# Case {case_number}", ""]
    leftover_by_case = []  # [(case, [field, ...]), ...] -- rendered at the bottom, see below
    ado_lines = _ado_section_lines(ado_error, ado_note, branches, pull_requests)
    ado_rendered = False  # the Azure DevOps section is whole-run, not per-case -- render it once

    if not crm_results:
        lines.append("_No CRM case tab found open in the automation Chrome window._")
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

        # Pulled up here (right after the at-a-glance details, before the
        # wall of Description/Notes/Activity Timeline text) rather than
        # buried after it, on the first case actually rendered.
        if not ado_rendered:
            lines.extend(ado_lines)
            lines.append("")
            ado_rendered = True

        lines.append("**Description:**")
        lines.append("")
        lines.append(_sanitize_freetext_for_markdown(c.get("description")) or "_(none)_")
        lines.append("")

        all_fields = c.get("all_fields") or []
        by_logical_name = {f["logical_name"]: f for f in all_fields}
        for logical_name in promoted_fields:
            f = by_logical_name.get(logical_name)
            if not f:
                continue
            lines.append(f"**{f['label']}:**")
            lines.append("")
            lines.append(_sanitize_freetext_for_markdown(str(f["value"])) or "_(none)_")
            lines.append("")

        leftover = [f for f in all_fields if f["logical_name"] not in promoted_fields]
        if leftover:
            leftover_by_case.append((c, leftover))

        lines.append("**Notes:**")
        lines.append("")
        if c.get("notes_error"):
            lines.append(f"_Could not load notes: {c['notes_error']}_")
        elif not c.get("notes"):
            lines.append("_No notes on this case._")
        else:
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

        lines.append("**Activity Timeline:**")
        lines.append("")
        if c.get("activities_error"):
            lines.append(f"_Could not load the activity timeline: {c['activities_error']}_")
        elif not c.get("activities"):
            lines.append("_No activities recorded on this case._")
        else:
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
    lines.append("")

    # Fallback for when no case was actually rendered above (no CRM tab
    # open, or every crm_result errored) -- the section still needs to show
    # up somewhere rather than silently vanishing.
    if not ado_rendered:
        lines.extend(ado_lines)
        lines.append("")

    if leftover_by_case:
        lines.append("## Other CRM Fields")
        lines.append("_Every other populated CRM field not already surfaced above -- uncurated, for the rare case "
                      "it has what you need._")
        lines.append("")
        multiple_cases = len(leftover_by_case) > 1
        for c, leftover in leftover_by_case:
            if multiple_cases:
                lines.append(f"### {c.get('title') or c.get('ticket_number') or c.get('id')}")
            for f in leftover:
                lines.append(f"- **{f['label']}:** {_sanitize_freetext_for_markdown(str(f['value']))}")
            lines.append("")

    return "\n".join(lines)


def write_and_open(markdown, output_dir, case_number, open_in_vscode=True):
    os.makedirs(output_dir, exist_ok=True)
    filename = f"case-{_safe_name(case_number)}.md"
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)

    if open_in_vscode:
        open_in_editor(path)

    return path
