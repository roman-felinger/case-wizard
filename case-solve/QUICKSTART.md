# case-solve Quick Start

Three-stage automation workflow:

```
case-brief T2611845    →   case-guide T2611845    →   case-solve T2611845
  (gather context)         (write walkthrough)         (implement + verify)
```

## 1. One-time setup

```powershell
cd case-solve

# Create virtual environment (or use existing)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Optional: copy config template (all defaults work, only needed to override)
copy config.example.json config.json
```

That's it! The script will auto-detect project types (Python, Node, Rust, .NET) and
dependency managers.

## 2. For each case: full workflow

```powershell
# Step 1: Gather case context
cd case-brief
python case_brief.py T2611845
# Review the brief that opens in VS Code

# Step 2: Generate implementation guide
cd ../case-guide
python case_guide.py T2611845
# Review the "for Dummies" guide that opens in VS Code

# Step 3: Auto-implement with verification
cd ../case-solve
.venv\Scripts\Activate.ps1  # If not already activated
python case_solve.py T2611845
```

That's the full pipeline. case-solve will:
- ✅ Ask which repo to clone
- ✅ Create a case-specific branch (`case/T2611845`)
- ✅ Have Claude guide implementation step-by-step
- ✅ Auto-apply all changes
- ✅ Run tests & verification
- ✅ Create logical git commits
- ✅ Generate a verification checklist

## 3. Review and push

Output goes to `case-solves/case-T2611845/`:
- **Repo**: `case-solves/repos/myrepo/` (branch: `case/T2611845`)
- **Checklist**: `case-solves/case-T2611845/VERIFICATION_CHECKLIST.md`

```powershell
# In VS Code, open the verification checklist
code case-solves/case-T2611845/VERIFICATION_CHECKLIST.md

# Run the manual checks from the checklist
# Then push and create a PR:
cd case-solves/repos/myrepo
git push -u origin case/T2611845

# Open a PR on GitHub/Azure DevOps
# Include case number T2611845 in the PR title
```

## Quick flag reference

```
python case_solve.py T2611845 --repo <url>        # Override repo URL
python case_solve.py T2611845 --show-plan         # Preview plan, don't apply
python case_solve.py T2611845 --no-implement      # Just set up branch
python case_solve.py T2611845 --dry-run           # Preview without committing
python case_solve.py T2611845 --skip-tests        # Skip verification
python case_solve.py T2611845 --skip-build        # Skip build check
python case_solve.py T2611845 --skip-lint         # Skip linting
python case_solve.py T2611845 --no-open           # Don't open VS Code
python case_solve.py -h                           # All options
```

## Troubleshooting

**"Claude call failed"**
- Install Claude Code: https://claude.com/claude-code
- Verify `claude --version` works in terminal

**"Guide not found"**
- Run `case-guide` first: `cd ../case-guide && python case_guide.py T2611845`

**"Git clone failed"**
- Verify you can clone manually: `git clone <url>`
- Use HTTPS URL if SSH keys aren't set up

**Tests fail during verification**
- Run `python case_solve.py T2611845 --skip-tests` to skip
- Or debug manually: `cd case-solves/repos/myrepo && npm test` (or pytest, etc.)

## What gets auto-detected

**Dependency managers:**
- Python: `requirements.txt` → pip install
- Node.js: `package.json` → npm install
- .NET: `*.csproj` → dotnet restore
- Rust: `Cargo.toml` → cargo build

**Test frameworks:**
- Python: pytest, unittest
- Node.js: npm test
- Rust: cargo test
- .NET: dotnet test

**Linters:**
- Python: black, pylint
- JavaScript: eslint
- Rust: cargo clippy

**Build commands:**
- npm build
- cargo build
- dotnet build
- python setup.py build

If your project uses different tools, they won't run automatically. Manually verify
your changes: just `cd case-solves/repos/myrepo` and run your normal test/build commands.

---

See `README.md` for full documentation and `CLAUDE.md` for architectural notes.
