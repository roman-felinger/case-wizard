# case-wizard

**Automate support cases: brief → guide → implement.**

```
Brief (gather context) → Guide (AI walkthrough) → Solve (auto-implement)
```

Three independent CLI scripts (`case-brief`, `case-guide`, `case-solve`), each a
standalone Python script with its own `-h` for the full flag list, plus a root
`case_wizard.py` for running them from one place. There's no app or GUI — this is run
from a terminal.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Mac/Linux

pip install -r requirements.txt
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

Each stage on its own, from its own folder or via `case_wizard.py` from the root — both
are equivalent:

```bash
python case-brief/case_brief.py T2611845
python case_wizard.py brief T2611845                 # same thing

python case-guide/case_guide.py T2611845
python case_wizard.py guide T2611845                 # same thing

python case-solve/case_solve.py T2611845 --repo https://dev.azure.com/org/proj/_git/repo
python case_wizard.py solve T2611845 --repo <url>    # same thing
```

Or chain all three for one case:

```bash
python case_wizard.py all T2611845 --repo <url>              # brief -> guide -> solve
python case_wizard.py all T2611845 --stop-after guide        # brief + guide only
python case_wizard.py all -h                                 # per-stage passthrough, etc.
```

A failed stage stops the chain. `case_wizard.py all` is just a thin wrapper: it runs
each stage's script in a subprocess, in order, the same as running them by hand.
`--repo` is only ever forwarded to solve; use `--brief-arg`/`--guide-arg`/`--solve-arg`
(repeatable) for anything else a given stage's own `-h` lists.

### 1. case-brief — gather context

Looks up the case from CRM via the Dataverse Web API, authenticated with OAuth
(Entra ID) device-code sign-in (`--skip-crm` to disable), and resolves any Azure
DevOps PR/branch links already pasted into the case (`--skip-ado` to disable). No
config file — org/CRM/OAuth client are fixed constants (this tool only ever talks
to one org and one CRM).

```bash
python case-brief/case_brief.py --demo             # fake data, fastest smoke test
python case-brief/case_brief.py T2611845            # real run
python case-brief/case_brief.py T2611845 --skip-crm # ADO only, no CRM sign-in
python case-brief/case_brief.py -h
```

