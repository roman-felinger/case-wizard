"""Unit tests for the root case_wizard.py dispatcher/chain.

case_wizard.py never runs the real stage scripts itself -- every test here patches
`case_wizard.run_one` (or `subprocess.run` underneath it) so these stay fast and
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

import case_wizard


class RunOneTests(unittest.TestCase):
    def test_forwards_argv_to_the_right_script(self):
        with mock.patch("case_wizard.subprocess.run") as run:
            run.return_value.returncode = 0
            case_wizard.run_one("guide", ["T2611845", "--model", "opus"])
        run.assert_called_once_with([sys.executable, str(case_wizard.SCRIPTS["guide"]), "T2611845", "--model", "opus"])

    def test_returns_the_script_exit_code(self):
        with mock.patch("case_wizard.subprocess.run") as run:
            run.return_value.returncode = 3
            self.assertEqual(case_wizard.run_one("brief", []), 3)

    def test_brief_demo_is_forwarded_untouched(self):
        # brief has its own real --demo flag -- case_wizard.py must not touch it.
        with mock.patch("case_wizard.subprocess.run") as run:
            run.return_value.returncode = 0
            case_wizard.run_one("brief", ["--demo"])
        run.assert_called_once_with([sys.executable, str(case_wizard.SCRIPTS["brief"]), "--demo"])


class ApplyDemoDefaultTests(unittest.TestCase):
    def test_no_demo_flag_is_a_no_op(self):
        self.assertEqual(case_wizard.apply_demo_default("guide", ["T1"]), ["T1"])

    def test_brief_is_never_touched(self):
        self.assertEqual(case_wizard.apply_demo_default("brief", ["--demo"]), ["--demo"])

    def test_guide_demo_alone_defaults_the_case_number(self):
        self.assertEqual(case_wizard.apply_demo_default("guide", ["--demo"]), [case_wizard.DEMO_CASE_NUMBER])

    def test_guide_demo_with_other_flags_defaults_the_case_number(self):
        self.assertEqual(
            case_wizard.apply_demo_default("guide", ["--demo", "--no-example"]),
            [case_wizard.DEMO_CASE_NUMBER, "--no-example"],
        )

    def test_explicit_case_number_wins_over_demo_default(self):
        self.assertEqual(case_wizard.apply_demo_default("guide", ["T2611845", "--demo"]), ["T2611845"])

    def test_solve_demo_also_defaults_the_case_number(self):
        self.assertEqual(
            case_wizard.apply_demo_default("solve", ["--demo", "--repo", "u"]),
            [case_wizard.DEMO_CASE_NUMBER, "--repo", "u"],
        )


class MainDispatchTests(unittest.TestCase):
    def test_unknown_stage_is_an_error(self):
        self.assertEqual(case_wizard.main(["bogus"]), 2)

    def test_no_args_prints_help_and_errors(self):
        self.assertEqual(case_wizard.main([]), 2)

    def test_help_flag_is_not_an_error(self):
        self.assertEqual(case_wizard.main(["-h"]), 0)

    def test_known_stage_delegates_to_run_one(self):
        with mock.patch("case_wizard.run_one", return_value=0) as run_one:
            case_wizard.main(["solve", "T1", "--repo", "u"])
        run_one.assert_called_once_with("solve", ["T1", "--repo", "u"])

    def test_getter_delegates_to_run_one_despite_being_outside_stages(self):
        # "getter" is in SCRIPTS but deliberately not in STAGES/`all` (it
        # operates over many cases, not one case_number) -- dispatch must
        # still find it via SCRIPTS, not STAGES.
        with mock.patch("case_wizard.run_one", return_value=0) as run_one:
            case_wizard.main(["getter", "--dry-run"])
        run_one.assert_called_once_with("getter", ["--dry-run"])


class ChainTests(unittest.TestCase):
    def test_runs_all_three_by_default(self):
        with mock.patch("case_wizard.run_one", return_value=0) as run_one:
            rc = case_wizard.run_chain(["T1"])
        self.assertEqual(rc, 0)
        self.assertEqual([c.args[0] for c in run_one.call_args_list], ["brief", "guide", "solve"])

    def test_stop_after_limits_the_chain(self):
        with mock.patch("case_wizard.run_one", return_value=0) as run_one:
            case_wizard.run_chain(["T1", "--stop-after", "guide"])
        self.assertEqual([c.args[0] for c in run_one.call_args_list], ["brief", "guide"])

    def test_a_failed_stage_stops_the_chain(self):
        def fake_run_one(stage, argv):
            return 1 if stage == "guide" else 0

        with mock.patch("case_wizard.run_one", side_effect=fake_run_one) as run_one:
            rc = case_wizard.run_chain(["T1"])
        self.assertEqual(rc, 1)
        self.assertEqual([c.args[0] for c in run_one.call_args_list], ["brief", "guide"])  # solve never called

    def test_repo_is_only_forwarded_to_solve(self):
        with mock.patch("case_wizard.run_one", return_value=0) as run_one:
            case_wizard.run_chain(["T1", "--repo", "https://example/repo"])
        calls = {c.args[0]: c.args[1] for c in run_one.call_args_list}
        self.assertNotIn("--repo", calls["brief"])
        self.assertNotIn("--repo", calls["guide"])
        self.assertIn("--repo", calls["solve"])
        self.assertEqual(calls["solve"][calls["solve"].index("--repo") + 1], "https://example/repo")

    def test_per_stage_extra_args_are_appended(self):
        with mock.patch("case_wizard.run_one", return_value=0) as run_one:
            case_wizard.run_chain(["T1", "--brief-arg=--demo", "--guide-arg=--no-example"])
        calls = {c.args[0]: c.args[1] for c in run_one.call_args_list}
        self.assertEqual(calls["brief"], ["T1", "--demo"])
        self.assertEqual(calls["guide"], ["T1", "--no-example"])


if __name__ == "__main__":
    unittest.main()
