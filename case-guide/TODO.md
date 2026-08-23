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
- **Consider whether `case-guide/lib/ado_api.py`'s deliberate duplication of
  `case-brief/lib/ado_api.py` is worth it long-term.** Kept as an
  independent copy on purpose (no cross-project imports), but it means a
  fix to case-brief's `find_related`/pagination/error-handling doesn't
  automatically reach case-guide's copy, and vice versa (this project's copy
  is now meaningfully ahead -- session reuse, concurrency, AdoAuthError,
  the generalized `warnings` list, `get_recent_prs`). Not changing this
  without an explicit decision to share code between the two projects.
