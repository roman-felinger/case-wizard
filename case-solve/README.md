# case-solve

Reads a case guide, clones the repo, implements the changes with Claude, verifies,
and commits. Never pushes — you review and push yourself.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Usage

```bash
python case_solve.py T2611845 --repo https://dev.azure.com/org/proj/_git/repo
python case_solve.py T2611845 --repo <url> --show-plan    # preview plan, no apply
python case_solve.py T2611845 --repo <url> --dry-run      # preview changes, no commit
python case_solve.py T2611845 --repo <url> --no-implement # branch only, no changes
python case_solve.py T2611845 --repo <url> --yes          # skip interactive confirm
python case_solve.py -h                                   # all options
```

Omit `--repo` in a real terminal and it prompts, suggesting a URL found in the guide
if there is one. `--yes` skips both the repo prompt and the confirmation prompt —
required for any non-interactive caller (e.g. case-wizard's own app), since there's
no terminal there to answer either one.

Requires:
- A guide already written by `case-guide` (reads
  `../case-guide/case-guides/case-<code>-for-dummies.md`)
- Claude CLI (`claude` on PATH, logged in)
- Git configured
- Network access to clone the repo

## What it does

1. Reads the guide
2. Resolves the repo URL (`--repo`, or a suggestion from the guide, or asks)
3. Clones/fetches the repo, creates branch `case/<code>`
4. Auto-detects the dependency manager and installs
5. Claude reads the guide + repo structure, generates an implementation plan, then
   file-by-file steps
6. Applies the changes
7. Auto-detects and runs tests/lint/build
8. Groups changes into logical commits
9. Writes a verification checklist

Output:
- Cloned repo: `case-solves/repos/<repo-name>/` (branch `case/<code>`) — cached and
  reused across runs
- Checklist: `case-solves/case-<code>/VERIFICATION_CHECKLIST.md`

### Review and push

```powershell
code case-solves/case-T2611845/VERIFICATION_CHECKLIST.md
# run the manual checks it lists, then:
cd case-solves/repos/myrepo
git push -u origin case/T2611845
# open a PR, mention the case number in the title
```

### What gets auto-detected

| | Dependency install | Tests | Lint | Build |
|---|---|---|---|---|
| Python | `requirements.txt` → pip | pytest / unittest | black, pylint | `setup.py build` |
| Node.js | `package.json` → npm | npm test | eslint | npm build |
| Rust | `Cargo.toml` → cargo | cargo test | cargo clippy | cargo build |
| .NET | `*.csproj` → dotnet restore | dotnet test | — | dotnet build |

A project using different tools won't get auto-verified — check it manually in
`case-solves/repos/<repo>/` with its normal commands.

## Config

Edit `config.json` (optional, see `config.example.json`) or use CLI flags — flags
always win. Nothing requires editing the config file.

## Troubleshooting

- **"Claude call failed"** — install [Claude Code](https://claude.com/claude-code),
  confirm `claude --version` and `claude login` both work.
- **"Guide not found"** — run case-guide first:
  `cd ../case-guide && python case_guide.py T2611845`.
- **"Git clone failed"** — verify `git clone <url>` works manually; use an HTTPS URL
  if SSH keys aren't set up.
- **Tests fail during verification** — `--skip-tests` to bypass, or debug directly in
  `case-solves/repos/<repo>/`.

See `CLAUDE.md` for architecture notes.
