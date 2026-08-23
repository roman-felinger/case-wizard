# case-brief

Gathers case context from CRM, Azure DevOps, and optionally Business Central into one Markdown brief.

## Quick Test

```bash
python case_brief.py --demo        # fake data, no setup needed
```

## Real Setup

```bash
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
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
python case_brief.py T2611845 --with-bc    # include Business Central
python case_brief.py T2611845 --no-open    # don't open in VS Code
python case_brief.py -h                    # all options
```

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
- `--repo` — suggest which repo to clone

## Status

✅ CRM (browser scraping), ✅ Azure DevOps — working  
⚠️ Business Central — selectors in progress
