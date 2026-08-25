# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```
..\.venv\Scripts\Activate.ps1   # from case-brief/, on Windows -- repo root's venv has everything

python case_brief.py --demo             # no browser/API calls, fake data — fastest way to check report.py changes
python case_brief.py T2611845           # real run: CRM lookup by ticket number + ADO search
python case_brief.py --skip-browser     # ADO-only, no Chrome
python case_brief.py -h                 # full flag list
```

```
python -m unittest discover -s tests -v   # from case-brief/ -- 128 tests, mocked, no network
python -m pytest tests                    # equivalent, if pytest is installed
```

Deliberately not exhaustive over every CLI flag or every branch of `build_parser`/
`main` — those are low-risk plumbing, easily eyeballed with `--demo`-style manual
runs. See root CLAUDE.md and README's "Status" section for what's actually been
verified against live data vs. plausible inputs only. `--demo` is the fastest smoke
test for `report.py`/CLI-plumbing changes since it skips Chrome and both APIs
entirely.

## Architecture

Two independent data sources are gathered, then merged into one Markdown report:

1. **CRM (default path: browser scraping, `lib/crm_scrape.py`)** — `lib/browser.py`
   launches a *separate*, dedicated Chrome profile (`chrome-automation-profile/`,
   gitignored) via CDP on a fixed debug port (`case_brief.CHROME_CFG`), distinct
   from your normal browsing profile. `case_brief.py::run_browser_scrape` polls
   that profile's open tabs until
   either a CRM tab is authenticated (ticket number given → API lookup via
   `crm_scrape.lookup_by_ticket`, riding on that tab's own session — no app
   registration needed) or a case tab is simply open (no ticket number → auto-detect
   via `crm_scrape.extract`). The window is closed by the script itself at the end of
   every run — sessions don't persist between runs by design, but the last-used
   CRM URL is cached to `.last_urls.json` so it reopens automatically next time.

   Scrapes the whole case, not a curated subset: the incident record is fetched with
   no `$select` at all (Dataverse returns every populated attribute when it's
   omitted), so an org's own custom fields — e.g. an "internal description" that a
   fixed field list used to silently drop — show up too, labeled via a best-effort
   `EntityDefinitions` metadata call (`crm_scrape.get_attribute_metadata`, cached per
   origin; degrades to raw logical names if metadata read is denied). Customer/owner
   are resolved from the lookup's own display-name annotation rather than
   `$expand` — this also fixed two latent gaps: a contact-type customer (the old
   `$expand=customerid_account` only ever worked for an account) and a team-owned
   case (`$expand=owninguser` only ever worked for a user owner). Notes and the
   Activity Timeline (phone calls, emails, tasks) live in separate Dataverse entities
   (`annotation` / `activitypointer`) and are fetched separately
   (`crm_scrape.get_notes` / `get_activities`), each capped (`NOTES_TOP` /
   `ACTIVITIES_TOP`) with truncation surfaced rather than silently dropped.

   Most of those "get everything" fields are org-specific noise most of the time,
   so `report.build_markdown`'s `promoted_fields` param (default:
   `report.DEFAULT_PROMOTED_FIELDS`, fixed -- not configurable, since this scrapes
   one CRM whose custom fields don't change) pulls specific fields out by
   `logical_name` into their own proper subsection right after Description —
   everything else lands in an uncurated "Other CRM Fields" section at the very
   bottom of the brief instead of cluttering the top.

2. **Azure DevOps (`lib/ado_api.py`)** — real REST API via a self-service PAT
   (`AZDO_PAT` env var, fixed -- see `ado_api.PAT_ENV_VAR`). `case_brief.py::run_ado_lookup`
   flattens everything CRM scraping just found (title, description, every extra
   field, every note, every activity — see `_collect_reference_text`) and scans it
   via `ado_api.parse_direct_references` for actual ADO PR/branch links a support
   engineer pasted while working the case. Any found are resolved with one targeted
   API call each (`get_pull_request` / `get_branch`) — no searching. There is no
   broader org-wide search (an earlier "list every branch in every repo, in every
   project" fallback was removed -- see `lib/ado_api.py`'s module docstring): this
   tool only ever talks to one org (`ado_api.ORG_URL`, fixed), and a case that never
   mentions its own work either doesn't have any yet or is faster to ask about than
   to brute-force search for.

   `report.build_markdown`'s `ado_note` param carries a plain-language summary of
   what the direct-reference lookup found/skipped.

The brief no longer suggests a repo to clone/branch commands for -- that guess
(fuzzy-matching the CRM customer name against ADO project/repo names) moved to
case-guide, which is the thing that actually needs it (see case-guide/CLAUDE.md's
"Repo suggestion"); case-brief's job is just the facts (CRM + any directly-linked
ADO work), not a guessed next step.

**Azure DevOps section placement** -- `report.build_markdown` renders it right after a
case's at-a-glance details (Ticket #/Customer/.../Created), before Description/Notes/
Activity Timeline, on the first successfully-rendered CRM case (`_ado_section_lines` +
the `ado_rendered` guard) -- it's whole-run data, not per-case, so it's rendered once
even with multiple CRM results, with a fallback render at the end for when no case
rendered at all (no CRM tab open, or every result errored).

**No config file.** Everything is either a CLI flag or a fixed constant now: the
Azure DevOps org URL/PAT env var (`ado_api.ORG_URL`/`ado_api.PAT_ENV_VAR`), CRM
ticket field/host pattern, output directory, and Chrome profile/port/executable
(`case_brief.TICKET_FIELD`/`CRM_HOST_CONTAINS`/`OUTPUT_DIR`/`CHROME_CFG`) --
this tool only ever runs against one org, one CRM, and its own dedicated Chrome
profile, so a config.json would have had nothing left worth putting in it.

`lib/report.py` is the only place that renders the final Markdown and writes/opens it
in VS Code — CRM and ADO results are plain dicts/lists by the time they reach it,
with no formatting logic living in the scrapers themselves.
