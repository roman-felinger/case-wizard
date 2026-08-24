# case-wizard

**Automate support cases: brief → guide → implement.**

```
Brief (gather context) → Guide (AI walkthrough) → Solve (auto-implement)
```

Three independent scripts (`case-brief`, `case-guide`, `case-solve`), driven from one
desktop app (`app/`, Streamlit) or run by hand.

## Quick Start

**Windows:** double-click `run.cmd`
**Mac/Linux:** `./run.sh`
**Any OS:** `python -m streamlit run app/main.py`

First run installs dependencies and Chromium (~1 min total, cached after that), then
opens `http://localhost:8501`.

## First-Time Setup

The app checks everything it needs on its own:

- **Python, Git, Claude CLI, Claude login** — auto-verified, no input needed. If
  something's missing, it tells you exactly what to install.
- **Azure DevOps** — paste an org URL and a [PAT](https://dev.azure.com/_usersSettings/tokens)
  (scopes: Code Read, Project and Team Read), click **Check Connection**. Works →
  saved to Windows Credential Manager automatically, nothing to re-enter.
- **CRM (Dynamics 365)** — checked automatically via a dedicated browser window the
  app controls (separate from your normal browser). If not logged in, click
  **Log in to CRM**; the window closes itself the moment login succeeds. The session
  persists, so this is normally a one-time thing.

Once both are green, the wizard never appears again — you get a one-line
"✅ All systems ready" status with a Recheck button. Change org URL, model, or
run-tests/lint/build defaults later in the **Settings** tab.

## The Three Stages

### 1. case-brief
Gathers case context from CRM + Azure DevOps.
Output: `case-brief/case-briefs/case-<number>.md`

### 2. case-guide
Turns the brief into a step-by-step walkthrough via a headless `claude` call.
Output: `case-guide/case-guides/case-<number>-for-dummies.md`

### 3. case-solve
Clones the repo, implements the guide's plan, runs tests/lint/build, commits as it
goes. Never pushes — you review and push yourself.
Output: `case-solve/case-solves/case-<number>/VERIFICATION_CHECKLIST.md`

## Requirements

- Python 3.8+, Git
- [Claude Code](https://claude.com/claude-code) installed and logged in (`claude login`
  — no API key needed)
- Dynamics 365 CRM access (any account with case access)
- An Azure DevOps [PAT](https://dev.azure.com/_usersSettings/tokens) (self-service,
  no admin approval needed)

## Manual Run (no app)

Each stage is a standalone script with its own `-h` for the full flag list; the app
just wraps these with a UI. Use the repo-root `.venv` (it already has everything all
three stages need):

```bash
.venv\Scripts\activate         # Windows
source .venv/bin/activate      # Mac/Linux

python case-brief/case_brief.py T2611845
python case-guide/case_guide.py T2611845
python case-solve/case_solve.py T2611845 --repo https://dev.azure.com/org/proj/_git/repo
```

`config.json` in each stage directory (see its `config.example.json`) is optional —
every setting there also has a CLI flag override, and the app always passes flags
explicitly rather than relying on a stage's local config file.

## Status

- **Brief:** CRM + ADO working
- **Guide:** stable, has a 63-test suite (`case-guide/tests/`)
- **Solve:** MVP — clone/branch/dependency-install verified; a real end-to-end Claude
  implementation run against a live repo is the main thing left to exercise
- **App:** Streamlit desktop UI; auto-shuts-down ~15s after the last browser tab
  closes

See `TROUBLESHOOT.md` if something's red and you're not sure why.