The first real run prints a one-time device code and a URL — open it in any browser
and sign in with your normal CRM account. Later runs are silent: the token is
cached (`case-brief/.token_cache/`, gitignored) and silently refreshed. No admin
app-registration step is needed (see `CLAUDE.md`'s Dataverse API section for why).

Output: `case-brief/case-briefs/case-<number>.md`

### 2. case-guide — write the walkthrough

Turns the brief into a step-by-step implementation guide via a headless `claude`
call, running as the `case-guide-writer` agent persona
(`.claude/agents/case-guide-writer.md`). No dry-run mode — every run makes a real
`claude` call. If a guide already exists and is newer than its brief, the run is
skipped rather than re-spending an ADO search + a `claude` call (delete the guide
file to force a regenerate).

```bash
python case-guide/case_guide.py 12345               # smoke test: reads the checked-in demo brief
python case-guide/case_guide.py T2611845 --model opus
python case-guide/case_guide.py -h
```

Requires a brief already written by case-brief and the `claude` CLI on PATH.
Optional `config.json` (see `case-guide/config.example.json`) for model/timeout/agent
overrides and the Azure DevOps org.

Output: `case-guide/case-guides/case-<number>.md`

### 3. case-solve — implement it

Clones the repo, has Claude implement the guide's plan, runs tests/lint/build, and
commits as it goes, grouped by category. Never pushes — you review and push
yourself. MVP: the two-stage Claude plan→apply flow is unit-tested but not yet
exercised end-to-end against a real repo.

```bash
python case-solve/case_solve.py T2611845 --repo <url> --show-plan   # preview plan, no apply
python case-solve/case_solve.py T2611845 --repo <url> --dry-run     # preview changes, no commit
python case-solve/case_solve.py T2611845 --repo <url>               # full run
python case-solve/case_solve.py -h
```

Requires the guide from case-guide, `claude` CLI (logged in), git, and network access
to clone the repo. `--yes` skips the repo/confirmation prompts (required for any
scripted/non-interactive caller). Optional `config.json` (see
`case-solve/config.example.json`) for `run_tests`/`run_lint`/`run_build`/`claude.*`.

Auto-detected per project:

| | Dependency install | Tests | Lint | Build |
|---|---|---|---|---|
| Python | `requirements.txt` → pip | pytest / unittest | black, pylint | `setup.py build` |
| Node.js | `package.json` → npm | npm test | eslint | npm build |
| Rust | `Cargo.toml` → cargo | cargo test | cargo clippy | cargo build |
| .NET | `*.csproj` → dotnet restore | dotnet test | — | dotnet build |

A project using different tools won't get auto-verified — check it manually.

Output: `case-solve/case-solves/case-<number>/VERIFICATION_CHECKLIST.md`, cloned repo
at `case-solve/case-solves/repos/<repo-name>/` (branch `case/<code>`, reused across
runs). Review it, then:

```bash
cd case-solve/case-solves/repos/<repo>
git push -u origin case/T2611845
# open a PR, mention the case number in the title
```

## Tests

Each stage's own tests run independently (they can't be collected in one pytest
process — see `run_tests.py`'s docstring for why):

```bash
python run_tests.py              # all three stages
python run_tests.py brief guide  # just these
```

## Status

- **Brief:** CRM (Dataverse Web API, OAuth) + ADO working, 123 tests (`case-brief/tests/`)
- **Guide:** stable, 84 tests (`case-guide/tests/`)
- **Solve:** MVP — clone/branch/dependency-install verified, 141 tests
  (`case-solve/tests/`); a real end-to-end Claude implementation run against a live
  repo is the main thing left to exercise

See `CLAUDE.md` for architecture notes and the troubleshooting section below if
something's not working.

## Troubleshooting

**`claude` CLI not found / not working.** Install from
[claude.com/claude-code](https://claude.com/claude-code), then run `claude login`. If
case-guide/case-solve fail with a real `claude` error rather than "not found", log in
again — a session can expire.

**CRM sign-in fails / case-brief can't read the case.** Run
`python case-brief/case_brief.py <case-number>` — the first time, it prints a
device code and a URL; open the URL in any browser and sign in with your normal CRM
account. Later runs reuse the cached token silently. If sign-in itself fails with an
AADSTS error mentioning consent or Conditional Access, that needs an Entra ID admin
to approve app access for this tenant — see `CLAUDE.md`'s Dataverse API section. To
force a fresh sign-in (e.g. after a permissions change), delete
`case-brief/.token_cache/`.

**Azure DevOps errors (case-brief, case-guide).** Both are hardcoded to one org
(`https://dev.azure.com/artexis`; case-guide still takes `--org-url` for a one-off
different org). Check `AZDO_PAT` is set and hasn't expired (PATs max out at 1 year),
with scopes **Code (Read)** and **Project and Team (Read)**.

**A stage fails.** Brief: almost always a CRM login issue (see above) — `--demo`
skips CRM/ADO entirely to check the script itself still runs. Guide: needs an
existing brief for that case number and a working `claude` login — there's no
dry-run mode. Solve: needs a real, reachable git clone URL and an existing guide;
`--show-plan` previews Claude's plan without applying anything, `--dry-run` applies
without committing.

**Network / firewall.** If CRM or ADO time out rather than showing a clear error:
check VPN if your org requires one, and that `*.dynamics.com` and `dev.azure.com`
aren't blocked.

**Still stuck.** Run the failing stage with `-h` to confirm you're passing what it
expects, then re-run it directly and read the actual error — each stage prints
exactly what failed rather than a generic message.
