# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in
this repository. It consolidates what used to be nine separate doc files (a
README/CLAUDE.md/TODO.md per stage plus a root README/TROUBLESHOOT) into this file
plus the root `README.md` — same information, fewer places to keep in sync. See
README.md for user-facing setup/usage/troubleshooting; this file is architecture and
design-rationale notes.

## Commands

```
.venv\Scripts\Activate.ps1   # from repo root, on Windows -- has everything all three stages need

python case-brief/case_brief.py --demo        # fake data, no browser/API calls -- fastest smoke test
python case-brief/case_brief.py T2611845      # real run: CRM lookup + ADO direct-reference resolution
python case-brief/case_brief.py --skip-browser # ADO-only, no Chrome

python case-guide/case_guide.py T2611845      # needs a brief already on disk, and the claude CLI on PATH
python case-guide/case_guide.py 12345         # smoke test: reads the checked-in demo brief

python case-solve/case_solve.py T2611845 --repo <url> --show-plan   # preview plan, no apply
python case-solve/case_solve.py T2611845 --repo <url> --dry-run     # preview changes, no commit
```

```
python run_tests.py                              # all three stages' test suites (must run as separate processes)
python -m unittest discover -s tests -v           # from any one stage's own directory, or repo root for case_wizard.py's own tests
```

Test counts: case-brief 120, case-guide 84, case-solve 141, root (`case_wizard.py`) 29
— all mocked, no network. Deliberately not exhaustive over every CLI flag or every
low-risk rendering/plumbing branch; those are easily eyeballed with `--demo`-style
manual runs. What no test suite here can cover: a real `claude` call, a live Azure
DevOps org/CRM, and (case-solve) a real end-to-end implementation run against a real
repo.

## Shared package (`shared/`)

Deliberately small — only pieces that were pure, stable, and already identical
across projects were ever extracted here (see "Known accepted duplication" below for
what was *not* extracted, and why).

- `ado_auth.py` — PAT → Basic-auth header. Used by both `ado_api.py` copies.
- `config.py` — JSON config load/deep-merge/`_comment`-stripping, used by case-guide
  and case-solve (case-brief has no config file at all).
- `console.py` — enables UTF-8 console output on Windows.
- `safe_name.py` — filename sanitizer (collapses unsafe/path-traversal characters),
  used by case-brief and case-guide for their output filenames.

There used to also be `shared/editor.py` (open a file in VS Code after a run, with a
`--no-open` flag on every stage to suppress it). Removed entirely — cut to shed the
implicit "must have VS Code on PATH" requirement; it was a convenience, not a
dependency any stage's actual job needs.

## case-brief

Two independent data sources, merged into one Markdown report:

**CRM (`lib/crm_scrape.py`, default path: browser scraping).** Always by ticket
number (no auto-detect from an already-open case tab — cut for being a confusing
second mode). `case_brief.py::run_browser_scrape` first tries a headless, no-window
pass: if `.last_urls.json` has a CRM URL from a previous run, it launches headless
against the same profile dir (reusing whatever cookies a previous headed sign-in
left there) and checks `crm_scrape.is_authenticated`. Anything else (no cached URL,
expired session, launch failed) falls back to the original headed flow:
`lib/browser.py` launches a dedicated, visible-but-minimized Chrome profile
(`chrome-automation-profile/`, gitignored) via CDP on a fixed debug port, distinct
from your normal browsing profile — no app registration needed either way. The
headed window is closed by the script itself at the end of any run that opened one;
the last-used CRM URL is always cached to `.last_urls.json`.

Scrapes the whole case, not a curated subset — the incident record is fetched with
no `$select` at all, so an org's own custom fields show up too, labeled via a
best-effort `EntityDefinitions` metadata call (degrades to raw logical names if
denied). Customer/owner are resolved from the lookup's own display-name annotation
rather than `$expand` (fixes a contact-type customer and a team-owned case, which
`$expand=customerid_account`/`$expand=owninguser` never covered). Notes and the
Activity Timeline are fetched separately, each capped with truncation surfaced
rather than silently dropped. Most "get everything" fields are org-specific noise
most of the time, so `report.build_markdown`'s `promoted_fields` param (default:
`report.DEFAULT_PROMOTED_FIELDS`, fixed) pulls specific fields into their own
subsection right after Description; everything else lands in an uncurated "Other CRM
Fields" section at the bottom.

**Azure DevOps (`lib/ado_api.py`).** Real REST API via a self-service PAT
(`AZDO_PAT` env var). `run_ado_lookup` flattens everything CRM scraping just found
(title, description, every extra field, every note, every activity) and scans it via
`parse_direct_references` for actual ADO PR/branch links a support engineer pasted
while working the case. Any found are resolved directly (`get_pull_request`/
`get_branch`) — no searching. There is no broader org-wide search: this tool only
ever talks to one org (`ado_api.ORG_URL`, fixed), and a case that never mentions its
own work either doesn't have any yet or is faster to ask about than to
brute-force search for.

