"""Unit tests for settings.py's config load/save/clear logic.

Scope: keyring is entirely mocked (unittest.mock.patch) -- no real Windows
Credential Manager writes ever happen here, and no real file outside
tempfile is ever touched: every test that exercises load_config/save_config/
clear_secrets patches the module-level `settings.CONFIG_FILE` constant to a
tempfile path instead of the real `.streamlit_config.json` next to this
module (which may hold a real PAT on a dev machine).

Specifically locked in:
- The keyring-failure-falls-back-to-file behavior for both save_config and
  load_config -- this fallback was added this session specifically so a
  keyring backend that raises (locked keychain, headless system, etc.)
  doesn't silently lose the user's PAT instead of degrading to file storage.
- KEYRING_AVAILABLE's own detection logic (import-time probe), exercised by
  reloading the module with a mocked `keyring` under both outcomes.
- get_env_dict as of this session should set ONLY AZDO_PAT and nothing else
  -- several other env vars (org url, skip-ado, max-prs, model, etc.) were
  deliberately removed as dead code that nothing on the reading end ever
  read (see the docstring in settings.py). This is regression-tested
  explicitly so a future change doesn't quietly resurrect them.

Deliberately skipped: real keyring backend behavior (SecretService/DPAPI
specifics), real file permissions/locking -- those need a real OS keychain
or a real filesystem and are out of scope for a pure-logic suite.

Run with: python -m unittest discover -s tests -v   (from app/)
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import settings


def _tmp_config_path(tmpdir):
    return Path(tmpdir) / ".streamlit_config.json"


class LoadConfigTests(unittest.TestCase):
    def test_returns_defaults_when_no_file_exists_and_keyring_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", False):
                config = settings.load_config()
        self.assertEqual(config, settings.DEFAULTS)
        # Defensive: must be a copy, not the live DEFAULTS dict.
        self.assertIsNot(config, settings.DEFAULTS)

    def test_file_config_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)
            cfg_path.write_text(json.dumps({"crm_url": "https://custom.example.com/"}))
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", False):
                config = settings.load_config()
        self.assertEqual(config["crm_url"], "https://custom.example.com/")
        # Untouched defaults still present.
        self.assertEqual(config["max_prs"], settings.DEFAULTS["max_prs"])

    def test_corrupt_config_file_is_ignored_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)
            cfg_path.write_text("{not valid json")
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", False):
                config = settings.load_config()  # must not raise
        self.assertEqual(config, settings.DEFAULTS)

    def test_keyring_pat_overrides_file_pat_when_keyring_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)
            cfg_path.write_text(json.dumps({"azdo_pat": "file-pat"}))
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", True), \
                 mock.patch.object(settings.keyring, "get_password", return_value="keyring-pat") as get_pw:
                config = settings.load_config()
        self.assertEqual(config["azdo_pat"], "keyring-pat")
        get_pw.assert_called_once_with(settings.SERVICE_NAME, "azdo_pat")

    def test_keyring_raising_on_read_falls_back_to_the_file_pat(self):
        """Regression test: a keyring backend that raises on get_password
        must not wipe out a PAT that was previously saved to the file
        fallback -- load_config should keep the file's value, not None."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)
            cfg_path.write_text(json.dumps({"azdo_pat": "file-pat"}))
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", True), \
                 mock.patch.object(settings.keyring, "get_password", side_effect=Exception("backend down")):
                config = settings.load_config()  # must not raise
        self.assertEqual(config["azdo_pat"], "file-pat")

    def test_keyring_returning_none_leaves_file_pat_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)
            cfg_path.write_text(json.dumps({"azdo_pat": "file-pat"}))
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", True), \
                 mock.patch.object(settings.keyring, "get_password", return_value=None):
                config = settings.load_config()
        self.assertEqual(config["azdo_pat"], "file-pat")


