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
# "Other Populated CRM Fields" dump at the bottom -- see build_markdown's
# `promoted_fields` param. Matched by logical_name (stable across a field's
# display label changing). Fixed here, not configurable -- case-brief has
# no config file (see case_brief.py's module docstring); a caller that
# needs a different set can still pass its own `promoted_fields` directly.
DEFAULT_PROMOTED_FIELDS = [
    "art_descriptionadditionalpublic",  # "Dodatečný veřejný popis" -- secondary/public
                                         # description; right after Description, before
                                         # the internal one
    "art_internaldescriptionandnotes",  # "Interní popis & poznámky"
]

# The case's own Helpdesk portal link. Rendered as the last entry in the
# "## Related Links" section (see _related_links_lines) rather than as one
# more text block under DEFAULT_PROMOTED_FIELDS -- it's a link, not prose --
# but still excluded from the "Other Populated CRM Fields" catch-all the same way
# DEFAULT_PROMOTED_FIELDS is (see build_markdown).
HELPDESK_LINK_FIELD = "art_helpdesklink"

# The case form's own "Estimate & Totals" widget -- exactly these four
# values (Estimate, Billable Hours, Non-Billable Hours, Total Hours), in
# this order, get pulled into their own "## Estimates & Totals" subsection
# placed last, right before "Other Populated CRM Fields" -- real info, but low
# priority to read. A fixed curated set, not a broad "any field whose
# label contains total/estimate" heuristic -- that swept in noise the
# widget itself doesn't show (kilometers, price, dispatch counts, an
# approver lookup, a rollup's own "last updated"/"status" metadata
# fields). Matched by *label*, not logical_name like DEFAULT_PROMOTED_FIELDS
# -- these are org rollup/calculated fields whose logical names aren't
# known ahead of time the way a handful of hand-picked promoted fields'
# are. Each matcher is a case-insensitive substring/equality check against
# the metadata-sourced label, tolerant of the label's exact Czech word
# order varying between what the case form displays and what the
# EntityDefinitions metadata call returns for the same field (observed:
# "Fakturované hodiny celkem" on the form vs. "Celkem fakturované hodiny"
# from metadata).
def _is_rollup_metadata_label(lowered):
    # A rollup field's own calculation-status/last-run-date sub-field
    # (e.g. "Total Billable Hours (stav)"/"... (datum poslední
    # aktualizace)") -- metadata about the value, not the value itself.
    return "(stav)" in lowered or "aktualizace" in lowered


# Match-precedence order -- "nefakturovan..." contains "fakturovan..." as
# a substring, so Non-Billable must be checked before Billable, and both
# must be checked before the bare "hodin..." (hours) catch-all that Total
# Hours uses so it doesn't also claim the billable/non-billable hour
# fields (which mention "hodiny" too).
_ESTIMATE_FIELD_MATCHERS = [
    ("Estimate", lambda l: l in ("odhad", "estimate")),
    ("Non-Billable Hours", lambda l: "nefakturovan" in l or "non-billable" in l or "non billable" in l),
    ("Billable Hours", lambda l: "fakturovan" in l or "billable" in l),
    ("Total Hours", lambda l: "hodin" in l or l in ("total hours", "hours total")),
]

# Display order in the rendered "## Estimates & Totals" section -- matches
# the case form's own "Estimate & Totals" widget top-to-bottom, not the
# match-precedence order above. All four are always listed for a case that
# has any of them at all (see build_markdown), even ones that came up
# empty on this particular case -- an unset Estimate is still worth
# knowing is unset, not silently absent from the section.
_ESTIMATE_CATEGORY_ORDER = ["Estimate", "Billable Hours", "Non-Billable Hours", "Total Hours"]


def _classify_estimate_field(label):
    """Which of the four "## Estimates & Totals" categories this field's
    label belongs to, or None if it's not one of them -- see
    _ESTIMATE_FIELD_MATCHERS."""
    lowered = (label or "").strip().lower()
    if _is_rollup_metadata_label(lowered):
        return None
    for category, matches in _ESTIMATE_FIELD_MATCHERS:
        if matches(lowered):
            return category
    return None

