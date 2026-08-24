"""
Starts the Streamlit server, then opens the dashboard in case-brief's own
shared, debuggable Chrome profile instead of Streamlit's default behavior
(opening whatever the OS's default browser is, with no debug port - a
window with no relationship at all to the one case-brief's own scraping
uses for CRM).

This way there's exactly one browser window: the one you're looking at
the dashboard in is the same one case-brief opens a CRM tab in and the
same one case-wizard's own CRM-login check attaches to. Log in to CRM in
a tab there and it's genuinely the same session case-brief's scraping
sees - no second window anywhere.
"""
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from crm_playwright import _chrome_cfg, CASE_BRIEF_DIR  # noqa: E402

sys.path.insert(0, str(CASE_BRIEF_DIR))
from lib import browser as cb_browser  # noqa: E402

DASHBOARD_URL = "http://localhost:8501"


def _wait_for_server(url, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    # Chrome comes up FIRST, before the server even starts - not after.
    # main.py's own startup check also calls ensure_chrome() the moment a
    # browser session connects to it; if that happened while THIS call was
    # still launching Chrome, both processes could race to grab the same
    # profile lock/port at once and one of them would crash. Launching
    # Chrome to completion before the server exists at all closes that
    # window entirely - by the time anything can connect, ensure_chrome()
    # reliably sees it already running.
    cfg = _chrome_cfg()
    try:
        cb_browser.ensure_chrome(cfg, visible=True)
    except RuntimeError as e:
        print(f"Could not open the browser automatically ({e}).")
        print(f"Once case-wizard starts, open {DASHBOARD_URL} yourself.")

    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(HERE / "main.py"), "--server.headless=true"],
    )

    if _wait_for_server(DASHBOARD_URL):
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            try:
                browser_handle = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{cfg['debug_port']}")
                ctx = browser_handle.contexts[0] if browser_handle.contexts else browser_handle.new_context()
                ctx.new_page().goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=15000)
            finally:
                pw.stop()
        except Exception as e:
            print(f"Chrome is open, but couldn't open the dashboard tab automatically ({e}).")
            print(f"Open {DASHBOARD_URL} yourself in that window.")
    else:
        print("Streamlit didn't come up in time - check the output above for errors.")

    server.wait()


if __name__ == "__main__":
    main()
