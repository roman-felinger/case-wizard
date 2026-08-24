# TODO / Future Upgrades

Ideas for later, not yet started.

- **Exercise the Azure DevOps branch/PR search against a real org.** Built
  and unit-tested for config/CLI plumbing, but not yet run against a live
  PAT + org — confirm the multi-project search, progress reporting, and
  `max_prs` truncation message all behave as expected on real data.
- **Speed up the multi-project ADO search.** No longer the default path (see
  `ado_api.parse_direct_references` / `case_brief.py::run_ado_lookup` — a
  direct CRM-linked PR/branch is now resolved with one API call instead),
  but the `--search-ado` fallback is still sequential, project-by-project.
  Could parallelize repo/branch/PR fetches (e.g. a thread pool) if it still
  turns out to be too slow on orgs with many projects when that fallback
  does run.
- **Verify the new "get everything" CRM scrape against a real case.** The
  full-record fetch (no `$select`), `EntityDefinitions` metadata labeling,
  and Notes/Activity Timeline calls (`crm_scrape.get_attribute_metadata` /
  `get_notes` / `get_activities`) are unit-tested against faked responses
  but not yet run against a live, logged-in CRM tab — confirm real field
  labels, memo-field HTML stripping, and the Notes/Activities sections all
  look right in an actual brief.
- **Verify direct ADO reference resolution against a real case with a
  linked PR/branch.** `ado_api.parse_direct_references` is unit-tested
  against made-up link text; needs a real case where a support engineer
  actually pasted a PR/branch URL to confirm the regex matches real-world
  formatting and the org-name check behaves with the real `org_url`.
