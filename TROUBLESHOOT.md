# Troubleshooting

## `claude` CLI not found / not working

Install from [claude.com/claude-code](https://claude.com/claude-code), then run
`claude login` in a terminal. If case-guide/case-solve fail with a real `claude`
error rather than "not found", `claude login` again — a session can expire.

## CRM shows not logged in / case-brief can't read the case

case-brief opens its own dedicated Chromium window (`case-brief/chrome-automation-
profile/`) — **not** your regular browser, since modern browsers block external
tools from reading their session cookies (an anti-malware protection, not a bug on
our end).

1. Run `python case-brief/case_brief.py <case-number>` — a real browser window opens
   pointed at CRM.
2. Log in there if prompted. The session persists (cached in that dedicated
   profile), so this is normally a one-time thing across runs.

**If the window flashes and closes instantly instead of opening:** a previous run
didn't shut down cleanly and left the profile locked. Delete
`case-brief/chrome-automation-profile/` and try again.

**If you don't want the browser to close automatically when case-brief finishes:**
pass `--keep-browser-open`.

## Azure DevOps errors (case-brief, case-guide)

1. Check the org URL format: `https://dev.azure.com/yourorg` (pass via `--org-url`
   or `azure_devops.org_url` in that stage's `config.json`).
2. Check the `AZDO_PAT` environment variable is set and hasn't expired (PATs max out
   at 1 year), with scopes **Code (Read)** and **Project and Team (Read)**. Create a
   new one at `https://dev.azure.com/yourorg/_usersSettings/tokens` if needed.
3. A different PAT env var name can be set via `--pat-env-var` / `azure_devops.pat_env_var`.

## A stage fails

**Brief:** almost always a CRM login issue — see above. Otherwise check the case
number actually exists in CRM. `--demo` skips CRM/ADO entirely if you just want to
check the script itself still runs.

**Guide:** needs an existing brief for that case number (run case-brief first) and a
working `claude` login. `--show-prompt` assembles the prompt without calling `claude`,
useful for isolating whether the problem is upstream (brief/ADO data) or in the
`claude` call itself.

**Solve:** needs a real, reachable git clone URL (`--repo`) — push access isn't
required, it only clones, branches, and commits locally; you push yourself. Common
failures: wrong/inaccessible repo URL, or the guide it's reading doesn't exist yet
(run case-guide first). `--show-plan` previews Claude's plan without applying
anything; `--dry-run` applies changes without committing.

## Network / firewall

If CRM or ADO time out rather than showing a clear error: check VPN if your org
requires one, and that `*.dynamics.com` and `dev.azure.com` aren't blocked.

## Still stuck

Run the failing stage with `-h` to confirm you're passing what it expects, then
re-run it directly (not through anything else) and read the actual error in the
terminal output — each stage prints exactly what failed rather than a generic
message.
