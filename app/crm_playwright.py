"""
CRM login detection - shares case-brief's own dedicated Chrome automation
profile (case-brief/chrome-automation-profile/, via case-brief/lib/browser.py)
instead of a separate profile the app kept to itself.

Why this matters: case-brief's own scraping (lib/crm_scrape.py) launches a
real system Chrome on a debug port and reuses it if one's already running
on that port (see browser.py's ensure_chrome()). If the app's login check
used a *different* browser/profile, confirming "CRM: logged in" here told
you nothing about the window case-brief was about to open - it would open
its own, still-logged-out window and need a fresh login anyway. Using the
exact same profile and the exact same reuse-if-alive mechanism means
logging in once here is genuinely the same session case-brief uses.

Why not the previous approach (Playwright's bundled Chromium via
launch_persistent_context in a headless check): that's a different browser
binary from the system Chrome.exe case-brief drives, so it couldn't have
shared a profile with case-brief's browser reliably even pointed at the
same directory - different Chromium builds sometimes refuse to open a
profile last touched by a different one. Attaching over CDP to the same
real Chrome, like case-brief already does, avoids that entirely.

Trade-off: this launches a real, visible Chrome window instead of a fully
headless one for the "just checking" case - unavoidable, since the whole
point is that it's the *same* window you use the dashboard in (see
app/launch.py, which opens that window at startup), and case-brief's
mechanism doesn't support a silent headless mode.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
CASE_BRIEF_DIR = (HERE.parent / "case-brief").resolve()
sys.path.insert(0, str(CASE_BRIEF_DIR))
from lib import browser as cb_browser  # noqa: E402  (path insert must come first)

# Selectors/markers that identify a Microsoft/AAD login page
LOGIN_MARKERS = [
    "input[type='email']",
    "#i0116",           # AAD email field
    "#i0118",           # AAD password field
    "text=Sign in",
]

# Host fragments that indicate we've been bounced to a login flow
LOGIN_HOST_FRAGMENTS = ["login.microsoftonline.com", "login.microsoft.com", "login.live.com"]

# Dynamics 365 app shell markers (any one is enough)
APP_MARKERS = ["#ApplicationBody", ".crmFullScreenContent", "#crmContentPanel", "#shell-container"]


def _chrome_cfg():
    """case-brief's own chrome.* config (profile_dir/debug_port/executable),
    resolved to an absolute profile_dir regardless of this process's cwd -
    the whole point is pointing at the exact same directory case-brief's
    own case_brief.py resolves relative to itself."""
    cfg = {"profile_dir": "./chrome-automation-profile", "debug_port": 9222, "executable": None}
    config_path = CASE_BRIEF_DIR / "config.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            cfg.update(data.get("chrome") or {})
        except Exception:
            pass
    profile_dir = cfg.get("profile_dir") or "./chrome-automation-profile"
    if not Path(profile_dir).is_absolute():
        profile_dir = str((CASE_BRIEF_DIR / profile_dir).resolve())
    cfg["profile_dir"] = profile_dir
    return cfg


def _page_state(page):
    """Inspect the current page and classify it as login / app / unknown."""
    url = (page.url or "").lower()

    if any(frag in url for frag in LOGIN_HOST_FRAGMENTS):
        return "login"

    for sel in LOGIN_MARKERS:
        try:
            if page.locator(sel).count() > 0:
                return "login"
        except Exception:
            pass

    for sel in APP_MARKERS:
        try:
            if page.locator(sel).count() > 0:
                return "app"
        except Exception:
            pass

    return "unknown"


def _find_or_open_tab(browser_handle, crm_url, timeout_ms):
    """Find an already-open tab for crm_url's host in the shared Chrome, or
    open a new one - never opens a second Chrome window."""
    host = crm_url.split("//")[-1].split("/")[0]
    ctx = browser_handle.contexts[0] if browser_handle.contexts else browser_handle.new_context()
    for p in ctx.pages:
        if host in (p.url or ""):
            return p
    page = ctx.new_page()
    page.goto(crm_url, wait_until="domcontentloaded", timeout=timeout_ms)
    return page


def check_login_headless(crm_url: str, timeout_s: int = 15):
    """
    Check whether the shared case-brief Chrome profile is currently logged
    into CRM. Attaches to (or launches, reusing case-brief's own
    ensure_chrome) the same Chrome case-brief's own scraping will use.

    Returns (status, message):
        True/False/None - logged in / not logged in / couldn't tell
    """
    if not crm_url:
        return None, "CRM URL not configured"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "Playwright not installed"

    cfg = _chrome_cfg()
    try:
        port, _ = cb_browser.ensure_chrome(cfg)
    except RuntimeError as e:
        return None, str(e)

    pw = sync_playwright().start()
    try:
        browser_handle = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        page = _find_or_open_tab(browser_handle, crm_url, timeout_s * 1000)
        page.wait_for_timeout(1200)  # let SPA redirects settle
        state = _page_state(page)
    except Exception as e:
        msg = str(e).splitlines()[0][:120]
        return None, f"CRM check error: {msg}"
    finally:
        pw.stop()  # detach only - the actual Chrome window stays open for case-brief to reuse

    if state == "login":
        return False, "Not logged in"
    if state == "app":
        return True, "Logged in"
    return None, "Could not determine login state"


def ensure_crm_tab_open(crm_url: str):
    """
    Make sure a CRM tab exists in the shared Chrome window - fast and
    synchronous (no polling for login), since that window is already
    visible at all times (app/launch.py opens it at startup) and the
    existing Recheck button is how login success gets noticed afterward.
    Never opens a second window: attaches to the already-running shared
    Chrome rather than launching a new one.
    """
    from playwright.sync_api import sync_playwright

    cfg = _chrome_cfg()
    port, _ = cb_browser.ensure_chrome(cfg, visible=True)

    pw = sync_playwright().start()
    try:
        browser_handle = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        _find_or_open_tab(browser_handle, crm_url, 15000)
    finally:
        pw.stop()  # detach - leave the window (and its tabs) open


def reset_profile():
    """
    Recovery for a stuck shared Chrome: force-closes it (case-brief's own
    close_chrome_window, which only touches processes matching this
    profile's path) so the next check/login/case-brief run starts fresh.
    """
    cb_browser.close_chrome_window(_chrome_cfg())


if __name__ == "__main__":
    # Standalone entrypoint, mainly for manual debugging:
    #   python crm_playwright.py --check <url>   -> headless-style check, prints JSON, exits
    #   python crm_playwright.py --login <url>   -> ensures a CRM tab is open, prints JSON, exits
    if len(sys.argv) < 3:
        print(json.dumps({"status": None, "message": "Usage: --check|--login <url>"}))
        sys.exit(1)

    mode, url = sys.argv[1], sys.argv[2]
    if mode == "--login":
        ensure_crm_tab_open(url)
        status, message = None, "Tab opened - check the shared Chrome window"
    else:
        status, message = check_login_headless(url)

    print(json.dumps({"status": status, "message": message}))
