"""Report generation: verification checklist, summary."""

import subprocess
import sys
from datetime import datetime
from pathlib import Path


class ReportGenerator:
    """Generates verification checklist and summary report."""

    def __init__(
        self,
        case_number: str,
        workspace,
        changes_summary: list,
        test_results,
        commits: list,
        guide_path: Path,
    ):
        self.case_number = case_number
        self.workspace = workspace
        self.changes_summary = changes_summary
        self.test_results = test_results
        self.commits = commits
        self.guide_path = guide_path

    def generate(self, output_path: Path) -> Path:
        """Generate report and write to file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        report = self._build_report()

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

        return output_path

    def _build_report(self) -> str:
        """Build the full report markdown."""
        lines = [
            f"# Case {self.case_number} - Implementation Summary",
            "",
            f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
        ]

        # Overview
        lines.extend(self._section_overview())

        # Changes made
        lines.extend(self._section_changes())

        # Verification results
        if self.test_results:
            lines.extend(self._section_verification())

        # Commits
        lines.extend(self._section_commits())

        # Manual verification checklist
        lines.extend(self._section_checklist())

        # Next steps
        lines.extend(self._section_next_steps())

        return "\n".join(lines)

    def _section_overview(self) -> list:
        """Overview section."""
        lines = [
            "## Overview",
            "",
            f"- **Case Number**: {self.case_number}",
            f"- **Repository**: {self.workspace.repo_url}",
            f"- **Branch**: `{self.workspace.branch_name}`",
            f"- **Working Directory**: {self.workspace.repo_dir}",
            f"- **Changes Made**: {len(self.changes_summary)}",
            f"- **Commits**: {len(self.commits)}",
            "",
        ]
        return lines

    def _section_changes(self) -> list:
        """Changes made section."""
        lines = [
            "## Changes Made",
            "",
        ]

        if not self.changes_summary:
            lines.append("No changes recorded.")
            lines.append("")
            return lines

        for i, change in enumerate(self.changes_summary, 1):
            file_path = (
                change["file_path"]
                if isinstance(change, dict)
                else change.file_path
            )
            description = (
                change.get("description", "")
                if isinstance(change, dict)
                else change.description
            )
            diff = (
                change.get("diff", "")
                if isinstance(change, dict)
                else getattr(change, "diff", "")
            )

            lines.append(f"### Change {i}: {file_path}")
            lines.append("")
            if description:
                lines.append(f"**Description**: {description}")
                lines.append("")

            # Show diff if available - real callers pass Change dataclass
            # instances (lib/implementer.py), not dicts, so this must not
            # be gated on isinstance(change, dict) or it never fires.
            if diff:
                lines.append("```diff")
                lines.append(diff[:500])  # Limit diff display
                if len(diff) > 500:
                    lines.append("... (truncated)")
                lines.append("```")
            lines.append("")

        return lines

    def _section_verification(self) -> list:
        """Verification results section."""
        lines = [
            "## Verification Results",
            "",
        ]

        if not self.test_results:
            lines.append("No verification results available.")
            lines.append("")
            return lines

        results = self.test_results
        total = results.total_checks
        passed = results.passed_checks
        failed = total - passed

        lines.append(f"**Summary**: {passed}/{total} checks passed")
        lines.append("")

        if failed > 0:
            lines.append("### ⚠️ Failed Checks")
            lines.append("")
            for check in results.checks:
                if not check.passed:
                    lines.append(f"**{check.name}**")
                    lines.append("")
                    if check.output:
                        lines.append("```")
                        lines.append(check.output[:300])
                        if len(check.output) > 300:
                            lines.append("... (truncated)")
                        lines.append("```")
                    lines.append("")
        else:
            lines.append("✅ **All checks passed!**")
            lines.append("")

        # Individual check results
        lines.append("### Check Details")
        lines.append("")
        for check in results.checks:
            status = "✅" if check.passed else "❌"
            lines.append(f"- {status} {check.name}")
        lines.append("")

        return lines

    def _section_commits(self) -> list:
        """Commits section."""
        lines = [
            "## Commits Created",
            "",
        ]

        if not self.commits:
            lines.append("No commits created (check --dry-run or review status).")
            lines.append("")
            return lines

        for commit in self.commits:
            lines.append(f"### {commit.hash[:7]}")
            lines.append("")
            lines.append(f"```")
            lines.append(commit.message)
            lines.append("```")
            lines.append("")
            lines.append(f"Files: {', '.join(commit.files_changed[:3])}")
            if len(commit.files_changed) > 3:
                lines.append(f"        ... and {len(commit.files_changed) - 3} more")
            lines.append("")

        return lines

    def _section_checklist(self) -> list:
        """Manual verification checklist."""
        lines = [
            "## Manual Verification Checklist",
            "",
            "Before merging this branch, please verify:",
            "",
            "### Local Testing",
            "- [ ] Run the full test suite locally",
            "- [ ] Test the primary feature/fix manually",
            "- [ ] Check for edge cases mentioned in the guide",
            "- [ ] Verify no regressions in related functionality",
            "",
            "### Code Review",
            "- [ ] Review all changes in the commit list above",
            "- [ ] Check for unintended modifications",
            "- [ ] Ensure code style matches project conventions",
            "- [ ] Verify error handling and logging",
            "",
            "### Integration",
            "- [ ] Build passes locally (`npm build`, `cargo build`, etc)",
            "- [ ] All linting checks pass",
            "- [ ] All tests pass",
            "- [ ] No conflicts with `main` or target branch",
            "",
            "### Documentation",
            "- [ ] Updated relevant docs/comments",
            "- [ ] Changelog entry added (if applicable)",
            "- [ ] API changes documented (if applicable)",
            "",
            "### Deployment Readiness",
            "- [ ] Configuration changes reviewed",
            "- [ ] Database migrations tested (if applicable)",
            "- [ ] No secrets or credentials committed",
            "- [ ] All environment variables documented",
            "",
        ]
        return lines

    def _section_next_steps(self) -> list:
        """Next steps section."""
        branch = self.workspace.branch_name
        repo_dir = self.workspace.repo_dir

        lines = [
            "## Next Steps",
            "",
            "### 1. Review Changes",
            f"```bash",
            f"cd {repo_dir}",
            f"git log {branch}..origin/main --oneline",
            f"git diff origin/main..{branch}",
            f"```",
            "",
            "### 2. Run Manual Tests",
            "See the checklist above for what to verify.",
            "",
            "### 3. Push and Create PR",
            f"```bash",
            f"cd {repo_dir}",
            f"git push -u origin {branch}",
            f"# Then open a pull request on GitHub/Azure DevOps",
            f"```",
            "",
            "### 4. Reference Case in PR",
            f"Include case number `{self.case_number}` in the PR title or description",
            "so reviewers can reference the original case guide.",
            "",
            "---",
            "",
            f"**Original Guide**: {self.guide_path}",
            "",
        ]
        return lines
