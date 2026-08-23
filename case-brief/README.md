# case-brief

Pulls a support case's context from Dynamics 365 CRM (and optionally Azure
DevOps, Business Central) and compiles it into one Markdown brief opened in
VS Code — so you start solving instead of tab-hopping between portals.

CRM needs no admin-approved app registration: it's read from a tab you have
open and logged into in a dedicated, separate Chrome profile, riding on that
tab's own session. Azure DevOps uses a self-service Personal Access Token
(no admin needed either). Business Central browser scraping exists but is
off by default (`--with-bc`) while its selectors are still being worked out.

## Try it right now (no setup)

```
python case_brief.py --demo
```

Fake sample data end-to-end, so you can see the report format before
touching real config.

## Real setup

1. **Install dependencies** (or just use the checked-in `.venv`):
   ```
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. **Config is optional.** Every setting has a built-in default, and every one
   can be set with a command-line flag instead of a file — run `python case_brief.py -h`
   to see them all. If you'd rather have a persistent file so you're not
   passing flags every time:
   ```
   copy config.example.json config.json
   ```
   The only thing you actually need to set is `azure_devops.org_url` (or pass
   `--org-url`) once you want ADO lookups. Everything else — `ticket_field`,
   `url_patterns`, `azure_devops.project` (leave `null` to search every project
   in the org instead of one you'd have to know), `azure_devops.max_prs` — only
   needs touching if your setup differs from the defaults.

3. **Azure DevOps PAT** (only if you're not using `--skip-ado`):
   - `https://dev.azure.com/{yourorg}/_usersSettings/tokens` → New Token, scopes:
     **Code (Read)** (for branches/PRs), plus **Project and Team (Read)** if you're
     leaving `project` as `null` (needed to list all projects in the org)
   - `setx AZDO_PAT "your-pat-here"` then open a **new** terminal (and if you're
     running from VS Code's integrated terminal, fully restart VS Code --
     a new terminal tab alone won't pick up the updated environment variable)

## Usage

```
python case_brief.py T2611845          # look up this case directly, no manual search needed
python case_brief.py T2611845 --skip-ado
python case_brief.py                   # auto-detect from a CRM case tab you already have open
python case_brief.py --with-bc         # also scrape an open Business Central tab
python case_brief.py --no-open         # don't launch VS Code

# one-off overrides without touching config.json:
python case_brief.py T2611845 --org-url https://dev.azure.com/myorg --project MyProject --max-prs 200
```

Run `python case_brief.py -h` for the complete list of flags (Azure DevOps,
CRM/BC host matching, Chrome profile/port, output location — anything that's
in `config.json` can be overridden this way).

### Each run

The script launches a **separate** Chrome profile (not your normal browsing
profile), minimized so it doesn't steal focus — check your taskbar for a
second Chrome icon. Sign into CRM there (any page — you don't need to find
the specific case); the script polls in the background and notices
automatically once you're signed in, no keypress needed.

Once it's done scraping, it **closes that Chrome window itself**. This
trades away session persistence (you'll sign in again next run) for a clean
slate every time — a deliberate choice. Your last-used CRM/BC URLs are still
remembered and reopened automatically on the next launch, so at least you're
not retyping them.

Output lands in `case-briefs/case-<number>.md` and opens automatically in VS Code.

## Layout

```
case_brief.py           CLI entry point / orchestration
lib/browser.py          Launches/attaches to the dedicated Chrome profile via CDP
lib/crm_scrape.py       CRM case lookup (by ticket number, or by an open tab's URL)
lib/bc_scrape.py        Business Central tab scraping (--with-bc, still rough)
lib/ado_api.py          Azure DevOps REST API (PAT auth)
lib/report.py           Markdown rendering + writing + opening in VS Code
config.example.json     Template -- copy to config.json and edit that copy (optional, see Setup)
```

## Status

Verified against real data: CRM lookup by ticket number (title, customer,
owner, priority, status, created date, description) works end to end against
a live case. Azure DevOps not yet exercised against a real org/PAT. Business
Central scraping found 0 fields on first real attempt — `bc_scrape.py` was
broadened (multi-frame search, wider selector, raw-text fallback) but is
unverified since; expect to iterate on it with real output once you're back
to testing that part with `--with-bc`.
