#!/usr/bin/env python3
"""Root-level entry point for the three case-wizard stages, individually or chained.

`brief`/`guide`/`solve` just forward everything after the stage name to that
stage's own script -- its flags never need duplicating here, so
`case.py brief -h` shows that script's real, current help text.

`all` runs all three in order for one case (brief -> guide -> solve), calling
each script via subprocess exactly as if you'd run them yourself one after
another -- no shared code, nothing changes about the three stages being
independent. Each stage already reads the previous one's output straight off
disk (guide reads case-brief's .md, solve reads case-guide's .md), so
chaining needs nothing more than calling them in order. A failed stage stops
the chain (later stages need its output). Interactive prompts (case-solve's
repo/confirm prompts if you skip --repo / --solve-arg=--yes) still work --
stdin/stdout are inherited, not captured.

Examples:
    python case.py brief T2611845
    python case.py guide T2611845 --model opus
    python case.py solve T2611845 --repo <url> --show-plan
    python case.py brief -h                              # forwarded --help

    python case.py all T2611845 --repo <url>              # full chain
    python case.py all T2611845 --stop-after guide        # brief + guide only
    python case.py all T2611845 --repo <url> --solve-arg --yes
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGES = ["brief", "guide", "solve"]
SCRIPTS = {stage: HERE / f"case-{stage}" / f"case_{stage}.py" for stage in STAGES}


def run_one(stage, argv):
    """Forward argv as-is to one stage's script."""
    return subprocess.run([sys.executable, str(SCRIPTS[stage]), *argv]).returncode


def build_chain_parser():
    parser = argparse.ArgumentParser(
        prog="case.py all",
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

    print(f"Unknown stage {stage!r}. Choose one of: {', '.join(STAGES)}, all", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
