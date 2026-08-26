# TODO

- New helper command that runs case-brief + case-guide (the first two stages) for
  every "new, relevant" case, instead of one case at a time. New = no brief
  generated for it yet. Relevant = accessible to me (visible in CRM) and currently
  unassigned (no owner, or owner is still the default Helpdesk e-mail rather than a
  person) -- i.e. cases worth picking up, not ones someone's already on. After
  running, print a summary list of the cases it just briefed/guided -- case number,
  implementation difficulty rating (pulled from the guide it just generated), and
  other relevant at-a-glance info (e.g. title/customer) -- so the output isn't just
  a pile of files but something to triage from directly.
  **Done (2026-08-26):** `case-getter/case_getter.py` (also reachable as
  `python case_wizard.py getter`). Lists every CRM case still owned by the CRM's
  default unassigned-case team ("Helpdesk e-mail" -- confirmed live, see CLAUDE.md's
  case-getter section), skips any that already have a brief on disk, and runs
  case-brief + case-guide for the rest, one at a time (a failure on one case doesn't
  stop the others). Prints a triage summary -- case number, title, customer,
  difficulty -- pulled back out of the brief/guide it just wrote. `--dry-run` lists
  without running anything; `--limit N` caps how many cases to process. Verified
  against live CRM data, including one real end-to-end brief+guide run.
  **Extended (2026-08-26):** also pulls in every active case already owned by the
  signed-in user (not just unassigned ones) -- resolved via a `WhoAmI` call
  (`crm_scrape.get_current_user_id`), each case's `owned_by_me` flag shown as
  "(mine)"/"(unassigned)" in both the dry-run listing and the triage summary.
  **Extended again (2026-08-26):** every run (including `--dry-run`) now also
  writes that same summary to `case-getter/gets/get-<timestamp>.md`
  (gitignored, one file per run) so a triage session leaves something on disk to
  refer back to, not just console output.
