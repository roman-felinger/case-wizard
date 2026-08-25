"""Azure DevOps Basic-auth-from-PAT helpers.

The one piece of case-brief's, case-guide's, and app's Azure DevOps code
that is pure, stable, and was already identical across all three copies.
The higher-level search/query logic (branch/PR search, pagination, error
handling) stays independent per project -- see case-brief/CLAUDE.md and
case-guide/CLAUDE.md's TODO before expanding this file's scope; the two
projects' search logic has already diverged on purpose.
"""
import base64
import os


def get_pat(env_var):
    pat = os.environ.get(env_var)
    if not pat:
        raise RuntimeError(
            f"Azure DevOps PAT not found. Set env var {env_var} "
            "(create one at https://dev.azure.com/{org}/_usersSettings/tokens)."
        )
    return pat


def auth_header(pat):
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
