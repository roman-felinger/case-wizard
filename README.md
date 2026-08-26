# case-wizard

**Automate support cases: brief → guide → implement.**

```
Brief (gather context) → Guide (AI walkthrough) → Solve (auto-implement)
```

Three independent CLI scripts (`case-brief`, `case-guide`, `case-solve`), each a
standalone Python script with its own `-h` for the full flag list, plus a root
`case_wizard.py` for running them from one place. There's no app or GUI — this is run
from a terminal.

A fourth script, `case-getter`, finds the work in the first place: it lists every
CRM case nobody has picked up yet (plus every active case already assigned to
whoever is signed in), (re)runs brief + guide for whichever are new or out of
date, and prints the whole list sorted by difficulty — so you get a ready-to-triage
list instead of having to go looking case by case.

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

### 0. case-getter — find new work automatically

Lists every active CRM case that's either still owned by the CRM's default
unassigned-case team ("Helpdesk e-mail" — nobody's claimed it yet) or already
owned by whoever is signed in, and prints a triage list of *all* of them, sorted
by implementation difficulty (easiest first by default) — never just "nothing
new found", since there's always a real list to see even when nothing's changed
since the last run. Only some of them actually get (re)processed: a case with no
brief on disk yet, or whose brief predates the CRM record's last edit, gets
case-brief then case-guide run for it (same as `case_wizard.py all <code>
--stop-after guide`, one case at a time; one case failing doesn't stop the rest).
A case that already has an up-to-date brief/guide is left alone — its existing
title/customer/difficulty is just read back for the list. Every run (including
`--dry-run`) writes that same triage list to `case-getter/gets/get-<timestamp>.md`.

```bash
python case-getter/case_getter.py                # refresh stale/new cases, list every relevant one
python case_wizard.py getter                      # same thing
python case-getter/case_getter.py --dry-run       # just list what's relevant, no writes
python case-getter/case_getter.py --limit 3       # cap how many new/stale cases to (re)process this run
python case-getter/case_getter.py --sort hardest  # triage list hardest-first instead of easiest-first
```

Needs the same CRM/Azure DevOps/`claude` access as case-brief and case-guide — it's
just automating running both of those over more than one case at a time.

### 1. case-brief — gather context

Looks up the case from CRM via the Dataverse Web API, authenticated with OAuth
(Entra ID) device-code sign-in, and resolves any Azure DevOps PR/branch links
already pasted into the case. No config file — org/CRM/OAuth client are fixed
constants (this tool only ever talks to one org and one CRM). There's no
CRM-skipping or ADO-skipping flag: the Azure DevOps lookup always runs (fails safe
into an "## Related Links" error note rather than breaking the run if it can't
complete), and Azure DevOps results are only ever resolved from links found *in*
the CRM case text, so without a CRM lookup there's nothing to report either way.

```bash
python case-brief/case_brief.py --demo             # fake data, fastest smoke test
python case-brief/case_brief.py T2611845            # real run
python case-brief/case_brief.py -h
```

The first real run prints a one-time device code and a URL — open it in any browser
and sign in with your normal CRM account. Later runs are silent: the token is
cached (`case-brief/.token_cache/`, gitignored) and silently refreshed. No admin
app-registration step is needed (see `CLAUDE.md`'s Dataverse API section for why).

Output: `case-brief/briefs/brief-<number>.md`

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

Output: `case-guide/guides/guide-<number>.md`

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
to clone the repo. Interactive-only — always prompts for the repo URL (unless
`--repo` is given) and always asks you to confirm before touching anything; there's
no flag to skip either prompt. Optional `config.json` (see
`case-solve/config.example.json`) for `run_tests`/`run_lint`/`run_build`/`claude.*`.

If the guide says the case isn't ready for a developer to start alone yet (waiting
on a customer reply, a manager sign-off, etc.), case-solve stops before touching
anything and points you at the guide's own "Before You Start" section — there's no
flag to override this either; fix the guide (or re-run case-guide) and re-run
case-solve once it's actually resolved.

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
python run_tests.py              # every stage
python run_tests.py brief guide  # just these
```

## Status

- **Brief:** CRM (Dataverse Web API, OAuth) + ADO working, 196 tests (`case-brief/tests/`)
- **Guide:** stable, 110 tests (`case-guide/tests/`)
- **Solve:** MVP — clone/branch/dependency-install verified, 157 tests
  (`case-solve/tests/`); a real end-to-end Claude implementation run against a live
  repo is the main thing left to exercise
- **Getter:** working, verified against live CRM data; 56 tests (`case-getter/tests/`)

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
