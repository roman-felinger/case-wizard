"""
Verify Azure DevOps API access.

Test organization URL and PAT token by making actual API calls.
"""

import os
import sys
from typing import Tuple

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.ado_auth import auth_header


def check_azdo_access(org_url: str, pat_token: str, timeout: int = 10) -> Tuple[bool, str]:
    """
    Check if Azure DevOps organization and PAT are valid.

    Makes actual API call to verify credentials work.

    Args:
        org_url: Organization URL (e.g., https://dev.azure.com/myorg)
        pat_token: Personal Access Token
        timeout: Request timeout in seconds

    Returns:
        (success: bool, message: str)
        - (True, "Organization name") if credentials work
        - (False, "Error message") if credentials fail
    """

    if not org_url or not pat_token:
        return False, "Organization URL and PAT are required"

    # Clean up org_url
    org_url = org_url.rstrip("/")
    if not org_url.startswith("http"):
        org_url = f"https://dev.azure.com/{org_url}"

    try:
        headers = auth_header(pat_token)

        # Test API call: Get organization info
        # This is a lightweight endpoint that just verifies auth
        api_url = f"{org_url}/_apis/resourceareas"
        response = requests.get(
            api_url,
            headers=headers,
            timeout=timeout,
        )

        if response.status_code == 200:
            # Success - get org name from URL for display
            org_name = org_url.split("/")[-1]
            return True, f"✅ Connected to {org_name}"

        elif response.status_code == 401:
            return False, "❌ Invalid credentials (check PAT and organization)"

        elif response.status_code == 404:
            return False, "❌ Organization not found (check URL format)"

        else:
            return False, f"❌ API error: {response.status_code}"

    except requests.exceptions.Timeout:
        return False, "⏳ Request timeout (check network/firewall)"

    except requests.exceptions.ConnectionError:
        return False, "❌ Cannot connect to Azure DevOps (check URL)"

    except Exception as e:
        return False, f"❌ Error: {str(e)}"
