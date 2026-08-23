"""Configuration and settings management for case-wizard."""
import json
import os
from pathlib import Path

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

HERE = Path(__file__).parent
CONFIG_FILE = HERE / ".streamlit_config.json"
SERVICE_NAME = "case-wizard"

# Default settings (fast, no unnecessary overhead)
DEFAULTS = {
    # Secrets (stored in Credential Manager)
    "azdo_pat": None,

    # Normal settings
    "azdo_org_url": None,
    "crm_url": "https://artex-crm.crm4.dynamics.com/",
    "open_in_vscode": True,

    # Advanced settings (defaults optimized for speed)
    "run_tests": False,          # Skip tests (slow)
    "run_lint": False,           # Skip lint (slow)
    "run_build": False,          # Skip build (slow)
    "auto_commit": True,         # Commit automatically (faster)
    "max_prs": 20,               # Fetch PRs (20 enough for context)
    "skip_ado": False,           # Get Azure DevOps context
    "include_style_prs": True,   # Include style examples (helps Claude)
    "claude_timeout": 600,       # 10 min timeout (reasonable)
    "claude_model": None,        # Use Claude's default (faster)
}


def load_config():
    """Load all configuration (secrets from keyring, settings from file)."""
    config = dict(DEFAULTS)

    # Load secrets from keyring
    if KEYRING_AVAILABLE:
        pat = keyring.get_password(SERVICE_NAME, "azdo_pat")
        if pat:
            config["azdo_pat"] = pat

    # Load settings from file
    if CONFIG_FILE.exists():
        try:
            file_config = json.loads(CONFIG_FILE.read_text())
            config.update(file_config)
        except:
            pass

    return config


def save_config(config):
    """Save configuration securely."""
    # Save secrets to keyring
    if KEYRING_AVAILABLE:
        if config.get("azdo_pat"):
            keyring.set_password(SERVICE_NAME, "azdo_pat", config["azdo_pat"])

    # Save non-secret settings to file
    file_config = {k: v for k, v in config.items()
                   if k not in ["azdo_pat", "claude_api_key"]}
    CONFIG_FILE.write_text(json.dumps(file_config, indent=2))


def clear_secrets():
    """Delete all secrets from Credential Manager."""
    if KEYRING_AVAILABLE:
        try:
            keyring.delete_password(SERVICE_NAME, "azdo_pat")
        except:
            pass
    CONFIG_FILE.unlink(missing_ok=True)


def get_env_dict(config):
    """Build environment dict for subprocess calls."""
    env = os.environ.copy()

    if config.get("azdo_pat"):
        env["AZDO_PAT"] = config["azdo_pat"]
    if config.get("azdo_org_url"):
        env["AZDO_ORG_URL"] = config["azdo_org_url"]
    if config.get("azdo_project"):
        env["AZDO_PROJECT"] = config["azdo_project"]

    # Pass advanced settings as env vars for subprocess
    if config.get("skip_ado"):
        env["CASE_GUIDE_SKIP_ADO"] = "1"
    if not config.get("auto_commit"):
        env["CASE_SOLVE_NO_AUTO_COMMIT"] = "1"
    if config.get("run_tests"):
        env["CASE_SOLVE_RUN_TESTS"] = "1"
    if config.get("run_lint"):
        env["CASE_SOLVE_RUN_LINT"] = "1"
    if config.get("run_build"):
        env["CASE_SOLVE_RUN_BUILD"] = "1"
    if config.get("max_prs"):
        env["AZDO_MAX_PRS"] = str(config["max_prs"])
    if config.get("claude_model"):
        env["CLAUDE_MODEL"] = config["claude_model"]

    return env


import os
