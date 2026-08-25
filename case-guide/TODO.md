# TODO / Future Upgrades

Everything from the original review passes plus a second round of
brainstormed items has been implemented -- shell=True fragility, discarded
PR-search-truncation signal, path-traversal-able case numbers, `_comment`
leaking into config, falsy-`or` CLI-default bugs, missing `--project`
override, auth-failure-looks-like-empty-result, no request
concurrency/session reuse, the silent `MAX_PROJECTS` cap, `--claude-arg`
unable to override to empty, prompt-size truncation, a committed test
suite, skip-if-unchanged, and an output sanity check. (There's no
`--show-prompt`/`--force` override flag -- skip-if-unchanged has no
override at all; delete the existing guide file to force a regenerate.) A
real end-to-end run against a live case + Azure DevOps org has since
happened too (case T2611845, artexis/BTECH), including the
`case-guide-writer` agent and house-style example added on top of that
pipeline -- see the root README's Status section. What's left:

- ~~An org-wide (not just per-project) PR sample, for later.~~ **Dropped
  along with the style-PR sample itself:** pulling completed PRs across every
  project in the org during that agent's design (not just BTECH) showed real
  per-project variation worth knowing about -- target branch (`test`,
  cherry-picked to `master`) held org-wide, but the named reviewer and
  repo-naming style didn't (BTECH: Adam Spivák; GiTy: Tomáš Juřík;
  ALTIUM/Artex AddOn: Michal Šráček). The live per-project sample
  (`gather_style_prs`/`ado_api.get_recent_prs`) this would have extended was
  itself removed -- it rarely changed the guide's advice enough to justify
  another live ADO call once the org-wide conventions that *do* hold
  everywhere (branch/PR naming, `test`->`master`) were written directly into
  `case-guide-writer.md` instead. The reviewer/repo-naming variation above is
  exactly the kind of detail a live per-project sample would be needed to get
  right -- if that specificity matters again, it'll have to come back as a
  live lookup, not a static note.
- ~~Consider whether `case-guide/lib/ado_api.py`'s deliberate duplication of
  `case-brief/lib/ado_api.py` is worth it long-term.~~ **Decided:** only the
  pure, stable, byte-for-byte-identical piece (Basic-auth-header-from-PAT
  construction) moved to the repo-root `shared/` package (`shared/ado_auth.py`),
  now imported by both projects' `ado_api.py`. The higher-level search/query
  logic (`find_related`, pagination, error handling, session reuse,
  concurrency, `AdoAuthError`) stays an independent copy per project on
  purpose -- case-guide's copy is genuinely ahead of case-brief's there, and
  merging that would be a behavior change, not a cleanup.
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
