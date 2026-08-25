# CLAUDE.md

Guidance for Claude Code when working with case-solve.

## Commands

```
..\.venv\Scripts\Activate.ps1   # from case-solve/, on Windows -- repo root's venv has everything

# Full run (prompts for repo URL)
python case_solve.py T2611845

# View implementation plan without applying
python case_solve.py T2611845 --show-plan

# Just set up branch, don't implement
python case_solve.py T2611845 --no-implement

# Dry-run (preview changes, don't commit)
python case_solve.py T2611845 --dry-run

# Full help
python case_solve.py -h
```

## Architecture

Independent from case-brief and case-guide — reads the case guide file they produce
(case-guide's `case-guides/case-<code>-for-dummies.md`), then implements changes
guided by Claude.

**Pipeline (`main` in `case_solve.py`):**

1. **Find guide** — locate the guide by case number (exact match, then glob fallback)
2. **Extract repo suggestion** — look for `git clone` link in guide text
3. **Prompt for repo URL** — suggest from guide, ask user to confirm or override
4. **Workspace setup** — clone (or fetch), create `case/<case-number>` branch
5. **Install dependencies** — auto-detect Python/Node/Rust/.NET and install
6. **Implementation** — Claude reads guide + repo structure, generates plan, applies changes
7. **Verification** — run tests, lint, build (auto-detect available tools)
8. **Commit** — group changes by category (tests, config, docs, source), one commit per group
9. **Report** — generate verification checklist, next steps

**Key modules:**

- `case_solve.py` — CLI, orchestration
- `lib/workspace.py` — clone, branch, dependencies
- `lib/implementer.py` — Claude-guided implementation (plan → steps → apply)
- `lib/verifier.py` — auto-detect and run tests/lint/build
- `lib/committer.py` — git operations, logical grouping
- `lib/report.py` — markdown checklist generation
- `.claude/agents/case-solver.md` — persona for Claude's implementation guidance

## Design Choices

### Independent Implementation Module
`lib/implementer.py` orchestrates three sub-steps:
1. **Plan** — Claude reads guide + repo structure, outputs a detailed plan
2. **Steps** — Claude breaks that plan into file-by-file changes (FILE, ACTION, CONTENT)
3. **Apply** — case-solve applies each step to the working tree

This two-stage Claude interaction (plan-then-steps) guards against:
- Silent truncation of complex repos
- Unintended overwrites (visual inspection of steps before apply)
- Re-invocation on a messy state

Downside: two Claude calls instead of one. Upside: safer, more auditable.

### Auto-Detection Over Templates
Workspace setup auto-detects dependency managers (pip, npm, cargo, dotnet) rather than
templates. Tests auto-detect (pytest, unittest, npm test, cargo test) rather than
requiring config. This makes case-solve work with any project layout without
pre-registration.

### Workspace Reuse
Cloned repos are cached in `case-solves/repos/<repo-name>/` and fetched between runs.
Each case gets its own branch in the same repo. This:
- Saves bandwidth on repeat runs
- Keeps a local history of all cases
- Lets you compare across cases in the same repo

### No Destructive Git Operations
- Branches are created fresh on each run (old one deleted if exists)
- Nothing is pushed automatically
- User must `git push` manually before opening a PR
- All commits are on a case-specific branch, `main` is never touched

## Config Merge Order

Same pattern as case-brief/case-guide:
1. **DEFAULTS** dict in case_solve.py (built-in)
2. **config.json** (if exists, deep-merged)
3. **CLI flags** (override everything, for `run_tests`/`run_lint`/`run_build` only)

`guide_dir`/`solves_dir` (fixed to `GUIDE_DIR`/`SOLVES_DIR`), `open_in_vscode` (always
on, `--no-open` overrides), and `claude.extra_args` (never had a CLI flag, never used)
were removed as config keys -- fixed/always-on/gone respectively, since none of them
had ever actually been changed from their default. `claude.model`/`agent`/`timeout`
stay config-only with no CLI flag, unlike case-guide's equivalents -- not worth adding
flags nobody's asked for.

## Testing Approach

This project is verify-by-running-against-real-cases, not unit-test heavy:

- `--show-plan` lets you see what Claude plans before applying
- `--dry-run` previews changes without committing
- Early smoke tests: run against a real case/repo combination to validate plan+steps
- Edge cases: merge conflicts, permission denied, etc. — handle as they arise

## Status

MVP: working directory structure, argument parsing, config merging, workspace setup,
dependency detection, skeleton of Claude integration.

Verified:
- Python packaging conventions followed
- Config inheritance works
- Workspace setup (clone, branch, basic dependency install)

Not yet exercised end-to-end:
- An actual Claude call for plan generation
- A real repo with actual changes applied
- Full verification suite against a live project
- Edge cases (conflicts, missing tools, permission errors)

## Future Improvements

- **Robustness**: better error messages, recovery from partial failures
- **Dependency managers**: poetry, pipenv, yarn, mix, etc.
- **Testing**: more sophisticated test selection (by-file, by-tag, etc.)
- **Branching**: smarter default branch detection (main vs master vs develop)
- **History**: track all case-solves, replay/diff across runs
