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
    """Check if Claude CLI is working by running a test prompt."""
    try:
        # Run a simple test prompt to verify Claude is working
        result = subprocess.run(
            ["claude", "-p"],
            input="Say 'OK' if you can read this.",
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0 and result.stdout:
            return True, "Responding to prompts"
        elif "not authenticated" in result.stderr.lower() or "login" in result.stderr.lower():
            return False, "Not logged in (run: claude login)"
        elif result.returncode != 0:
            return False, "Not responding"
        else:
            return False, "Check failed"
    except FileNotFoundError:
        return False, "Claude CLI not found"
    except subprocess.TimeoutExpired:
        return False, "Timeout (Claude not responding)"
    except Exception as e:
        return False, "Check failed"


def check_crm_tab(crm_url: str = None):
    """Check if CRM is accessible and user might be logged in."""
    if not crm_url:
        return None, "CRM URL not configured"

    try:
        from crm_check import check_crm_accessibility
        logged_in, message = check_crm_accessibility(crm_url)

        if logged_in is True:
            return True, "Logged in to CRM"
        elif logged_in is False:
            return None, "CRM accessible - awaiting login"
        else:
            return None, "CRM check pending"

    except ImportError:
        return None, "CRM check unavailable"
    except Exception:
        return None, "CRM check pending"


def check_config(config):
    """Check if config is set up (warning, not critical)."""
    if config.get("azdo_pat") and config.get("azdo_org_url"):
        return True, f"ADO: {config['azdo_org_url']}"
    # Return None (warning) instead of False (critical)
    # This allows setup wizard to show config form
    return None, "Azure DevOps: Configure in next step"


def run_health_check(config):
    """Run all health checks and return results."""
    checks = [
        ("Python 3.8+", check_python()),
        ("Git", check_git()),
        ("Claude CLI", check_claude()),
        ("Claude Logged In", check_claude_login()),
        ("CRM Browser Tab", check_crm_tab(config.get("crm_url"))),
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
