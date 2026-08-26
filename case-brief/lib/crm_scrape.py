"""Reads a Dynamics 365 CRM case via the Dataverse Web API, given a `page`
object exposing exactly `.url` and `.evaluate(js, arg)` -- in production
that's lib/dataverse_page.py's DataverseApiPage, backed by a real OAuth
(Entra ID) access token (see lib/dataverse_auth.py; no admin app
registration needed -- see CLAUDE.md's Dataverse API section). Deliberately
written against that narrow, transport-agnostic interface rather than a
concrete client, which is what let auth swap from an earlier
browser-cookie-riding implementation to OAuth without changing a line of
this file -- see CLAUDE.md's "Removed in the 2026-08-26 Dataverse API
migration" section for that history.

Always looked up by ticket number (lookup_by_ticket).

Scrapes everything on the case, not a curated subset:
  - Every populated attribute on the incident record itself (no $select at
    all -- Dataverse returns the full record when it's omitted), labeled
    with the entity's real display names via a best-effort metadata lookup.
    This is deliberate: a fixed $select list silently drops anything not on
    it (that's how an org's "internal description"-style custom field went
    missing before), and there's no way to know every org's custom fields
    in advance.
  - Notes and the Activity Timeline (phone calls, emails, tasks, ...), which
    the case *page* shows but which live in separate Dataverse entities
    (`annotation` / `activitypointer`) rather than on the incident record.
  - The case page's "Dev" tab "Related links" grid (linked Azure DevOps
    PRs/branches a support engineer attached directly, not just pasted into
    free text) -- see RELATED_LINKS_NAV_PROPERTY below.
"""
import base64
import html
import re

SELECT_NONE = None  # no $select -- see module docstring; kept as a name so
                     # "we deliberately don't restrict this" is greppable.

_FETCH_JS = """async (url) => {
    try {
        const resp = await fetch(url, {
            credentials: 'include',
            headers: {
                'Accept': 'application/json',
                'OData-MaxVersion': '4.0',
                'OData-Version': '4.0',
                'Prefer': 'odata.include-annotations="*"'
            }
        });
        if (!resp.ok) { return { __error: `HTTP ${resp.status}: ${(await resp.text()).slice(0, 300)}` }; }
        return await resp.json();
    } catch (e) { return { __error: String(e) }; }
}"""

_FORMATTED_SUFFIX = "@OData.Community.Display.V1.FormattedValue"

# Curated fields already surfaced at the top level of the result dict (see
# _to_result) -- excluded from "all_fields" so they don't show up twice.
_SUMMARY_FIELDS = {
    "incidentid", "title", "ticketnumber", "prioritycode", "statuscode",
    "createdon", "modifiedon", "description", "customerid", "ownerid",
}

# Pure Dataverse/DB plumbing that's never meaningful case content -- kept
# short and deliberately: "get everything" should still mean "everything a
# person would recognize as part of the case", not raw replication metadata.
_IGNORE_FIELDS = {
    "versionnumber", "timezoneruleversionnumber", "importsequencenumber",
    "entityimage", "entityimage_url", "entityimage_timestamp",
    "overriddencreatedon", "utcconversiontimezonecode",
}

_HTML_TAG_RE = re.compile(r"<[a-zA-Z/][^>]*>")

# Matches a whole <a href="...">text</a> anchor so _strip_html can keep the
# URL instead of throwing it away with the rest of the markup. This matters
# beyond readability: case_brief.py's _collect_reference_text/
# ado_api.parse_direct_references scan this same stripped text for pasted
# Azure DevOps PR/branch links, and a rich-text hyperlink (e.g. a PR link
# pasted from Outlook, or CRM's own "Web Portal Link") is exactly that --
# an <a> tag whose visible text has no URL in it at all. Losing the href
# here means the link is gone by the time it reaches that scan, not just
# hidden from the human reading the brief.
_A_TAG_RE = re.compile(r'(?is)<a\b[^>]*\bhref=["\']([^"\']*)["\'][^>]*>(.*?)</a>')

