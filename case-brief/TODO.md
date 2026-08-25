# TODO / Future Upgrades

Ideas for later, not yet started.

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
  formatting and the org-name check behaves against `ado_api.ORG_URL`.
