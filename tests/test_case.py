"""Unit tests for the root case.py dispatcher/chain.

case.py never runs the real stage scripts itself -- every test here patches
`case.run_one` (or `subprocess.run` underneath it) so these stay fast and
network/CRM/claude-free. The one thing worth locking in beyond plain
dispatch is the chain's control flow: it must stop at the requested
--stop-after stage, stop immediately (without touching later stages) the
moment one stage fails, and only ever forward --repo to solve.

Run with: python -m unittest discover -s tests -v   (from the repo root)
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import case


class RunOneTests(unittest.TestCase):
    def test_forwards_argv_to_the_right_script(self):
        with mock.patch("case.subprocess.run") as run:
            run.return_value.returncode = 0
            case.run_one("guide", ["T2611845", "--model", "opus"])
        run.assert_called_once_with([sys.executable, str(case.SCRIPTS["guide"]), "T2611845", "--model", "opus"])

    def test_returns_the_script_exit_code(self):
        with mock.patch("case.subprocess.run") as run:
            run.return_value.returncode = 3
            self.assertEqual(case.run_one("brief", []), 3)


class MainDispatchTests(unittest.TestCase):
    def test_unknown_stage_is_an_error(self):
        self.assertEqual(case.main(["bogus"]), 2)

    def test_no_args_prints_help_and_errors(self):
        self.assertEqual(case.main([]), 2)

    def test_help_flag_is_not_an_error(self):
        self.assertEqual(case.main(["-h"]), 0)

    def test_known_stage_delegates_to_run_one(self):
        with mock.patch("case.run_one", return_value=0) as run_one:
            case.main(["solve", "T1", "--repo", "u"])
        run_one.assert_called_once_with("solve", ["T1", "--repo", "u"])


class ChainTests(unittest.TestCase):
    def test_runs_all_three_by_default(self):
        with mock.patch("case.run_one", return_value=0) as run_one:
            rc = case.run_chain(["T1"])
        self.assertEqual(rc, 0)
        self.assertEqual([c.args[0] for c in run_one.call_args_list], ["brief", "guide", "solve"])

    def test_stop_after_limits_the_chain(self):
        with mock.patch("case.run_one", return_value=0) as run_one:
            case.run_chain(["T1", "--stop-after", "guide"])
        self.assertEqual([c.args[0] for c in run_one.call_args_list], ["brief", "guide"])

    def test_a_failed_stage_stops_the_chain(self):
        def fake_run_one(stage, argv):
            return 1 if stage == "guide" else 0

        with mock.patch("case.run_one", side_effect=fake_run_one) as run_one:
            rc = case.run_chain(["T1"])
        self.assertEqual(rc, 1)
        self.assertEqual([c.args[0] for c in run_one.call_args_list], ["brief", "guide"])  # solve never called

    def test_repo_is_only_forwarded_to_solve(self):
        with mock.patch("case.run_one", return_value=0) as run_one:
            case.run_chain(["T1", "--repo", "https://example/repo"])
        calls = {c.args[0]: c.args[1] for c in run_one.call_args_list}
        self.assertNotIn("--repo", calls["brief"])
        self.assertNotIn("--repo", calls["guide"])
        self.assertIn("--repo", calls["solve"])
        self.assertEqual(calls["solve"][calls["solve"].index("--repo") + 1], "https://example/repo")

    def test_per_stage_extra_args_are_appended(self):
        with mock.patch("case.run_one", return_value=0) as run_one:
            case.run_chain(["T1", "--brief-arg=--demo", "--guide-arg=--no-open"])
        calls = {c.args[0]: c.args[1] for c in run_one.call_args_list}
        self.assertEqual(calls["brief"], ["T1", "--demo"])
        self.assertEqual(calls["guide"], ["T1", "--no-open"])


if __name__ == "__main__":
    unittest.main()
