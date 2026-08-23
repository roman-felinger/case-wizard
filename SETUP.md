# case-wizard Setup Guide

Complete setup instructions for the three-stage case automation suite.

## Prerequisites

- **Python 3.8+** — check with `python --version`
- **Git** — check with `git --version`
- **Claude CLI** — install from https://claude.com/claude-code
- **Chrome** — for case-brief's CRM scraping
- **Node.js** (optional) — only if working on Node-based projects

## Installation

### 1. Clone the repository

```powershell
git clone https://github.com/yourusername/case-wizard.git
cd case-wizard
```

### 2. Create and activate virtual environment

```powershell
# Create venv
python -m venv .venv

# Activate it (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Or on Windows cmd:
.venv\Scripts\activate.bat

# Or on Mac/Linux:
source .venv/bin/activate

# Verify it's active (you should see (.venv) in your prompt)
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

This installs all dependencies for all three projects:
- **case-brief**: `msal`, `playwright` (for CRM/BC scraping)
- **case-guide** & **case-solve**: `requests` (for API calls)

### 4. Install Claude CLI (one-time)

```powershell
# Go to https://claude.com/claude-code
# Download and install for your OS
# Then verify it's on PATH:
claude --version

# Log in (if not already):
claude login
```

### 5. Set up Azure DevOps PAT (optional)

To use Azure DevOps lookups in case-brief and case-guide, set your PAT:

```powershell
# Create a PAT at: https://dev.azure.com/{yourorg}/_usersSettings/tokens
# Scopes needed: Code (Read), Project and Team (Read)

# Set it as an environment variable (Windows PowerShell)
$env:AZDO_PAT = "your-pat-here"

# Or set it permanently:
[Environment]::SetEnvironmentVariable("AZDO_PAT", "your-pat-here", "User")
# Then restart your shell for it to take effect

# Verify it's set:
$env:AZDO_PAT
```

## Configuration (Optional)

Each project has a `config.example.json` template. Copy and edit if you want
persistent settings (otherwise all defaults work, and you can override with flags).

```powershell
# case-brief
copy case-brief\config.example.json case-brief\config.json
# Edit case-brief\config.json to customize

# case-guide
copy case-guide\config.example.json case-guide\config.json
# Edit case-guide\config.json to customize

# case-solve
copy case-solve\config.example.json case-solve\config.json
# Edit case-solve\config.json to customize
```

You only need to do this if you want to override defaults. **All defaults work
without any config files.**

## Verify Installation

```powershell
# Make sure venv is active
.\.venv\Scripts\Activate.ps1

# Check each tool works
python case-brief\case_brief.py -h
python case-guide\case_guide.py -h
python case-solve\case_solve.py -h

# All should print help text without errors
```

If you see "No module named 'requests'" etc., you may need to reinstall:

```powershell
pip install -r requirements.txt --force-reinstall
```

## Ready to Use!

```powershell
# Make sure venv is active
.\.venv\Scripts\Activate.ps1

# Try a demo run (no real data needed)
cd case-brief
python case_brief.py --demo

# Then read each project's README for how to use it:
# - case-brief/README.md
# - case-guide/README.md
# - case-solve/README.md
```

## Troubleshooting

### "ModuleNotFoundError: No module named requests"
```powershell
# Make sure venv is activated
.\.venv\Scripts\Activate.ps1

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

### "claude: command not found"
```powershell
# Install Claude Code from https://claude.com/claude-code
# Then verify it's on PATH
claude --version

# If it still fails, add Claude to PATH:
# (Path depends on your OS and Claude installation)
# On Windows, usually: C:\Program Files (x86)\Claude\bin
```

### "Python version error"
```powershell
# Check Python version
python --version

# If < 3.8, install a newer version from https://python.org
# Then recreate your venv:
.venv   # Delete the old .venv folder first
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### "Chrome not found" (case-brief)
```powershell
# Install Chrome from https://google.com/chrome
# Or use --skip-browser in case-brief to skip CRM scraping
python case-brief\case_brief.py T2611845 --skip-browser
```

### "Playwright browser not installed"
```powershell
# Playwright needs to download browsers the first time
# This can take a few minutes:
python -m playwright install

# Then try again
python case-brief\case_brief.py --demo
```

## First Run

Once everything is set up:

```powershell
# Activate venv
.\.venv\Scripts\Activate.ps1

# Stage 1: Gather case context
cd case-brief
python case_brief.py T2611845
# Follow prompts, sign into CRM if needed

# Stage 2: Generate guide
cd ../case-guide
python case_guide.py T2611845
# Reviews the brief and asks Claude to write a guide

# Stage 3: Auto-implement
cd ../case-solve
python case_solve.py T2611845
# Interactive: asks which repo to clone
# Automatic: implements, tests, commits
# Output: verification checklist
```

That's it! Check each project's README for detailed usage docs.

## Next Steps

1. **Read the main README.md** — overview of the three projects
2. **Read each project's README** — detailed usage and flags
3. **Read each project's CLAUDE.md** — architecture notes
4. **Try a real case** — use with an actual support case to iterate

## Getting Help

Each project has its own documentation:

- **case-brief/** → `README.md`, `CLAUDE.md`
- **case-guide/** → `README.md`, `CLAUDE.md`
- **case-solve/** → `README.md`, `CLAUDE.md`, `QUICKSTART.md`

Check those files first for:
- Detailed feature descriptions
- All command-line flags
- Architecture decisions
- Troubleshooting tips
- Status (what's been tested, what's experimental)

---

**You're all set!** Start with case-brief and follow the three-stage workflow.
