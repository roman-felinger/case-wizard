"""
Automatic CRM login verification.

Opens browser, waits for user to log in, verifies authentication, then closes.
"""

import asyncio
import time
from pathlib import Path

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


async def check_crm_login(crm_url: str, timeout_seconds: int = 30) -> tuple[bool, str]:
    """
    Check if CRM tab is accessible and user is logged in.

    Opens browser, waits for login, verifies authentication.

    Returns:
        (success: bool, message: str)
        - (True, "Logged in") if user authenticated
        - (False, "Login timeout") if user didn't log in within timeout
        - (False, "Error: ...") if something failed
    """

    if not PLAYWRIGHT_AVAILABLE:
        return False, "Playwright not installed (needed for CRM check)"

    try:
        async with async_playwright() as p:
            # Launch browser
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                # Navigate to CRM
                await page.goto(crm_url, wait_until="domcontentloaded", timeout=10000)

                # Wait for user to log in (30 seconds default)
                # Check for authenticated state by looking for CRM-specific elements
                start_time = time.time()
                authenticated = False

                while time.time() - start_time < timeout_seconds:
                    try:
                        # Check for CRM authenticated indicators
                        # Look for: nav bar, header, main content area
                        nav = await page.query_selector('[role="navigation"]')
                        header = await page.query_selector('header')
                        main_content = await page.query_selector('main, [role="main"]')

                        # If we see these elements, user is likely authenticated
                        if nav or header or main_content:
                            authenticated = True
                            break

                        # Also check URL didn't stay at login page
                        current_url = page.url
                        if "login" not in current_url.lower() and "signin" not in current_url.lower():
                            # If we navigated away from login, user probably authenticated
                            authenticated = True
                            break

                    except Exception:
                        pass

                    # Wait a bit before checking again
                    await asyncio.sleep(1)

                if authenticated:
                    return True, "✅ CRM authenticated and ready"
                else:
                    return False, f"⏳ No login detected after {timeout_seconds} seconds"

            finally:
                await context.close()
                await browser.close()

    except Exception as e:
        return False, f"Error: {str(e)}"


def check_crm_login_sync(crm_url: str, timeout_seconds: int = 30) -> tuple[bool, str]:
    """
    Synchronous wrapper for check_crm_login (for Streamlit compatibility).
    """
    try:
        result = asyncio.run(check_crm_login(crm_url, timeout_seconds))
        return result
    except RuntimeError:
        # Event loop already running (Streamlit environment)
        # Just return a message that checking needs to happen differently
        return None, "Manual check needed (run in separate process)"
    except Exception as e:
        return False, f"Error: {str(e)}"
