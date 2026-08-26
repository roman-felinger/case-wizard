#!/usr/bin/env python3
"""
case-solve: Read a case guide, implement the changes automatically.

Workflow: case-brief → case-guide → case-solve
  1. case-brief gathers case context (CRM, ADO) into a markdown brief
  2. case-guide reads the brief, asks Claude for a walkthrough
  3. case-solve reads the guide, clones the repo, implements changes on a branch

Each run:
  - Reads the guide already written by case-guide
  - Prompts for repo URL (suggests one parsed from the guide, but you can override)
  - Clones repo (or uses cached clone) and creates a case-specific branch
  - Installs dependencies (pip, npm, dotnet, cargo as detected)
  - Uses Claude to guide implementation step-by-step, applying changes
  - Runs tests, build, lint checks (auto-detects available tools)
  - Groups changes into logical commits by category (tests, dependencies,
    config, docs, source, other)
  - Outputs a verification checklist for manual steps
  - Generates a summary report

The cloned repo is cached at case-solves/repos/<repo-name>/ (shared, reused
across cases); case-solves/<case-code>/ holds this case's branch info and
verification checklist for the developer to review before pushing.

Usage:
  python case_solve.py T2611845                    # Full run, prompts for repo
  python case_solve.py T2611845 --repo https://... # Override repo URL
  python case_solve.py T2611845 --no-implement     # Stop after branch creation
  python case_solve.py T2611845 --show-plan        # Show implementation plan, don't apply
  python case_solve.py -h                          # All flags
"""

import argparse
import copy
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.console import enable_utf8_console

enable_utf8_console()  # this script prints Unicode; see shared/console.py

from shared.config import deep_merge, strip_comments
from shared.safe_name import safe_name as _safe_name

HERE = Path(__file__).parent
CONFIG_PATH = HERE / "config.json"
GUIDE_DIR = HERE.parent / "case-guide" / "guides"
SOLVES_DIR = HERE / "case-solves"

# Default configuration
DEFAULTS = {
    "run_tests": True,
    "run_lint": True,
    "run_build": True,
    "claude": {
        "model": None,
        "agent": "case-solver",
        "timeout": 900,  # 15 minutes for implementation
    },
}


def load_config(path=None):
    """Load config.json if it exists, deep-merge into DEFAULTS."""
    path = path or CONFIG_PATH
    cfg = copy.deepcopy(DEFAULTS)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            deep_merge(cfg, json.load(f))
        cfg = strip_comments(cfg)
    return cfg


def apply_cli_overrides(cfg, args):
    """Apply CLI flag overrides to config."""
    if args.skip_tests:
        cfg["run_tests"] = False
    if args.skip_lint:
        cfg["run_lint"] = False
    if args.skip_build:
        cfg["run_build"] = False
    return cfg


def guide_filename(case_number):
    """Expected guide filename for a case number."""
    safe = _safe_name(case_number)
    return f"guide-{safe}.md"


def find_guide(case_number, guide_dir):
    """Find the guide file, with fallback to substring match."""
    guide_dir = Path(guide_dir)

    # Try exact match first
    exact = guide_dir / guide_filename(case_number)
    if exact.exists():
        return exact

    # Try substring match (glob)
    safe = _safe_name(case_number)
    pattern = f"guide-*{safe}*.md"
    matches = list(guide_dir.glob(pattern))

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        sys.exit(
            f"Ambiguous: found {len(matches)} guides matching '{pattern}':\n"
            + "\n".join(f"  {m.name}" for m in matches)
            + "\nRun case-guide with a more specific case number."
        )
    else:
        sys.exit(
            f"Guide not found: {exact}\n\n"
            f"Run case-guide first:\n"
            f"  cd ../case-guide\n"
            f"  python case_guide.py {case_number}"
        )


