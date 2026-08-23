# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python case_brief.py --demo             # no browser/API calls, fake data — fastest way to check report.py changes
python case_brief.py T2611845           # real run: CRM lookup by ticket number + ADO search
python case_brief.py --skip-browser     # ADO-only, no Chrome
python case_brief.py -h                 # full flag list
```

No lint/test commands — no committed test suite (see root CLAUDE.md and README's
"Status" section for what's actually been verified against live data vs. plausible
inputs only). `--demo` is the fastest smoke test for `report.py`/CLI-plumbing changes
since it skips Chrome and both APIs entirely.

## Architecture

Two independent data sources are gathered, then merged into one Markdown report:

1. **CRM (default path: browser scraping, `lib/crm_scrape.py`)** — `lib/browser.py`
   launches a *separate*, dedicated Chrome profile (`chrome-automation-profile/`,
   gitignored) via CDP on `chrome.debug_port`, distinct from your normal browsing
   profile. `case_brief.py::run_browser_scrape` polls that profile's open tabs until
   either a CRM tab is authenticated (ticket number given → API lookup via
   `crm_scrape.lookup_by_ticket`, riding on that tab's own session — no app
   registration needed) or a case tab is simply open (no ticket number → auto-detect
   via `crm_scrape.extract`). The window is closed by the script itself at the end of
   every run — sessions don't persist between runs by design, but the last-used
   CRM/BC URLs are cached to `.last_urls.json` so they reopen automatically next time.

2. **Azure DevOps (`lib/ado_api.py`)** — real REST API via a self-service PAT
   (`AZDO_PAT` env var by default). `ado_api.find_related` searches branches/PRs whose
   name/title/description contains the case number, across every project in the org
   unless `azure_devops.project` is set. Truncation (`max_prs` cap) is surfaced to the
   report rather than silently dropped (`prs_truncated`/`max_prs` threaded through to
   `report.build_markdown`).

3. **Business Central (`lib/bc_scrape.py`, off by default via `--with-bc`)** — scrapes
   an open BC tab in the same automation Chrome profile. Selectors are still being
   worked out (multi-frame search, wide aria-label match, raw-text fallback) — see
   README's Status section before trusting its output.

**Repo suggestion (`case_brief.py::resolve_suggested_repos`)** decides which repo(s) to
show ready-to-copy `git clone`/`git checkout -b` commands for, even when Azure DevOps
found zero matching branches/PRs yet (the common case for a brand-new case). Priority
order: `--repo` flag → `customer_repo_map` entry in config.json → fuzzy-match the CRM
customer name against ADO project names, then repo names, via
`difflib.SequenceMatcher` (`_best_fuzzy_match` requires the top match to both clear a
threshold *and* beat the runner-up by a margin — an ambiguous guess is treated as no
guess, since it would suggest the wrong repo silently).

**Config merge order** (`load_config` → `apply_cli_overrides`): `DEFAULTS` dict →
`config.json` (deep-merged) → CLI flags, each layer overriding the previous. Every
setting is reachable by either config.json or a flag; there is no setting that
requires editing config.json.

`lib/report.py` is the only place that renders the final Markdown and writes/opens it
in VS Code — CRM, ADO, and BC results are plain dicts/lists by the time they reach it,
with no formatting logic living in the scrapers themselves.
