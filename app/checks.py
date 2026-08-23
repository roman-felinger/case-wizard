"""System health checks and diagnostics for case-wizard."""
import subprocess
import sys
from pathlib import Path


def check_python():
    """Check Python version."""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        return True, f"Python {version.major}.{version.minor}.{version.micro}"
    return False, f"Python {version.major}.{version.minor} (need 3.8+)"


def check_git():
    """Check if git is installed."""
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, "Git not found in PATH"
    except Exception as e:
        return False, str(e)


def check_claude():
    """Check if Claude CLI is available."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, "Claude CLI not in PATH"
    except Exception as e:
        return False, "Claude CLI not installed"


def check_claude_login():
    """Check if Claude is logged in."""
    try:
        result = subprocess.run(
            ["claude", "login", "--check"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, "Logged in"
        return False, "Not logged in (run: claude login)"
    except Exception:
        # If --check doesn't work, assume not logged in
        return False, "Not logged in (run: claude login)"


def check_crm_tab():
    """Check if CRM tab might be open (heuristic)."""
    # This is hard to check directly without browser integration
    # Return as warning (user needs to verify)
    return None, "Please verify: Dynamics 365 tab open + logged in"


def check_config(config):
    """Check if config is set up."""
    if config.get("azdo_pat") and config.get("azdo_org_url"):
        return True, f"ADO: {config['azdo_org_url']}"
    return False, "Azure DevOps PAT or org URL missing"


def run_health_check(config):
    """Run all health checks and return results."""
    checks = [
        ("Python 3.8+", check_python()),
        ("Git", check_git()),
        ("Claude CLI", check_claude()),
        ("Claude Logged In", check_claude_login()),
        ("CRM Browser Tab", check_crm_tab()),
        ("Azure DevOps Config", check_config(config)),
    ]

    results = {}
    for name, (status, message) in checks:
        results[name] = {
            "status": status,  # True, False, or None (warning)
            "message": message,
        }

    return results


def get_startup_issues(health_check_results):
    """Get critical issues that block startup."""
    critical = []
    warnings = []

    for check_name, result in health_check_results.items():
        if result["status"] is False:
            critical.append((check_name, result["message"]))
        elif result["status"] is None:
            warnings.append((check_name, result["message"]))

    return critical, warnings
