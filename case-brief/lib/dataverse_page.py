"""A minimal stand-in for a Playwright Page, backed by a real Dataverse Web
API access token instead of a same-origin cookie-authenticated browser tab.

Why this shape: crm_scrape.py's every function takes a `page` argument and
uses exactly two things from it -- `.url` (a string, to derive the CRM
origin) and `.evaluate(js, arg)` (crm_scrape's in-page fetch: `js` is
always its own _FETCH_JS, `arg` is the URL to fetch). DataverseApiPage
implements that exact narrow interface over `requests` + a Bearer token, so
every function in crm_scrape.py -- lookup_by_ticket, get_notes,
get_activities, get_attribute_metadata, is_authenticated -- and everything
downstream that consumes their output (report.py, case_guide.py's brief
parsing, ...) works completely unchanged. This is the whole point: the
data-acquisition layer (this file + dataverse_auth.py) is the only thing
that's new; crm_scrape.py itself was never scraping the CRM UI to begin
with (see its own module docstring) -- it already made these exact Web API
calls, just riding a browser's session cookie for auth instead of an OAuth
token.
"""
import requests

_FORMATTED_ANNOTATIONS_HEADER = 'odata.include-annotations="*"'


class DataverseApiPage:
    """Duck-types enough of a Playwright Page for crm_scrape.py to use
    unmodified. `js` (crm_scrape._FETCH_JS) is accepted and ignored --
    unlike the real Page, the fetch here happens directly in Python via
    `requests` rather than inside a browser, but the request itself
    (headers, error shape) matches _FETCH_JS exactly so behavior -- and
    every existing crm_scrape.py test's expectations -- carries over."""

    def __init__(self, origin, access_token, session=None):
        # crm_scrape.py only ever regexes the origin back out of `.url` --
        # it never navigates or reads anything else from it.
        self.url = f"{origin}/"
        self._token = access_token
        self._session = session or requests.Session()

    def evaluate(self, js, arg):
        url = arg
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Prefer": _FORMATTED_ANNOTATIONS_HEADER,
        }
        try:
            r = self._session.get(url, headers=headers, timeout=30)
        except requests.RequestException as e:
            return {"__error": str(e)}

        if not r.ok:
            return {"__error": f"HTTP {r.status_code}: {r.text[:300]}"}
        try:
            return r.json()
        except ValueError:
            return {"__error": f"Non-JSON response: {r.text[:300]}"}
