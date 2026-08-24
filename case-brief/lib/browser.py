"""Launches a dedicated, visible Chrome profile with remote debugging enabled,
and connects to it via the Chrome DevTools Protocol (CDP) so the *_scrape
modules can read whatever pages you have open there.

This profile is separate from your everyday Chrome profile -- it won't touch
your normal history, bookmarks, or logins. The first time you use it, sign
into CRM / Azure DevOps by hand in the window it opens; the session cookies
persist in the profile folder afterwards like any browser, so you generally
only log in once (until a session expires).
"""
import json
import os
import subprocess
import time

import requests
from playwright.sync_api import sync_playwright

STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".last_urls.json")


def load_last_urls():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_last_urls(urls):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(urls, f, indent=2)

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_chrome_exe(configured_path=None):
    if configured_path and os.path.exists(configured_path):
        return configured_path
    for path in CHROME_CANDIDATES:
        if os.path.exists(path):
            return path
    raise RuntimeError(
        "Could not find chrome.exe in the usual locations. "
        "Set chrome.executable in config.json to its full path."
    )


def _cdp_alive(port):
    try:
        r = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=1)
        return r.ok
    except requests.RequestException:
        return False


def ensure_chrome(cfg, visible=False, extra_urls=None):
    """Makes sure a debuggable Chrome is running, launching it if needed.
    Returns (port, launched_fresh) -- launched_fresh is True only when this
    call actually started a new Chrome process (vs. reusing one already
    running from a previous invocation you left open).

    visible=False (default, case-brief's own CLI usage): opens minimized so
    it doesn't steal focus from whatever you're doing at the terminal.
    visible=True (case-wizard's desktop app, where this window IS the
    thing you're looking at): opens normally, focused.

    extra_urls, if given, are opened as additional tabs on a fresh launch
    only (e.g. the app's own dashboard URL) - on top of whatever CRM
    pages you last had open (see load_last_urls below).

    Does NOT wait for you to log in -- pair this with wait_until_ready()
    below, which polls instead of blocking on a keypress.
    """
    port = cfg.get("debug_port", 9222)
    if _cdp_alive(port):
        return port, False

    profile_dir = os.path.abspath(cfg.get("profile_dir", "./chrome-automation-profile"))
    os.makedirs(profile_dir, exist_ok=True)
    chrome_exe = find_chrome_exe(cfg.get("executable"))

    print(f"Launching dedicated Chrome profile at {profile_dir} (debug port {port})...")
    if visible:
        print("Sign into CRM there if prompted.")
    else:
        print("It opens minimized (won't steal focus) -- check your taskbar for a second Chrome icon and sign into CRM there.")
        print("It'll be closed automatically once this run finishes.")

    # Reopen whatever CRM pages you last had open, so a fresh launch (e.g. after
    # you did close the window) doesn't also make you retype the URL from scratch.
    # You'll still need to sign in again if the session itself expired.
    last_urls = load_last_urls()
    reopen_urls = list(extra_urls or []) + [u for u in last_urls.values() if u]

    # SW_SHOWMINNOACTIVE (7) shows the window minimized without activating
    # it - only applied when visible=False (case-brief's own CLI usage).
    startupinfo = None
    if not visible and os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 7

    subprocess.Popen(
        [
            chrome_exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            *reopen_urls,
        ],
        startupinfo=startupinfo,
    )

    for _ in range(30):
        if _cdp_alive(port):
            break
        time.sleep(0.5)
    else:
        raise RuntimeError("Chrome did not come up with remote debugging enabled in time.")

    return port, True


def wait_until_ready(port, check_fn, message, timeout=300, poll_interval=2):
    """Polls the automation Chrome until check_fn(pages) returns truthy --
    no keypress needed, just log in / open the tab over there and this
    notices on its own. check_fn is re-run against a fresh connection each
    poll (cheap) since a Page handle doesn't survive across connections.

    Raises TimeoutError if it never becomes ready within `timeout` seconds.
    """
    print(message)
    deadline = time.time() + timeout
    last_status = 0
    while time.time() < deadline:
        pw, pages = get_pages(port)
        try:
            if check_fn(pages):
                return
        finally:
            close(pw)
        if time.time() - last_status > 10:
            print("  ...still waiting")
            last_status = time.time()
        time.sleep(poll_interval)
    raise TimeoutError("Timed out waiting -- make sure you're signed in and the right tab is open, then try again.")


def get_pages(port):
    """Returns (playwright_handle, list_of_open_pages) for the running Chrome.
    Call close(playwright_handle) when done -- it only detaches, it does not
    close your actual Chrome window. See close_chrome_window() for that.
    """
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
    pages = []
    for context in browser.contexts:
        pages.extend(context.pages)
    return pw, pages


def close(pw):
    pw.stop()


def close_chrome_window(cfg):
    """Fully closes the automation Chrome window once a run is done -- unlike
    close(), which only detaches Playwright and leaves Chrome running.

    Note the tradeoff: since nothing survives to keep the session warm, the
    NEXT run will need you to sign in again (session cookies may or may not
    outlive a full browser restart depending on your org's session policy).
    That's the deliberate choice here, matching "close it when you're done"
    over "leave it running so re-login is rare".
    """
    port = cfg.get("debug_port", 9222)
    if not _cdp_alive(port):
        return

    try:
        pw = sync_playwright().start()
        try:
            pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}").close()
        finally:
            pw.stop()
    except Exception:
        pass

    time.sleep(1)
    if not _cdp_alive(port):
        return

    # Graceful close didn't take -- force it via the process list, matched by
    # this profile's path so we don't touch your regular Chrome windows.
    profile_dir = os.path.abspath(cfg.get("profile_dir", "./chrome-automation-profile"))
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{profile_dir}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], timeout=15, capture_output=True)
    except Exception:
        pass
