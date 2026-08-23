# case-wizard

**Automate your support cases from brief to implementation.**

A three-stage automation suite that turns a support case into a fully implemented,
tested, and committed feature branch — with minimal manual work.

```
┌────────────────────────┐
│  1. case-brief         │  Gather case context (CRM, ADO, BC)
└────────────┬───────────┘
             │ ↓
┌────────────────────────┐
│  2. case-guide         │  Turn brief into a walkthrough guide
└────────────┬───────────┘
             │ ↓
┌────────────────────────┐
│  3. case-solve         │  Implement, test, commit, verify
└────────────────────────┘
             ↓
        Ready to push & PR ✅
```

## The Three Stages

### 1. case-brief
**Gather case context** from your organization's systems into one Markdown brief.

Pulls from:
- **Dynamics 365 CRM** — case title, customer, owner, priority, description
- **Azure DevOps** — related branches, PRs, commits
- **Business Central** (optional) — financial data
- **Fuzzy repo matching** — suggests which codebase owns the case

Output: `case-briefs/case-<code>.md` — a concise summary, ready to understand the problem.

```bash
python case_brief.py T2611845
# Opens brief in VS Code
```

### 2. case-guide
**Turn the brief into a plain-language "how to solve" guide** using Claude.

Reads the brief + live Azure DevOps detail (branches, PR comments, review history),
then asks Claude to write a 5-section guide:
1. **Get set up** — clone, branch, install dependencies
2. **What's already been tried** — context from related PRs/issues
3. **What still needs developing** — the actual work
4. **How to verify and ship** — testing + review checklist
5. **Edge cases & gotchas** — things that could go wrong

Output: `case-guides/case-<code>-for-dummies.md` — a walkthrough, ready to implement.

```bash
python case_guide.py T2611845
# Opens guide in VS Code
```

### 3. case-solve
**Implement the changes automatically** using Claude to guide you through,
verify with tests, create logical commits, and generate a checklist.

Fully automated:
- Clone repo (or use cached clone)
- Create feature branch `case/<case-number>`
- Install dependencies (auto-detects Python/Node/.NET/Rust)
- Claude reads guide + repo structure
- Claude generates implementation plan & step-by-step changes
- Apply changes automatically
- Run tests, lint, build (auto-detects available tools)
- Create logical commits by file category
- Generate verification checklist for manual steps

Output:
- Cloned repo with branch: `case-solves/repos/<repo>/` (on branch `case/T2611845`)
- Verification checklist: `case-solves/case-T2611845/VERIFICATION_CHECKLIST.md`
- Ready to push and create a PR

```bash
python case_solve.py T2611845
# Interactive: asks which repo to clone
# Automatic: implements, tests, commits
# Output: verification checklist
```

## Quick Start

### One-time setup

```powershell
# Clone this repo
git clone https://github.com/yourusername/case-wizard.git
cd case-wizard

# Install dependencies (Python 3.8+)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Install the Claude CLI (if not already done)
# https://claude.com/claude-code

# (Optional) Create config files
copy case-brief/config.example.json case-brief/config.json
copy case-guide/config.example.json case-guide/config.json
copy case-solve/config.example.json case-solve/config.json
# Then edit them to customize (or just use CLI flags)
```

### For each case

```powershell
# Activate venv (if not already activated)
.\.venv\Scripts\Activate.ps1

# 1. Gather context
python case-brief/case_brief.py T2611845
# Review the brief that opens in VS Code

# 2. Generate guide
cd case-guide
python case_guide.py T2611845
# Review the guide that opens in VS Code

# 3. Implement & verify
cd ../case-solve
python case_solve.py T2611845
# Watch it auto-implement, test, commit

# 4. Manual verification & push
code case-solves/case-T2611845/VERIFICATION_CHECKLIST.md
# Follow checklist, run manual tests, push branch
```

## Features

- **Minimal setup** — no admin approval needed, uses your existing credentials
- **Cached repos** — clone once, fetch on repeat runs
- **Auto-detection** — detects Python/Node/.NET/Rust, test frameworks, linters
- **Claude-guided** — each stage uses Claude for intelligence: context gathering,
  guide writing, implementation planning
- **Safe by default** — all work is on isolated branches, nothing pushes automatically
- **Verification built-in** — tests, lint, build checks auto-run and reported
- **Logical commits** — groups changes by type (tests, config, docs, source code)
- **Human-readable output** — verification checklist guides final manual steps

## Projects

Each project is independent but designed to work together:

| Project | Purpose | Input | Output |
|---------|---------|-------|--------|
| **case-brief** | Gather context | Case code, open CRM/BC tabs, Azure DevOps PAT | Markdown brief |
| **case-guide** | Write guide | Case brief file, live ADO re-query (optional) | Markdown guide ("for Dummies") |
| **case-solve** | Implement | Case guide file, repo URL (interactive or flag) | Implemented branch, verification checklist |

See each project's `README.md` for detailed docs, and `CLAUDE.md` for architecture notes.

## Architecture