The brief no longer suggests a repo to clone/branch commands for — that guess moved
to case-guide (see below), which is the thing that actually needs it; case-brief's
job is just the facts.

**No config file.** Everything is a CLI flag or a fixed constant — org URL, PAT env
var, CRM ticket field/host pattern, output directory, Chrome profile/port/executable
— this tool only ever runs against one org, one CRM, and its own dedicated Chrome
profile, so a config.json would have had nothing left worth putting in it.

`lib/report.py` is the only place that renders the final Markdown and writes it —
CRM/ADO results are plain dicts/lists by the time they reach it.

## case-guide

Independent from case-brief at the business-logic level — reading the case's data is
a filesystem contract (reads the Markdown file `case_brief.py` already wrote).
`lib/ado_api.py` here is a deliberate standalone copy of case-brief's own module for
search/query logic (see "Known accepted duplication" below).

Every request goes through one `requests.Session` (via `open_session`) instead of a
fresh connection per call, and independent per-repo/branch/PR fetches run through a
small thread pool (`ado_api.MAX_WORKERS`) since they don't depend on each other.

**Repo suggestion (`lib/repo_suggest.py::resolve_suggested_repos`)** decides which
repo(s)/branch to suggest, even when Azure DevOps found zero matching branches/PRs
yet (the common case for a brand-new case). No manual override — it's a fuzzy-match
of the case's customer name against ADO project names, then repo names, via
`difflib.SequenceMatcher` (`best_fuzzy_match` requires the top match to both clear a
threshold *and* beat the runner-up by a margin; an ambiguous guess is treated as no
guess). `case_guide.py::_extract_customer`/`_extract_case_title` pull the customer
name/case title back out of the brief Markdown by regex, relying on case-brief's
fixed rendering layout. `gather_suggested_repo` merges this guess with any confirmed
match from this run's own live ADO search — confirmed always beats guessed.

**A guessed repo is never presented as confirmed, at two layers:**
`format_suggested_repo` tags each auto-matched entry inline
("⚠️ guessed from customer name...") and the prompt instructs `claude` to carry that
tag into its own prose. `case_guide.py::_add_guess_warning` is the actual guarantee,
independent of whether `claude` kept the hint: after `call_claude` returns, if any
suggested repo came from the fuzzy match (not a confirmed ADO search hit), it
force-inserts a standalone warning block right after the guide's title.

`.claude/agents/case-guide-writer.md` (repo root) is the persona the headless
`claude` call runs as — brevity, house-style, convention-matching.

**Pipeline (`main` in `case_guide.py`):**

1. `find_brief` locates the brief by exact filename match, falling back to a unique
   substring glob match; ambiguous/missing matches are reported rather than guessed.
2. `gather_ado_detail` re-runs the same branch/PR search case-brief does, then
   fetches one level deeper per hit (commit messages, changed files, review
   comments) concurrently. `ado_api.AdoAuthError` (401/403) is deliberately NOT
   swallowed like other request failures — an expired/under-scoped PAT is a hard
   error, not "no related work found" (a very different claim to make to someone
   picking up a case).
3. `format_ado_detail` renders that into Markdown, folding any partial-search
   warnings into a visible note rather than presenting a partial result as complete.
4. `_truncate` caps the assembled ADO-detail text (and, with a different limit, the
   house-style example) at a fixed size before it goes into the prompt.
5. `find_example_guide` picks the most recently written other guide as a
   tone/structure anchor (`--no-example` disables).
