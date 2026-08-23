# case-solve

Automatically implement case fixes: clone the repo, create a branch, let Claude guide
implementation, run tests, commit changes, and generate a verification checklist.

Part of the three-stage automation:
1. **case-brief** — gather case context → brief
2. **case-guide** — turn brief into a "how to solve" guide
3. **case-solve** — automatically solve it, with verification

## Try it right now (requires a guide)

```
# First, run case-guide to create the guide
cd ../case-guide
python case_guide.py T2611845

# Then, from case-solve:
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python case_solve.py T2611845
```

The script will:
1. Read the guide
2. Ask which repo to clone (suggests from guide if found)
3. Clone/fetch the repo and create a case-specific branch
4. Have Claude analyze the guide and repo structure, then generate step-by-step implementation
5. Apply all changes automatically
6. Run tests, lint, and build checks
7. Create logical git commits
8. Generate a verification checklist

Output lands in `case-solves/case-<code>/` with:
- The cloned repo in `case-solves/repos/<repo-name>`
- A branch: `case/T2611845`
- A verification checklist: `case-solves/case-<code>/VERIFICATION_CHECKLIST.md`

## Setup

1. **Install dependencies:**
   ```
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. **Install the `claude` CLI** if not already done:
   - Get it from https://claude.com/claude-code
   - Make sure `claude` is on your PATH

3. **Config is optional.** Every setting has a default and can be overridden with a flag:
   ```
   copy config.example.json config.json
   # Edit config.json if you want persistent settings (optional)
   ```

## Usage

### Full run (most common)
```
python case_solve.py T2611845
```

Interactive: asks which repo to clone, then runs full implementation + tests + commits.

### Common variations
```
python case_solve.py T2611845 --repo https://github.com/myorg/myrepo  # Override repo URL
python case_solve.py T2611845 --show-plan                             # See plan, don't apply
python case_solve.py T2611845 --no-implement                          # Just create branch, stop
python case_solve.py T2611845 --skip-tests --skip-build               # Skip verification
python case_solve.py T2611845 --dry-run                               # Preview, don't commit
python case_solve.py -h                                               # All flags
```

## What it does

### 1. Finds the guide
Locates the case guide already written by `case-guide`, with fallback to substring glob matching.

### 2. Prompts for repo URL
- Suggests any `git clone` link found in the guide
- Offers fallback from config.json `customer_repo_map`
- Lets you paste a URL if neither applies

### 3. Sets up workspace
- Clones (or fetches latest on) the repo
- Caches cloned repos in `case-solves/repos/` for reuse
- Creates `case/<case-number>` branch
- Auto-detects and installs dependencies:
  - Python: `requirements.txt` → venv + pip
  - Node.js: `package.json` → npm install
  - .NET: `*.csproj` → dotnet restore
  - Rust: `Cargo.toml` → cargo build

### 4. Implementation (Claude-guided)
- Claude reads the case guide + repo structure
- Generates a detailed implementation plan
- Breaks it into step-by-step file changes
- Applies each change to the working tree
- Automatically handles file creation, modification, deletion

### 5. Verification
Auto-detects and runs:
- **Tests**: pytest, unittest, npm test, cargo test, dotnet test
- **Lint**: black, pylint, eslint, cargo clippy
- **Build**: npm build, cargo build, dotnet build, python setup.py build

Reports results (which passed, which failed, output snippets).

### 6. Commits
Groups changes by category (tests, config, docs, source code) and creates logical commits.
Each commit message references the case number:
```
[case/T2611845] Source Code

  - src/api.py
  - src/handler.py
```

### 7. Verification Checklist
Generates `VERIFICATION_CHECKLIST.md` with:
- Summary of all changes
- Test results
- Manual verification steps for the developer
- Next steps to push and create a PR

## Architecture

```
case_solve.py                  CLI entry point / orchestration
lib/workspace.py               Clone, branch, install dependencies
lib/implementer.py             Claude-guided implementation
lib/verifier.py                Run tests, lint, build checks
lib/committer.py               Git operations, logical commits
lib/report.py                  Verification checklist generation
config.example.json            Config template (optional)
```

Independent modules — no shared code with case-brief or case-guide (deliberate).

## Config

**Default config path**: `config.json` (gitignored)

**Merge order**: DEFAULTS → config.json (if exists) → CLI flags

Every setting can be overridden with a command-line flag, so you never need a config file.

Key settings:
- `guide_dir`: where case-guide writes guides (default: `../case-guide/case-guides`)
- `solves_dir`: where to store cloned repos and output (default: `./case-solves`)
- `claude.agent`: the Claude Code agent to run (default: `case-solver`)
- `claude.timeout`: max seconds for Claude calls (default: 900)
- `run_tests`, `run_lint`, `run_build`: auto-detect and run (all true by default)

See `config.example.json` for all options.

## Status

**This is a working MVP.**

Verified:
- Directory structure and argument parsing
- Config merging (DEFAULTS → file → CLI)
- Workspace setup (clone, branch, basic dependency detection)
- Library module structure

Not yet exercised end-to-end:
- An actual Claude call for implementation
- A real repo with actual changes
- Verification against a live project (Python/Node/Rust/.NET)
- Edge cases around merge conflicts, permission errors, etc.

Next steps:
- Run against a real case guide + repo to iterate on implementation prompts
- Add more robust dependency detection (poetry, pipenv, yarn, etc.)
- Handle merge conflicts gracefully
- Better error messages for common failures

## Troubleshooting

### "Claude call failed"
- Make sure `claude` CLI is installed and on your PATH
- Run `claude --version` to verify
- Check that you're logged in: `claude --help` should work

### "Guide not found"
- Run `case-guide` first: `cd ../case-guide && python case_guide.py T2611845`
- Check that the guide file exists in `../case-guide/case-guides/`

### "Git clone failed"
- Verify you can access the repo: `git clone <url>` manually
- Check SSH keys / credentials if needed
- Paste the full HTTPS URL instead of SSH if you get permission denied

### Tests/build fail
- Run `python case_solve.py <case> --skip-tests --skip-build` to skip verification
- Review the error output in the verification checklist
- Run tests manually in the repo to debug: `cd case-solves/repos/<repo> && npm test` etc.

---

Part of the personal toolbox automation suite. Designed to be plug-and-play with
`case-brief` and `case-guide`.
