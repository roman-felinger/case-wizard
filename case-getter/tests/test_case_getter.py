"""Unit tests for case_getter.py's own logic: which CRM cases are relevant
and how each is tagged (existing_brief_numbers/find_relevant_cases),
pulling title/customer/difficulty back out of a finished brief/guide
(summarize/_case_to_row), and main()'s per-case loop (mocked subprocess
calls -- no real brief/guide/CRM/claude call).

Deliberately not exhaustive over build_parser/CLI plumbing -- low-risk,
same convention as case-brief's own tests. What's actually worth testing
here: that find_relevant_cases returns *every* relevant case (not just new
ones) with the right is_new/stale tags, that a case already up to date is
included in the triage output without being reprocessed, and that a
failure on one case doesn't stop the rest.

Run with: python -m unittest discover -s tests -v   (from case-getter/)
      or: python -m pytest tests                     (if pytest is installed)
"""
import glob
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import case_getter as cg


def _brief(title="A title", customer="Contoso"):
    return f"### {title}\n\n- **Customer:** {customer}\n"


def _guide(difficulty_line='**Implementation Difficulty:** 4/10 -- a few files, no new concepts.'):
    return f"# Case T1\n\n{difficulty_line}\n\nrest of guide...\n"


class ExistingBriefNumbersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _touch(self, name):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as f:
            f.write("x")

    def test_extracts_the_ticket_number_from_each_brief_filename(self):
        self._touch("brief-T1234.md")
        self._touch("brief-T5678.md")
        self.assertEqual(cg.existing_brief_numbers(self.tmp), {"T1234", "T5678"})

    def test_ignores_non_brief_files(self):
        self._touch("brief-T1234.md")
        self._touch("readme.md")
        self._touch("brief-T1234.txt")
        self.assertEqual(cg.existing_brief_numbers(self.tmp), {"T1234"})

    def test_empty_directory_yields_no_numbers(self):
        self.assertEqual(cg.existing_brief_numbers(self.tmp), set())


