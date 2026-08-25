"""Configuration and settings management for case-wizard."""
import json
import os
from pathlib import Path

try:
    import keyring
    # Test if keyring backend is available
    try:
        # Simple test: try to get a dummy value
        keyring.get_password("test", "test")
        KEYRING_AVAILABLE = True
    except Exception:
        # Keyring imported but backend not working (e.g., on headless system)
        KEYRING_AVAILABLE = False
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
    # Note: case-solve always commits as it goes and never pushes on its
    # own - that's not a toggle, so there's no "auto_commit" setting here.
    "run_tests": False,          # Skip tests (slow)
    "run_lint": False,           # Skip lint (slow)
    "run_build": False,          # Skip build (slow)
    "max_prs": 20,               # Fetch PRs (20 enough for context)
    "skip_ado": False,           # Get Azure DevOps context
    "include_style_prs": True,   # Include style examples (helps Claude)
    "claude_timeout": 600,       # 10 min timeout (reasonable)
    "claude_model": None,        # Use Claude's default (faster)
}


def load_config():
    """Load all configuration (secrets from keyring, settings from file)."""
    config = dict(DEFAULTS)

    # Load settings from file first (includes PAT if keyring failed on save).
    # Only known DEFAULTS keys are pulled in -- a key that drops out of
    # DEFAULTS (e.g. a removed setting) is dropped here too, rather than
    # silently round-tripping forever in a file save_config keeps rewriting.
    if CONFIG_FILE.exists():
        try:
            file_config = json.loads(CONFIG_FILE.read_text())
            for key, value in file_config.items():
                if key in DEFAULTS:
                    config[key] = value
        except:
            pass

    # Try to load secrets from keyring (overrides file config)
    if KEYRING_AVAILABLE:
        try:
            pat = keyring.get_password(SERVICE_NAME, "azdo_pat")
            if pat:
                config["azdo_pat"] = pat
        except Exception:
            # Keyring failed, but PAT might be in file config already
            pass

    return config


def save_config(config):
    """Save configuration securely (keyring preferred, fallback to file)."""
    file_config = {k: v for k, v in config.items()
                   if k not in ["claude_api_key"]}

    # Try to save PAT to keyring
    pat_saved_to_keyring = False
    if config.get("azdo_pat") and KEYRING_AVAILABLE:
        try:
            keyring.set_password(SERVICE_NAME, "azdo_pat", config["azdo_pat"])
            pat_saved_to_keyring = True
            # Remove from file config since it's in keyring
            file_config.pop("azdo_pat", None)
        except Exception:
            # Keyring failed, will save to file instead
            pass

    # Save to file (includes PAT if keyring failed)
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
    """Build environment dict for subprocess calls.

    Only AZDO_PAT actually gets read by anything (lib/ado_api.py in each
    stage) - org URL, skip-ADO, max PRs, model, run-tests/lint/build etc.
    are CLI flags on the stage scripts instead, built and passed by main.py's
    run_button block. Don't add more env vars here without also adding the
    os.environ.get() on the reading end - see git history for what setting
    these without a reader looked like.
    """
    env = os.environ.copy()
    if config.get("azdo_pat"):
        env["AZDO_PAT"] = config["azdo_pat"]
    return env
