"""Git operations: stage, commit with logical grouping."""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Commit:
    """A single git commit."""

    hash: str
    message: str
    files_changed: list  # File paths


class Committer:
    """Handles git operations and logical commit grouping."""

    def __init__(self, workspace):
        self.workspace = workspace
        self.repo_dir = workspace.repo_dir

    def commit_changes(self, changes_summary: list) -> list:
        """
        Commit changes with logical grouping.

        Groups files by type (tests, config, docs, source) and creates one commit per group.
        Returns list of Commit objects.
        """
        commits = []

        # Group changes by file category
        groups = self._group_changes(changes_summary)

        for group_name, files in groups.items():
            if not files:
                continue

            # Stage files
            for file_path in files:
                self._run_git(["add", file_path])

            # Create commit message
            message = self._build_commit_message(group_name, files)

            # Commit
            commit_hash = self._commit(message)
            commits.append(
                Commit(hash=commit_hash, message=message, files_changed=files)
            )

            print(f"  ✓ Committed {len(files)} files: {group_name}")

        return commits

    def _group_changes(self, changes: list) -> dict:
        """Group changes by file category (tests, config, docs, source, etc)."""
        groups = {
            "Tests": [],
            "Configuration": [],
            "Documentation": [],
            "Source Code": [],
            "Dependencies": [],
            "Other": [],
        }

        for change in changes:
            file_path = change["file_path"] if isinstance(change, dict) else change.file_path

            # Categorize - dependency-manifest filenames checked first since
            # they're more specific than (and would otherwise be swallowed
            # by) the generic .json/.txt extension checks below.
            if "test" in file_path.lower():
                groups["Tests"].append(file_path)
            elif any(
                file_path.endswith(f)
                for f in ["requirements.txt", "package.json", "Cargo.toml", ".csproj"]
            ):
                groups["Dependencies"].append(file_path)
            elif any(
                file_path.endswith(ext)
                for ext in [".json", ".yaml", ".yml", ".env", ".config"]
            ):
                groups["Configuration"].append(file_path)
            elif any(
                file_path.endswith(ext) for ext in [".md", ".txt", ".rst"]
            ):
                groups["Documentation"].append(file_path)
            elif any(
                file_path.endswith(ext)
                for ext in [".py", ".js", ".ts", ".rs", ".cs", ".go", ".java"]
            ):
                groups["Source Code"].append(file_path)
            else:
                groups["Other"].append(file_path)

        return groups

    def _build_commit_message(self, group_name: str, files: list) -> str:
        """Build a commit message for a group of files."""
        lines = [f"[case/{self.workspace.case_number}] {group_name}"]

        # Add file list
        lines.append("")
        for file_path in files[:5]:  # Limit to first 5
            lines.append(f"  - {file_path}")

        if len(files) > 5:
            lines.append(f"  - ... and {len(files) - 5} more")

        return "\n".join(lines)

    def _commit(self, message: str) -> str:
        """Create a commit and return the hash."""
        result = self._run_git(["commit", "-m", message], capture=True)
        # Extract hash from output: "[branch d3adb33] message"
        if result:
            for line in result.split("\n"):
                if "[" in line and "]" in line:
                    # Extract hash between brackets
                    start = line.find("[") + 1
                    end = line.find("]")
                    if start < end:
                        hash_part = line[start:end].split()
                        if len(hash_part) > 1:
                            return hash_part[1]
        return "unknown"

    def _run_git(self, args: list, capture: bool = False) -> str:
        """Run a git command in the repo directory."""
        cmd = ["git"] + args
        result = subprocess.run(
            cmd,
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            sys.exit(f"Git command failed: {' '.join(cmd)}\n{result.stderr}")

        return result.stdout if capture else ""
