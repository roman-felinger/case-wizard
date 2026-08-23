"""A small number of high-value streamlit.testing.v1.AppTest smoke tests
for main.py.

main.py itself is ~1000 lines of Streamlit UI rendering tightly coupled to
a live Streamlit session (st.button, st.text_input, st.form, ...) and is
NOT unit-tested here beyond these two smoke checks -- see the other test_*
files for the actual logic (settings/checks/azdo_check/crm_playwright/
progress) that main.py merely orchestrates.

Every external dependency main.py's top-level code can reach on a first
render is mocked at its source module before AppTest executes the script:
settings.load_config, checks.run_health_check, crm_playwright's
check_login_headless (imported into main.py as check_crm_login_dom),
azdo_check.check_azdo_access, and shutdown_watcher.start_once. AppTest
executes main.py in-process by re-importing its dependencies through the
normal `sys.modules` cache, so patching the attribute on the already
-imported module (imported once at the top of this file, same as every
other test file) is visible to main.py's own `from x import y` at exec
time. No real subprocess, browser, or network call happens in this file.

Kept intentionally small: two scenarios (a rendering crash on first load,
and the all-green preflight banner) rather than exhaustively driving every
button/form -- see the module docstring above for why the rest of main.py
is out of scope for plain unittest.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from streamlit.testing.v1 import AppTest
    APPTEST_IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on the streamlit version installed
    AppTest = None
    APPTEST_IMPORT_ERROR = e

# Import once so mock.patch.object below patches the same module objects
# main.py's own `from x import y` will resolve against at exec time.
import checks
import settings
import crm_playwright
import azdo_check
import shutdown_watcher

MAIN_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")

BASE_CONFIG = {
    "azdo_pat": "fake-pat",
    "azdo_org_url": "https://dev.azure.com/fakeorg",
    "crm_url": "https://fake-crm.example.com/",
    "open_in_vscode": True,
    "run_tests": False,
    "run_lint": False,
    "run_build": False,
    "max_prs": 20,
    "skip_ado": False,
    "include_style_prs": True,
    "claude_timeout": 600,
    "claude_model": None,
}

ALL_GREEN_HEALTH = {
    "Python 3.8+": {"status": True, "message": "Python 3.11.0"},
    "Git": {"status": True, "message": "git version 2.40.0"},
    "Claude CLI": {"status": True, "message": "1.2.3"},
    "Claude Logged In": {"status": True, "message": "Responding to prompts"},
    "CRM Browser Tab": {"status": True, "message": "Logged in"},
    "Azure DevOps Config": {"status": True, "message": "ADO: https://dev.azure.com/fakeorg"},
}


@unittest.skipIf(AppTest is None, f"streamlit.testing.v1.AppTest unavailable: {APPTEST_IMPORT_ERROR}")
class MainWizardSmokeTests(unittest.TestCase):
    def _patches(self, config, health):
        return [
            mock.patch.object(settings, "load_config", return_value=dict(config)),
            mock.patch.object(checks, "run_health_check", return_value=health),
            mock.patch.object(crm_playwright, "check_login_headless", return_value=(True, "Logged in")),
            mock.patch.object(azdo_check, "check_azdo_access", return_value=(True, "Connected to fakeorg")),
            mock.patch.object(shutdown_watcher, "start_once", return_value=None),
        ]

    def test_first_render_does_not_raise_when_a_critical_check_fails(self):
        health = dict(ALL_GREEN_HEALTH)
        health["Git"] = {"status": False, "message": "Git not found in PATH"}
        patches = self._patches(BASE_CONFIG, health)
        with _apply(patches):
            at = AppTest.from_file(MAIN_PY, default_timeout=30).run()
        self.assertEqual(at.exception, [])
        self.assertTrue(any("Setup Verification" in t.value for t in at.title))

    def test_all_green_health_shows_the_all_systems_ready_banner(self):
        patches = self._patches(BASE_CONFIG, ALL_GREEN_HEALTH)
        with _apply(patches):
            at = AppTest.from_file(MAIN_PY, default_timeout=30).run()
        self.assertEqual(at.exception, [])
        success_texts = [el.value for el in at.success]
        self.assertTrue(any("All systems ready" in t for t in success_texts))


class _apply:
    """Enter/exit a list of already-constructed mock.patch context managers
    together, so _patches() can build the list once and this test file
    doesn't need a fixed-arity `with a, b, c, d, e:` per scenario."""

    def __init__(self, patches):
        self._patches = patches

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc_info):
        for p in reversed(self._patches):
            p.stop()
        return False


if __name__ == "__main__":
    unittest.main()
