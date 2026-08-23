"""
CRM login detection via a dedicated, persistent browser window.

Why not `requests`: your CRM session lives in your daily browser's cookie
jar. A plain HTTP request from Python has no cookies and always gets
redirected to the Microsoft login page - so it can never see a real login.

Why not read your browser's cookies directly: modern Edge/Chrome encrypt
cookies with App-Bound Encryption specifically to block external tools
from reading them (anti-infostealer protection). No reliable workaround
without running as Administrator.

So: case-wizard drives its own small persistent Chromium profile (separate
from your daily browser, stored in .crm_profile/). You log in there once;
the session persists across app restarts just like a normal browser
profile would. Every check after that is a fast, headless DOM read -
no cookies extracted, no admin rights, no manual confirmation.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
PROFILE_DIR = HERE / ".crm_profile"


def reset_profile():
    """
    Recovery for a stuck profile: if a previous browser session was
    killed abruptly (crash, force-stop) instead of shutting down
    cleanly, Chromium can leave behind an exclusive lock on the profile
    directory that blocks every future check/login attempt with no
    clear error. This kills any leftover process still holding it and
    clears the lock markers so the next check starts fresh.
    """
    if sys.platform != "win32":
        return

    try:
        ps_cmd = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -like '*.crm_profile*' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
        )
        for pid in result.stdout.split():
            subprocess.run(["taskkill", "/F", "/PID", pid.strip()], capture_output=True, timeout=5)
    except Exception:
        pass

    for lockfile in [PROFILE_DIR / "lockfile", PROFILE_DIR / "Default" / "LOCK"]:
        try:
            lockfile.unlink(missing_ok=True)
        except Exception:
            pass

# Selectors/markers that identify a Microsoft/AAD login page
LOGIN_MARKERS = [
    "input[type='email']",
    "#i0116",           # AAD email field
    "#i0118",           # AAD password field
    "text=Sign in",
]

# Host fragments that indicate we've been bounced to a login flow
LOGIN_HOST_FRAGMENTS = ["login.microsoftonline.com", "login.microsoft.com", "login.live.com"]


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

    # Dynamics 365 app shell markers (any one is enough)
    app_markers = ["#ApplicationBody", ".crmFullScreenContent", "#crmContentPanel", "#shell-container"]
    for sel in app_markers:
        try:
            if page.locator(sel).count() > 0:
                return "app"
        except Exception:
            pass

    return "unknown"


def check_login_headless(crm_url: str, timeout_s: int = 15):
    """
    Fast, silent check: does the persisted profile show a logged-in CRM
    session right now? No window is shown.

    Returns (status, message):
        True  -> logged in
        False -> not logged in (login page detected)
        None  -> couldn't tell (network issue, still loading, etc.)
    """
    if not crm_url:
        return None, "CRM URL not configured"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "Playwright not installed"

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=True
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(crm_url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
                page.wait_for_timeout(1200)  # let SPA redirects settle
                state = _page_state(page)
            finally:
                context.close()

        if state == "login":
            return False, "Not logged in"
        if state == "app":
            return True, "Logged in"
        return None, "Could not determine login state"

    except Exception as e:
        msg = str(e).splitlines()[0][:120]
        if "Executable doesn't exist" in msg:
            return None, "Browser not installed (run: playwright install chromium)"
        return None, f"CRM check error: {msg}"


def open_login_window(crm_url: str, max_wait_s: int = 600):
    """
    Show a real, visible browser window (same persistent profile) so the
    user can log in. Polls the DOM and auto-closes the window the moment
    login succeeds - no button to click, no confirmation checkbox.

    Meant to be run out-of-process (see __main__ below) so it never
    blocks the Streamlit UI thread.

    Returns (status, message) - same contract as check_login_headless.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(crm_url, wait_until="domcontentloaded")

            start = time.time()
            while time.time() - start < max_wait_s:
                state = _page_state(page)
                if state == "app":
                    return True, "Logged in"
                time.sleep(1)

            return None, "Timed out waiting for login"
        finally:
            context.close()


if __name__ == "__main__":
    # Standalone entrypoint so this can run as a detached subprocess:
    #   python crm_playwright.py --check <url>   -> headless check, prints JSON, exits
    #   python crm_playwright.py --login <url>   -> visible login window, prints JSON, exits
    if len(sys.argv) < 3:
        print(json.dumps({"status": None, "message": "Usage: --check|--login <url>"}))
        sys.exit(1)

    mode, url = sys.argv[1], sys.argv[2]
    if mode == "--login":
        status, message = open_login_window(url)
    else:
        status, message = check_login_headless(url)

    print(json.dumps({"status": status, "message": message}))