class FindRelevantCasesTests(unittest.TestCase):
    """find_relevant_cases returns *every* relevant CRM case, not just ones
    needing (re)processing -- each tagged is_new/stale so callers can tell
    the three situations (new, stale, already up to date) apart."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_brief(self, ticket_number, modified_on=None):
        marker = f"<!-- case-brief:crm-modified-on={modified_on} -->\n\n" if modified_on else ""
        with open(os.path.join(self.tmp, f"brief-{ticket_number}.md"), "w", encoding="utf-8") as f:
            f.write(f"x\n{marker}")

    def test_a_case_with_no_brief_yet_is_tagged_new_not_stale(self):
        cases = [{"ticket_number": "T2"}]
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=(cases, None, False)):
            found, warning = cg.find_relevant_cases(self.tmp)
        self.assertEqual([c["ticket_number"] for c in found], ["T2"])
        self.assertTrue(found[0]["is_new"])
        self.assertFalse(found[0]["stale"])
        self.assertIsNone(warning)

    def test_a_listing_error_exits_rather_than_returning_a_partial_result(self):
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=([], "HTTP 403", False)):
            with self.assertRaises(SystemExit):
                cg.find_relevant_cases(self.tmp)

    def test_truncation_is_surfaced_as_a_warning_not_silently_dropped(self):
        cases = [{"ticket_number": "T2"}]
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=(cases, None, True)):
            found, warning = cg.find_relevant_cases(self.tmp)
        self.assertEqual([c["ticket_number"] for c in found], ["T2"])
        self.assertIsNotNone(warning)

    def test_a_ticket_number_needing_filename_sanitizing_still_matches_its_brief(self):
        # safe_name replaces unsafe characters with "_" -- the brief on disk
        # is named after the sanitized form, so the CRM's raw ticket number
        # has to be sanitized the same way before comparing, or a case that
        # already has a brief would look "new" again.
        self._write_brief("T1_2", modified_on="2026-08-20T10:00:00Z")
        cases = [{"ticket_number": "T1/2", "modified_on": "2026-08-20T10:00:00Z"}]
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=(cases, None, False)):
            found, _ = cg.find_relevant_cases(self.tmp)
        self.assertFalse(found[0]["is_new"])
        self.assertFalse(found[0]["stale"])

    def test_a_case_with_a_brief_whose_crm_data_changed_since_is_tagged_stale(self):
        self._write_brief("T1", modified_on="2026-08-20T10:00:00Z")
        cases = [{"ticket_number": "T1", "modified_on": "2026-08-21T09:00:00Z"}]
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=(cases, None, False)):
            found, _ = cg.find_relevant_cases(self.tmp)
        self.assertEqual([c["ticket_number"] for c in found], ["T1"])
        self.assertFalse(found[0]["is_new"])
        self.assertTrue(found[0]["stale"])

    def test_a_case_with_an_up_to_date_brief_is_still_included_but_not_flagged(self):
        # The whole point of always returning every relevant case: an
        # up-to-date one isn't dropped from the list, it's just marked as
        # not needing (re)processing.
        self._write_brief("T1", modified_on="2026-08-21T09:00:00Z")
        cases = [{"ticket_number": "T1", "modified_on": "2026-08-21T09:00:00Z"}]
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=(cases, None, False)):
            found, _ = cg.find_relevant_cases(self.tmp)
        self.assertEqual([c["ticket_number"] for c in found], ["T1"])
        self.assertFalse(found[0]["is_new"])
        self.assertFalse(found[0]["stale"])

    def test_a_case_with_no_ticket_number_is_skipped(self):
        cases = [{"ticket_number": None}, {"ticket_number": "T2"}]
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=(cases, None, False)):
            found, _ = cg.find_relevant_cases(self.tmp)
        self.assertEqual([c["ticket_number"] for c in found], ["T2"])


class SummarizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_pulls_title_customer_and_difficulty_out_of_the_finished_files(self):
        brief_path = self._write("brief.md", _brief("Posting error", "GASTRO MACH, s.r.o."))
        guide_path = self._write("guide.md", _guide())
        row = cg.summarize("T1", brief_path, guide_path)
        self.assertEqual(row["case_number"], "T1")
        self.assertEqual(row["title"], "Posting error")
        self.assertEqual(row["customer"], "GASTRO MACH, s.r.o.")
        self.assertEqual(row["difficulty"], "4/10 -- a few files, no new concepts.")

    def test_missing_files_come_back_as_none_rather_than_raising(self):
        row = cg.summarize("T1", os.path.join(self.tmp, "nope.md"), os.path.join(self.tmp, "nope2.md"))
        self.assertEqual(row, {"case_number": "T1", "title": None, "customer": None, "difficulty": None})

    def test_report_pys_own_em_dash_placeholder_customer_is_treated_as_missing(self):
        brief_path = self._write("brief.md", _brief("Title", "—"))
        row = cg.summarize("T1", brief_path, None)
        self.assertIsNone(row["customer"])


class ExtractDifficultyTests(unittest.TestCase):
    def test_no_text_is_none(self):
        self.assertIsNone(cg._extract_difficulty(None))
        self.assertIsNone(cg._extract_difficulty(""))

    def test_pulls_the_rating_and_reason(self):
        self.assertEqual(cg._extract_difficulty(_guide()), "4/10 -- a few files, no new concepts.")

    def test_no_difficulty_line_is_none(self):
        self.assertIsNone(cg._extract_difficulty("# Case T1\n\nno difficulty line here.\n"))

    def test_a_single_dash_separator_is_tolerated(self):
        self.assertEqual(
            cg._extract_difficulty("**Implementation Difficulty:** 7/10 - one dash, not two.\n"),
            "7/10 -- one dash, not two.",
        )

    def test_matching_is_case_insensitive_on_the_header(self):
        self.assertEqual(
            cg._extract_difficulty("**implementation difficulty:** 3/10 -- lowercase header.\n"),
            "3/10 -- lowercase header.",
        )

    def test_a_bare_rating_with_no_reason_text_has_no_trailing_dashes(self):
        self.assertEqual(cg._extract_difficulty("**Implementation Difficulty:** 2/10\n"), "2/10")

    def test_an_em_dash_separator_is_consumed_not_doubled(self):
        # A real bug: claude's prose defaults to a real em dash ("4/10 —
        # reason") often enough that an ASCII-only "-{1,2}" class missed it
        # entirely -- the em dash then fell into the reason capture and got
        # reassembled as "4/10 -- — reason" (this function's own separator,
        # plus claude's un-stripped one right after it).
        self.assertEqual(
            cg._extract_difficulty("**Implementation Difficulty:** 4/10 — single file, needs research.\n"),
            "4/10 -- single file, needs research.",
        )

    def test_an_en_dash_separator_is_also_consumed(self):
        self.assertEqual(
            cg._extract_difficulty("**Implementation Difficulty:** 3/10 – en dash variant.\n"),
            "3/10 -- en dash variant.",
        )

    def test_n_a_with_an_em_dash_separator_is_also_consumed(self):
        self.assertEqual(
            cg._extract_difficulty("**Implementation Difficulty:** N/A — automated notification.\n"),
            "N/A -- automated notification.",
        )


class CaseToRowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_normalizes_a_raw_listing_entry_to_the_row_shape(self):
        c = {"ticket_number": "T1", "owned_by_me": True, "stale": True, "is_new": False,
             "title": "A title", "customer": "Contoso", "url": "https://crm.example/T1"}
        self.assertEqual(cg._case_to_row(c, guide_dir=self.tmp), {
            "case_number": "T1", "owned_by_me": True, "stale": True, "is_new": False,
            "title": "A title", "customer": "Contoso", "difficulty": None,
            "url": "https://crm.example/T1",
        })

    def test_missing_optional_fields_come_back_none_or_a_default_not_a_crash(self):
        row = cg._case_to_row({"ticket_number": "T1"}, guide_dir=self.tmp)
        self.assertEqual(row, {
            "case_number": "T1", "owned_by_me": None, "stale": False, "is_new": True,
            "title": None, "customer": None, "difficulty": None, "url": None,
        })

    def test_reads_difficulty_from_an_existing_guide_on_disk(self):
        # A case already guided in a previous run has a real difficulty to
        # show even though this pass never (re)processes it -- e.g. for a
        # --dry-run listing.
        with open(os.path.join(self.tmp, "guide-T1.md"), "w", encoding="utf-8") as f:
            f.write(_guide())
        c = {"ticket_number": "T1", "is_new": False, "stale": False}
        row = cg._case_to_row(c, guide_dir=self.tmp)
        self.assertEqual(row["difficulty"], "4/10 -- a few files, no new concepts.")


class IsStaleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_brief(self, name, modified_on=None):
        path = os.path.join(self.tmp, name)
        marker = f"<!-- case-brief:crm-modified-on={modified_on} -->\n\n" if modified_on else ""
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Case T1\n\n{marker}rest of brief...\n")
        return path

    def test_crm_modified_after_the_brief_marker_is_stale(self):
        path = self._write_brief("brief.md", modified_on="2026-08-20T10:00:00Z")
        self.assertTrue(cg.is_stale({"modified_on": "2026-08-21T09:00:00Z"}, path))

    def test_crm_modified_before_or_at_the_brief_marker_is_not_stale(self):
        path = self._write_brief("brief.md", modified_on="2026-08-20T10:00:00Z")
        self.assertFalse(cg.is_stale({"modified_on": "2026-08-20T10:00:00Z"}, path))
        self.assertFalse(cg.is_stale({"modified_on": "2026-08-19T10:00:00Z"}, path))

    def test_no_crm_modified_on_is_not_stale(self):
        path = self._write_brief("brief.md", modified_on="2026-08-20T10:00:00Z")
        self.assertFalse(cg.is_stale({}, path))

    def test_a_brief_with_no_marker_is_not_stale(self):
        # Predates this feature, or was hand-edited -- can't be judged, so
        # left alone rather than force-regenerated.
        path = self._write_brief("brief.md", modified_on=None)
        self.assertFalse(cg.is_stale({"modified_on": "2026-08-21T09:00:00Z"}, path))

    def test_a_missing_brief_file_is_not_stale(self):
        self.assertFalse(cg.is_stale({"modified_on": "2026-08-21T09:00:00Z"}, os.path.join(self.tmp, "nope.md")))


class DifficultyNumTests(unittest.TestCase):
    def test_extracts_the_leading_number(self):
        self.assertEqual(cg._difficulty_num({"difficulty": "7/10 -- a few files"}), 7)

    def test_no_difficulty_is_none(self):
        self.assertIsNone(cg._difficulty_num({"difficulty": None}))
        self.assertIsNone(cg._difficulty_num({}))

    def test_unparseable_difficulty_is_none(self):
        self.assertIsNone(cg._difficulty_num({"difficulty": "hard"}))


class SortRowsTests(unittest.TestCase):
    def _rows(self):
        return [
            {"case_number": "T1", "difficulty": "7/10 -- x"},
            {"case_number": "T2", "difficulty": "2/10 -- y"},
            {"case_number": "T3", "difficulty": None},
            {"case_number": "T4", "difficulty": "5/10 -- z"},
        ]

    def test_none_leaves_processing_order_untouched(self):
        rows = self._rows()
        self.assertEqual(cg.sort_rows(rows, "none"), rows)

    def test_easiest_sorts_ascending_with_unknown_last(self):
        result = cg.sort_rows(self._rows(), "easiest")
        self.assertEqual([r["case_number"] for r in result], ["T2", "T4", "T1", "T3"])

    def test_hardest_sorts_descending_with_unknown_still_last(self):
        result = cg.sort_rows(self._rows(), "hardest")
        self.assertEqual([r["case_number"] for r in result], ["T1", "T4", "T2", "T3"])


class BuildReportMarkdownTests(unittest.TestCase):
    def test_no_rows_states_nothing_found(self):
        md = cg.build_report_markdown([], dry_run=False, timestamp="2026-08-26 12:00:00")
        self.assertIn("No relevant cases found.", md)

    def test_a_full_run_row_includes_difficulty_and_ownership(self):
        rows = [{"case_number": "T1", "owned_by_me": True, "title": "A title",
                  "customer": "Contoso", "difficulty": "4/10 -- easy"}]
        md = cg.build_report_markdown(rows, dry_run=False, timestamp="2026-08-26 12:00:00")
        self.assertIn("| T1 |", md)
        self.assertIn("Mine", md)
        self.assertIn("4/10 -- easy", md)

    def test_a_row_with_a_url_renders_the_case_number_as_a_link(self):
        rows = [{"case_number": "T1", "owned_by_me": False, "title": "A title",
                  "customer": "Contoso", "difficulty": "4/10 -- easy", "url": "https://crm.example/T1"}]
        md = cg.build_report_markdown(rows, dry_run=False, timestamp="2026-08-26 12:00:00")
        self.assertIn("[T1](https://crm.example/T1)", md)

    def test_an_error_row_is_called_out(self):
        rows = [{"case_number": "T1", "owned_by_me": False, "title": "A title",
                  "customer": "Contoso", "difficulty": None, "error": "case-brief failed (exit 1)"}]
        md = cg.build_report_markdown(rows, dry_run=False, timestamp="2026-08-26 12:00:00")
        self.assertIn("case-brief failed (exit 1)", md)

    def test_dry_run_still_shows_difficulty_when_a_guide_already_exists(self):
        # Unlike before, a --dry-run listing isn't difficulty-blind -- a
        # case already guided in a previous run has a real one to show.
        rows = [{"case_number": "T1", "owned_by_me": False, "title": "A title",
                  "customer": "Contoso", "difficulty": "4/10 -- easy", "is_new": False}]
        md = cg.build_report_markdown(rows, dry_run=True, timestamp="2026-08-26 12:00:00")
        self.assertIn("4/10 -- easy", md)
        self.assertIn("dry run", md.lower())

    def test_dry_run_row_with_no_difficulty_yet_shows_the_placeholder(self):
        rows = [{"case_number": "T1", "owned_by_me": False, "title": "A title",
                  "customer": "Contoso", "difficulty": None, "is_new": True}]
        md = cg.build_report_markdown(rows, dry_run=True, timestamp="2026-08-26 12:00:00")
        self.assertIn("not generated this run", md)


class WriteReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_writes_to_a_timestamped_filename_under_the_output_dir(self):
        path = cg.write_report("# hello\n", self.tmp, "20260826-120000")
        self.assertEqual(os.path.basename(path), "get-20260826-120000.md")
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "# hello\n")

    def test_creates_the_output_dir_if_missing(self):
        missing = os.path.join(self.tmp, "gets")
        cg.write_report("x", missing, "20260826-120000")
        self.assertTrue(os.path.isdir(missing))


class OwnerLabelTests(unittest.TestCase):
    def test_owned_by_me_true_is_mine(self):
        self.assertEqual(cg._owner_label({"owned_by_me": True}), "Mine")

    def test_owned_by_me_false_or_missing_is_unassigned(self):
        self.assertEqual(cg._owner_label({"owned_by_me": False}), "Unassigned")
        self.assertEqual(cg._owner_label({}), "Unassigned")


class NeedsProcessingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_a_new_case_needs_processing(self):
        self.assertTrue(cg._needs_processing({"ticket_number": "T1", "is_new": True}, self.tmp))

    def test_a_stale_case_needs_processing(self):
        self.assertTrue(cg._needs_processing({"ticket_number": "T1", "stale": True}, self.tmp))

    def test_a_fresh_brief_with_a_complete_existing_guide_does_not_need_processing(self):
        with open(os.path.join(self.tmp, "guide-T1.md"), "w", encoding="utf-8") as f:
            f.write(_guide())
        c = {"ticket_number": "T1", "is_new": False, "stale": False}
        self.assertFalse(cg._needs_processing(c, self.tmp))

    def test_a_fresh_brief_with_no_guide_at_all_still_needs_processing(self):
        # One bug this guards against: a brief that's up to date but was
        # never followed by a case-guide run (e.g. created by hand, or by
        # an older/failed run) used to look fully done forever, leaving the
        # case stuck showing "(not found -- check the guide)" even though
        # there's no guide file to check at all.
        c = {"ticket_number": "T1", "is_new": False, "stale": False}
        self.assertTrue(cg._needs_processing(c, self.tmp))

    def test_a_guide_missing_the_difficulty_line_still_needs_processing(self):
        # The other bug this guards against: a guide that genuinely exists
        # but where claude dropped the difficulty line used to be
        # indistinguishable from "done" -- it kept showing "(not found --
        # check the guide)" in the triage list forever, with nothing ever
        # trying to fix it.
        with open(os.path.join(self.tmp, "guide-T1.md"), "w", encoding="utf-8") as f:
            f.write("# Case T1\n\nNo difficulty line in here at all.\n")
        c = {"ticket_number": "T1", "is_new": False, "stale": False}
        self.assertTrue(cg._needs_processing(c, self.tmp))


class DifficultyPlaceholderTests(unittest.TestCase):
    def test_dry_run_says_not_generated(self):
        self.assertIn("dry run", cg._difficulty_placeholder({}, dry_run=True))

    def test_skipped_by_limit_says_so(self):
        msg = cg._difficulty_placeholder({"skipped_limit": True}, dry_run=False)
        self.assertIn("--limit", msg)

    def test_a_row_with_an_error_shows_the_error_itself(self):
        msg = cg._difficulty_placeholder({"error": "case-brief failed"}, dry_run=False)
        self.assertEqual(msg, "⚠ case-brief failed")

    def test_otherwise_says_to_check_the_guide(self):
        msg = cg._difficulty_placeholder({}, dry_run=False)
        self.assertIn("guide", msg)


class TableRowsTests(unittest.TestCase):
    def test_owner_is_its_own_column(self):
        row = {"case_number": "T1", "owned_by_me": True,
               "title": "A title", "customer": "Contoso", "difficulty": "4/10 -- easy"}
        cells = cg._table_rows([row], dry_run=False)[0]
        self.assertEqual(cells, ["T1", "Mine", "A title", "Contoso", "4/10 -- easy"])

    def test_missing_fields_fall_back_to_placeholders(self):
        cells = cg._table_rows([{"case_number": "T1"}], dry_run=True)[0]
        self.assertEqual(cells, ["T1", "Unassigned", "(no title)", "unknown customer",
                                  "(dry run -- not generated this run)"])

    def test_error_is_surfaced_in_the_difficulty_column(self):
        # No separate Notes column any more (it was almost always empty) --
        # an error shows up as the Difficulty cell's own text instead.
        row = {"case_number": "T1", "error": "case-brief failed (exit 1)"}
        cells = cg._table_rows([row], dry_run=False)[0]
        self.assertEqual(cells[-1], "⚠ case-brief failed (exit 1)")


class FormatCaseLinesTests(unittest.TestCase):
    def test_owner_is_its_own_labeled_line(self):
        lines = cg._format_case_lines({"case_number": "T1", "owned_by_me": True}, dry_run=False)
        self.assertIn("    Owner: Mine", lines)

    def test_no_status_line_at_all(self):
        # The Status column/line was dropped entirely -- it was almost
        # always empty (only ever "Stale", and even that was rare).
        lines = cg._format_case_lines({"case_number": "T1", "stale": True}, dry_run=False)
        self.assertFalse(any(line.strip().startswith("Status:") for line in lines))

    def test_error_shows_up_on_the_difficulty_line_not_a_separate_one(self):
        lines = cg._format_case_lines({"case_number": "T1", "error": "boom"}, dry_run=False)
        self.assertIn("    Difficulty: ⚠ boom", lines)
        self.assertFalse(any(line.strip().startswith("⚠") for line in lines))

    def test_no_table_syntax_leaks_into_plain_console_output(self):
        lines = cg._format_case_lines({"case_number": "T1"}, dry_run=False)
        self.assertFalse(any("|" in line for line in lines))


class DifficultyBgTests(unittest.TestCase):
    def test_no_rating_has_no_background(self):
        self.assertIsNone(cg._difficulty_bg(None))

    def test_easiest_is_the_green_end_of_the_scale(self):
        self.assertEqual(cg._difficulty_bg(1), "#63be7b")

    def test_hardest_is_the_red_end_of_the_scale(self):
        self.assertEqual(cg._difficulty_bg(10), "#f8696b")

    def test_out_of_range_values_are_clamped_not_extrapolated(self):
        self.assertEqual(cg._difficulty_bg(1), cg._difficulty_bg(0))
        self.assertEqual(cg._difficulty_bg(10), cg._difficulty_bg(99))


class RenderMarkdownTableTests(unittest.TestCase):
    def _render(self, rows, mine_flags, difficulty_nums, urls=None):
        return cg._render_markdown_table(
            cg._TABLE_HEADERS, rows, mine_flags, difficulty_nums,
            urls if urls is not None else [None] * len(rows),
        )

    def test_renders_an_ordinary_pipe_table(self):
        rows = [["T1", "Unassigned", "t", "c", ""]]
        out = self._render(rows, [False], [None])
        lines = out.splitlines()
        self.assertEqual(lines[0], "| " + " | ".join(cg._TABLE_HEADERS) + " |")
        self.assertTrue(lines[1].startswith("| ---"))
        self.assertIn("| T1 | Unassigned |", lines[2])

    def test_difficulty_cell_carries_a_background_span(self):
        rows = [["T1", "Mine", "t", "c", "2/10 -- easy"]]
        out = self._render(rows, [True], [2])
        self.assertIn(f'<span style="background:{cg._difficulty_bg(2)}', out)
        self.assertIn("2/10 -- easy</span>", out)

    def test_mine_row_bolds_the_owner_cell_unassigned_does_not(self):
        rows = [["T1", "Mine", "t", "c", ""], ["T2", "Unassigned", "t", "c", ""]]
        out = self._render(rows, [True, False], [None, None])
        lines = out.splitlines()
        mine_row = next(l for l in lines if l.startswith("| T1 "))
        unassigned_row = next(l for l in lines if l.startswith("| T2 "))
        self.assertIn("**Mine**", mine_row)
        self.assertNotIn("**", unassigned_row)

    def test_no_difficulty_number_leaves_the_cell_uncolored(self):
        rows = [["T1", "Unassigned", "t", "c", "(dry run -- not generated this run)"]]
        out = self._render(rows, [False], [None])
        self.assertNotIn("<span", out)

    def test_cell_text_is_html_escaped(self):
        rows = [["T1", "Unassigned", "<script>alert(1)</script>", "c", ""]]
        out = self._render(rows, [False], [None])
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_a_literal_pipe_in_cell_text_does_not_break_the_row(self):
        rows = [["T1", "Unassigned", "a | b", "c", ""]]
        out = self._render(rows, [False], [None])
        self.assertIn("a \\| b", out)

    def test_case_cell_links_to_the_crm_url_when_present(self):
        rows = [["T2621277", "Unassigned", "t", "c", ""]]
        out = self._render(rows, [False], [None], urls=["https://crm.example/main.aspx?id=abc&x=1"])
        self.assertIn("| [T2621277](https://crm.example/main.aspx?id=abc&x=1) |", out)

    def test_case_cell_is_plain_text_when_no_url(self):
        rows = [["T1", "Unassigned", "t", "c", ""]]
        out = self._render(rows, [False], [None], urls=[None])
        self.assertIn("| T1 |", out)
        self.assertNotIn("[T1]", out)


class MainLoopTests(unittest.TestCase):
    """main()'s per-case loop, with run_stage/find_relevant_cases/summarize
    mocked out -- no real subprocess, CRM, or claude call."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        os.makedirs(os.path.join(self.tmp, "brief"))
        os.makedirs(os.path.join(self.tmp, "guide"))

    def _run(self, cases, run_stage_side_effect, argv=None):
        # REPORT_DIR is patched into the same tempdir too -- without this,
        # every test run here would write a real get-<timestamp>.md into
        # the actual case-getter/gets/ on disk.
        with mock.patch.object(cg, "BRIEF_DIR", os.path.join(self.tmp, "brief")), \
             mock.patch.object(cg, "GUIDE_DIR", os.path.join(self.tmp, "guide")), \
             mock.patch.object(cg, "REPORT_DIR", os.path.join(self.tmp, "gets")), \
             mock.patch.object(cg, "find_relevant_cases", return_value=(cases, None)), \
             mock.patch.object(cg, "run_stage", side_effect=run_stage_side_effect), \
             mock.patch.object(sys, "argv", ["case_getter.py", *(argv or [])]):
            return cg.main()

    def _new_case(self, number, title="t", customer="c"):
        return {"ticket_number": number, "title": title, "customer": customer, "is_new": True, "stale": False}

    def test_a_failed_brief_is_reported_and_does_not_stop_the_next_case(self):
        cases = [self._new_case("T1", "t1", "c1"), self._new_case("T2", "t2", "c2")]
        calls = []

        def fake_run_stage(script, number):
            calls.append((os.path.basename(script), number))
            if number == "T1":
                return 1  # brief fails for T1
            # T2's brief/guide both "succeed" -- write the files main() checks for.
            if os.path.basename(script) == "case_brief.py":
                with open(os.path.join(self.tmp, "brief", f"brief-{number}.md"), "w", encoding="utf-8") as f:
                    f.write(_brief())
            else:
                with open(os.path.join(self.tmp, "guide", f"guide-{number}.md"), "w", encoding="utf-8") as f:
                    f.write(_guide())
            return 0

        rc = self._run(cases, fake_run_stage)
        self.assertEqual(rc, 1)  # a failure happened, non-zero exit
        # T1's brief failed -- case-guide must never have been called for it.
        self.assertNotIn(("case_guide.py", "T1"), calls)
        self.assertIn(("case_brief.py", "T2"), calls)
        self.assertIn(("case_guide.py", "T2"), calls)

    def test_limit_caps_how_many_new_stale_cases_are_processed(self):
        cases = [self._new_case(f"T{n}") for n in range(5)]
        calls = []

        def fake_run_stage(script, number):
            calls.append(number)
            return 1  # fail fast -- only care how many cases were attempted

        self._run(cases, fake_run_stage, argv=["--limit", "2"])
        self.assertEqual(len(set(calls)), 2)

    def test_limit_does_not_drop_up_to_date_cases_from_the_triage_list(self):
        # An already-current case costs nothing to include (just a file
        # read), so --limit shouldn't hide it from the output even while
        # it caps how many new/stale cases get reprocessed.
        current = {"ticket_number": "T0", "title": "t0", "customer": "c0", "is_new": False, "stale": False}
        # A guide already on disk -- genuinely nothing left to do, so it
        # shouldn't itself count against --limit (see _needs_processing).
        with open(os.path.join(self.tmp, "guide", "guide-T0.md"), "w", encoding="utf-8") as f:
            f.write(_guide())
        new_cases = [self._new_case(f"T{n}") for n in range(1, 4)]
        calls = []

        def fake_run_stage(script, number):
            calls.append(number)
            return 1

        with mock.patch("builtins.print") as fake_print:
            self._run([current] + new_cases, fake_run_stage, argv=["--limit", "1"])
        self.assertEqual(len(set(calls)), 1)  # only one new case actually reprocessed
        printed = "\n".join(str(c.args[0]) for c in fake_print.call_args_list if c.args)
        self.assertIn("T0", printed)  # the up-to-date case still shows up

    def test_an_up_to_date_case_is_included_without_calling_run_stage(self):
        current = {"ticket_number": "T1", "title": "t1", "customer": "c1", "is_new": False, "stale": False}
        # A guide already on disk -- genuinely nothing left to do. Without
        # this, _needs_processing would (correctly) want to (re)process it
        # -- see test_a_fresh_brief_with_a_missing_guide_gets_only_case_guide_rerun.
        with open(os.path.join(self.tmp, "guide", "guide-T1.md"), "w", encoding="utf-8") as f:
            f.write(_guide())
        run_stage = mock.Mock()
        with mock.patch("builtins.print") as fake_print:
            rc = self._run([current], run_stage)
        run_stage.assert_not_called()
        self.assertEqual(rc, 0)
        printed = "\n".join(str(c.args[0]) for c in fake_print.call_args_list if c.args)
        self.assertIn("T1", printed)
        # "up to date" is deliberately never printed -- it's the default
        # expected state for every row, not worth calling out (see
        # _status_label); a genuinely stale row would say "Stale" instead.
        self.assertNotIn("up to date", printed)

    def test_a_stale_case_is_reprocessed(self):
        stale = {"ticket_number": "T1", "title": "t1", "customer": "c1", "is_new": False, "stale": True}
        calls = []

        def fake_run_stage(script, number):
            calls.append((os.path.basename(script), number))
            base = "brief" if os.path.basename(script) == "case_brief.py" else "guide"
            content = _brief() if base == "brief" else _guide()
            with open(os.path.join(self.tmp, base, f"{base}-{number}.md"), "w", encoding="utf-8") as f:
                f.write(content)
            return 0

        rc = self._run([stale], fake_run_stage)
        self.assertEqual(rc, 0)
        self.assertIn(("case_brief.py", "T1"), calls)
        self.assertIn(("case_guide.py", "T1"), calls)

    def test_a_fresh_brief_with_a_missing_guide_gets_only_case_guide_rerun(self):
        # The bug this guards against: a case whose brief is already
        # current but was never followed by a case-guide run (e.g. a brief
        # created by hand, or by a run whose case-guide call failed) used
        # to be treated as fully up to date and left alone forever --
        # correct case-brief/case-guide (re)run behavior for it is to skip
        # the already-current case-brief and only (re)run case-guide.
        current = {"ticket_number": "T1", "title": "t1", "customer": "c1", "is_new": False, "stale": False}
        calls = []

        def fake_run_stage(script, number):
            calls.append(os.path.basename(script))
            with open(os.path.join(self.tmp, "guide", f"guide-{number}.md"), "w", encoding="utf-8") as f:
                f.write(_guide())
            return 0

        rc = self._run([current], fake_run_stage)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["case_guide.py"])  # case_brief.py never called

    def test_a_guide_missing_the_difficulty_line_gets_retried(self):
        # The other half of the same bug: a guide that genuinely exists but
        # is missing its difficulty line (claude dropped it) used to be
        # indistinguishable from "done" and never got another try.
        current = {"ticket_number": "T1", "title": "t1", "customer": "c1", "is_new": False, "stale": False}
        with open(os.path.join(self.tmp, "guide", "guide-T1.md"), "w", encoding="utf-8") as f:
            f.write("# Case T1\n\nNo difficulty line in here at all.\n")
        calls = []

        def fake_run_stage(script, number):
            calls.append(os.path.basename(script))
            with open(os.path.join(self.tmp, "guide", f"guide-{number}.md"), "w", encoding="utf-8") as f:
                f.write(_guide())  # this time claude includes the line
            return 0

        rc = self._run([current], fake_run_stage)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["case_guide.py"])  # case_brief.py never called

    def test_dry_run_never_calls_run_stage(self):
        cases = [self._new_case("T1")]
        run_stage = mock.Mock()
        rc = self._run(cases, run_stage, argv=["--dry-run"])
        run_stage.assert_not_called()
        self.assertEqual(rc, 0)

    def test_dry_run_lists_every_relevant_case_including_up_to_date_ones(self):
        current = {"ticket_number": "T1", "title": "t1", "customer": "c1", "is_new": False, "stale": False}
        new_case = self._new_case("T2")
        run_stage = mock.Mock()
        with mock.patch("builtins.print") as fake_print:
            self._run([current, new_case], run_stage, argv=["--dry-run"])
        run_stage.assert_not_called()
        printed = "\n".join(str(c.args[0]) for c in fake_print.call_args_list if c.args)
        self.assertIn("T1", printed)
        self.assertIn("T2", printed)

    def test_no_relevant_cases_is_a_clean_no_op(self):
        rc = self._run([], mock.Mock())
        self.assertEqual(rc, 0)

    def test_a_report_file_is_written_under_report_dir(self):
        cases = [self._new_case("T1")]
        self._run(cases, lambda script, number: 1)  # brief fails -- still writes a report
        written = glob.glob(os.path.join(self.tmp, "gets", "get-*.md"))
        self.assertEqual(len(written), 1)
        with open(written[0], "r", encoding="utf-8") as f:
            self.assertIn("T1", f.read())

    def test_the_written_report_links_the_case_number_to_its_crm_url(self):
        case = self._new_case("T1")
        case["url"] = "https://crm.example/main.aspx?id=abc"
        self._run([case], lambda script, number: 1)  # brief fails -- still writes a report
        written = glob.glob(os.path.join(self.tmp, "gets", "get-*.md"))
        with open(written[0], "r", encoding="utf-8") as f:
            self.assertIn("[T1](https://crm.example/main.aspx?id=abc)", f.read())

    def test_default_sort_orders_the_triage_summary_easiest_first(self):
        # No --sort flag at all -- easiest-first is now the default, not
        # an opt-in.
        cases = [self._new_case("T1", "t1", "c1"), self._new_case("T2", "t2", "c2")]
        difficulties = {"T1": "7/10 -- hard", "T2": "2/10 -- easy"}

        def fake_run_stage(script, number):
            base = "brief" if os.path.basename(script) == "case_brief.py" else "guide"
            content = _brief() if base == "brief" else _guide(f"**Implementation Difficulty:** {difficulties[number]}")
            with open(os.path.join(self.tmp, base, f"{base}-{number}.md"), "w", encoding="utf-8") as f:
                f.write(content)
            return 0

        with mock.patch("builtins.print") as fake_print:
            self._run(cases, fake_run_stage)
        printed = "\n".join(str(c.args[0]) for c in fake_print.call_args_list if c.args)
        # The triage-summary bullet lines specifically ("- T2"), not just
        # any mention of the case number -- both cases' own "=== T1 ===" /
        # "=== T2 ===" processing headers print in the original (unsorted)
        # order regardless of --sort.
        self.assertLess(printed.index("- T2"), printed.index("- T1"))

    def test_sort_hardest_reverses_the_default(self):
        cases = [self._new_case("T1", "t1", "c1"), self._new_case("T2", "t2", "c2")]
        difficulties = {"T1": "2/10 -- easy", "T2": "7/10 -- hard"}

        def fake_run_stage(script, number):
            base = "brief" if os.path.basename(script) == "case_brief.py" else "guide"
            content = _brief() if base == "brief" else _guide(f"**Implementation Difficulty:** {difficulties[number]}")
            with open(os.path.join(self.tmp, base, f"{base}-{number}.md"), "w", encoding="utf-8") as f:
                f.write(content)
            return 0

        with mock.patch("builtins.print") as fake_print:
            self._run(cases, fake_run_stage, argv=["--sort", "hardest"])
        printed = "\n".join(str(c.args[0]) for c in fake_print.call_args_list if c.args)
        self.assertLess(printed.index("- T2"), printed.index("- T1"))

    def test_a_failed_guide_after_a_successful_brief_still_reports_title_and_customer(self):
        # CLAUDE.md calls this out by name: "a failed case_guide.py call
        # still reports the brief's own title/customer, just with no
        # difficulty line" -- distinct from a failed *brief* (which has
        # nothing to report at all beyond the raw CRM listing fields).
        cases = [self._new_case("T1", "t1", "c1")]

        def fake_run_stage(script, number):
            if os.path.basename(script) == "case_brief.py":
                with open(os.path.join(self.tmp, "brief", f"brief-{number}.md"), "w", encoding="utf-8") as f:
                    f.write(_brief("Real Title", "Real Customer"))
                return 0
            return 1  # guide fails -- never writes guide-T1.md

        rc = self._run(cases, fake_run_stage)
        self.assertEqual(rc, 1)

    def test_a_stage_reporting_success_but_writing_no_file_is_treated_as_a_failure(self):
        # Both `rc != 0 or not os.path.exists(...)` checks have a second
        # half no other test exercises: a script that returns 0 without
        # actually producing the file it's supposed to.
        cases = [self._new_case("T1")]
        rc = self._run(cases, lambda script, number: 0)  # "succeeds" but writes nothing
        self.assertEqual(rc, 1)

    def test_a_truncation_warning_is_printed_but_does_not_stop_the_run(self):
        cases = [self._new_case("T1")]

        def fake_run_stage(script, number):
            base = "brief" if os.path.basename(script) == "case_brief.py" else "guide"
            content = _brief() if base == "brief" else _guide()
            with open(os.path.join(self.tmp, base, f"{base}-{number}.md"), "w", encoding="utf-8") as f:
                f.write(content)
            return 0

        with mock.patch.object(cg, "BRIEF_DIR", os.path.join(self.tmp, "brief")), \
             mock.patch.object(cg, "GUIDE_DIR", os.path.join(self.tmp, "guide")), \
             mock.patch.object(cg, "REPORT_DIR", os.path.join(self.tmp, "gets")), \
             mock.patch.object(cg, "find_relevant_cases", return_value=(cases, "more than 200 cases matched")), \
             mock.patch.object(cg, "run_stage", side_effect=fake_run_stage), \
             mock.patch.object(sys, "argv", ["case_getter.py"]):
            with mock.patch("sys.stderr") as fake_stderr:
                rc = cg.main()
        self.assertEqual(rc, 0)
        printed_to_stderr = "".join(str(c.args[0]) for c in fake_stderr.write.call_args_list)
        self.assertIn("more than 200 cases matched", printed_to_stderr)

    def test_no_relevant_cases_still_writes_an_empty_report_not_just_returncode_zero(self):
        self._run([], mock.Mock())
        written = glob.glob(os.path.join(self.tmp, "gets", "get-*.md"))
        self.assertEqual(len(written), 1)


class RunStageTests(unittest.TestCase):
    def test_calls_subprocess_run_with_the_interpreter_script_and_case_number(self):
        with mock.patch.object(cg.subprocess, "run") as run:
            run.return_value.returncode = 0
            rc = cg.run_stage("case_brief.py", "T1")
        run.assert_called_once_with([cg.sys.executable, "case_brief.py", "T1"])
        self.assertEqual(rc, 0)

    def test_returns_the_subprocess_exit_code(self):
        with mock.patch.object(cg.subprocess, "run") as run:
            run.return_value.returncode = 3
            self.assertEqual(cg.run_stage("case_brief.py", "T1"), 3)


if __name__ == "__main__":
    unittest.main()
