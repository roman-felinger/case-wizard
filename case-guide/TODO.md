# TODO / Future Upgrades

Everything from the original review passes plus a second round of
brainstormed items has been implemented -- shell=True fragility, discarded
PR-search-truncation signal, path-traversal-able case numbers, `_comment`
leaking into config, falsy-`or` CLI-default bugs, missing `--project`
override, auth-failure-looks-like-empty-result, no request
concurrency/session reuse, the silent `MAX_PROJECTS` cap, `--claude-arg`
unable to override to empty, `--show-prompt`, prompt-size truncation, a
committed test suite, skip-if-unchanged/`--force`, and an output sanity
check. A real end-to-end run against a live case + Azure DevOps org has
since happened too (case T2611845, artexis/BTECH), including the
`case-guide-writer` agent, house-style example, and style-PR sample added on
top of that pipeline -- see README's Status section. What's left:

- **An org-wide (not just per-project) PR sample, for later.** Pulling
  completed PRs across every project in the org during that agent's design
  (not just BTECH) showed real per-project variation worth knowing about --
  target branch (`test`, cherry-picked to `master`) held org-wide, but the
  named reviewer and repo-naming style didn't (BTECH: Adam Spivák; GiTy:
  Tomáš Juřík; ALTIUM/Artex AddOn: Michal Šráček). `get_recent_prs` stays
  per-project on purpose for that reason, but an org-wide sample could be
  worth surfacing separately later (e.g. to answer "is `test`->`master` a
  real org convention or just this project's habit") -- not built now since
  nothing in the guide-writing flow needs it yet.
- ~~Consider whether `case-guide/lib/ado_api.py`'s deliberate duplication of
  `case-brief/lib/ado_api.py` is worth it long-term.~~ **Decided:** only the
  pure, stable, byte-for-byte-identical piece (Basic-auth-header-from-PAT
  construction) moved to the repo-root `shared/` package (`shared/ado_auth.py`),
  now imported by both projects' `ado_api.py`. The higher-level search/query
  logic (`find_related`, pagination, error handling, session reuse,
  concurrency, `AdoAuthError`, `get_recent_prs`) stays an independent copy per
  project on purpose -- case-guide's copy is genuinely ahead of case-brief's
  there, and merging that would be a behavior change, not a cleanup.
- **Verify the customer↔project auto-match against real ADO project names.**
  `lib/repo_suggest.py`'s fuzzy-matching (`_fuzzy_score`/`best_fuzzy_match`,
  moved here from case-brief) is unit-tested with made-up names but not yet
  checked against how your org's actual projects are named vs. how CRM
  customer names actually look -- the threshold/lead values may need tuning
  once you see real guesses.
- **Actually run the clone + branch-create, not just suggest the commands.**
  `lib/repo_suggest.py` resolves a repo/branch and feeds it to the guide's
  "Get set up" step, but a real next step would be to run it automatically --
  offer to pick a repo, clone/pull it locally, and create the branch -- so
  starting work on a case skips the copy-paste entirely.
