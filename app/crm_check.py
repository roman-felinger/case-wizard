"""
CRM login detection.

Simple HTTP-based check: test if CRM is accessible and user might be logged in.
"""

import webbrowser
import requests
from typing import Tuple


def check_crm_accessibility(crm_url: str, timeout: int = 5) -> Tuple[bool, str]:
    """
    Check if CRM is accessible (simple HTTP check).

    Makes a HEAD request to detect:
    - If URL redirects to login page → user not logged in
    - If page loads → user might be logged in or auth is cached

    Args:
        crm_url: Organization CRM URL
        timeout: Request timeout in seconds

    Returns:
        (logged_in: bool, message: str)
        - (True, "message") if user appears logged in
        - (False, "message") if redirected to login
        - (None, "message") if can't determine
    """
    try:
        # Try to access CRM with no redirect following
        response = requests.head(crm_url, timeout=timeout, allow_redirects=False)

        # Check response code
        if response.status_code == 302 or response.status_code == 301:
            # Redirected - likely to login page
            location = response.headers.get("Location", "").lower()
            if "login" in location or "signin" in location or "auth" in location:
                return False, "⏳ Not logged in - waiting for login..."

        elif response.status_code == 200:
            # Page loaded without redirect - user likely logged in
            return True, "✅ CRM accessible - you appear to be logged in"

        elif response.status_code == 401 or response.status_code == 403:
            # Unauthorized - not logged in
            return False, "⏳ Not logged in - please log in..."

        else:
            # Other status - can't determine
            return None, f"ⓘ CRM status unclear (HTTP {response.status_code})"

    except requests.exceptions.Timeout:
        return None, "⏱️ CRM check timed out - check network"

    except requests.exceptions.ConnectionError:
        return None, "❌ Cannot reach CRM - check URL or network"

    except Exception as e:
        return None, f"ⓘ CRM check error: {str(e)}"


def open_crm_in_browser(crm_url: str) -> bool:
    """
    Open CRM in browser (system default).

    Args:
        crm_url: Organization CRM URL

    Returns:
        True if opened successfully
    """
    try:
        webbrowser.open(crm_url)
        return True
    except Exception:
        return False
