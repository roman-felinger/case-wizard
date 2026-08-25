# case-guide

Turns a case brief into a step-by-step implementation guide using Claude.

## Quick Test

```bash
python case_guide.py 12345 --no-open
```

No `--demo` flag here -- every run needs a real brief on disk and makes a real
`claude` call. `12345` works out of the box because
`../case-brief/case-briefs/case-12345.md` is case-brief's `--demo` output, checked
into git as a fixture -- no CRM/ADO setup needed to try this stage.

## Setup

Use the repo root's `.venv` — it already has everything all three stages need:

```bash
..\.venv\Scripts\Activate.ps1      # from case-guide/, on Windows
```

## Usage

From the repo root, `python case_wizard.py guide ...` is equivalent to everything below.

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

Output: `case-guides/case-<code>.md`

## Config

Edit `config.json` (optional) or use CLI flags. See `config.example.json`.
Which repo to suggest for the guide's "Get set up" step is auto-guessed by
fuzzy-matching the CRM customer name against Azure DevOps project/repo names
-- there's no manual override. When the suggestion is a guess rather than a
repo Azure DevOps actually confirmed for this case, the written guide always
gets a "⚠️ guessed, not confirmed" warning right after its title — verify it
before running any clone/checkout commands.

## Testing

```bash
python -m unittest discover -s tests -v   # 88 tests, mocked, no network
```
