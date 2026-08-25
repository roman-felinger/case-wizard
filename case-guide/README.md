# case-guide

Turns a case brief into a step-by-step implementation guide using Claude.

## Setup

Use the repo root's `.venv` — it already has everything all three stages need:

```bash
..\.venv\Scripts\Activate.ps1      # from case-guide/, on Windows
```

## Usage

```bash
python case_guide.py T2611845
python case_guide.py T2611845 --model opus      # use a different model
python case_guide.py T2611845 --no-open         # don't open in VS Code
python case_guide.py -h                         # all options
```

Requires:
- Brief from `case-brief` (reads `../case-brief/case-briefs/case-<code>.md`)
- Claude CLI (`claude` on PATH)
- `AZDO_PAT` env var (for Azure DevOps pull)

Output: `case-guides/case-<code>-for-dummies.md`

## Config

Edit `config.json` (optional) or use CLI flags. See `config.example.json`.
Which repo to suggest for the guide's "Get set up" step is auto-guessed by
fuzzy-matching the CRM customer name against Azure DevOps project/repo names
-- there's no manual override.

## Testing

```bash
python -m unittest discover -s tests -v   # 87 tests, mocked, no network
```
