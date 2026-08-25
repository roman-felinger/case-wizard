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
python case_brief.py -h                    # all options
```

CRM scraping pulls the whole case (every populated field, Notes, the Activity
Timeline) rather than a curated subset. Azure DevOps branches/PRs are resolved
directly from any link already pasted into the CRM case (description, a note,
a custom field) — one API call each, no searching; there is no broader
org-wide search (see `lib/ado_api.py`'s module docstring for why).

Requires:
- CRM tab open and logged in (browser scraping via Chrome)
- `AZDO_PAT` env var (Azure DevOps token)

Output: `case-briefs/case-<number>.md`

## Config

The Azure DevOps org, CRM ticket field, and CRM host pattern are all fixed
in `case_brief.py`/`lib/ado_api.py` — this tool only ever talks to one org
and one CRM. `config.json` (optional, see `config.example.json`) only
covers the Chrome automation profile.

## Status

✅ CRM (browser scraping), ✅ Azure DevOps — working
