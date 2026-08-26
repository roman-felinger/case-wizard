#!/usr/bin/env python3
"""Root-level entry point for the three case-wizard stages, individually or chained.

`brief`/`guide`/`solve`/`getter` just forward everything after the stage name
to that script -- its flags never need duplicating here, so
`case_wizard.py brief -h` shows that script's real, current help text.
`getter` (case-getter/case_getter.py) is dispatched the same way but isn't
part of the `all` chain below -- it runs brief+guide over every new,
unassigned CRM case it finds, not one case_number at a time.

`all` runs all three in order for one case (brief -> guide -> solve), calling
each script via subprocess exactly as if you'd run them yourself one after
another -- no shared code, nothing changes about the three stages being
independent. Each stage already reads the previous one's output straight off
disk (guide reads case-brief's .md, solve reads case-guide's .md), so
chaining needs nothing more than calling them in order. A failed stage stops
the chain (later stages need its output). case-solve is interactive-only (repo/
confirm prompts, no flag to skip either) -- stdin/stdout are inherited, not
captured, so those prompts still work when chained through `all`.

`--demo` works for every stage, without a case number:
  - brief has its own real --demo flag (fake CRM/ADO data) -- forwarded as-is.
  - guide/solve have no such flag (guide always makes a real `claude` call,
    solve always needs a real repo -- neither has a fake-data mode of its
    own), so case_wizard.py strips --demo before forwarding and, if you didn't
    already give a case number, fills in case 12345 -- the case case-brief's
    own --demo run writes, checked into git (case-brief/briefs/brief-
    12345.md and case-guide's matching case-guide/guides/guide-12345.md) so
    guide/solve have something real to run against with no CRM/ADO/repo
    setup.

Examples:
    python case_wizard.py brief T2611845
    python case_wizard.py guide T2611845 --model opus
    python case_wizard.py solve T2611845 --repo <url> --show-plan
    python case_wizard.py brief -h                              # forwarded --help

    python case_wizard.py guide --demo                           # same as: guide 12345
    python case_wizard.py solve --demo --repo <url>

    python case_wizard.py all T2611845 --repo <url>              # full chain
    python case_wizard.py all T2611845 --stop-after guide        # brief + guide only

    python case_wizard.py getter                                  # brief+guide every new, unassigned case
    python case_wizard.py getter --dry-run                        # just list them
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGES = ["brief", "guide", "solve"]
SCRIPTS = {stage: HERE / f"case-{stage}" / f"case_{stage}.py" for stage in STAGES}
# case-getter isn't a chain stage (it operates over many cases at once, not
# one case_number -- see case-getter/case_getter.py), so it's dispatched
# but deliberately left out of STAGES/`all`.
SCRIPTS["getter"] = HERE / "case-getter" / "case_getter.py"

# The case case-brief's own --demo run writes (case_brief.py's demo_data()
# falls back to ticket_number "12345" when no case number is given) --
# checked in at case-brief/briefs/brief-12345.md and
# case-guide/guides/guide-12345.md so guide/solve, which have no
# fake-data mode of their own, have something real to run --demo against.
DEMO_CASE_NUMBER = "12345"
DEMO_AWARE_STAGES = {"guide", "solve"}  # brief has its own real --demo flag


def apply_demo_default(stage, argv):
    """For stages with no --demo of their own: strip it, default the case number.

    Only fills in DEMO_CASE_NUMBER when none was given -- if you passed a real
    case number alongside --demo, that number wins and --demo is just dropped.
    """
    if stage not in DEMO_AWARE_STAGES or "--demo" not in argv:
        return argv
    argv = [a for a in argv if a != "--demo"]
    has_case_number = bool(argv) and not argv[0].startswith("-")
    return argv if has_case_number else [DEMO_CASE_NUMBER, *argv]


def run_one(stage, argv):
    """Forward argv to one stage's script (see apply_demo_default for the one exception)."""
    argv = apply_demo_default(stage, argv)
    return subprocess.run([sys.executable, str(SCRIPTS[stage]), *argv]).returncode


def build_chain_parser():
    parser = argparse.ArgumentParser(
        prog="case_wizard.py all",
        description="Run brief -> guide -> solve in order for one case.",
    )
    parser.add_argument("case_number", help="Case code, e.g. T2611845")
    parser.add_argument("--repo", metavar="URL", help="Git clone URL, forwarded to case-solve's --repo")
    parser.add_argument(
        "--stop-after", choices=STAGES, default="solve", metavar="STAGE",
        help="Stop after this stage (brief/guide/solve, default: solve -- the full chain)",
    )
    parser.add_argument("--brief-arg", metavar="ARG", action="append", dest="brief_args",
                         help="Extra raw argument for case_brief.py, repeatable")
    parser.add_argument("--guide-arg", metavar="ARG", action="append", dest="guide_args",
                         help="Extra raw argument for case_guide.py, repeatable")
    parser.add_argument("--solve-arg", metavar="ARG", action="append", dest="solve_args",
                         help="Extra raw argument for case_solve.py, repeatable")
    return parser


def run_chain(argv):
    args = build_chain_parser().parse_args(argv)
    run_upto = STAGES[: STAGES.index(args.stop_after) + 1]

    for stage in run_upto:
        stage_argv = [args.case_number]
        if stage == "solve" and args.repo:
            stage_argv += ["--repo", args.repo]
        stage_argv += getattr(args, f"{stage}_args") or []

        print(f"\n=== {stage} ===", flush=True)
        rc = run_one(stage, stage_argv)
        if rc != 0:
            print(f"\n{stage} failed (exit {rc}) -- stopping chain.", file=sys.stderr)
            return rc

    print(f"\nDone: {', '.join(run_upto)} completed for {args.case_number}.")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.rstrip())
        return 0 if argv else 2

    stage, rest = argv[0], argv[1:]
    if stage == "all":
        return run_chain(rest)
    if stage in SCRIPTS:
        return run_one(stage, rest)

    print(f"Unknown stage {stage!r}. Choose one of: {', '.join(STAGES)}, all, getter", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
