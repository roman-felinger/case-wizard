"""OAuth (Entra ID) authentication for the Dataverse Web API -- the
maintainable alternative to lib/browser.py's cookie-riding auth bridge.

Investigated 2026-08-26 (see CLAUDE.md's "Dataverse API access" section for
the full writeup). Findings:

  - No admin app registration is required. Entra ID's well-known, Microsoft
    first-party PUBLIC client below (native/desktop app type -- no secret,
    same category as e.g. Azure CLI's own client ID) is already granted
    delegated `user_impersonation` access to the Dataverse API in this
    tenant, so a plain user can sign in and get a token without an admin
    registering or consenting to anything new.
  - Verified end-to-end: device-code sign-in as rfelinger@artex-is.cz
    against tenant 2fb165ea-8dc4-4800-ace7-db202bb064e6, WhoAmI returned
    200, and a live `incidents` query returned real case data -- so this
    identity's existing Dataverse security role (the same one the browser
    session already used) covers read access through this path too.
  - If a tenant *has* locked this client down (Conditional Access, or a
    user-consent restriction), the token request below fails with a
    specific AADSTS error instead of silently doing something else --
    see get_access_token's docstring for what that means for the caller.

Token cache is a plaintext-on-disk-but-gitignored (case-brief/.token_cache/,
already in .gitignore) MSAL SerializableTokenCache -- holds a refresh token,
which is a credential, so it must never be committed or logged. This lets a
device-code sign-in happen only once; every run after that is silent
(acquire_token_silent, using the cached refresh token) until that refresh
token itself expires or is revoked.
"""
import os

import msal

# The org this tool only ever talks to (see case_brief.py's CRM_ORIGIN) --
# also the Dataverse API's OAuth resource identifier (Dataverse uses the
# environment's own URL as its resource/audience, not a fixed GUID).
RESOURCE = "https://artex-crm.crm4.dynamics.com"

# Well-known Microsoft first-party public client ID (no secret -- see
# module docstring). Multi-tenant authority below so this works regardless
# of which tenant `common`/`organizations` login resolves to.
CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d"
AUTHORITY = "https://login.microsoftonline.com/organizations"

TOKEN_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".token_cache", "dataverse.bin"
)


class DataverseAuthError(RuntimeError):
    """Auth failed -- distinct from a plain RuntimeError so callers (and
    case_brief.py's top-level error handling) can recognize "you need to
    fix sign-in/permissions" without string-matching a message."""


def _load_cache():
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_PATH):
        try:
            with open(TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
                cache.deserialize(f.read())
        except (OSError, ValueError):
            pass  # corrupt/unreadable cache -- fall through to a fresh sign-in rather than crash
    return cache


def _save_cache(cache):
    if not cache.has_state_changed:
        return
    os.makedirs(os.path.dirname(TOKEN_CACHE_PATH), exist_ok=True)
    with open(TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
        f.write(cache.serialize())


def get_access_token(resource=RESOURCE, app_factory=msal.PublicClientApplication):
    """Returns a valid Dataverse access token.

    Tries a silent refresh from the on-disk cache first (no user
    interaction). Falls back to an interactive device-code sign-in (prints
    a URL + one-time code to stdout, then blocks polling until you complete
    it in any browser, or it expires) only when there's no cached account
    or the silent refresh fails.

    `app_factory` is overridable purely for testing (inject a fake
    PublicClientApplication) -- production callers should never pass it.

    Raises DataverseAuthError with a specific message on failure, including
    the case where this tenant's Conditional Access / consent policy blocks
    the well-known client entirely -- that needs an Entra ID admin action
    (approve/consent the client, or register a dedicated app instead), not
    a retry.
    """
    cache = _load_cache()
    app = app_factory(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent([f"{resource}/.default"], account=accounts[0])

    if not result:
        flow = app.initiate_device_flow(scopes=[f"{resource}/.default"])
        if "user_code" not in flow:
            raise DataverseAuthError(
                "Could not start Dataverse sign-in: "
                f"{flow.get('error')} - {flow.get('error_description')}"
            )
        # Loud and boxed, not just MSAL's one-line flow["message"] -- this is
        # a one-time interruption in the middle of an otherwise-silent CLI
        # run, easy to miss among case_brief.py's other progress lines. Also
        # flush=True throughout: without it this can sit in Python's stdout
        # buffer unseen whenever stdout isn't a live terminal (piped/
        # redirected output, a background-run wrapper, ...), and this is the
        # one and only thing standing between the caller and an apparently
        # silent hang until the device code expires (~15 min).
        print("\n" + "=" * 70, flush=True)
        print("ACTION NEEDED: sign in to Dataverse to continue.", flush=True)
        print(flow["message"], flush=True)
        print("Waiting for you to finish signing in in your browser...", flush=True)
        print("=" * 70 + "\n", flush=True)
        result = app.acquire_token_by_device_flow(flow)

    _save_cache(app.token_cache)

    if not result or "access_token" not in result:
        result = result or {}
        raise DataverseAuthError(
            "Dataverse sign-in failed: "
            f"{result.get('error')} - {result.get('error_description')}. "
            "If this mentions consent, Conditional Access, or the client "
            "being blocked, an Entra ID admin needs to approve app access "
            "for this tenant -- see CLAUDE.md's Dataverse API section."
        )
    return result["access_token"]
