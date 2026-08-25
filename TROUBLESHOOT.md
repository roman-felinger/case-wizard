# Troubleshooting

## System checks red (Python / Git / Claude CLI / Claude Working)

The app tells you exactly what's missing and links to the installer. After fixing:

- **Claude CLI not found / not working:** install from
  [claude.com/claude-code](https://claude.com/claude-code), then run `claude login`
  in a terminal. "Claude Working" runs a real test prompt, not just a version check —
  if it's red, `claude login` again.
- **Python / Git:** install, restart your terminal, click **Recheck**.

## CRM shows not logged in

The app checks this via case-brief's own dedicated Chromium window
(`case-brief/chrome-automation-profile/`) — **not** your regular browser, since
modern browsers block external tools from reading their session cookies (an
anti-malware protection, not a bug on our end).

1. Click **🔑 Log in to CRM** — a real browser window opens.
2. Log in there. It detects success and closes itself automatically — no need to
   click anything after.
3. That session persists across app restarts, so this is normally one-time.

**If the window flashes and closes instantly instead of opening:** a previous
session didn't shut down cleanly and left the profile locked. Click
**♻️ Reset session**, then try **Log in to CRM** again.

## Azure DevOps shows invalid / not connected

1. Check the org URL format: `https://dev.azure.com/yourorg`
2. Check the PAT hasn't expired (max 1 year) and has scopes **Code (Read)** and
   **Project and Team (Read)**. Create a new one at
   `https://dev.azure.com/yourorg/_usersSettings/tokens` if needed.
3. Paste both into the ADO section and click **Check Connection** — it saves
   automatically the moment it succeeds.

## A stage fails

**Brief:** almost always a CRM login issue — check that first, click **Recheck CRM**,
try again. Otherwise check the case number actually exists in CRM.

**Guide:** needs an existing brief for that case number (run Brief first) and a
working Claude login. Check the preflight status, then try again.

**Solve:** needs a real git clone URL (paste it in the Solve tab before running) and
push access isn't required — it only clones, branches, and commits locally; you
push yourself. Common failures: wrong/inaccessible repo URL, or the guide it's
reading doesn't exist yet (run Guide first).

## Network / firewall

If CRM or ADO time out rather than showing a clear error: check VPN if your org
requires one, and that `*.dynamics.com` and `dev.azure.com` aren't blocked.

## Still stuck

1. Preflight all green? If not, that's the actual problem — fix it there first.
2. Restart the app.
3. Check the full output in the stage tab's "📋 Full Output" expander for the real
   error instead of the summary line.