# origin -> (labels: {logical_name: display_label}, memo_fields: {logical_name, ...})
# Metadata doesn't change within a run, so this is fetched once per origin.
# Exposed via reset_metadata_cache() so tests (or a long-lived process
# talking to more than one org) aren't stuck with a stale/fake entry.
_METADATA_CACHE = {}

NOTES_TOP = 100
ACTIVITIES_TOP = 50

# A note's attached file (Dataverse's `annotation.documentbody`, base64) is
# only actually fetched/inlined into the brief when it's both small and a
# type the brief can do something useful with -- everything else stays a
# named-but-not-fetched reference, same as before this existed, so one huge
# log dump or a handful of PDFs/zips attached to a case doesn't balloon
# either the API traffic or the brief itself. See _fetch_inlinable_attachments.
ATTACHMENT_MAX_FETCH_BYTES = 3_000_000  # ~3 MB -- comfortably covers a screenshot or a log
ATTACHMENT_TEXT_MAX_CHARS = 20_000      # inlined text is read by a person *and* fed into
                                         # case-guide's LLM prompt -- capped well below the
                                         # fetch cap itself, which just bounds the download
_INLINABLE_TEXT_MIME_PREFIXES = ("text/", "application/json", "application/xml")
_INLINABLE_IMAGE_MIME_PREFIXES = ("image/",)

# The incident form's "Dev" tab "Related links" grid (e.g. a linked Azure
# DevOps PR/branch) -- a plain custom entity/relationship, not documented or
# discoverable from the incident record itself. Schema found via a live
# investigation against a real case (2026-08-26; see CLAUDE.md's case-brief
# section for how). Fetched via $expand on the incident record (get_related_links)
# rather than a separate $filter query against art_relatedlinks' own entity set,
# since $expand is what that investigation actually confirmed works -- and it
# sidesteps ever needing art_relatedlinks' entity-set name or its lookup
# attribute back to incident, only this relationship's navigation property name.
RELATED_LINKS_NAV_PROPERTY = "art_relatedlinks_Incident_Incident"

# The org's model-driven Customer Service app id -- included in the case
# record's own deep link (see _to_result) so it opens directly in that app
# instead of Dynamics falling back to a default (or prompting to pick one).
CRM_APP_ID = "a192020e-f294-ed11-aad1-000d3a2cc485"

# Every new case is created owned by this team until a human picks it up --
# confirmed live 2026-08-26 (see CLAUDE.md's case-getter section): a sample
# of currently-active cases still owned by it were all genuinely unclaimed
# ("Nový"/New status, no other owner ever assigned). Resolved to a GUID at
# runtime by name (see _resolve_team_id) rather than hardcoded like
# CRM_APP_ID above, so recreating the team in this org doesn't need a code
# change here too.
DEFAULT_UNASSIGNED_TEAM_NAME = "Helpdesk e-mail"

# Cap on how many unassigned cases list_new_cases considers at once -- same
# "signal a partial result, don't silently truncate" pattern as
# NOTES_TOP/ACTIVITIES_TOP.
NEW_CASES_TOP = 200


def reset_metadata_cache():
    _METADATA_CACHE.clear()


def _replace_anchor(m):
    """<a href="URL">text</a> -> "text (URL)" so the URL survives _strip_html
    instead of being discarded with the rest of the tag. See _A_TAG_RE."""
    href, inner = html.unescape(m.group(1)).strip(), m.group(2)
    inner_text = re.sub(r"<[^>]+>", "", inner).strip()  # drop nested tags (e.g. <span>) from the anchor text
    if not href or href.lower().startswith("mailto:"):
        return inner_text
    if href in inner_text:
        return inner_text
    return f"{inner_text} ({href})" if inner_text else href


