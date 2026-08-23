"""Extracts a rough summary of an open Business Central web client tab.

Unlike CRM/ADO, BC's public API lives on a different origin
(api.businesscentral.dynamics.com) than the web client
(businesscentral.dynamics.com) and expects bearer-token auth, so the
same-origin cookie-fetch trick doesn't apply here. Instead this reads the
rendered page: BC's web client labels its inputs with aria-label (it's built
to be screen-reader accessible), so a label/value scrape gets you most of
what's visible on a card or list page.

Two things make BC's DOM trickier than CRM/ADO's: the client can render
inside an iframe (so the top document alone may come up empty), and labels
can land on elements other than <input>/<textarea>. This checks every frame
and a broader set of elements, and always includes a capped raw-text dump as
a fallback so a wrong selector guess doesn't silently return nothing.
"""

_EXTRACT_JS = """() => {
    const pairs = [];
    const seen = new Set();
    const selector = 'input[aria-label], textarea[aria-label], [role="textbox"][aria-label], ' +
                     '[role="gridcell"][aria-label], [role="cell"][aria-label], [aria-label][aria-labelledby]';
    document.querySelectorAll(selector).forEach(el => {
        const label = (el.getAttribute('aria-label') || '').trim();
        const value = (el.value !== undefined && el.value !== '' ? el.value : (el.innerText || '')).trim();
        const key = label + '\\u0001' + value;
        if (label && value && label !== value && !seen.has(key)) {
            seen.add(key);
            pairs.push([label, value]);
        }
    });
    return {
        title: document.title,
        pairs,
        text: document.body ? document.body.innerText.slice(0, 4000) : '',
    };
}"""


def find_bc_tabs(pages, host="businesscentral.dynamics.com"):
    return [p for p in pages if host in p.url]


def extract(page):
    best = {"title": None, "pairs": [], "text": ""}

    frames = page.frames  # includes the main frame plus any iframes
    for frame in frames:
        try:
            data = frame.evaluate(_EXTRACT_JS)
        except Exception:
            continue
        if not best["title"]:
            best["title"] = data.get("title")
        if len(data.get("pairs", [])) > len(best["pairs"]):
            best["pairs"] = data["pairs"]
        if len(data.get("text", "")) > len(best["text"]):
            best["text"] = data.get("text", "")

    fields = [{"label": label, "value": value} for label, value in best["pairs"][:40]]

    return {
        "url": page.url,
        "page_title": best["title"] or page.title(),
        "fields": fields,
        "raw_text": best["text"] if not fields else None,
    }
