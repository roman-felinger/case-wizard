# TODO / Future Upgrades

Ideas for later, not yet started.

- **Actually run the clone + branch-create, not just print the commands.**
  The brief has a "Useful Commands" section with ready-to-copy `git clone` +
  `git checkout -b <case-number>-<slugified-title>` commands for the repo(s)
  it identifies -- from confirmed ADO branch/PR matches, or (for a brand new
  case with none yet) an auto-matched guess between the CRM customer name
  and ADO project/repo names (`case_brief.py::resolve_suggested_repos`,
  overridable via `customer_repo_map` in config.json or `--repo`). A real
  next step would be to run these automatically -- offer to pick a repo,
  clone/pull it locally, and create the branch -- so starting work on a case
  skips the copy-paste entirely.
- **Verify the customer↔project auto-match against real ADO project names.**
  The fuzzy-matching logic (`_fuzzy_score`/`_best_fuzzy_match`) is
  unit-tested with made-up names but not yet checked against how your org's
  actual projects are named vs. how CRM customer names actually look --
  the threshold/lead values may need tuning once you see real guesses.
- **Fix `bc_scrape.py` against real Business Central output.** It's found 0
  labeled fields on the one real attempt so far; selectors were broadened
  (multi-frame search, wider aria-label match, raw-text fallback) but
  unverified since. Needs another real `--with-bc` run and iteration on
  whatever the raw-text dump reveals about BC's actual DOM structure.
- **Exercise the Azure DevOps branch/PR search against a real org.** Built
  and unit-tested for config/CLI plumbing, but not yet run against a live
  PAT + org — confirm the multi-project search, progress reporting, and
  `max_prs` truncation message all behave as expected on real data.
- **Speed up the multi-project ADO search.** Currently sequential,
  project-by-project. Could parallelize repo/branch/PR fetches (e.g. a
  thread pool) if it turns out to be too slow on orgs with many projects.