class SaveConfigTests(unittest.TestCase):
    def test_saves_pat_to_keyring_and_omits_it_from_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", True), \
                 mock.patch.object(settings.keyring, "set_password") as set_pw:
                settings.save_config({"azdo_pat": "secret-pat", "crm_url": "https://x/"})
            set_pw.assert_called_once_with(settings.SERVICE_NAME, "azdo_pat", "secret-pat")
            saved = json.loads(cfg_path.read_text())
        self.assertNotIn("azdo_pat", saved)
        self.assertEqual(saved["crm_url"], "https://x/")

    def test_keyring_raising_on_write_falls_back_to_saving_the_pat_in_the_file(self):
        """Regression test: this fallback was added this session so a
        failed keyring backend on save doesn't silently lose the PAT --
        it must land in the file config instead of disappearing."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", True), \
                 mock.patch.object(settings.keyring, "set_password", side_effect=Exception("backend down")):
                settings.save_config({"azdo_pat": "secret-pat"})  # must not raise
            saved = json.loads(cfg_path.read_text())
        self.assertEqual(saved["azdo_pat"], "secret-pat")

    def test_saves_pat_to_file_directly_when_keyring_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", False):
                settings.save_config({"azdo_pat": "secret-pat"})
            saved = json.loads(cfg_path.read_text())
        self.assertEqual(saved["azdo_pat"], "secret-pat")

    def test_does_not_attempt_keyring_write_when_pat_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", True), \
                 mock.patch.object(settings.keyring, "set_password") as set_pw:
                settings.save_config({"azdo_pat": None, "crm_url": "https://x/"})
            set_pw.assert_not_called()

    def test_claude_api_key_is_never_persisted_to_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", False):
                settings.save_config({"claude_api_key": "should-not-be-saved", "crm_url": "https://x/"})
            saved = json.loads(cfg_path.read_text())
        self.assertNotIn("claude_api_key", saved)


class ClearSecretsTests(unittest.TestCase):
    def test_deletes_keyring_entry_and_removes_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)
            cfg_path.write_text("{}")
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", True), \
                 mock.patch.object(settings.keyring, "delete_password") as delete_pw:
                settings.clear_secrets()
            delete_pw.assert_called_once_with(settings.SERVICE_NAME, "azdo_pat")
        self.assertFalse(cfg_path.exists())

    def test_swallows_keyring_delete_errors_and_still_removes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)
            cfg_path.write_text("{}")
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", True), \
                 mock.patch.object(settings.keyring, "delete_password", side_effect=Exception("not found")):
                settings.clear_secrets()  # must not raise
        self.assertFalse(cfg_path.exists())

    def test_missing_config_file_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _tmp_config_path(tmp)  # never created
            with mock.patch.object(settings, "CONFIG_FILE", cfg_path), \
                 mock.patch.object(settings, "KEYRING_AVAILABLE", False):
                settings.clear_secrets()  # must not raise (missing_ok=True)


class GetEnvDictTests(unittest.TestCase):
    """Regression coverage: get_env_dict should set ONLY AZDO_PAT. Other env
    vars (org url, skip-ado, max-prs, model, run-tests/lint/build, etc.)
    were deliberately removed this session as dead code -- the stage
    scripts read those as CLI flags instead, not environment variables."""

    def test_sets_only_azdo_pat_when_pat_is_configured(self):
        base_env = {"SOME_UNRELATED_VAR": "1"}
        with mock.patch.dict(os.environ, base_env, clear=True):
            env = settings.get_env_dict({"azdo_pat": "secret-pat", "azdo_org_url": "https://x/"})
        self.assertEqual(env["AZDO_PAT"], "secret-pat")
        # Everything else that was in os.environ passes through untouched...
        self.assertEqual(env["SOME_UNRELATED_VAR"], "1")
        # ...but no other case-wizard-specific var got added.
        added_keys = set(env) - set(base_env)
        self.assertEqual(added_keys, {"AZDO_PAT"})

    def test_does_not_set_azdo_pat_when_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            env = settings.get_env_dict({"azdo_org_url": "https://x/"})
        self.assertNotIn("AZDO_PAT", env)

    def test_does_not_set_azdo_pat_when_pat_is_empty_string(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            env = settings.get_env_dict({"azdo_pat": ""})
        self.assertNotIn("AZDO_PAT", env)

    def test_never_sets_removed_dead_code_env_vars(self):
        config = {
            "azdo_pat": "secret-pat",
            "azdo_org_url": "https://dev.azure.com/org",
            "skip_ado": True,
            "max_prs": 5,
            "claude_model": "opus",
            "run_tests": True,
            "run_lint": True,
            "run_build": True,
            "claude_timeout": 42,
        }
        with mock.patch.dict(os.environ, {}, clear=True):
            env = settings.get_env_dict(config)
        self.assertEqual(set(env), {"AZDO_PAT"})

    def test_env_dict_is_a_copy_and_does_not_mutate_real_os_environ(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings.get_env_dict({"azdo_pat": "secret-pat"})
            self.assertNotIn("AZDO_PAT", os.environ)


class KeyringAvailableDetectionTests(unittest.TestCase):
    """KEYRING_AVAILABLE is computed once, at import time, by probing
    keyring.get_password. These tests reload the module under a mocked
    `keyring` to exercise both outcomes of that probe without ever hitting
    a real Credential Manager backend."""

    def _reload_with(self, fake_keyring_module):
        with mock.patch.dict(sys.modules, {"keyring": fake_keyring_module}):
            importlib.reload(settings)
        # Restore the real module state for other tests in the suite.
        self.addCleanup(lambda: importlib.reload(settings))

    def test_keyring_available_true_when_probe_succeeds(self):
        fake_keyring = mock.Mock()
        fake_keyring.get_password.return_value = None
        self._reload_with(fake_keyring)
        self.assertTrue(settings.KEYRING_AVAILABLE)

    def test_keyring_available_false_when_probe_raises(self):
        fake_keyring = mock.Mock()
        fake_keyring.get_password.side_effect = Exception("no backend")
        self._reload_with(fake_keyring)
        self.assertFalse(settings.KEYRING_AVAILABLE)

    def test_keyring_available_false_when_keyring_is_not_importable(self):
        with mock.patch.dict(sys.modules, {"keyring": None}):
            importlib.reload(settings)
        self.addCleanup(lambda: importlib.reload(settings))
        self.assertFalse(settings.KEYRING_AVAILABLE)


if __name__ == "__main__":
    unittest.main()