# English labels for DEFAULT_PROMOTED_FIELDS, used in place of whatever
# label the CRM metadata call returns for these two fields (Czech on this
# org: "Dodatečný veřejný popis" / "Interní popis & poznámky") -- both for
# the field's own "**Label:**" header when it's populated, and as the name
# used in Details' combined "missing" line when it isn't (there's no
# metadata-sourced label to fall back on in that case, since the field is
# simply absent from all_fields -- crm_scrape._extract_all_fields drops
# None/"" values).
_PROMOTED_FIELD_ENGLISH_LABELS = {
    "art_descriptionadditionalpublic": "Additional Public Description",
    # Not "Internal Description & Notes" -- that reads as one combined item
    # with the case's own Notes (the activity/annotation notes rendered
    # separately below, see missing_details.append("Notes")), when they're
    # two distinct things that happen to sit next to each other in the same
    # combined "missing" line.
    "art_internaldescriptionandnotes": "Internal Description",
}


def _format_bytes(size):
    """1536 -> "1.5 KB". Used only for the attachment-size hint next to a
    note's filename -- doesn't need to be exact, just readable."""
    if not size:
        return None
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024


def _attachment_relative_path(case_number, note):
    """Where a note's inlined *image* attachment gets saved on disk,
    relative to the brief's own output_dir -- a pure function of
    case_number + the note, computed identically here (for the Markdown
    image link build_markdown renders) and in collect_attachments (for the
    actual file write_and_open persists), so the two always agree without
    needing to share mutable state.

    Prefixed with the note's own annotation id (first 8 chars) so two
    different notes attaching a same-named file (e.g. two separate
    "screenshot.png") don't collide on disk.
    """
    safe_case = _safe_name(case_number)
    note_id = (note.get("id") or "")[:8]
    safe_file = _safe_name(note.get("filename") or "attachment")
    prefix = f"{note_id}-" if note_id else ""
    return f"attachments/{safe_case}/{prefix}{safe_file}"


def _note_attachment_lines(case_number, n):
    """Renders one note's attached file. Three cases, depending on what
    crm_scrape._fetch_inlinable_attachments managed to fetch for it:

    - A small text-like file: inlined directly as a fenced code block --
      genuinely useful for a person *and* for case-guide's LLM prompt to
      read, since the whole brief is plain text anyway.
    - A small image: saved to disk by write_and_open/collect_attachments
      and linked with a normal Markdown image tag (a relative path, so it
      renders in any Markdown viewer). NOT inlined as a base64 data URI --
      that would bloat the brief file and add pure noise tokens to
      case-guide's text-only `claude -p` call, which can't actually "see"
      an image in its prompt text anyway; a real file next to the brief is
      useful to the *human* reading it, which a giant base64 blob is not.
    - Anything else (too large, or a type this brief has no useful way to
      show inline -- PDF, zip, docx, ...): just named, same as before this
      feature existed -- open it from CRM instead.
    """
    size_note = f" ({_format_bytes(n.get('filesize'))})" if n.get("filesize") else ""
    header = f"  _(attachment: {n['filename']}{size_note})_"
    attachment = n.get("attachment")

    if attachment and attachment.get("kind") == "text":
        lines = [header, "", "```", attachment["content"], "```"]
        if attachment.get("truncated"):
            lines.append("_(attachment truncated -- see the full file in CRM)_")
        return lines

    if attachment and attachment.get("kind") == "image":
        rel = _attachment_relative_path(case_number, n)
        return [header, "", f"![{n['filename']}]({rel})"]

    return [f"  _(attachment: {n['filename']}{size_note} — not included in this brief, see CRM)_"]