6. `gather_suggested_repo` resolves the repo/branch to suggest (see above).
7. `build_prompt` fills a fixed 5-section template; `call_claude` shells out to
   `claude -p` non-interactively, piping the prompt on stdin, resolved via
   `shutil.which` (not `shell=True`). Runs as the `case-guide-writer` agent via
   `--agent` (`--no-agent` falls back to claude's plain default persona). A
   `subprocess.run(..., timeout=...)` is a safety net in case an unexpected
   permission prompt ever hangs it.
8. `_looks_like_guide` is a loose sanity check on `claude`'s output — used only to
   print a warning, never to block writing the file.

**Skip-if-unchanged:** if a guide already exists and is newer than its brief, `main`
returns early instead of re-spending an ADO search + a `claude` call. No override
flag — delete the existing guide file to force a regenerate.

**Config merge order:** `DEFAULTS` → `config.json` (deep-merged, `_comment` stripped)
→ CLI flags.

## case-solve

Independent from case-brief and case-guide — reads the guide file case-guide
produces. MVP: every pipeline stage is unit-tested with mocks, but a real
end-to-end run (an actual `claude` call producing a usable plan/steps against a real
repo, plus edge cases like merge conflicts or missing tools) hasn't happened yet.

**Pipeline (`main` in `case_solve.py`):**

1. Find guide (exact match, then glob fallback)
2. Extract repo suggestion (`git clone` link in guide text)
3. Prompt for repo URL (suggest from guide, ask user to confirm/override; `--yes`
   requires `--repo` explicitly rather than guessing, since a non-interactive caller
   has no terminal to answer a prompt with)
4. Workspace setup — clone/fetch, create `case/<case-number>` branch
5. Install dependencies — auto-detect Python/Node/Rust/.NET
6. Implementation — Claude reads guide + repo structure, generates a plan, then
   file-by-file steps, then applies them
7. Verification — run tests/build/lint (auto-detect available tools)
8. Commit — group changes by category (tests, dependencies, config, docs, source,
   other), one commit per group
9. Report — verification checklist, next steps

**Key modules:** `lib/workspace.py` (clone/branch/dependencies), `lib/implementer.py`
(Claude-guided implementation), `lib/verifier.py` (auto-detect + run tests/lint/
build), `lib/committer.py` (git ops, logical grouping), `lib/report.py` (checklist
generation), `.claude/agents/case-solver.md` (repo root — persona for Claude's
implementation guidance).

**Two-stage Claude interaction (plan → steps → apply)**, not one shot: guards
against silent truncation on complex repos, lets you visually inspect steps before
they're applied, and avoids re-invocation on a messy state. Costs a second Claude
call; buys auditability.

**Auto-detection over templates** for both dependency install and
tests/lint/build — works with any project layout without pre-registration, at the
cost of not covering tools outside the fixed table (poetry, pipenv, yarn, mix, ...
are known gaps).

**Workspace reuse:** cloned repos are cached in `case-solves/repos/<repo-name>/` and
fetched between runs; each case gets its own branch in the same repo. Saves
bandwidth, keeps local history, lets you compare across cases in the same repo.

**No destructive git operations:** branches are created fresh each run (old one
deleted if it exists), nothing is ever pushed automatically, `main`/`master` is
never touched.

**Config merge order:** same pattern as the other two stages — `DEFAULTS` dict →
`config.json` (deep-merged) → CLI flags (`run_tests`/`run_lint`/`run_build` only;
`claude.model`/`agent`/`timeout` are config-only, no CLI flag).

## Known accepted duplication

`case-brief/lib/ado_api.py` and `case-guide/lib/ado_api.py` are two independent
copies of Azure DevOps query logic (177 vs. 280 lines) — only the pure,
byte-for-byte-identical auth-header piece was ever extracted, to `shared/ado_auth.py`.

This was deliberately re-examined again on 2026-08-26 (request: merge further if it
can be done without causing harm) and the answer is still no, for a concrete reason
found on inspection rather than just precedent: the two copies aren't just
differently-featured, they use genuinely different request/error models.
case-brief's calls bare `requests.get` per request and lets a 401/403 raise a plain
`requests.HTTPError` (every caller wraps ADO calls in a blanket `except Exception`
already, so this is fine for it). case-guide's reuses one `requests.Session` across
a whole run and raises a distinct `AdoAuthError` on 401/403 that's deliberately NOT
swallowed by its best-effort `_get_or` helper — an expired PAT has to read as a hard
error there, not as "no related work found." Merging even just the closest thing to
duplicated CRUD (`list_repos`/`get_repo`) would mean either changing case-brief's
error semantics (a real behavior change, not a cleanup) or forking behavior inside
the shared function per caller (which doesn't actually reduce complexity). Left as
independent copies; this note exists so a future pass doesn't have to re-derive the
same conclusion from scratch.

## Removed in the 2026-08-26 simplification pass

- `msal` dependency — was listed in every `requirements.txt` but never actually
  imported anywhere in the codebase.
- VS Code auto-open (`shared/editor.py`, every stage's `--no-open` flag,
  `open_in_vscode`/`open_in_editor`/`open_editor` params and config keys) — a
  convenience, not a real dependency; cut to shed the implicit "must have VS Code on
  PATH" requirement.
- Nine separate doc files (a README.md/CLAUDE.md/TODO.md per stage, plus root
  TROUBLESHOOT.md) collapsed into this file and the root README.md.
- CRM browser scraping (Playwright + a dedicated Chrome profile) was considered for
  replacement with a direct Dynamics 365 Web API call, which would have dropped the
  heaviest dependency in the project. Not pursued — no API-access path is currently
  available for this CRM instance, so browser scraping stays the only option.

## Future ideas

- **case-brief:** verify the "get everything" CRM scrape (full-record fetch, no
  `$select`; `EntityDefinitions` metadata labeling; Notes/Activity Timeline calls)
  and direct ADO reference resolution against real, live cases — both are currently
  only unit-tested against faked responses.
- **case-guide:** verify the customer↔project fuzzy match
  (`repo_suggest._fuzzy_score`/`best_fuzzy_match`) against how your org's actual ADO
  projects are named vs. how CRM customer names look — the threshold/lead values may
  need tuning. Longer term: actually run the clone + branch-create instead of just
  suggesting the commands, so starting work on a case skips the copy-paste.
- **case-solve:** better error messages/recovery from partial failures; more
  dependency managers (poetry, pipenv, yarn, mix); smarter test selection
  (by-file/by-tag); smarter default-branch detection (main vs. master vs. develop);
  track/replay/diff case-solve runs across a repo's history.
