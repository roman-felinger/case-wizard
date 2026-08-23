"""
CRM login verification.

Simple approach: open CRM in default browser, ask user to confirm login.
No browser automation needed (avoids Playwright dependency).
"""

import webbrowser
import time


def open_crm_in_browser(crm_url: str) -> bool:
    """
    Open CRM in user's default browser.

    Args:
        crm_url: Organization CRM URL

    Returns:
        True if opened successfully, False otherwise
    """
    try:
        webbrowser.open(crm_url)
        return True
    except Exception as e:
        return False


def check_crm_on_startup(crm_url: str) -> tuple[bool, str]:
    """
    Check if CRM might already be logged in (on app startup).

    This is a heuristic check - we can't verify without browser automation.
    Returns status based on assumptions.

    Args:
        crm_url: Organization CRM URL

    Returns:
        (status: bool, message: str)
        - (None, "Not checked") if need manual verification
        - (False, "Not ready") if likely not logged in
    """
    # On startup, we can't really verify without browser automation
    # Return "not checked" - user needs to click the button
    return None, "Click 'Check CRM Login' to verify"


def prompt_crm_login(crm_url: str) -> tuple[bool, str]:
    """
    Prompt user to log into CRM and confirm when ready.

    Opens browser, waits for user confirmation.

    Args:
        crm_url: Organization CRM URL

    Returns:
        (success: bool, message: str)
    """
    # Open browser
    if not open_crm_in_browser(crm_url):
        return False, "❌ Could not open browser"

    # Browser opened - user will log in
    # We return success after user confirms (handled in UI)
    return True, f"✅ CRM opened at {crm_url} - Please log in and confirm"
