#!/usr/bin/env python3
"""Run all three case-wizard test suites (case-brief, case-guide, case-solve).

Each stage's tests/ has to run in its own pytest invocation, not one combined
call over all three: they're all named "tests" with no unique package name,
so a single pytest process collecting all of them at once assigns duplicate
module names and errors out (`ModuleNotFoundError` on the second and third).
Running one subprocess per stage, cwd'd into that stage's folder -- exactly
what each stage's own README already documents -- avoids that entirely.

Examples:
    python run_tests.py              # all three
    python run_tests.py brief guide  # just these
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGES = ["brief", "guide", "solve"]
DIRS = {stage: HERE / f"case-{stage}" for stage in STAGES}


def pytest_available():
    return subprocess.run(
        [sys.executable, "-c", "import pytest"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def run_stage(stage, use_pytest):
    print(f"\n=== case-{stage} ===", flush=True)
    cmd = [sys.executable, "-m", "pytest", "tests", "-q"] if use_pytest \
        else [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    return subprocess.run(cmd, cwd=DIRS[stage]).returncode == 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    stages = [s for s in argv if not s.startswith("-")] or STAGES
    unknown = [s for s in stages if s not in STAGES]
    if unknown:
        print(f"Unknown stage(s): {', '.join(unknown)}. Choose from: {', '.join(STAGES)}", file=sys.stderr)
        return 2

    use_pytest = pytest_available()
    print(f"Using {'pytest' if use_pytest else 'unittest (pytest not installed)'}")

    results = {stage: run_stage(stage, use_pytest) for stage in stages}

    print("\n=== summary ===")
    for stage, ok in results.items():
        print(f"  case-{stage}: {'PASS' if ok else 'FAIL'}")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
