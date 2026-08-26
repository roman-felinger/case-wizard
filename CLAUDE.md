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

python case-guide/case_guide.py T2611845      # needs a brief already on disk, and the claude CLI on PATH
python case-guide/case_guide.py 12345         # smoke test: reads the checked-in demo brief

python case-solve/case_solve.py T2611845 --repo <url> --show-plan   # preview plan, no apply
python case-solve/case_solve.py T2611845 --repo <url> --dry-run     # preview changes, no commit

python case-getter/case_getter.py             # brief + guide every new, unassigned CRM case
python case-getter/case_getter.py --dry-run   # just list what it would pick up
```

```
python run_tests.py                              # every stage's test suite (must run as separate processes)
python -m unittest discover -s tests -v           # from any one stage's own directory, or repo root for case_wizard.py's own tests
```

Test counts: case-brief 196, case-guide 110, case-solve 157, case-getter 56,
root (`case_wizard.py`) 30 — all mocked, no network (case-getter's own tests mock
subprocess/CRM calls; see its own section below for how it was verified live once).
Deliberately not exhaustive over every CLI flag or every low-risk rendering/plumbing
branch; those are easily eyeballed with `--demo`-style manual runs. What no test
suite here can cover: a real `claude` call, a live Azure DevOps org/CRM, and
(case-solve) a real end-to-end implementation run against a real repo.

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

## Output filenames (2026-08-26)

case-brief and case-guide used to both write `case-<code>.md` into differently
named folders (`case-briefs/`, `case-guides/`) — the same filename for two
different kinds of file, distinguishable only by which folder it happened to be
sitting in. Renamed so the filename itself says what it is: case-brief now writes
`brief-<code>.md` into `case-brief/briefs/`; case-guide now writes
`guide-<code>.md` into `case-guide/guides/`. case-getter's own run reports moved
from `case-getter/case-gets/` to `case-getter/gets/` to match (still one file per
run, `get-<timestamp>.md`, not per case — see case-getter's own section). Every
place that constructs or parses either pattern moved together:
`report.write_and_open` (case-brief); `case_guide.py`'s `find_brief`/`DEFAULTS`/
the guide's own `write_and_open` stem; `case_solve.py`'s `guide_filename`/
`find_guide`/`GUIDE_DIR`; and `case_getter.py`'s `BRIEF_DIR`/`GUIDE_DIR`/
`REPORT_DIR`/`existing_brief_numbers` (construct *and* parse — it regexes
case-brief's filenames back into ticket numbers). The checked-in demo files
were renamed to match: `case-brief/briefs/brief-12345.md`,
`case-guide/guides/guide-12345.md`. `lib/writer.py::guide_filename` itself
needed no change — it never hardcoded the `"case-"`/`"guide-"` prefix, the
caller (`case_guide.py`) already supplies the whole stem.

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
exactly one "## Related Links" section and one "## Details" section (Description,
the promoted description fields, Notes, Activity Timeline).

Related Links renders, in this fixed order: (1) the case's own CRM record link
(`Case link:`), (2) the case's own Helpdesk portal link (`Helpdesk link:`) — both
always available on a real case, so neither is ever reported as missing; (3) the Dev
tab's `related_links` grid; (4) Azure DevOps branches/PRs resolved from a direct
reference found elsewhere in the CRM case (see `report._related_links_lines`/
`HELPDESK_LINK_FIELD`). (3) and (4) are genuinely optional — a case may not have
either yet. Only (3) is ever reported missing, though, as one combined line — e.g.
`_No linked Azure DevOps items found for this case._` (see `report._join_and`,
still there for when a future category needs combining with it). Branches/PRs
coming back empty is deliberately NOT reported at all, even when literally true —
a case simply not having referenced its own work yet isn't worth a dedicated
"not found" callout every time. A related link's own bullet has no status/
created-on shown (CRM's own snapshot from whenever it was attached, not refreshed
since, unlike the ADO section which fetches live) — a plain-text label with the URL
itself as the hyperlink, same convention as the Helpdesk link (so it's clickable
and still readable/copyable without clicking through, rather than a descriptive
label hiding the URL from view). The Helpdesk link field (`art_helpdesklink`) is
matched by logical_name the same way `DEFAULT_PROMOTED_FIELDS` is, but rendered as
a link in Related Links instead of a text block under Details, and excluded from
"Other Populated CRM Fields" the same way promoted fields are.

Details' own members are combined the same way — whichever came up empty (with no
error) named together in one line, e.g. `_No Additional Public Description,
Internal Description, Notes, and Activity Timeline found for this case._` — rather
than either a single blanket "nothing found" line that stays silent about which
specific thing is missing, or a separate "not found" line per missing member
cluttering the section.

**No duplicate PR/branch linking between related_links and the ADO section
(2026-08-26).** A PR attached in CRM's Dev tab grid used to also get resolved and
listed again in the ADO branches/PRs section — its URL was part of the text
`case_brief.py`'s `_collect_reference_text` scanned for direct references, so it
always turned up there too. Fixed two ways: `_collect_reference_text` no longer
includes `related_links` at all (superseded by the fix below, and scanning it just
meant resolving-then-discarding); `run_ado_lookup`'s new `_related_link_refs` parses
just the `related_links` URLs the same way `ado_api.parse_direct_references` parses
everything else, and excludes any branch/PR already covered by them (from wherever
it was found — a note, a field, anywhere) before resolving. Matched by
(project, id) for PRs — Azure DevOps PR ids are unique org-wide — and (project,
branch) for branches, deliberately NOT including repo: the CRM-stored related-link
URL and the one resolved via the ADO API can represent the same repo as a different
string (a repo GUID vs. its human-readable name), so comparing on repo too would
miss real duplicates. `--demo` bypasses `run_ado_lookup` (no real API calls), so its
own `related_links`/`branches`/`pull_requests` sample data is kept deliberately
non-overlapping by hand instead, so the demo doesn't visually reintroduce the very
duplication this dedup exists to prevent.

**`art_descriptionadditionalpublic`, not `art_additionalpublicdescription`
(2026-08-26).** `DEFAULT_PROMOTED_FIELDS`' secondary/public-description entry had
the wrong logical name (word order swapped) — confirmed wrong against a real case's
brief, where the field was landing in "Other Populated CRM Fields" under its raw
Czech label instead of getting promoted. Fixed in `report.py`, `case_brief.py`'s
demo data, and the matching tests.

**Case link (2026-08-26).** `crm_scrape._to_result` builds the case's own CRM
record deep link (`main.aspx?appid=...&forceUCI=1&pagetype=entityrecord&etn=
incident&id=...`) — the `appid` (`crm_scrape.CRM_APP_ID`, this org's Customer
Service model-driven app) and `forceUCI=1` were added 2026-08-26 so the link opens
directly in that app instead of Dynamics falling back to a default app or prompting
to pick one. `report._related_links_lines` renders it as the very first bullet in
"## Related Links" (`Case link: [url](url)`, same plain-label/URL-as-hyperlink
style as the Helpdesk link) — it's a detail of the case record itself, not one more
piece of related work, so it's also deliberately never part of that section's
"missing" line (crm_scrape.py always populates it once a case is found, so there's
nothing to
report absent).

**Description folded into the combined "missing" line too (2026-08-26).** An empty
Description used to still render its own `**Description:**` header followed by
`_(none)_`. It's now treated like the other optional Details members -- omitted
entirely and named in the combined "missing" line instead (first, ahead of the
promoted fields/Notes/Activity Timeline, matching its position in the rendered
Details -- see `build_markdown`), so a case with nothing to show doesn't clutter
the brief with an empty header + placeholder for something that isn't there.

**English labels for known CRM fields (2026-08-26).** The CRM org's own field labels
are mostly Czech. `DEFAULT_PROMOTED_FIELDS`' two known fields get a fixed English
label (`report._PROMOTED_FIELD_ENGLISH_LABELS`) that overrides whatever label the
metadata call returned, used both for the field's own subsection header and for
Details' combined "missing" line. `art_internaldescriptionandnotes` is labeled just
"Internal Description", not "Internal Description & Notes" -- the latter read as one
combined item with the case's own Notes (the activity/annotation notes, a distinct
thing rendered separately, see `missing_details.append("Notes")` -- capitalized to
match, since it now sits in the same combined "missing" line as the Title-Case field
labels). Activity Timeline's own entry in that same line
(`missing_details.append("Activity Timeline")`) is capitalized for the same reason.
"## Estimates & Totals" fields are matched by label, not logical_name (org rollup
fields whose logical names aren't known ahead of time). This started as a broad "any
field whose label contains total/estimate/celkem/odhad" heuristic with a separate
skip-list and a Czech→English translation table, but that swept in noise (kilometers,
price, dispatch counts, a rollup's own "(stav)"/"(datum poslední aktualizace)"
metadata) the case form's own "Estimate & Totals" widget doesn't show. Replaced
2026-08-26 with a fixed curated set of exactly the four fields that widget shows —
Estimate, Billable Hours, Non-Billable Hours, Total Hours, rendered in that order
regardless of the order the CRM returned them in (`report._ESTIMATE_CATEGORY_ORDER`).
`report._classify_estimate_field`/`_ESTIMATE_FIELD_MATCHERS` match each field's label
against that fixed set (case-insensitive substring/equality, tolerant of the label's
Czech word order varying between the case form's own label and what the
EntityDefinitions metadata call returns for the same field — observed: "Fakturované
hodiny celkem" on the form vs. "Celkem fakturované hodiny" from metadata), skipping a
rollup's own "(stav)"/"...aktualizace" metadata sub-fields so they're never mistaken
for the real value. No blurb and no `logical_name` shown per bullet, unlike "Other
Populated CRM Fields" — this section is meant to be skimmed, not used to hunt for a
field worth promoting. A field that doesn't match one of the four (kilometers, price,
dispatch counts, the "Odhad schválen" approver lookup, ...) isn't specially dropped
anymore — it just isn't pulled out of "Other Populated CRM Fields", the same as any
other uncurated field.

**"Other CRM Fields" renamed "Other Populated CRM Fields" (2026-08-26), no blurb.**
Its explanatory italic line ("Every other populated CRM field not already surfaced
above...") is gone — the renamed heading says what it is on its own.

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

## case-getter (2026-08-26)

A helper on top of case-brief and case-guide, not a third independent stage: it
finds cases worth briefing/guiding, then runs those two stages' own scripts as
subprocesses exactly as `case_wizard.py all <code> --stop-after guide` would, one
case at a time. Not part of `case_wizard.py`'s `all` chain (that chain is
per-case_number; case-getter operates over however many cases it finds) — it's
dispatched via `case_wizard.py getter` as an extra entry in `SCRIPTS`, deliberately
outside `STAGES`.

**"New" and "relevant", made concrete.** New = no brief already on disk
(`case-brief/briefs/brief-<code>.md`) — re-briefing/re-guiding a case that
already has one is what the normal per-case commands are for.
Relevant = still Active and either still owned by the CRM's default
unassigned-case team (nobody's claimed it yet) **or** already owned by whoever is
signed in (2026-08-26 addition -- yours already, not someone else's). "Accessible
to me" needed no extra filter code: the Dataverse Web API call is already scoped to
the signed-in user's own security role (see case-brief's Dataverse API access
investigation above), so the listing query only ever returns what that user could
already see in the CRM UI.

**Investigated live before writing the filter (2026-08-26), same as case-brief's
own Dataverse work: an unfiltered query over active cases showed every one of them
owned either by a real `systemuser` or by a `team` called "Helpdesk e-mail" —**
confirming that team *is* the "nobody's touched this yet" default every new case
starts under, and that incidents expose it directly via `_owningteam_value` (not
just the generic, polymorphic `_ownerid_value`). `crm_scrape.list_new_cases`
resolves that team's id by name at runtime (`_resolve_team_id`, a `teams?$filter=
name eq '...'` call) rather than hardcoding its GUID like `CRM_APP_ID` — so
recreating the team in this org doesn't need a code change here too — then filters
`incidents` on `statecode eq 0 and (_owningteam_value eq {team_id} or
_owninguser_value eq {my_user_id})`, `my_user_id` resolved via
`get_current_user_id`'s `WhoAmI` call on the same token/page rather than a
parameter a caller would otherwise have to already know. A `WhoAmI` failure
degrades to the team-only filter (each case's `owned_by_me` then just always
False) rather than failing the whole listing. Verified against live data: of 26
currently-active cases owned by that team, all 26 were genuinely untouched (status
"Nový"/New, no other owner ever assigned); of the 4 active cases owned by the
signed-in user, `list_new_cases` correctly flagged all 4 as `owned_by_me: True` —
and a real `case_getter.py --limit 1` run against one of the unassigned ones
produced a correct brief, a correct guide (including a parseable
`**Implementation Difficulty:**` line), and a correct triage summary line, end to
end.

**`$select`-ing the bare `owninguser` attribute silently misbehaves (2026-08-26
finding).** First attempt selected `owninguser` (matching how `prioritycode`/
`statuscode`/etc. are selected by their bare logical name) and got back a case
where a case you owned still showed `owned_by_me: False` for every row. Live
comparison showed `$select=owninguser` alone returns the *entire* record (every
field on the incident, as if $select were ignored) while `$select=ticketnumber,
owninguser` together returns *neither* — no owner field at all, silently, not an
error. The fix: select `_owninguser_value` (the underscore-prefixed nav-property-
value form), which behaves correctly alone or combined with other fields — the
same documented form `_customerid_value` right next to it in the same `$select`
already relied on, that this addition should have matched from the start. Filed as
a concrete gotcha in `list_new_cases`'s own `$select` line, not just here, since
the failure mode (wrong data, no error) is exactly the kind that's easy to miss in
review.

Deliberately a curated `$select` in `list_new_cases`, unlike `lookup_by_ticket`'s
"get everything" — this is a triage list across possibly dozens of cases, not one
case's full brief, so pulling every field for every row would be slow and mostly
wasted. Capped at `crm_scrape.NEW_CASES_TOP` (200), with hitting the cap surfaced as
a warning rather than silently dropping the rest — same "signal, don't silently
truncate" pattern as `NOTES_TOP`/`ACTIVITIES_TOP`.

**Where the listing logic lives.** `crm_scrape.list_new_cases` (the actual OData
query) and `case_brief.list_relevant_cases` (auth + wiring, mirroring
`run_crm_lookup`'s own shape) both live in case-brief, since that's who already owns
the Dataverse connection/`CRM_ORIGIN` — case-getter imports `case_brief` directly for
this one call rather than a third copy of Dataverse auth plumbing. Running the
brief/guide stages themselves still goes through `subprocess` (`run_stage`, same
shape as `case_wizard.py`'s own `run_one`), not a function call into either
script — each stage stays independently invocable/dependency-isolated, and a
`case-brief`/`case-guide` failure on one case can't take the whole run down with it.

**Reading a finished brief/guide back for the summary line is a filesystem
contract, not an import** — `_CASE_TITLE_RE`/`_CUSTOMER_RE`/`_DIFFICULTY_RE` are a
small, deliberate duplication of the same three patterns case-guide's own
`_extract_case_title`/`_extract_customer`/`_DIFFICULTY_RE` already use against the
brief/guide's fixed rendering shape — the same tradeoff (independence over DRY)
"Known accepted duplication" below documents for case-brief's and case-guide's own
`ado_api.py` copies.

**One case failing doesn't stop the run.** A failed `case_brief.py` call skips
`case_guide.py` for that case (nothing to guide yet) and is reported in the
summary with an error note; a failed `case_guide.py` call still reports the
brief's own title/customer, just with no difficulty line. `main`'s exit code is
non-zero if *any* case failed, so a scripted caller can tell — but every other
case in the batch still gets processed.

No config file, same as case-brief — `--limit`/`--dry-run`/`--sort` are the only
flags; the unassigned-team name is a fixed constant
(`crm_scrape.DEFAULT_UNASSIGNED_TEAM_NAME`), not something this tool ever needs to
vary per run.

**Always lists every relevant case, not just new ones (2026-08-26 addition).**
`find_relevant_cases` (renamed from `find_new_relevant_cases`) no longer filters
its result down to cases needing (re)processing — it returns *every* relevant
case, each tagged `is_new`/`stale` so callers can tell three situations apart:
no brief yet, a brief that's out of date (see `is_stale` — compares the CRM
record's own `modifiedon` against a hidden marker `report.build_markdown` stamps
into every brief), and a case that already has a current brief/guide. Only the
first two actually get case-brief/case-guide (re)run; a case already up to date
is left alone and its existing title/customer/difficulty is just read back off
disk (`summarize`) for the triage list — cheap, no subprocess call. This exists
because a run that finds nothing new/stale used to print "no relevant cases
found", which is a useless answer when there's still real work sitting in CRM
that just hasn't changed since it was last briefed — the triage list is now
"what's relevant right now", not "what changed since last time". `--limit` still
caps how many new/stale cases actually get (re)processed in one run, but no
longer hides the rest of the relevant cases from the output — an already-current
case is free to include (a file read) so it's never counted against the limit;
a new/stale case that *is* skipped for hitting the limit still shows up in the
list with whatever's already on disk (nothing, for a case never processed
before). `_tag` renders the three situations as ", stale" / ", up to date" /
no suffix appended to the existing "mine"/"unassigned" ownership tag.

**Sorted by difficulty by default (2026-08-26 addition).** `--sort` used to
default to `"none"` (plain processing order) and only affected a full run, since
a `--dry-run` listing had no difficulty yet to sort by (nothing had been
guided). Now that up-to-date cases carry a real difficulty read straight off an
existing guide, sorting is meaningful in a dry run too — `--sort` defaults to
`"easiest"` and applies to both a full run's summary and a `--dry-run` listing;
`"hardest"`/`"none"` are still available. A case with no difficulty yet (never
guided, or a guide that failed to generate) always sorts last regardless of
direction (`sort_rows`/`_difficulty_num`) — "unknown" isn't the same as
"easiest".

**Run reports (2026-08-26).** Every run (including `--dry-run`) writes a Markdown
report to `case-getter/gets/get-<timestamp>.md` (gitignored, same as the other
stages' generated output) — the same title/customer/difficulty/ownership
information `print_summary`/the dry-run listing already put on the console, so a
triage session leaves something on disk to refer back to. One file per *run*, not
per case (`get-YYYYMMDD-HHMMSS.md`) — unlike case-brief/case-guide/case-solve,
whose output is inherently per-case, case-getter's own output is a run's worth of
triage across however many cases it found, so a per-case filename doesn't fit.
`build_report_markdown`/`write_report` are pure functions of `(rows, dry_run,
timestamp)` — `main` computes one `datetime.now()` per run and derives both the
human-readable timestamp (in the file) and the filesystem-safe one (in the
filename) from it, rather than calling `datetime.now()` twice and risking the two
drifting apart across a slow run.

## case-solve

Independent from case-brief and case-guide — reads the guide file case-guide
produces. MVP: every pipeline stage is unit-tested with mocks, but a real
end-to-end run (an actual `claude` call producing a usable plan/steps against a real
repo, plus edge cases like merge conflicts or missing tools) hasn't happened yet.

**Pipeline (`main` in `case_solve.py`):**

1. Find guide (exact match, then glob fallback)
2. Social readiness gate — stop here if the guide says a developer can't start
   alone yet (see "Social readiness gate" below)
3. Extract repo suggestion (`git clone` link in guide text)
4. Prompt for repo URL (suggest from guide, ask user to confirm/override — always
   interactive; see "No non-interactive escape hatch" below)
5. Workspace setup — clone/fetch, create `case/<case-number>` branch
6. Install dependencies — auto-detect Python/Node/Rust/.NET
7. Implementation — Claude reads guide + repo structure, generates a plan, then
   file-by-file steps, then applies them
8. Verification — run tests/build/lint (auto-detect available tools)
9. Commit — group changes by category (tests, dependencies, config, docs, source,
   other), one commit per group
10. Report — verification checklist, next steps

**Key modules:** `lib/workspace.py` (clone/branch/dependencies), `lib/implementer.py`
(Claude-guided implementation), `lib/verifier.py` (auto-detect + run tests/lint/
build), `lib/committer.py` (git ops, logical grouping), `lib/report.py` (checklist
generation), `.claude/agents/case-solver.md` (repo root — persona for Claude's
implementation guidance).

**Social readiness gate (2026-08-26).** case-guide's prompt asks `claude` for a
`**Ready for Implementation:** Yes` / `No -- <reason>` line right after the case
summary, plus a "## Before You Start -- Social Steps" section when the answer is
No (see case-guide's own section above). case-solve's `check_readiness` parses
that exact line back out of the guide it just read (`case_solve._READINESS_RE`, an
independent copy of case-guide's `_READINESS_RE` -- same "own copy, not shared"
tradeoff as the two `ado_api.py`'s, see "Known accepted duplication" below; keep
the marker regex itself in sync between the two if the wording ever changes) and,
on No, `main` stops immediately -- before even resolving/prompting for a repo --
printing the reason and pointing at the guide's own Social Steps section, rather
than setting up a workspace and cloning a repo for work a developer can't start
yet. **No override flag** (`--ignore-readiness` was considered and removed
2026-08-26 at the user's request -- see "No non-interactive escape hatch" below):
if the gate fires on a case that's actually fine, the fix is to correct the guide
(or re-run case-guide) and re-run case-solve, not to force past it from the CLI. A
guide with no readiness marker at all (an older guide, or `claude` dropped the
line despite the prompt asking for it) is treated as ready, matching case-guide's
own `_has_readiness_marker` warning, which already tells the operator to
double-check by hand in that case rather than this gate additionally
hard-blocking a case that may well be fine to start.

**No non-interactive escape hatch (2026-08-26).** case-solve originally had a
`--yes` flag (skip the interactive repo/confirmation prompts, for a scripted
caller) alongside `--ignore-readiness`. Both were removed at the user's explicit
request -- case-solve is interactive-only now, full stop: `main` always calls
`prompt_for_repo`/`confirm_before_implementing` (unless `--repo` is given, which
still only skips the repo prompt, not the confirmation one) and always honors the
readiness gate with no bypass. A caller that needs to drive case-solve
non-interactively has no supported way to do so today -- that's a deliberate gap,
not an oversight, until/unless asked for again.

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

- `case-brief`'s `--skip-crm` flag — never actually gave a usable "ADO-only" mode:
  `run_ado_lookup` only ever resolves branches/PRs from a direct reference it finds
  *in the CRM case's own text* (see `_collect_reference_text`) — there is no
  broader org-wide search (see `lib/ado_api.py`'s module docstring for why). With
  the CRM lookup skipped there was nothing to scan, so every `--skip-crm` run
  produced a brief with no CRM data and no ADO data either — a flag that looked
  like a real mode but could only ever produce an empty file. Removed rather than
  fixed: there was no ADO-only mode to make work without adding the org-wide
  search this tool deliberately doesn't do.
- `case-brief`'s `--skip-ado` flag — the Azure DevOps lookup now always runs
  unconditionally instead of being optional. It was already effectively
  best-effort (a single failed branch/PR resolution was caught and counted per-item
  rather than raised, see `run_ado_lookup`'s docstring), so `main` now also wraps
  the call to `run_ado_lookup` itself in a try/except -- an unexpected failure
  (e.g. `ado_api.parse_direct_references` raising) sets `ado_error` and the brief
  still gets built and written with whatever CRM data was gathered, instead of the
  whole run dying with nothing written. `--skip-ado` had no real use case left once
  the lookup can't break the run: it only ever added latency on a case with no ADO
  references to find, which the lookup already resolves quickly and reports as
  "not found" rather than erroring.
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
  `--skip-browser` was renamed `--skip-crm` at the time (still ADO-only, just no
  longer browser-specific wording now that CRM auth never opens a browser) — since
  removed outright, see "Removed in the 2026-08-26 simplification pass" below.
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
- **case-getter:** the unassigned-team filter has only been checked against this
  one org's data (26 active cases, all genuinely unclaimed) — worth re-confirming
  after this org's CRM setup changes (a renamed/re-created default team, a second
  queue added). No override for the team name today (fixed constant, see
  case-getter's own CLAUDE.md section) if that ever needs to vary.