def collect_attachments(case_number, crm_results):
    """Image attachments (crm_scrape.get_notes' note["attachment"]) that
    need saving to disk alongside the brief, for _attachment_relative_path's
    Markdown image links (see _note_attachment_lines) to resolve. Text
    attachments need no separate file -- they're inlined directly into the
    Markdown itself.

    Returns [{"relative_path": ..., "bytes": ...}, ...], ready for
    write_and_open to persist under the brief's own output_dir.
    """
    attachments = []
    for c in crm_results or []:
        if c.get("error"):
            continue
        for n in c.get("notes") or []:
            att = n.get("attachment")
            if att and att.get("kind") == "image":
                attachments.append({
                    "relative_path": _attachment_relative_path(case_number, n),
                    "bytes": att["bytes"],
                })
    return attachments


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
                          case_url=None, include_ado=True):
    """The '## Related Links' section's lines -- the case's own CRM record
    link (`case_url`) and its Helpdesk portal link (`helpdesk_link`, an
    optional {"label", "value"} dict -- see HELPDESK_LINK_FIELD) first,
    since those two are always available on a real case; then the
    optional, may-or-may-not-exist stuff -- the case form's own Dev-tab
    "Related links" grid, then Azure DevOps branches/PRs resolved from a
    direct reference found elsewhere in the CRM case (description/notes/
    fields/activities -- NOT the Dev-tab grid, which is already covered by
    the related_links bullets above it; see case_brief.py's
    run_ado_lookup/_related_link_refs, which excludes anything already
    covered by related_links before it ever reaches here, so the same PR/
    branch never gets linked twice).

    Whatever was actually found is listed as its own bullet -- a related
    link or Helpdesk link's own label as plain text with the URL itself as
    the hyperlink (so it's both clickable and readable/copyable without
    clicking through, rather than a descriptive label hiding the URL from
    view). Neither `case_url` nor `helpdesk_link` is ever reported as
    "missing" when absent -- they're always-available intrinsic details of
    the case record, not an optional related resource that may or may not
    exist. Branches/PRs aren't reported as missing either, even when
    genuinely empty -- unlike related_links (still folded into a "_No
    linked Azure DevOps items found for this case._" line when empty, with
    no error), a case simply not having referenced its own work yet isn't
    worth a dedicated "not found" callout every time.

    `include_ado` gates just the branches/PRs category. It's whole-run, not
    per-case (see build_markdown's `ado_rendered`) -- False skips rendering
    it a second time for a later case rather than reporting the *global*
    search's absence of branches/PRs as if it were empty for that case too.
    """
    lines = ["## Related Links"]

    if case_url:
        # Label is plain text, URL is the hyperlink -- same reasoning as
        # the related-links/Helpdesk-link bullets below.
        lines.append(f"- Case link: [{case_url}]({case_url})")

    if helpdesk_link and helpdesk_link.get("value"):
        url = helpdesk_link["value"]
        lines.append(f"- {helpdesk_link.get('label') or 'Helpdesk link'}: [{url}]({url})")

    missing = []
    if related_links_error:
        lines.append(f"_Could not load linked Azure DevOps items: {related_links_error}_")
    else:
        for link in related_links or []:
            label = link.get("name") or link.get("url") or "(unnamed link)"
            url = link.get("url")
            # No status/created-on extra here -- often stale (CRM's own
            # snapshot from whenever the link was attached, not refreshed
            # since), unlike the ADO-resolved branches/PRs below which
            # fetch it live.
            lines.append(f"- {label}: [{url}]({url})" if url else f"- {label}")
        if not related_links:
            # Named distinctly from the section's own "Related Links"
            # heading -- and from the Helpdesk link, which is itself
            # rendered in this same section -- so this line never reads as
            # "no related links" while a Helpdesk link bullet sits right
            # above it. This specifically means the CRM case form's own
            # Dev-tab grid (crm_scrape.get_related_links), not the section
            # as a whole.
            missing.append("linked Azure DevOps items")

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

    if missing:
        lines.append(f"_No {_join_and(missing)} found for this case._")

    return lines


