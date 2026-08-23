# case-solve

Auto-implement changes from a case guide: clone repo, create branch, apply changes, run tests, commit.

## Setup

```bash
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Usage

```bash
python case_solve.py T2611845
python case_solve.py T2611845 --show-plan       # preview plan, no apply
python case_solve.py T2611845 --dry-run         # preview changes, no commit
python case_solve.py T2611845 --repo PROJ/NAME  # specify repo, don't prompt
python case_solve.py T2611845 --no-implement    # setup only, no changes
python case_solve.py -h                         # all options
```

Requires:
- Guide from `case-guide` (reads `../case-guide/case-guides/case-<code>-for-dummies.md`)
- Claude CLI (`claude` on PATH)
- Git configured
- Internet (to clone repos)

Output:
- Cloned repo in `case-solves/repos/<repo>/` on branch `case/<code>`
- Checklist in `case-solves/<code>/VERIFICATION_CHECKLIST.md`

## What It Does

1. Reads the guide
2. Suggests repo from guide, prompts for URL (or use `--repo`)
3. Clones/fetches repo, creates case branch
4. Auto-detects dependency manager (pip/npm/cargo/dotnet), installs
5. Claude reads guide + repo, generates implementation plan
6. Applies changes file-by-file
7. Auto-detects and runs tests/lint/build
8. Groups changes into logical commits
9. Outputs verification checklist

Nothing is pushed automatically. You review and push manually.

## Config

Edit `config.json` (optional) or use CLI flags. See `config.example.json`.
