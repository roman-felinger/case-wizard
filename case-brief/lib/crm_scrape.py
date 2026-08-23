"""Reads a Dynamics 365 CRM case using an already-open, already-logged-in
browser tab -- no OAuth, no app registration.

Trick: the Dataverse Web API lives on the *same origin* as the CRM UI itself.
A same-origin fetch with credentials included rides on the page's own session
cookie, the same way the CRM UI's own JavaScript calls that API internally.

Two ways to find the case:
  - By ticket number (lookup_by_ticket): works from ANY open, logged-in CRM
    tab -- you don't need to navigate to the specific case yourself, just
    have CRM open to something. This is the preferred path when you already
    know the ticket number.
  - By URL (find_case_tabs/extract): auto-detects whichever case you already
    have open, for when you don't pass a ticket number at all.
"""
import html
import re

SELECT_FIELDS = "title,ticketnumber,prioritycode,statuscode,createdon,description"
EXPAND = "customerid_account($select=name),owninguser($select=fullname)"

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


def _strip_html(text):
    if not text:
        return text
    text = re.sub(r"(?i)<div[^>]*>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<p[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _to_result(case, origin, tab_url):
    incident_id = case.get("incidentid")
    return {
        "id": incident_id,
        # Deep link into the CRM UI, so the brief has something clickable
        # and the browser module can reopen this exact case next time.
        "url": f"{origin}/main.aspx?pagetype=entityrecord&etn=incident&id={incident_id}" if incident_id else tab_url,
        "title": case.get("title"),
        "ticket_number": case.get("ticketnumber"),
        "priority": case.get("prioritycode@OData.Community.Display.V1.FormattedValue") or case.get("prioritycode"),
        "status": case.get("statuscode@OData.Community.Display.V1.FormattedValue") or case.get("statuscode"),
        "created_on": case.get("createdon"),
        "description": _strip_html(case.get("description")),
        "customer": (case.get("customerid_account") or {}).get("name"),
        "owner": (case.get("owninguser") or {}).get("fullname"),
    }


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
    api_url = (
        f"{origin}/api/data/v9.2/incidents"
        f"?$filter={ticket_field} eq '{escaped}'"
        f"&$select={SELECT_FIELDS}&$expand={EXPAND}&$top=1"
    )

    result = page.evaluate(_FETCH_JS, api_url)
    if result.get("__error"):
        return {"error": result["__error"], "url": page.url}

    values = result.get("value", [])
    if not values:
        return {"error": f"No case found with {ticket_field} = '{ticket_number}'.", "url": page.url}

    return _to_result(values[0], origin, page.url)


def find_case_tabs(pages, host_contains):
    matches = []
    for page in pages:
        url = page.url
        if any(h in url for h in host_contains) and "etn=incident" in url:
            matches.append(page)
    return matches


def extract(page):
    m = re.search(r"[?&]id=(?:%7B)?([0-9a-fA-F-]{36})", page.url)
    if not m:
        return {"error": "Could not find a case id in the tab URL.", "url": page.url}
    incident_id = m.group(1)
    origin = re.match(r"(https?://[^/]+)", page.url).group(1)
    api_url = f"{origin}/api/data/v9.2/incidents({incident_id})?$select={SELECT_FIELDS}&$expand={EXPAND}"

    result = page.evaluate(_FETCH_JS, api_url)
    if result.get("__error"):
        return {"error": result["__error"], "url": page.url}

    return _to_result(result, origin, page.url)