def build_markdown(case_number, crm_results, branches, pull_requests,
                    ado_error=None, ado_note=None, promoted_fields=None):
    if promoted_fields is None:
        promoted_fields = DEFAULT_PROMOTED_FIELDS

    lines = [f"# Case {case_number}", ""]

    # Hidden marker recording the CRM record's own last-modified timestamp
    # as of this brief's generation -- invisible in any Markdown viewer (an
    # HTML comment), not part of the rendered brief. Read back by
    # case-getter to detect a brief gone stale: if a later CRM listing
    # shows a newer modifiedon than what's stamped here, the case changed
    # since this brief was written. Only one marker per file, taken from
    # the first successfully-looked-up case -- in practice a brief is
    # always exactly one case (case-brief only ever looks up one ticket
    # number at a time).
    first_modified_on = next(
        (c.get("modified_on") for c in crm_results if not c.get("error") and c.get("modified_on")), None,
    )
    if first_modified_on:
        lines.append(f"<!-- case-brief:crm-modified-on={first_modified_on} -->")
        lines.append("")

    leftover_by_case = []  # [(case, [field, ...]), ...] -- rendered at the bottom, see below
    estimates_by_case = []  # [(case, {category: field}), ...], rendered just above leftover_by_case -- see _classify_estimate_field
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
            case_url=c.get("url"),
            include_ado=not ado_rendered,
        ))
        lines.append("")
        ado_rendered = True

        lines.append("## Details")
        lines.append("")

        # Whichever of these optional Details members (Description,
        # promoted fields, Notes, Activity Timeline) are actually empty
        # (not errored -- an error already explains itself) get folded into
        # one combined "_No X, Y, and Z found for this case._" line at the
        # end of Details, rather than a separate "_(none)_"/"(not filled
        # in)"/"No notes on this case." line each.
        missing_details = []

        description = c.get("description")
        if description:
            lines.append("**Description:**")
            lines.append("")
            lines.append(_sanitize_freetext_for_markdown(description))
            lines.append("")
        else:
            missing_details.append("Description")

        for logical_name in promoted_fields:
            f = by_logical_name.get(logical_name)
            english_label = _PROMOTED_FIELD_ENGLISH_LABELS.get(logical_name)
            if f:
                lines.append(f"**{english_label or f['label']}:**")
                lines.append("")
                lines.append(_sanitize_freetext_for_markdown(str(f["value"])) or "_(none)_")
                lines.append("")
            else:
                missing_details.append(english_label or logical_name)

        # Helpdesk link is promoted into "## Related Links" above, not
        # rendered as a text block here -- excluded the same way
        # promoted_fields is, so it doesn't also show up in "Other
        # Populated CRM Fields" at the bottom.
        excluded_fields = set(promoted_fields) | {HELPDESK_LINK_FIELD}
        leftover = [f for f in all_fields if f["logical_name"] not in excluded_fields]
        # Pull the four "## Estimates & Totals" fields out into their own
        # bucket (rendered below, in fixed display order) before whatever
        # remains lands in the uncurated "Other Populated CRM Fields" dump. At most
        # one field per category -- first match wins if a case somehow has
        # more than one field classifying the same way.
        by_category = {}
        for f in leftover:
            category = _classify_estimate_field(f.get("label"))
            if category and category not in by_category:
                by_category[category] = f
        if by_category:
            estimates_by_case.append((c, by_category))
            matched_names = {f["logical_name"] for f in by_category.values()}
            leftover = [f for f in leftover if f["logical_name"] not in matched_names]
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
                    lines.extend(_note_attachment_lines(case_number, n))
                lines.append("")
            if c.get("notes_truncated"):
                lines.append("_Only the most recent notes are shown -- older ones were omitted._")
            lines.append("")
        else:
            missing_details.append("Notes")

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
            missing_details.append("Activity Timeline")

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

    if estimates_by_case:
        lines.append("## Estimates & Totals")
        lines.append("")
        multiple_estimate_cases = len(estimates_by_case) > 1
        for c, by_category in estimates_by_case:
            if multiple_estimate_cases:
                lines.append(f"### {c.get('title') or c.get('ticket_number') or c.get('id')}")
            for category in _ESTIMATE_CATEGORY_ORDER:
                # All four always listed, even when this particular one
                # wasn't populated on this case (crm_scrape drops empty/
                # None fields before they ever reach here, so a genuinely
                # unset Estimate simply never shows up in by_category) --
                # an em dash, same convention as the at-a-glance details
                # above, rather than silently dropping the line.
                f = by_category.get(category)
                value = _sanitize_freetext_for_markdown(str(f["value"])) if f else "—"
                lines.append(f"- **{category}:** {value}")
            lines.append("")

    if leftover_by_case:
        lines.append("## Other Populated CRM Fields")
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


def write_and_open(markdown, output_dir, case_number, attachments=None):
    """Writes the brief itself, then any image attachments (collect_attachments)
    alongside it under output_dir/attachments/<case>/ -- each entry's
    "relative_path" already includes that prefix (see
    _attachment_relative_path), so this just joins it onto output_dir and
    makes whatever subdirectories are needed."""
    os.makedirs(output_dir, exist_ok=True)
    filename = f"brief-{_safe_name(case_number)}.md"
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)

    for att in attachments or []:
        att_path = os.path.join(output_dir, att["relative_path"])
        os.makedirs(os.path.dirname(att_path), exist_ok=True)
        with open(att_path, "wb") as f:
            f.write(att["bytes"])

    return path
