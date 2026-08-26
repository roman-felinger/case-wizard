# TODO

- Make sure AZDO content is reachable in case-brief and links are investigated
  properly. **Done (2026-08-26):** the CRM form's "Related links" grid (Dev tab --
  linked PRs) is now fetched too (`crm_scrape.get_related_links`, entity
  `art_relatedlinks`, found via a live investigation against T2611845), rendered
  in its own brief subsection, and fed into the same direct-reference resolution
  as anything pasted into free text. See CLAUDE.md's case-brief section.
- Include some kind of difficulty scale and add to the guide (1-10 implementation
  difficulty). **Done (2026-08-26):** case-guide's prompt now asks claude for
  `**Implementation Difficulty:** X/10` right after the case summary, scored
  against a fixed 10-band rubric (`case_guide.DIFFICULTY_RUBRIC`) so it stays
  consistent across separate guides instead of a fresh unanchored guess each time.
- Make sure internal description is retrieved and displayed properly in the brief.
  **Done (2026-08-26):** this was already wired up (`report.DEFAULT_PROMOTED_FIELDS`
  promotes `art_internaldescriptionandnotes` right after Description) but `--demo`'s
  sample data used a made-up field name that never exercised it -- fixed to use the
  real logical name. Still not verified against a real live case.
