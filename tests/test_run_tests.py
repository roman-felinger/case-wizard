"""Unit tests for the root run_tests.py aggregator.

Patches run_tests.run_stage/pytest_available so these never actually shell
out to pytest/unittest -- the thing worth locking in is the aggregation
logic: an unknown stage name is rejected, a stage filter runs only those
stages, and the overall exit code is non-zero if any stage failed even when
others passed.

Run with: python -m unittest discover -s tests -v   (from the repo root)
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_tests


class MainTests(unittest.TestCase):
    def test_unknown_stage_is_an_error(self):
        with mock.patch("run_tests.pytest_available", return_value=True):
            self.assertEqual(run_tests.main(["bogus"]), 2)

    def test_defaults_to_all_three_stages(self):
        with mock.patch("run_tests.pytest_available", return_value=True), \
             mock.patch("run_tests.run_stage", return_value=True) as run_stage:
            rc = run_tests.main([])
        self.assertEqual(rc, 0)
        self.assertEqual([c.args[0] for c in run_stage.call_args_list], run_tests.STAGES)

    def test_stage_filter_runs_only_those_stages(self):
        with mock.patch("run_tests.pytest_available", return_value=True), \
             mock.patch("run_tests.run_stage", return_value=True) as run_stage:
            run_tests.main(["brief", "solve"])
        self.assertEqual([c.args[0] for c in run_stage.call_args_list], ["brief", "solve"])

    def test_any_failure_makes_the_overall_result_fail(self):
        def fake_run_stage(stage, use_pytest):
            return stage != "guide"

        with mock.patch("run_tests.pytest_available", return_value=True), \
             mock.patch("run_tests.run_stage", side_effect=fake_run_stage):
            rc = run_tests.main([])
        self.assertEqual(rc, 1)

    def test_falls_back_to_unittest_when_pytest_is_missing(self):
        with mock.patch("run_tests.pytest_available", return_value=False), \
             mock.patch("run_tests.run_stage", return_value=True) as run_stage:
            run_tests.main(["brief"])
        self.assertEqual(run_stage.call_args_list[0].args[1], False)


if __name__ == "__main__":
    unittest.main()
