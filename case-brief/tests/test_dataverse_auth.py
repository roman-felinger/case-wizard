"""Unit tests for lib/dataverse_auth.py.

msal.PublicClientApplication itself is never exercised here (that would
mean actually talking to Entra ID) -- get_access_token takes an
`app_factory` override specifically so a FakeApp can stand in, matching
the pattern the rest of this test suite uses for external dependencies
(FakePage in test_crm_scrape.py, mocked subprocess/CDP in test_browser.py).

TOKEN_CACHE_PATH is patched to a tempfile path for every test so nothing
here ever touches (or needs) the real gitignored cache.

Run with: python -m unittest discover -s tests -v   (from case-brief/)
      or: python -m pytest tests                     (if pytest is installed)
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import dataverse_auth


class FakeTokenCache:
    """Stands in for msal.SerializableTokenCache -- just enough for
    _load_cache/_save_cache to round-trip through it."""
    def __init__(self):
        self.has_state_changed = False
        self._state = ""

    def deserialize(self, s):
        self._state = s

    def serialize(self):
        return self._state or "{}"


class FakeApp:
    """Stands in for msal.PublicClientApplication. `accounts`,
    `silent_result`, `device_flow`, and `device_result` are set per-test to
    drive get_access_token through its silent/device-code branches."""
    def __init__(self, client_id, authority=None, token_cache=None):
        self.client_id = client_id
        self.authority = authority
        self.token_cache = token_cache
        self.accounts = []
        self.silent_result = None
        self.device_flow = {"user_code": "ABC123", "message": "Go sign in at https://example/device"}
        self.device_result = {"access_token": "tok-abc"}
        self.silent_calls = []
        self.device_flow_calls = 0

    def get_accounts(self):
        return self.accounts

    def acquire_token_silent(self, scopes, account):
        self.silent_calls.append((scopes, account))
        return self.silent_result

    def initiate_device_flow(self, scopes):
        return self.device_flow

    def acquire_token_by_device_flow(self, flow):
        self.device_flow_calls += 1
        return self.device_result


def _factory(app):
    def factory(client_id, authority=None, token_cache=None):
        app.token_cache = token_cache  # mirrors what the real constructor does
        return app
    return factory


class GetAccessTokenTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache_path = os.path.join(self.tmpdir, "dataverse.bin")
        patcher = mock.patch("lib.dataverse_auth.TOKEN_CACHE_PATH", self.cache_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        cache_patcher = mock.patch("lib.dataverse_auth.msal.SerializableTokenCache", FakeTokenCache)
        cache_patcher.start()
        self.addCleanup(cache_patcher.stop)

    def test_silent_refresh_is_used_when_a_cached_account_exists(self):
        app = FakeApp("id")
        app.accounts = [{"username": "u@x.com"}]
        app.silent_result = {"access_token": "silent-tok"}
        token = dataverse_auth.get_access_token(app_factory=_factory(app))
        self.assertEqual(token, "silent-tok")
        self.assertEqual(app.device_flow_calls, 0)  # no interactive prompt needed

    def test_falls_back_to_device_flow_when_no_cached_account(self):
        app = FakeApp("id")
        token = dataverse_auth.get_access_token(app_factory=_factory(app))
        self.assertEqual(token, "tok-abc")
        self.assertEqual(app.device_flow_calls, 1)

    def test_falls_back_to_device_flow_when_silent_refresh_returns_nothing(self):
        app = FakeApp("id")
        app.accounts = [{"username": "u@x.com"}]
        app.silent_result = None  # expired refresh token, e.g.
        token = dataverse_auth.get_access_token(app_factory=_factory(app))
        self.assertEqual(token, "tok-abc")
        self.assertEqual(app.device_flow_calls, 1)

    def test_device_flow_start_failure_raises_a_clear_auth_error(self):
        app = FakeApp("id")
        app.device_flow = {"error": "invalid_client", "error_description": "AADSTS700016: blocked"}
        with self.assertRaises(dataverse_auth.DataverseAuthError) as cm:
            dataverse_auth.get_access_token(app_factory=_factory(app))
        self.assertIn("AADSTS700016", str(cm.exception))

    def test_device_flow_completion_failure_raises_a_clear_auth_error(self):
        app = FakeApp("id")
        app.device_result = {"error": "authorization_pending", "error_description": "AADSTS70016: expired"}
        with self.assertRaises(dataverse_auth.DataverseAuthError) as cm:
            dataverse_auth.get_access_token(app_factory=_factory(app))
        self.assertIn("admin", str(cm.exception).lower())

    def test_save_cache_writes_file_only_when_state_changed(self):
        cache = FakeTokenCache()
        cache.has_state_changed = False
        dataverse_auth._save_cache(cache)
        self.assertFalse(os.path.exists(self.cache_path))

        cache.has_state_changed = True
        dataverse_auth._save_cache(cache)
        self.assertTrue(os.path.exists(self.cache_path))

    def test_load_cache_ignores_a_corrupt_cache_file_instead_of_raising(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            f.write("not valid msal cache state")
        # FakeTokenCache.deserialize doesn't raise on garbage input, so
        # this mainly locks in that _load_cache doesn't crash outright when
        # the file exists but the real msal cache would reject its content
        # (covered structurally -- deserialize raising ValueError/OSError
        # is caught in _load_cache).
        cache = dataverse_auth._load_cache()
        self.assertIsInstance(cache, FakeTokenCache)

    def test_scope_requested_is_resource_default(self):
        app = FakeApp("id")
        app.accounts = [{"username": "u@x.com"}]
        app.silent_result = {"access_token": "t"}
        dataverse_auth.get_access_token(resource="https://org.crm.dynamics.com", app_factory=_factory(app))
        scopes, _ = app.silent_calls[0]
        self.assertEqual(scopes, ["https://org.crm.dynamics.com/.default"])


if __name__ == "__main__":
    unittest.main()
