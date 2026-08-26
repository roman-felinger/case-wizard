#!/usr/bin/env python3
"""Run every case-wizard test suite (case-brief, case-guide, case-solve,
case-getter).

Each stage's tests/ has to run in its own pytest invocation, not one combined
call over all of them: they're all named "tests" with no unique package name,
so a single pytest process collecting all of them at once assigns duplicate
module names and errors out (`ModuleNotFoundError` on the second and later
ones). Running one subprocess per stage, cwd'd into that stage's folder --
exactly what each stage's own README already documents -- avoids that
entirely.

Output is one row per stage (result + a one-line note), not each stage's raw
dot-per-test log -- a failing stage's full output is printed afterward, since
a compact table isn't enough to debug an actual failure from.

Examples:
    python run_tests.py              # every stage
    python run_tests.py brief guide  # just these
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGES = ["brief", "guide", "solve", "getter"]
DIRS = {stage: HERE / f"case-{stage}" for stage in STAGES}


def pytest_available():
    return subprocess.run(
        [sys.executable, "-c", "import pytest"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def summarize(output):
    """The one line worth showing for a run: pytest's own final summary line
    ("88 passed in 0.24s" / "3 failed, 85 passed in 0.30s"), or for the
    unittest fallback, its "Ran N tests in Xs" line plus the OK/FAILED verdict
    that follows it on its own line."""
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    if not lines:
        return "(no output)"
    last = lines[-1]
    if last == "OK" or last.startswith("FAILED"):
        ran = next((l for l in reversed(lines) if l.startswith("Ran ")), "")
        return f"{ran} -- {last}" if ran else last
    return last


def run_stage(stage, use_pytest):
    cmd = [sys.executable, "-m", "pytest", "tests", "-q"] if use_pytest \
        else [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    result = subprocess.run(cmd, cwd=DIRS[stage], capture_output=True, text=True)
    output = result.stdout + result.stderr
    return result.returncode == 0, summarize(output), output


def print_table(rows):
    stage_w = max(len(f"case-{stage}") for stage in rows) + 2
    result_w = len("RESULT") + 2
    print(f"{'STAGE':<{stage_w}}{'RESULT':<{result_w}}NOTES")
    for stage, (ok, notes, _) in rows.items():
        print(f"{'case-' + stage:<{stage_w}}{'PASS' if ok else 'FAIL':<{result_w}}{notes}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    stages = [s for s in argv if not s.startswith("-")] or STAGES
    unknown = [s for s in stages if s not in STAGES]
    if unknown:
        print(f"Unknown stage(s): {', '.join(unknown)}. Choose from: {', '.join(STAGES)}", file=sys.stderr)
        return 2

    use_pytest = pytest_available()
    print(f"Using {'pytest' if use_pytest else 'unittest (pytest not installed)'}\n")

    rows = {stage: run_stage(stage, use_pytest) for stage in stages}
    print_table(rows)

    failed = {stage: output for stage, (ok, _, output) in rows.items() if not ok}
    for stage, output in failed.items():
        print(f"\n=== case-{stage} output ===\n{output.rstrip()}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
