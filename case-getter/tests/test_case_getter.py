"""Unit tests for case_getter.py's own logic: which CRM cases count as
"new" (existing_brief_numbers/find_new_relevant_cases), pulling
title/customer/difficulty back out of a finished brief/guide
(summarize), and main()'s per-case loop (mocked subprocess calls -- no
real brief/guide/CRM/claude call).

Deliberately not exhaustive over build_parser/CLI plumbing -- low-risk,
same convention as case-brief's own tests. What's actually worth testing
here: the "new" filter (a case with a brief already on disk must never be
re-processed), and a failure on one case must not stop the rest.

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


class FindNewRelevantCasesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_brief(self, ticket_number):
        with open(os.path.join(self.tmp, f"brief-{ticket_number}.md"), "w", encoding="utf-8") as f:
            f.write("x")

    def test_excludes_cases_that_already_have_a_brief(self):
        self._write_brief("T1")
        cases = [{"ticket_number": "T1"}, {"ticket_number": "T2"}]
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=(cases, None, False)):
            new_cases, warning = cg.find_new_relevant_cases(self.tmp)
        self.assertEqual([c["ticket_number"] for c in new_cases], ["T2"])
        self.assertIsNone(warning)

    def test_a_listing_error_exits_rather_than_returning_a_partial_result(self):
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=([], "HTTP 403", False)):
            with self.assertRaises(SystemExit):
                cg.find_new_relevant_cases(self.tmp)

    def test_truncation_is_surfaced_as_a_warning_not_silently_dropped(self):
        cases = [{"ticket_number": "T2"}]
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=(cases, None, True)):
            new_cases, warning = cg.find_new_relevant_cases(self.tmp)
        self.assertEqual([c["ticket_number"] for c in new_cases], ["T2"])
        self.assertIsNotNone(warning)

    def test_a_ticket_number_needing_filename_sanitizing_still_matches_its_brief(self):
        # safe_name replaces unsafe characters with "_" -- the brief on disk
        # is named after the sanitized form, so the CRM's raw ticket number
        # has to be sanitized the same way before comparing, or a case that
        # already has a brief would look "new" again.
        self._write_brief("T1_2")
        cases = [{"ticket_number": "T1/2"}]
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=(cases, None, False)):
            new_cases, _ = cg.find_new_relevant_cases(self.tmp)
        self.assertEqual(new_cases, [])

    def test_a_brand_new_case_is_tagged_not_stale(self):
        cases = [{"ticket_number": "T2"}]
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=(cases, None, False)):
            new_cases, _ = cg.find_new_relevant_cases(self.tmp)
        self.assertEqual(new_cases[0]["stale"], False)

    def test_a_case_with_a_brief_whose_crm_data_changed_since_is_included_as_stale(self):
        path = os.path.join(self.tmp, "brief-T1.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Case T1\n\n<!-- case-brief:crm-modified-on=2026-08-20T10:00:00Z -->\n\nold content\n")
        cases = [{"ticket_number": "T1", "modified_on": "2026-08-21T09:00:00Z"}]
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=(cases, None, False)):
            new_cases, _ = cg.find_new_relevant_cases(self.tmp)
        self.assertEqual([c["ticket_number"] for c in new_cases], ["T1"])
        self.assertTrue(new_cases[0]["stale"])

    def test_a_case_with_an_up_to_date_brief_is_excluded(self):
        path = os.path.join(self.tmp, "brief-T1.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Case T1\n\n<!-- case-brief:crm-modified-on=2026-08-21T09:00:00Z -->\n\ncontent\n")
        cases = [{"ticket_number": "T1", "modified_on": "2026-08-21T09:00:00Z"}]
        with mock.patch.object(cg.case_brief, "list_relevant_cases", return_value=(cases, None, False)):
            new_cases, _ = cg.find_new_relevant_cases(self.tmp)
        self.assertEqual(new_cases, [])


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

    def test_a_guide_missing_the_difficulty_line_comes_back_none(self):
        guide_path = self._write("guide.md", "# Case T1\n\nno difficulty line here.\n")
        row = cg.summarize("T1", None, guide_path)
        self.assertIsNone(row["difficulty"])


class CaseToRowTests(unittest.TestCase):
    def test_normalizes_a_raw_listing_entry_to_the_row_shape(self):
        c = {"ticket_number": "T1", "owned_by_me": True, "stale": True, "title": "A title", "customer": "Contoso"}
        self.assertEqual(cg._case_to_row(c), {
            "case_number": "T1", "owned_by_me": True, "stale": True, "title": "A title", "customer": "Contoso",
        })

    def test_missing_optional_fields_come_back_none_or_false_not_a_crash(self):
        row = cg._case_to_row({"ticket_number": "T1"})
        self.assertEqual(row, {"case_number": "T1", "owned_by_me": None, "stale": False, "title": None, "customer": None})


class TagTests(unittest.TestCase):
    def test_non_stale_case_renders_exactly_like_ownership_tag(self):
        self.assertEqual(cg._tag({"owned_by_me": True}), "mine")
        self.assertEqual(cg._tag({"owned_by_me": False}), "unassigned")

    def test_stale_case_appends_stale(self):
        self.assertEqual(cg._tag({"owned_by_me": True, "stale": True}), "mine, stale")
        self.assertEqual(cg._tag({"owned_by_me": False, "stale": True}), "unassigned, stale")


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
        self.assertIn("No new, relevant cases found.", md)

    def test_a_full_run_row_includes_difficulty_and_ownership(self):
        rows = [{"case_number": "T1", "owned_by_me": True, "title": "A title",
                  "customer": "Contoso", "difficulty": "4/10 -- easy"}]
        md = cg.build_report_markdown(rows, dry_run=False, timestamp="2026-08-26 12:00:00")
        self.assertIn("## T1 (mine)", md)
        self.assertIn("**Difficulty:** 4/10 -- easy", md)

    def test_an_error_row_is_called_out(self):
        rows = [{"case_number": "T1", "owned_by_me": False, "title": "A title",
                  "customer": "Contoso", "difficulty": None, "error": "case-brief failed (exit 1)"}]
        md = cg.build_report_markdown(rows, dry_run=False, timestamp="2026-08-26 12:00:00")
        self.assertIn("case-brief failed (exit 1)", md)

    def test_dry_run_never_mentions_difficulty(self):
        rows = [{"case_number": "T1", "owned_by_me": False, "title": "A title", "customer": "Contoso"}]
        md = cg.build_report_markdown(rows, dry_run=True, timestamp="2026-08-26 12:00:00")
        self.assertNotIn("Difficulty", md)
        self.assertIn("dry run", md.lower())


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


class OwnershipTagTests(unittest.TestCase):
    def test_owned_by_me_true_is_tagged_mine(self):
        self.assertEqual(cg._ownership_tag({"owned_by_me": True}), "mine")

    def test_owned_by_me_false_or_missing_is_tagged_unassigned(self):
        self.assertEqual(cg._ownership_tag({"owned_by_me": False}), "unassigned")
        self.assertEqual(cg._ownership_tag({}), "unassigned")


class MainLoopTests(unittest.TestCase):
    """main()'s per-case loop, with run_stage/find_new_relevant_cases/
    summarize mocked out -- no real subprocess, CRM, or claude call."""

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
             mock.patch.object(cg, "find_new_relevant_cases", return_value=(cases, None)), \
             mock.patch.object(cg, "run_stage", side_effect=run_stage_side_effect), \
             mock.patch.object(sys, "argv", ["case_getter.py", *(argv or [])]):
            return cg.main()

    def test_a_failed_brief_is_reported_and_does_not_stop_the_next_case(self):
        cases = [{"ticket_number": "T1", "title": "t1", "customer": "c1"},
                 {"ticket_number": "T2", "title": "t2", "customer": "c2"}]
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

    def test_limit_caps_how_many_cases_are_processed(self):
        cases = [{"ticket_number": f"T{n}", "title": "t", "customer": "c"} for n in range(5)]
        calls = []

        def fake_run_stage(script, number):
            calls.append(number)
            return 1  # fail fast -- only care how many cases were attempted

        self._run(cases, fake_run_stage, argv=["--limit", "2"])
        self.assertEqual(len(set(calls)), 2)

    def test_dry_run_never_calls_run_stage(self):
        cases = [{"ticket_number": "T1", "title": "t", "customer": "c"}]
        run_stage = mock.Mock()
        rc = self._run(cases, run_stage, argv=["--dry-run"])
        run_stage.assert_not_called()
        self.assertEqual(rc, 0)

    def test_no_new_cases_is_a_clean_no_op(self):
        rc = self._run([], mock.Mock())
        self.assertEqual(rc, 0)

    def test_a_report_file_is_written_under_report_dir(self):
        cases = [{"ticket_number": "T1", "title": "t", "customer": "c"}]
        self._run(cases, lambda script, number: 1)  # brief fails -- still writes a report
        written = glob.glob(os.path.join(self.tmp, "gets", "get-*.md"))
        self.assertEqual(len(written), 1)
        with open(written[0], "r", encoding="utf-8") as f:
            self.assertIn("T1", f.read())

    def test_sort_orders_the_triage_summary_by_difficulty(self):
        # Two cases, both "succeeding" with different difficulty ratings --
        # --sort easiest should print/report T2 (2/10) before T1 (7/10)
        # even though T1 was processed first.
        cases = [{"ticket_number": "T1", "title": "t1", "customer": "c1"},
                 {"ticket_number": "T2", "title": "t2", "customer": "c2"}]
        difficulties = {"T1": "7/10 -- hard", "T2": "2/10 -- easy"}

        def fake_run_stage(script, number):
            base = "brief" if os.path.basename(script) == "case_brief.py" else "guide"
            content = _brief() if base == "brief" else _guide(f"**Implementation Difficulty:** {difficulties[number]}")
            with open(os.path.join(self.tmp, base, f"{base}-{number}.md"), "w", encoding="utf-8") as f:
                f.write(content)
            return 0

        with mock.patch("builtins.print") as fake_print:
            self._run(cases, fake_run_stage, argv=["--sort", "easiest"])
        printed = "\n".join(str(c.args[0]) for c in fake_print.call_args_list if c.args)
        # The bulleted triage-summary lines specifically ("- T2 (..."),
        # not just any mention of the case number -- both cases' own
        # "=== T1 ===" / "=== T2 ===" processing headers print in the
        # original (unsorted) order regardless of --sort.
        self.assertLess(printed.index("- T2 ("), printed.index("- T1 ("))


if __name__ == "__main__":
    unittest.main()
