# case-brief

Gathers case context from CRM and Azure DevOps into one Markdown brief.

## Quick Test

```bash
python case_brief.py --demo        # fake data, no setup needed
```

## Real Setup

Use the repo root's `.venv` — it already has everything all three stages need:

```bash
..\.venv\Scripts\Activate.ps1      # from case-brief/, on Windows
```

Set Azure DevOps PAT:
```powershell
$env:AZDO_PAT = "your-pat-here"    # or setx AZDO_PAT "your-pat-here"
```

## Usage

```bash
python case_brief.py T2611845              # lookup by ticket number
python case_brief.py                       # auto-detect from open CRM tab
python case_brief.py T2611845 --skip-ado   # CRM only, no Azure DevOps
python case_brief.py T2611845 --no-open    # don't open in VS Code
python case_brief.py T2611845 --search-ado # also fall back to a full org-wide ADO search (slow; off by default)
python case_brief.py -h                    # all options
```

CRM scraping pulls the whole case (every populated field, Notes, the Activity
Timeline) rather than a curated subset. Azure DevOps branches/PRs are resolved
directly from any link already pasted into the CRM case (description, a note,
a custom field) — one API call each, no searching. Pass `--search-ado` to also
fall back to a full org-wide branch/PR search when nothing was linked
directly; it's opt-in because it can be slow on orgs with many projects/repos.

Requires:
- CRM tab open and logged in (browser scraping via Chrome)
- `AZDO_PAT` env var (Azure DevOps token)
- Config file or CLI flags for URLs (see `config.example.json`)

Output: `case-briefs/case-<number>.md`

## Config

Edit `config.json` (optional) or use CLI flags. All settings have defaults.

Key overrides:
- `--org-url` — Azure DevOps org
- `--project` — restrict to one project (default: search all)

## Status

✅ CRM (browser scraping), ✅ Azure DevOps — working
