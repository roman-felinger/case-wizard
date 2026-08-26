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
"""
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
    "createdon", "description", "customerid", "ownerid",
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


def get_notes(page, origin, incident_id):
    """Notes (Dataverse's generic `annotation` entity) attached to the case
    -- shown on the case page's Notes/timeline, not part of the incident
    record itself, so this is a separate call.

    Returns (notes, truncated, error). Capped at NOTES_TOP most recent;
    truncation is signaled rather than silently dropped, same pattern as
    ado_api's max_prs.
    """
    url = (
        f"{origin}/api/data/v9.2/annotations"
        f"?$filter=_objectid_value eq {incident_id}"
        f"&$select=subject,notetext,createdon,filename,isdocument"
        f"&$orderby=createdon desc&$top={NOTES_TOP}"
    )
    data, error = _fetch(page, url)
    if error:
        return [], False, error

    raw = data.get("value", [])
    notes = [{
        "subject": n.get("subject"),
        "text": _strip_html(n.get("notetext")),
        "created_on": n.get("createdon"),
        "filename": n.get("filename") if n.get("isdocument") else None,
    } for n in raw]
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


def _to_result(case, origin, tab_url, labels=None, memo_fields=None):
    labels = labels or {}
    memo_fields = memo_fields or set()
    incident_id = case.get("incidentid")

    return {
        "id": incident_id,
        # Deep link into the CRM UI, so the brief has something clickable.
        "url": f"{origin}/main.aspx?pagetype=entityrecord&etn=incident&id={incident_id}" if incident_id else tab_url,
        "title": case.get("title"),
        "ticket_number": case.get("ticketnumber"),
        "priority": case.get("prioritycode" + _FORMATTED_SUFFIX) or case.get("prioritycode"),
        "status": case.get("statuscode" + _FORMATTED_SUFFIX) or case.get("statuscode"),
        "created_on": case.get("createdon"),
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
    tacks on Notes + the Activity Timeline, which live in separate
    Dataverse entities and aren't part of the incident record itself."""
    labels, memo_fields = get_attribute_metadata(page, origin)
    result = _to_result(case, origin, page.url, labels, memo_fields)

    incident_id = case.get("incidentid")
    if incident_id:
        notes, notes_truncated, notes_error = get_notes(page, origin, incident_id)
        activities, activities_truncated, activities_error = get_activities(page, origin, incident_id)
    else:
        notes, notes_truncated, notes_error = [], False, None
        activities, activities_truncated, activities_error = [], False, None

    result.update(
        notes=notes, notes_truncated=notes_truncated, notes_error=notes_error,
        activities=activities, activities_truncated=activities_truncated, activities_error=activities_error,
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
