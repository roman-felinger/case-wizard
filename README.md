# case-wizard

**Automate support cases: brief → guide → implement.**

```
Brief (gather context) → Guide (AI walkthrough) → Solve (auto-implement)
```

Three independent CLI scripts (`case-brief`, `case-guide`, `case-solve`), each a
standalone Python script with its own `-h` for the full flag list. There's no app or
GUI — this is run from a terminal.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Mac/Linux

pip install -r requirements.txt
python -m playwright install chromium   # one-time, ~115 MB -- used for CRM scraping
```

## Requirements

- Python 3.8+, Git
- [Claude Code](https://claude.com/claude-code) installed and logged in (`claude login`
  — no API key needed)
- Dynamics 365 CRM access (any account with case access)
- An Azure DevOps [PAT](https://dev.azure.com/_usersSettings/tokens) (self-service,
  no admin approval needed; scopes: Code Read, Project and Team Read) — set it as the
  `AZDO_PAT` environment variable

## Usage

```bash
python case-brief/case_brief.py T2611845
python case-guide/case_guide.py T2611845
python case-solve/case_solve.py T2611845 --repo https://dev.azure.com/org/proj/_git/repo
```

case-guide and case-solve each optionally take a `config.json` (see their
`config.example.json`) for settings without a CLI flag. case-brief has no config
file at all — it only ever talks to one org, one CRM, and its own dedicated
Chrome profile, all fixed constants in its source.

## The Three Stages

### 1. case-brief
Gathers case context from CRM + Azure DevOps.
Output: `case-brief/case-briefs/case-<number>.md`

```bash
python case-brief/case_brief.py --demo        # fake data, no setup needed -- fastest smoke test
python case-brief/case_brief.py T2611845      # real run: CRM lookup + ADO search
python case-brief/case_brief.py -h            # full flag list
```

### 2. case-guide
Turns the brief into a step-by-step walkthrough via a headless `claude` call.
Output: `case-guide/case-guides/case-<number>-for-dummies.md`

```bash
python case-guide/case_guide.py T2611845 --show-prompt   # preview the prompt, no claude call
python case-guide/case_guide.py T2611845                 # full run
python case-guide/case_guide.py -h                       # full flag list
```

### 3. case-solve
Clones the repo, implements the guide's plan, runs tests/lint/build, commits as it
goes. Never pushes — you review and push yourself.
Output: `case-solve/case-solves/case-<number>/VERIFICATION_CHECKLIST.md`

```bash
python case-solve/case_solve.py T2611845 --repo <url> --show-plan   # preview plan, no apply
python case-solve/case_solve.py T2611845 --repo <url> --dry-run     # preview changes, no commit
python case-solve/case_solve.py T2611845 --repo <url>               # full run
python case-solve/case_solve.py -h                                  # full flag list
```

## Status

- **Brief:** CRM + ADO working, 154 tests (`case-brief/tests/`)
- **Guide:** stable, 94 tests (`case-guide/tests/`)
- **Solve:** MVP — clone/branch/dependency-install verified, 144 tests
  (`case-solve/tests/`); a real end-to-end Claude implementation run against a live
  repo is the main thing left to exercise

See `TROUBLESHOOT.md` if something's not working and you're not sure why.