def read_guide(path):
    """Read and parse the guide file."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# Own copy of case-guide's _READINESS_RE (see case_guide.py's
# "Readiness check" section of PROMPT_TEMPLATE) -- same "independent copy,
# not shared" tradeoff as the two ado_api.py's (CLAUDE.md's "Known accepted
# duplication"). Keep the marker regex itself in sync with case-guide's if
# the wording ever changes; the trailing "-- <reason>" capture is this
# side's own addition, used only to surface the reason in the stop message.
_READINESS_RE = re.compile(r"(?im)\*\*Ready for Implementation:\*\*\s*(Yes|No)\b(?:\s*--\s*(.+))?")


def check_readiness(guide_text):
    """Whether the guide says a developer can start alone. Returns
    (ready: bool, reason: str or None).

    No marker at all -- an older guide, or claude dropped the line despite
    PROMPT_TEMPLATE asking for it -- is treated as ready. case-guide's own
    write_and_open path already warns the operator to double-check by hand
    when the marker is missing (see _has_readiness_marker); a missing line
    here isn't reason enough to hard-block a real case that's actually fine
    to start."""
    match = _READINESS_RE.search(guide_text[:1000])
    if not match or match.group(1).lower() == "yes":
        return True, None
    reason = (match.group(2) or "").strip() or None
    return False, reason


def extract_repo_suggestion(guide_text):
    """Extract suggested repo URL from guide (if present in 'Get set up' section)."""
    # Simple heuristic: look for 'git clone' in guide
    for line in guide_text.split("\n"):
        if "git clone" in line.lower():
            # Extract URL
            parts = line.split()
            for i, part in enumerate(parts):
                if "github" in part or "dev.azure" in part or "gitlab" in part:
                    return part.rstrip(".")
    return None


def prompt_for_repo(suggested_repo=None):
    """Interactively ask user for repo URL."""
    print("\n" + "=" * 70)
    if suggested_repo:
        print(f"Suggested repo: {suggested_repo}")
        prompt = "Enter repo URL (or press Enter to use suggested): "
    else:
        prompt = "Enter repo URL (clone link): "

    while True:
        url = input(prompt).strip()
        if url:
            return url
        elif suggested_repo:
            return suggested_repo
        else:
            print("Repo URL required.")


def extract_repo_name(repo_url):
    """Extract repo name from URL."""
    # GitHub: https://github.com/org/repo → repo
    # ADO: https://dev.azure.com/org/project/_git/repo → repo
    # GitLab: https://gitlab.com/org/repo → repo
    return repo_url.rstrip("/").split("/")[-1].replace(".git", "")


def confirm_before_implementing(case_number, repo_url, branch_name):
    """Show details and confirm before making changes."""
    repo_name = extract_repo_name(repo_url)

    print("\n" + "=" * 70)
    print("CONFIRMATION REQUIRED")
    print("=" * 70)
    print(f"\nAbout to make changes to your repository:")
    print(f"  Repository: {repo_name}")
    print(f"  Clone URL:  {repo_url}")
    print(f"  Branch:     {branch_name}")
    print(f"\nActions that will be performed:")
    print(f"  1. Clone repository (or fetch if cached)")
    print(f"  2. Create branch: {branch_name}")
    print(f"  3. Install dependencies")
    print(f"  4. Apply changes from guide")
    print(f"  5. Run tests/lint/build (if enabled)")
    print(f"  6. Create commits")
    print(f"\nYou can review changes before pushing.\n")

    while True:
        response = input("Proceed with implementation? (yes/no): ").strip().lower()
        if response in ["yes", "y"]:
            return True
        elif response in ["no", "n"]:
            print("Cancelled.")
            return False
        else:
            print("Please enter 'yes' or 'no'.")


def build_parser():
    """Build and return ArgumentParser."""
    parser = argparse.ArgumentParser(
        prog="case_solve.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Positional
    parser.add_argument("case_number", help="Case code (e.g., T2611845)")

    # Repo & workspace
    repo = parser.add_argument_group("repo & workspace")
    repo.add_argument(
        "--repo",
        metavar="URL",
        help="Git clone URL (suggests from guide if not provided)",
    )
    # Modes
    modes = parser.add_argument_group("modes")
    modes.add_argument(
        "--show-plan",
        action="store_true",
        help="Show implementation plan from Claude, don't apply changes",
    )
    modes.add_argument(
        "--no-implement",
        action="store_true",
        help="Stop after creating the branch (skip implementation)",
    )
    modes.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't commit or modify anything (inspect changes only)",
    )
    # Verification
    verify = parser.add_argument_group("verification (auto-detect, can override)")
    verify.add_argument(
        "--skip-tests",
        action="store_true",
        help="Don't run test suite",
    )
    verify.add_argument(
        "--skip-lint",
        action="store_true",
        help="Don't run linting checks",
    )
    verify.add_argument(
        "--skip-build",
        action="store_true",
        help="Don't run build",
    )

    return parser


def main():
    args = build_parser().parse_args()
    cfg = load_config()
    apply_cli_overrides(cfg, args)

    # Validate claude is installed
    if not shutil.which("claude"):
        sys.exit(
            "claude CLI not found. Install Claude Code (https://claude.com/claude-code) "
            "and ensure it's on your PATH."
        )

    # Find and read guide
    guide_path = find_guide(args.case_number, GUIDE_DIR)
    guide_text = read_guide(guide_path)
    print(f"✓ Found guide: {guide_path}")

    # Social readiness gate: a guide can say a developer can't start alone
    # yet (needs a customer reply, a manager sign-off, ...) -- see
    # case_guide.py's "Readiness check". Stop here, before even asking for a
    # repo, rather than setting up a workspace for work that can't start. No
    # override flag -- if this fires on a case that's actually fine, fix the
    # guide (or re-run case-guide) rather than forcing case-solve past it.
    ready, reason = check_readiness(guide_text)
    if not ready:
        print("\n" + "=" * 70)
        print("NOT READY FOR IMPLEMENTATION")
        print("=" * 70)
        print(f"\nThe guide marks this case as not ready: {reason or 'no reason given'}")
        print(f"See \"## Before You Start -- Social Steps\" in {guide_path} for what to do first.")
        print("\nRe-run case-solve once that's resolved.")
        return 1

    # Resolve repo URL
    suggested_repo = extract_repo_suggestion(guide_text)
    repo_url = args.repo or prompt_for_repo(suggested_repo)
    print(f"✓ Using repo: {repo_url}")

    # Confirm before making changes
    branch_name = f"case/{args.case_number}"
    if not confirm_before_implementing(args.case_number, repo_url, branch_name):
        return 1  # User cancelled

    # Import heavy modules here (after arg parsing, config loading)
    from lib.workspace import WorkspaceManager
    from lib.implementer import Implementer
    from lib.verifier import Verifier
    from lib.committer import Committer
    from lib.report import ReportGenerator

    # Setup workspace
    workspace_mgr = WorkspaceManager(
        case_number=args.case_number,
        repo_url=repo_url,
        solves_dir=SOLVES_DIR,
    )
    workspace = workspace_mgr.setup()
    print(f"✓ Workspace ready: {workspace.repo_dir}")
    print(f"✓ Branch created: {workspace.branch_name}")

    if args.no_implement:
        print("\nBranch ready. Stopping here (--no-implement).")
        return 0

    # Implementation
    implementer = Implementer(
        workspace=workspace,
        guide_text=guide_text,
        case_number=args.case_number,
        cfg=cfg,
    )

    if args.show_plan:
        plan = implementer.generate_plan()
        print("\n" + "=" * 70)
        print("IMPLEMENTATION PLAN:")
        print("=" * 70)
        print(plan)
        return 0

    changes_summary = implementer.implement()
    print(f"✓ Implementation complete: {len(changes_summary)} logical changes")

    # Verification
    if not args.dry_run:
        verifier = Verifier(workspace=workspace, cfg=cfg)
        test_results = verifier.run_all_checks()
        print(f"✓ Verification complete: {test_results.total_checks} checks")

        # Commit
        committer = Committer(workspace=workspace)
        commits = committer.commit_changes(changes_summary)
        print(f"✓ Committed: {len(commits)} logical commits")
    else:
        test_results = None
        commits = []
        print("(dry-run: skipping verification and commits)")

    # Report
    report_gen = ReportGenerator(
        case_number=args.case_number,
        workspace=workspace,
        changes_summary=changes_summary,
        test_results=test_results,
        commits=commits,
        guide_path=guide_path,
    )

    report_path = report_gen.generate(workspace.case_dir / "VERIFICATION_CHECKLIST.md")
    print(f"\n✓ Report generated: {report_path}")

    print("\n" + "=" * 70)
    print("Next steps:")
    print(f"  1. Review changes in {workspace.repo_dir}")
    print(f"  2. Read verification checklist: {report_path}")
    print(f"  3. Run manual tests (see checklist)")
    print(f"  4. Push branch: git push -u origin {workspace.branch_name}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