```
case-wizard/
├── case-brief/           ← Stage 1: gather context
│   ├── case_brief.py
│   ├── lib/
│   │   ├── crm_scrape.py      Browser scraping via CDP
│   │   ├── bc_scrape.py        Business Central (experimental)
│   │   ├── ado_api.py          Azure DevOps REST API
│   │   └── report.py           Markdown generation
│   ├── config.example.json
│   ├── requirements.txt
│   └── README.md
│
├── case-guide/           ← Stage 2: write guide
│   ├── case_guide.py
│   ├── lib/
│   │   ├── ado_api.py          (own copy, not shared)
│   │   └── writer.py
│   ├── .claude/agents/
│   │   └── case-guide-writer.md  ← Claude persona
│   ├── tests/                  Unit tests (mocked, no network)
│   ├── config.example.json
│   ├── requirements.txt
│   └── README.md
│
├── case-solve/           ← Stage 3: implement
│   ├── case_solve.py
│   ├── lib/
│   │   ├── workspace.py         Clone, branch, deps
│   │   ├── implementer.py       Claude-guided changes
│   │   ├── verifier.py          Tests, lint, build
│   │   ├── committer.py         Git operations
│   │   └── report.py            Verification checklist
│   ├── .claude/agents/
│   │   └── case-solver.md       ← Claude persona
│   ├── config.example.json
│   ├── requirements.txt
│   └── README.md
│
├── .venv/                Virtual env (gitignored)
├── .gitignore            Root-level ignores
├── requirements.txt      Top-level deps (links to subprojects)
└── README.md             This file
```

**Design note**: Each project is **self-contained** (no shared code imports).
This is intentional — it keeps projects independent and easy to update/fork
without cascading changes.

## Configuration

All three projects follow the same config pattern:

1. **Built-in defaults** (no setup needed)
2. **Optional config.json** (for persistent settings)
3. **CLI flags** (override everything)

For example:
```bash
# Use all defaults
python case_brief.py T2611845

# Override with flag (no config file needed)
python case_brief.py T2611845 --org-url https://dev.azure.com/myorg

# Or save to config.json for all future runs
copy case-brief/config.example.json case-brief/config.json
# Edit config.json, then all runs use it
```

See each project's `config.example.json` for all options.

## Prerequisites

- **Python 3.8+** (already on most systems)
- **Git** (for cloning, branching, committing)
- **Claude CLI** (https://claude.com/claude-code) — for guide writing and implementation
- **Azure DevOps PAT** (personal access token) — for ADO querying (optional, not needed for basic case-brief)
- **Chrome** (for CRM scraping in case-brief)
- **Node.js/npm** (only if testing Node-based codebases)

All optional except Python, Git, and Claude CLI.

## What You Need to Provide

### For case-brief
- **Open CRM tab** — signed in to Dynamics 365 in a Chrome window (case-brief opens it)
- **Optional: Business Central tab** — signed in to BC (use `--with-bc`)
- **Azure DevOps PAT** — set `AZDO_PAT` env var (optional, for ADO search)

### For case-guide
- **Case brief** — already written by case-brief
- **Claude CLI** — logged in and on PATH
- **Optional: Azure DevOps PAT** — for live branch/PR re-query

### For case-solve
- **Case guide** — already written by case-guide
- **Claude CLI** — logged in and on PATH
- **Git credentials** — so you can clone/push repos (SSH keys or HTTPS token)

## Status

**All three projects working and ready to use.**

### case-brief
Verified end-to-end against real data: Dynamics 365 case lookup works ✅
Azure DevOps search unverified on real org.
Business Central scraping still being refined.

### case-guide
Verified end-to-end: multiple real cases, real ADO org, real `claude` calls ✅
House-style example and style-PR sampling verified.
Only one project's conventions tested (needs multi-project validation).

### case-solve
Structure and argument parsing verified ✅
Needs real-world testing: actual Claude calls, real file changes, live verification suites.

## Troubleshooting

### "Claude not found"
```powershell
# Install Claude Code: https://claude.com/claude-code
# Then verify it's on PATH:
claude --version
```

### "Git clone failed"
```powershell
# Test git access manually:
git clone <repo-url>
# If it fails, check SSH keys or credentials
```

### "Tests fail during verification"
```powershell
# Skip verification in case-solve:
python case-solve\case_solve.py T2611845 --skip-tests
# Then debug manually in the cloned repo
```

### "Azure DevOps PAT not working"
```powershell
# Set env var:
$env:AZDO_PAT = "your-pat-here"
# Verify it's set:
$env:AZDO_PAT
# Then run the command again
```

See each project's README for more troubleshooting.

## Contributing & Extending

Each project is designed to be hacked on independently:

- **Improve case-brief's CRM scraping?** Edit `case-brief/lib/crm_scrape.py`, no impact on other projects.
- **Change case-guide's prompt?** Edit `case-guide/.claude/agents/case-guide-writer.md`, the guide changes next run.
- **Add a new verification check to case-solve?** Edit `case-solve/lib/verifier.py`, no cascading changes.

Each project has its own:
- Python environment (`.venv/`)
- Dependencies (`requirements.txt`)
- Configuration (`config.json`)
- Tests (if any)
- Documentation (`README.md`, `CLAUDE.md`)

## License

This is a personal automation suite. Feel free to fork, extend, and customize for your needs.

## Next Steps

1. **Clone this repo** and follow Quick Start above
2. **Have a real case handy** — run case-brief first, then case-guide, then case-solve
3. **Iterate** — each tool will reveal edge cases; open an issue or PR if you find something
4. **Customize** — every tool can be extended (Claude persona, verification checks, commit strategy, etc.)

---

**The goal: automate the boring stuff, keep the interesting problem-solving.**

Made with ❤️ for developers who have better things to do than tab-hop between portals.
