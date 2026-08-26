"""Unit tests for the root run_tests.py aggregator.

Patches run_tests.run_stage/pytest_available so these never actually shell
out to pytest/unittest -- the thing worth locking in is the aggregation
logic: an unknown stage name is rejected, a stage filter runs only those
stages, the overall exit code is non-zero if any stage failed even when
others passed, and a failing stage's raw output actually gets printed (a
compact table alone isn't enough to debug a failure from).

Run with: python -m unittest discover -s tests -v   (from the repo root)
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_tests


class SummarizeTests(unittest.TestCase):
    def test_pytest_pass_summary_line(self):
        output = "......                          [100%]\n88 passed in 0.24s\n"
        self.assertEqual(run_tests.summarize(output), "88 passed in 0.24s")

    def test_pytest_failure_summary_line(self):
        output = "===== short test summary info =====\nFAILED tests/test_x.py::test_y\n3 failed, 85 passed in 0.30s\n"
        self.assertEqual(run_tests.summarize(output), "3 failed, 85 passed in 0.30s")

    def test_unittest_ok_combines_with_the_ran_line(self):
        output = "..........\n----------------------------------------------------------------------\nRan 88 tests in 0.032s\n\nOK\n"
        self.assertEqual(run_tests.summarize(output), "Ran 88 tests in 0.032s -- OK")

    def test_unittest_failed_combines_with_the_ran_line(self):
        output = "Ran 88 tests in 0.032s\n\nFAILED (failures=2)\n"
        self.assertEqual(run_tests.summarize(output), "Ran 88 tests in 0.032s -- FAILED (failures=2)")

    def test_empty_output(self):
        self.assertEqual(run_tests.summarize(""), "(no output)")


class MainTests(unittest.TestCase):
    @staticmethod
    def _ok(stage, use_pytest):
        return True, "ok", ""

    def test_unknown_stage_is_an_error(self):
        with mock.patch("run_tests.pytest_available", return_value=True):
            self.assertEqual(run_tests.main(["bogus"]), 2)

    def test_defaults_to_every_stage(self):
        with mock.patch("run_tests.pytest_available", return_value=True), \
             mock.patch("run_tests.run_stage", side_effect=self._ok) as run_stage:
            rc = run_tests.main([])
        self.assertEqual(rc, 0)
        self.assertEqual([c.args[0] for c in run_stage.call_args_list], run_tests.STAGES)

    def test_stage_filter_runs_only_those_stages(self):
        with mock.patch("run_tests.pytest_available", return_value=True), \
             mock.patch("run_tests.run_stage", side_effect=self._ok) as run_stage:
            run_tests.main(["brief", "solve"])
        self.assertEqual([c.args[0] for c in run_stage.call_args_list], ["brief", "solve"])

    def test_any_failure_makes_the_overall_result_fail(self):
        def fake_run_stage(stage, use_pytest):
            return (stage != "guide"), "notes", "raw output"

        with mock.patch("run_tests.pytest_available", return_value=True), \
             mock.patch("run_tests.run_stage", side_effect=fake_run_stage):
            rc = run_tests.main([])
        self.assertEqual(rc, 1)

    def test_falls_back_to_unittest_when_pytest_is_missing(self):
        with mock.patch("run_tests.pytest_available", return_value=False), \
             mock.patch("run_tests.run_stage", side_effect=self._ok) as run_stage:
            run_tests.main(["brief"])
        self.assertEqual(run_stage.call_args_list[0].args[1], False)

    def test_a_failed_stages_raw_output_is_printed(self):
        def fake_run_stage(stage, use_pytest):
            return (stage != "guide"), "notes", "THE ACTUAL FAILURE DETAIL"

        with mock.patch("run_tests.pytest_available", return_value=True), \
             mock.patch("run_tests.run_stage", side_effect=fake_run_stage), \
             mock.patch("builtins.print") as fake_print:
            run_tests.main([])
        printed = "\n".join(str(c.args[0]) for c in fake_print.call_args_list if c.args)
        self.assertIn("THE ACTUAL FAILURE DETAIL", printed)


if __name__ == "__main__":
    unittest.main()
