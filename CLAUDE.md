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

python case-brief/case_brief.py --demo        # fake data, no API calls -- fastest smoke test
python case-brief/case_brief.py T2611845      # real run: CRM lookup (OAuth) + ADO direct-reference resolution
python case-brief/case_brief.py --skip-crm    # ADO-only, no CRM sign-in

python case-guide/case_guide.py T2611845      # needs a brief already on disk, and the claude CLI on PATH
python case-guide/case_guide.py 12345         # smoke test: reads the checked-in demo brief

python case-solve/case_solve.py T2611845 --repo <url> --show-plan   # preview plan, no apply
python case-solve/case_solve.py T2611845 --repo <url> --dry-run     # preview changes, no commit
```

```
python run_tests.py                              # all three stages' test suites (must run as separate processes)
python -m unittest discover -s tests -v           # from any one stage's own directory, or repo root for case_wizard.py's own tests
```

Test counts: case-brief 123, case-guide 84, case-solve 141, root (`case_wizard.py`) 29
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

**CRM (`lib/crm_scrape.py`, over the real Dataverse Web API).** Always by ticket
number (no auto-detect from an already-open case tab — cut for being a confusing
second mode). `crm_scrape.py` was never HTML-scraping the CRM UI — it makes real
Dataverse Web API calls (`/api/data/v9.2/incidents`, `/annotations`,
`/activitypointers`, `EntityDefinitions`) and always has. What changed 2026-08-26 is
*how* those calls get authenticated: OAuth (Entra ID) via MSAL device-code sign-in
(`lib/dataverse_auth.py`), not a Playwright-driven Chrome tab riding the CRM
session's own cookie. `case_brief.py::run_crm_lookup` gets a token and wraps it in
`DataverseApiPage` (`lib/dataverse_page.py`), which duck-types the two things
`crm_scrape.py` actually uses off a `page` argument — `.url` and
`.evaluate(js, arg)` — over `requests` + a Bearer token instead of an in-page
browser fetch. That's the whole seam: `crm_scrape.py`, `report.py`, and their
existing tests needed zero changes. Token cache (`case-brief/.token_cache/`,
gitignored — holds a refresh token, a credential) makes every run after the first
sign-in silent — no browser, no Chrome profile, nothing to keep logged in by hand.
Does **not** retry or degrade on failure — an expired/blocked token or a permissions
error surfaces as an explicit `DataverseAuthError`/HTTP error, not a silent partial
result.

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

**Dataverse API access investigation (2026-08-26).** Before replacing the browser
scraper, verified end-to-end rather than assumed:
1. **Auth mechanism**: device-code OAuth via MSAL, using a well-known Microsoft
   first-party *public* client ID (`51f81489-12ee-4a9e-aaae-a2591f45987d` — a
   native/desktop app type, no secret, already delegated `user_impersonation` access
   to Dataverse in this tenant). **No Entra ID admin app registration was needed.**
2. **Identity/permissions**: signed in as `rfelinger@artex-is.cz`
   (tenant `2fb165ea-8dc4-4800-ace7-db202bb064e6`); `WhoAmI` returned 200; a live
   `incidents` query returned real case data. Same user, same Dataverse security
   role as the browser session already used — permissions don't vary by auth
   transport, only by the underlying user/role, so this covers `annotations`/
   `activitypointers`/`EntityDefinitions` too (same API, same role).
3. **Table name confirmed, not assumed**: CRM cases are the `incident` entity
   (`incidents` as an API set name), matching what `crm_scrape.py` already assumed.
4. **Data parity**: `DataverseApiPage.evaluate` calls the exact same REST endpoints
   with the exact same headers as `crm_scrape._FETCH_JS`'s old in-browser fetch,
   returning the identical JSON shape — as the same user against the same
   environment, output is structurally identical by construction, not just by
   spot-check, and confirmed with a real end-to-end run against a live ticket.
5. If a tenant *does* block the well-known client (Conditional Access / consent
   policy), `get_access_token` raises `DataverseAuthError` with the AADSTS error
   text rather than hanging or silently doing something else — that's the "admin
   needs to do something" signal called for by this investigation, not encountered
   here.

Browser-based scraping (`lib/browser.py`, a Playwright-driven Chrome profile riding
the CRM session's own cookie) was removed outright once this was proven, rather than
kept as a second, parallel path — see "Removed in the 2026-08-26 Dataverse API
migration" below.

**Azure DevOps (`lib/ado_api.py`).** Real REST API via a self-service PAT
(`AZDO_PAT` env var). `run_ado_lookup` flattens everything CRM scraping just found
(title, description, every extra field, every note, every activity, every Related
link — see next paragraph) and scans it via `parse_direct_references` for actual ADO
PR/branch links a support engineer pasted or attached while working the case. Any
found are resolved directly (`get_pull_request`/`get_branch`) — no searching. There
is no broader org-wide search: this tool only ever talks to one org
(`ado_api.ORG_URL`, fixed), and a case that never mentions its own work either
doesn't have any yet or is faster to ask about than to brute-force search for.

**Related links (the case form's "Dev" tab, 2026-08-26).** Besides links merely
pasted into free text, the case form has its own "Dev" tab with a "Související
odkazy" (Related links) grid — entries like "PR 20216 ✅ (CU-BTECH)" pointing at a
`dev.azure.com` PR. This isn't part of the incident record or any field
`crm_scrape.py` already fetched; it's a separate custom entity/relationship,
`art_relatedlinks`, found by live investigation (querying `incident`'s registered
1:N/N:N relationship metadata, then `$expand`-ing each one against a real case until
one came back with data — see the entity's own name and fields below).
`crm_scrape.get_related_links` fetches it via `$expand=art_relatedlinks_Incident_Incident`
directly on the incident record (`RELATED_LINKS_NAV_PROPERTY`) rather than a
`$filter` query against `art_relatedlinks`'s own entity set, since that's what the
investigation actually confirmed works — it also means never needing to know that
entity's real entity-set name or its lookup attribute back to incident, only this
relationship's navigation property name. Each entry's `art_name` (display label,
often carrying a status emoji/tag CRM users typed by hand) and `art_urllink` (the
actual PR/branch URL) are exposed as `related_links` on the case result and: (1)
rendered into the "## Related Links" section by `report.py` (see below), showing
the raw CRM label alongside the link; and (2) fed into `case_brief.py`'s
`_collect_reference_text` alongside notes/activities/fields, so `run_ado_lookup`
resolves them the exact same way as a link merely pasted somewhere — real
title/status/created-by via `ado_api.get_pull_request`, not just the raw CRM
label. Not yet verified against more than the one case used to find it — the
Dev tab grid is likely rare/empty on most cases, same caveat as Notes/Activities.

**Report structure — "## Related Links" / "## Details" (2026-08-26).** The brief's
top-level sections were consolidated so each case's own heading is followed by
exactly one "## Related Links" section (everything that points at outside work:
Azure DevOps branches/PRs resolved from a direct reference in the CRM case, the
Dev tab's `related_links` grid above, and finally the case's own Helpdesk portal
link, in that order — see `report._related_links_lines`/`HELPDESK_LINK_FIELD`) and
one "## Details" section (Description, the promoted description fields, Notes,
Activity Timeline). Whatever was actually found in Related Links is listed first;
a single "_No related links found in the CRM case._" line only appears at the very
end, and only if the combined list (branches + PRs + CRM related links + Helpdesk
link) came up completely empty — never as an upfront assumption ahead of the
search's own results, which is what the old per-category "No direct Azure DevOps
link found"/"No matching branches found"/"No matching pull requests found"
messages did. The Helpdesk link field (`art_helpdesklink`) is matched by
logical_name the same way `DEFAULT_PROMOTED_FIELDS` is, but rendered as a link in
Related Links instead of a text block under Details, and excluded from "Other CRM
Fields" the same way promoted fields are.

The brief no longer suggests a repo to clone/branch commands for — that guess moved
to case-guide (see below), which is the thing that actually needs it; case-brief's
job is just the facts.

**No config file.** Everything is a CLI flag or a fixed constant — org URL, PAT env
var, CRM ticket field, output directory, the Dataverse OAuth client ID/authority/
token-cache path — this tool only ever runs against one org and one CRM, so a
config.json would have had nothing left worth putting in it.

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
7. `build_prompt` fills a fixed 6-section template; `call_claude` shells out to
   `claude -p` non-interactively, piping the prompt on stdin, resolved via
   `shutil.which` (not `shell=True`). Runs as the `case-guide-writer` agent via
   `--agent` (`--no-agent` falls back to claude's plain default persona). A
   `subprocess.run(..., timeout=...)` is a safety net in case an unexpected
   permission prompt ever hangs it.
8. `_looks_like_guide` is a loose sanity check on `claude`'s output — used only to
   print a warning, never to block writing the file. `_has_difficulty_rating` is the
   same pattern for the difficulty line (see below).

**Implementation difficulty rating (2026-08-26).** Section 2 of `PROMPT_TEMPLATE`
asks `claude` for one line right after the case summary —
`**Implementation Difficulty:** X/10 -- <short reason>`. X has to come from a fixed
10-band rubric (`DIFFICULTY_RUBRIC`, inlined into every prompt regardless of
`--agent`/`--no-agent`) rather than `claude`'s own free-floating judgment per call —
the whole point is that the same kind of case scores the same way across separate
guides/cases, which a fresh, unanchored 1-10 guess every time would not reliably do.
`case-guide-writer.md`'s persona doc reinforces the same rubric/brevity expectation
for when the agent *is* used, but the rubric itself lives in `PROMPT_TEMPLATE` so it
applies either way. `_has_difficulty_rating` is a loose regex sanity check (same
warn-only pattern as `_looks_like_guide`) in case `claude` drops the line.

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
  heaviest dependency in the project. Not pursued at the time — no API-access path
  was known to be available for this CRM instance, so browser scraping stayed the
  only option.
  **Superseded 2026-08-26**: re-investigated and found to work — see case-brief's
  "Dataverse API access investigation" section above. `msal` (listed just above as
  removed for being unused) is back in `requirements.txt`, now actually imported by
  `lib/dataverse_auth.py`.

## Removed in the 2026-08-26 Dataverse API migration

Once OAuth access was proven end-to-end (see case-brief's "Dataverse API access
investigation"), the browser-based CRM auth it replaced was deleted outright rather
than kept as a second, parallel path:

- `case-brief/lib/browser.py` and `case-brief/tests/test_browser.py` — the
  Playwright/CDP Chrome-automation-profile machinery (`ensure_chrome`,
  `launch_headless_context`, `wait_until_ready`, `close_chrome_window`, the
  `.last_urls.json` cache, ...).
- `case_brief.py`'s `run_browser_scrape`/`_try_headless_scrape`/`_remember_crm_url`,
  the `CHROME_CFG`/`CRM_HOST_CONTAINS` constants, and the `--keep-browser-open` flag.
  `--skip-browser` was renamed `--skip-crm` (still ADO-only, just no longer
  browser-specific wording now that CRM auth never opens a browser).
  There is no `--api` flag — Dataverse OAuth is simply how CRM auth works now, not
  an opt-in alternative to something else.
- The `playwright` dependency and the `python -m playwright install chromium`
  setup step, and `case-brief/chrome-automation-profile/`'s `.gitignore` entry.
- `crm_scrape.py`, `report.py`, and everything downstream (`case_guide.py`'s brief
  parsing) needed **no changes** — see the data-parity point in the investigation
  notes for why.

## Future ideas

- **case-brief:** verify the "get everything" CRM scrape (full-record fetch, no
  `$select`; `EntityDefinitions` metadata labeling; Notes/Activity Timeline calls)
  and direct ADO reference resolution against real, live cases — both are currently
  only unit-tested against faked responses. A live OAuth run against `incidents`
  is confirmed (see the Dataverse API access investigation); `annotations`/
  `activitypointers`/`EntityDefinitions` haven't specifically been exercised live
  yet, ideally against a case with a memo-type/lookup/option-set field populated.
  Make sure AZDO content is actually reachable and that direct-reference links
  found in the case are investigated properly (not just detected).
  Internal description: already wired (`report.DEFAULT_PROMOTED_FIELDS` includes
  `art_internaldescriptionandnotes`, promoted into its own subsection right after
  Description whenever the field is populated — see `case-brief`'s own section
  above); `--demo`'s sample data now uses the real logical name too (2026-08-26) so
  running it actually exercises that path instead of the field landing in "Other
  CRM Fields" under a made-up name. Still not exercised against a real case.
- **case-guide:** verify the customer↔project fuzzy match
  (`repo_suggest._fuzzy_score`/`best_fuzzy_match`) against how your org's actual ADO
  projects are named vs. how CRM customer names look — the threshold/lead values may
  need tuning. Longer term: actually run the clone + branch-create instead of just
  suggesting the commands, so starting work on a case skips the copy-paste.
- **case-solve:** better error messages/recovery from partial failures; more
  dependency managers (poetry, pipenv, yarn, mix); smarter test selection
  (by-file/by-tag); smarter default-branch detection (main vs. master vs. develop);
  track/replay/diff case-solve runs across a repo's history.