def _strip_html(text):
    if not text:
        return text
    text = _A_TAG_RE.sub(_replace_anchor, text)
    text = re.sub(r"(?i)<div[^>]*>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<p[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_like_html(text):
    return bool(text) and bool(_HTML_TAG_RE.search(text))


def _fetch(page, url):
    """Runs the shared in-page fetch and returns (data, error) -- error is
    None on success, else a short message. Every call site already has to
    treat `{"__error": ...}` as a real failure rather than case data; this
    keeps that check in one place instead of repeating it everywhere."""
    result = page.evaluate(_FETCH_JS, url)
    if result.get("__error"):
        return None, result["__error"]
    return result, None


def get_attribute_metadata(page, origin):
    """Best-effort: the incident entity's attribute metadata, giving real
    display labels (instead of raw logical names like `new_internaldesc`)
    and which fields are long-text (Memo) so their HTML can be stripped the
    same way `description` always was. Cached per origin for the run.

    Failure here (e.g. a security role without metadata read) degrades to
    raw logical names as labels rather than crashing the scrape -- getting
    everything, just less prettily labeled, beats getting nothing.
    """
    if origin in _METADATA_CACHE:
        return _METADATA_CACHE[origin]

    labels, memo_fields = {}, set()
    url = (
        f"{origin}/api/data/v9.2/EntityDefinitions(LogicalName='incident')/Attributes"
        f"?$select=LogicalName,DisplayName,AttributeTypeName"
    )
    data, error = _fetch(page, url)
    if not error:
        for attr in data.get("value", []):
            logical = attr.get("LogicalName")
            if not logical:
                continue
            label = ((attr.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label")
            if label:
                labels[logical] = label
            type_name = (attr.get("AttributeTypeName") or {}).get("Value")
            if type_name == "MemoType":
                memo_fields.add(logical)

    _METADATA_CACHE[origin] = (labels, memo_fields)
    return labels, memo_fields


def _extract_all_fields(record, labels, memo_fields):
    """Every populated field on `record` beyond the small curated summary
    (title/ticket/priority/status/created/description/customer/owner).

    Each Dataverse lookup arrives as two JSON keys -- `_ownerid_value` (the
    raw GUID) and `ownerid@...FormattedValue` (the display text) -- which
    are collapsed here into one field keyed by the plain logical name
    (`ownerid`), preferring the friendly display text when Dataverse
    provided one.
    """
    formatted = {}
    for key, value in record.items():
        if not key.endswith(_FORMATTED_SUFFIX):
            continue
        base = key[: -len(_FORMATTED_SUFFIX)]
        if base.startswith("_") and base.endswith("_value"):
            base = base[1:-len("_value")]
        formatted[base] = value

    fields = []
    seen = set()
    for key, value in record.items():
        if "@" in key:
            continue  # an annotation -- already folded into `formatted`
        logical = key[1:-len("_value")] if key.startswith("_") and key.endswith("_value") else key
        if logical in seen or logical in _IGNORE_FIELDS or logical in _SUMMARY_FIELDS:
            continue
        seen.add(logical)

        display_value = formatted.get(logical, value)
        if isinstance(display_value, str) and (logical in memo_fields or _looks_like_html(display_value)):
            display_value = _strip_html(display_value)
        if display_value in (None, ""):
            continue

        fields.append({"logical_name": logical, "label": labels.get(logical, logical), "value": display_value})

    fields.sort(key=lambda f: f["label"].lower())
    return fields


def _is_inlinable_mimetype(mimetype):
    mimetype = (mimetype or "").lower()
    return mimetype.startswith(_INLINABLE_TEXT_MIME_PREFIXES + _INLINABLE_IMAGE_MIME_PREFIXES)


def _fetch_inlinable_attachments(page, origin, notes):
    """Fetches `documentbody` for whichever of `notes` are small,
    inlinable-type file attachments (see ATTACHMENT_MAX_FETCH_BYTES/
    _is_inlinable_mimetype) and fills in each qualifying note's
    "attachment" key -- {"kind": "text", "content": ..., "truncated": bool}
    or {"kind": "image", "bytes": <raw decoded bytes>}. Every other note's
    "attachment" is left at get_notes' own default of None.

    A second, separate request from get_notes' own query -- documentbody is
    base64 file content, potentially large, and most notes aren't
    attachments at all, so fetching it unconditionally for every one of up
    to NOTES_TOP notes would mean downloading bytes nobody asked for.
    Mutates `notes` in place; best-effort -- a failure here (or a body that
    doesn't decode) still leaves every note's filename/size/mimetype intact
    (already set by get_notes), just without the fetched content, same
    "get everything, just less" degrade as get_attribute_metadata's own
    failure mode.
    """
    candidates = {
        n["id"]: n for n in notes
        if n.get("id") and n.get("filename")
        and (n.get("filesize") or 0) <= ATTACHMENT_MAX_FETCH_BYTES
        and _is_inlinable_mimetype(n.get("mimetype"))
    }
    if not candidates:
        return

    id_filter = " or ".join(f"annotationid eq {annotation_id}" for annotation_id in candidates)
    url = f"{origin}/api/data/v9.2/annotations?$select=annotationid,documentbody&$filter={id_filter}"
    data, error = _fetch(page, url)
    if error:
        return

    for row in data.get("value", []):
        note = candidates.get(row.get("annotationid"))
        body_b64 = row.get("documentbody")
        if not note or not body_b64:
            continue
        try:
            raw_bytes = base64.b64decode(body_b64)
        except Exception:
            continue  # malformed/unexpected encoding -- leave "attachment" at None

        if (note.get("mimetype") or "").lower().startswith(_INLINABLE_IMAGE_MIME_PREFIXES):
            note["attachment"] = {"kind": "image", "bytes": raw_bytes}
        else:
            text = raw_bytes.decode("utf-8", errors="replace")
            truncated = len(text) > ATTACHMENT_TEXT_MAX_CHARS
            note["attachment"] = {
                "kind": "text",
                "content": text[:ATTACHMENT_TEXT_MAX_CHARS] if truncated else text,
                "truncated": truncated,
            }


def get_notes(page, origin, incident_id):
    """Notes (Dataverse's generic `annotation` entity) attached to the case
    -- shown on the case page's Notes/timeline, not part of the incident
    record itself, so this is a separate call.

    Returns (notes, truncated, error). Capped at NOTES_TOP most recent;
    truncation is signaled rather than silently dropped, same pattern as
    ado_api's max_prs. Each note's "attachment" is filled in by
    _fetch_inlinable_attachments for whichever attached files qualify (see
    there) -- None for the rest, same as before this existed.
    """
    url = (
        f"{origin}/api/data/v9.2/annotations"
        f"?$filter=_objectid_value eq {incident_id}"
        f"&$select=annotationid,subject,notetext,createdon,filename,isdocument,mimetype,filesize"
        f"&$orderby=createdon desc&$top={NOTES_TOP}"
    )
    data, error = _fetch(page, url)
    if error:
        return [], False, error

    raw = data.get("value", [])
    notes = [{
        "id": n.get("annotationid"),
        "subject": n.get("subject"),
        "text": _strip_html(n.get("notetext")),
        "created_on": n.get("createdon"),
        "filename": n.get("filename") if n.get("isdocument") else None,
        "mimetype": n.get("mimetype") if n.get("isdocument") else None,
        "filesize": n.get("filesize") if n.get("isdocument") else None,
        "attachment": None,
    } for n in raw]

    _fetch_inlinable_attachments(page, origin, notes)
    return notes, len(raw) >= NOTES_TOP, None


def get_activities(page, origin, incident_id):
    """The case page's Activity Timeline (phone calls, emails, tasks, ...)
    -- Dataverse's generic `activitypointer` entity, which rolls up every
    concrete activity type in one query instead of hitting each one
    separately.

    Returns (activities, truncated, error). Capped at ACTIVITIES_TOP most
    recent.
    """
    url = (
        f"{origin}/api/data/v9.2/activitypointers"
        f"?$filter=_regardingobjectid_value eq {incident_id}"
        f"&$select=subject,activitytypecode,createdon,description,statuscode"
        f"&$orderby=createdon desc&$top={ACTIVITIES_TOP}"
    )
    data, error = _fetch(page, url)
    if error:
        return [], False, error

    raw = data.get("value", [])
    activities = [{
        "type": a.get("activitytypecode"),
        "subject": a.get("subject"),
        "status": a.get("statuscode" + _FORMATTED_SUFFIX) or a.get("statuscode"),
        "created_on": a.get("createdon"),
        "description": _strip_html(a.get("description")),
    } for a in raw]
    return activities, len(raw) >= ACTIVITIES_TOP, None


def get_related_links(page, origin, incident_id):
    """The case form's "Dev" tab "Related links" grid -- see
    RELATED_LINKS_NAV_PROPERTY above for what this is and how it was found.

    Returns (links, error). No cap/truncation -- unlike Notes/Activities
    this grid is a handful of manually-added links at most in practice, not
    an unbounded timeline.
    """
    url = (
        f"{origin}/api/data/v9.2/incidents({incident_id})"
        f"?$select=incidentid"
        f"&$expand={RELATED_LINKS_NAV_PROPERTY}"
        f"($select=art_name,art_urllink,statuscode,createdon;$orderby=createdon desc)"
    )
    data, error = _fetch(page, url)
    if error:
        return [], error

    raw = data.get(RELATED_LINKS_NAV_PROPERTY) or []
    links = [{
        "name": r.get("art_name"),
        "url": r.get("art_urllink"),
        "status": r.get("statuscode" + _FORMATTED_SUFFIX) or r.get("statuscode"),
        "created_on": r.get("createdon"),
    } for r in raw]
    return links, None


def _resolve_team_id(page, origin, team_name):
    """GUID for a team, looked up by name. Returns (team_id, error) -- same
    escaping as lookup_by_ticket's ticket-number filter, for the same
    reason (a `'` in the name would otherwise break out of the OData string
    literal)."""
    escaped = team_name.replace("'", "''")
    url = f"{origin}/api/data/v9.2/teams?$filter=name eq '{escaped}'&$select=teamid"
    data, error = _fetch(page, url)
    if error:
        return None, error
    values = data.get("value", [])
    if not values:
        return None, f"No team found named '{team_name}'."
    return values[0]["teamid"], None


def get_current_user_id(page):
    """The signed-in user's own systemuserid, via the Web API's WhoAmI
    action -- resolved from the page's own token rather than a parameter a
    caller would otherwise have to already know. Used by list_new_cases to
    also surface cases already owned by whoever is running the query.
    Returns (user_id, error)."""
    origin = re.match(r"(https?://[^/]+)", page.url).group(1)
    data, error = _fetch(page, f"{origin}/api/data/v9.2/WhoAmI")
    if error:
        return None, error
    user_id = data.get("UserId")
    if not user_id:
        return None, "WhoAmI response had no UserId."
    return user_id, None


def list_new_cases(page, team_name=DEFAULT_UNASSIGNED_TEAM_NAME):
    """Every currently-active case that's either still owned by `team_name`
    (the CRM's default queue every new case lands in -- i.e. nobody has
    picked it up yet) or already owned by whoever is signed in (`page`'s
    own token, resolved via get_current_user_id) -- work that's unclaimed,
    or already yours. Used by case-getter (../../case-getter/case_getter.py)
    to find work; case-brief itself never calls this (it only ever looks up
    one case by ticket number).

    "Accessible to me" needs no extra filter here: the Dataverse Web API
    call is already scoped to the signed-in user's own security role (see
    CLAUDE.md's Dataverse API access investigation), so this only ever
    returns what that user could already see in the CRM UI.

    A WhoAmI failure degrades to the team-only filter (each case's
    "owned_by_me" then just always False) rather than failing the whole
    listing -- the same "get everything, just less" tradeoff
    get_attribute_metadata already makes for a denied metadata call.

    Deliberately a curated $select, unlike lookup_by_ticket's "get
    everything" -- this is a triage list across possibly many cases, not
    one case's full brief, so pulling every field for every row would be
    slow and mostly unused.

    Returns (cases, error, truncated). error means the whole query failed
    to run (team not found, permissions, ...) -- cases is always [] in that
    case. truncated means more than NEW_CASES_TOP cases matched (same
    "signal a partial result" pattern as NOTES_TOP/ACTIVITIES_TOP).
    """
    origin = re.match(r"(https?://[^/]+)", page.url).group(1)
    team_id, error = _resolve_team_id(page, origin, team_name)
    if error:
        return [], error, False

    user_id, _ = get_current_user_id(page)  # best-effort -- see docstring
    owner_filter = f"_owningteam_value eq {team_id}"
    if user_id:
        owner_filter = f"({owner_filter} or _owninguser_value eq {user_id})"

    url = (
        f"{origin}/api/data/v9.2/incidents"
        # `_owninguser_value`, not the bare `owninguser` -- confirmed live
        # (2026-08-26): $select-ing the bare attribute name for a lookup
        # field silently returns something *other* than that field (either
        # every field, or none of them, depending what else is in the
        # $select list) rather than an error, so a wrong name here fails
        # silently, not loudly. The underscore-prefixed nav-property-value
        # form is Dataverse's own documented way to $select a lookup's raw
        # value, and is what `_customerid_value` right next to it already
        # relies on.
        f"?$select=incidentid,ticketnumber,title,prioritycode,statuscode,createdon,modifiedon,_customerid_value,_owninguser_value"
        f"&$filter=statecode eq 0 and {owner_filter}"
        f"&$orderby=createdon desc&$top={NEW_CASES_TOP}"
    )
    data, error = _fetch(page, url)
    if error:
        return [], error, False

    raw = data.get("value", [])
    cases = [{
        "id": c.get("incidentid"),
        "ticket_number": c.get("ticketnumber"),
        "title": c.get("title"),
        "priority": c.get("prioritycode" + _FORMATTED_SUFFIX) or c.get("prioritycode"),
        "status": c.get("statuscode" + _FORMATTED_SUFFIX) or c.get("statuscode"),
        "created_on": c.get("createdon"),
        # Cheap to select here (a plain scalar field, not a lookup -- no
        # underscore-suffix gotcha like _owninguser_value above) and needed
        # for case-getter's own staleness check (see _to_result's
        # "modified_on" for the full explanation).
        "modified_on": c.get("modifiedon"),
        "customer": c.get("_customerid_value" + _FORMATTED_SUFFIX),
        "owned_by_me": bool(user_id) and c.get("_owninguser_value") == user_id,
        "url": (f"{origin}/main.aspx?appid={CRM_APP_ID}&forceUCI=1&pagetype=entityrecord&etn=incident&id={c.get('incidentid')}"
                if c.get("incidentid") else None),
    } for c in raw]
    return cases, None, len(raw) >= NEW_CASES_TOP


def _to_result(case, origin, tab_url, labels=None, memo_fields=None):
    labels = labels or {}
    memo_fields = memo_fields or set()
    incident_id = case.get("incidentid")

    return {
        "id": incident_id,
        # Deep link into the CRM UI, so the brief has something clickable.
        # appid+forceUCI pin it to the actual Customer Service app rather
        # than Dynamics falling back to a default/prompting to pick one.
        "url": (f"{origin}/main.aspx?appid={CRM_APP_ID}&forceUCI=1&pagetype=entityrecord&etn=incident&id={incident_id}"
                if incident_id else tab_url),
        "title": case.get("title"),
        "ticket_number": case.get("ticketnumber"),
        "priority": case.get("prioritycode" + _FORMATTED_SUFFIX) or case.get("prioritycode"),
        "status": case.get("statuscode" + _FORMATTED_SUFFIX) or case.get("statuscode"),
        "created_on": case.get("createdon"),
        # Dataverse's own last-modified timestamp -- report.py stamps this
        # into a hidden marker in the rendered brief (see build_markdown),
        # which case-getter reads back to detect a brief gone stale (see
        # its own module docstring): if a later CRM listing shows a newer
        # modifiedon than what's stamped here, the case changed since this
        # brief was written.
        "modified_on": case.get("modifiedon"),
        "description": _strip_html(case.get("description")),
        # Resolved from Dataverse's own display-name annotation for the
        # lookup, not a nested $expand -- this covers both account- and
        # contact-type customers (the old $expand=customerid_account only
        # ever worked when the customer was an account) and both user- and
        # team-owned cases (the old $expand=owninguser only ever worked for
        # a user owner, never a team).
        "customer": case.get("_customerid_value" + _FORMATTED_SUFFIX),
        "owner": case.get("_ownerid_value" + _FORMATTED_SUFFIX),
        "all_fields": _extract_all_fields(case, labels, memo_fields) if case else [],
    }


def _finish(page, origin, case):
    """Shared tail of lookup_by_ticket/extract: labels the raw record and
    tacks on Notes + the Activity Timeline + the Dev tab's Related links
    grid, which all live in separate Dataverse entities/relationships and
    aren't part of the incident record itself."""
    labels, memo_fields = get_attribute_metadata(page, origin)
    result = _to_result(case, origin, page.url, labels, memo_fields)

    incident_id = case.get("incidentid")
    if incident_id:
        notes, notes_truncated, notes_error = get_notes(page, origin, incident_id)
        activities, activities_truncated, activities_error = get_activities(page, origin, incident_id)
        related_links, related_links_error = get_related_links(page, origin, incident_id)
    else:
        notes, notes_truncated, notes_error = [], False, None
        activities, activities_truncated, activities_error = [], False, None
        related_links, related_links_error = [], None

    result.update(
        notes=notes, notes_truncated=notes_truncated, notes_error=notes_error,
        activities=activities, activities_truncated=activities_truncated, activities_error=activities_error,
        related_links=related_links, related_links_error=related_links_error,
    )
    return result


def find_authenticated_tabs(pages, host_contains):
    """Any tab open on the CRM origin, regardless of which page it's on --
    used as the auth bridge for lookup_by_ticket."""
    return [p for p in pages if any(h in p.url for h in host_contains)]


def is_authenticated(page):
    """Lightweight check: does this tab's session actually work against the
    Web API right now? Used to poll for "you've signed in" without needing
    a keypress -- a tab sitting on a login/redirect page fails this.
    """
    try:
        origin = re.match(r"(https?://[^/]+)", page.url).group(1)
        result = page.evaluate(_FETCH_JS, f"{origin}/api/data/v9.2/WhoAmI")
    except Exception:
        return False
    return not result.get("__error")


def lookup_by_ticket(page, ticket_number, ticket_field="ticketnumber"):
    origin = re.match(r"(https?://[^/]+)", page.url).group(1)
    escaped = ticket_number.replace("'", "''")
    # No $select -- Dataverse returns every attribute on the matched
    # record when it's omitted, which is the whole point (see module
    # docstring). $top=1 still limits how many *records* come back.
    api_url = f"{origin}/api/data/v9.2/incidents?$filter={ticket_field} eq '{escaped}'&$top=1"

    result = page.evaluate(_FETCH_JS, api_url)
    if result.get("__error"):
        return {"error": result["__error"], "url": page.url}

    values = result.get("value", [])
    if not values:
        return {"error": f"No case found with {ticket_field} = '{ticket_number}'.", "url": page.url}

    return _finish(page, origin, values[0])
