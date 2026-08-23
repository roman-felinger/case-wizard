"""Claude-guided implementation: read guide, get steps, apply changes."""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Change:
    """A single logical change (file modification, new file, etc)."""

    file_path: str  # Relative to repo
    description: str  # What changed
    diff: str  # The diff
    content_after: str = ""  # Full file content after change


class Implementer:
    """Orchestrates Claude-guided implementation."""

    def __init__(self, workspace, guide_text: str, case_number: str, cfg: dict):
        self.workspace = workspace
        self.guide_text = guide_text
        self.case_number = case_number
        self.cfg = cfg
        self.changes = []

    def generate_plan(self) -> str:
        """Ask Claude to generate implementation plan without applying it."""
        prompt = self._build_plan_prompt()
        plan = self._call_claude(prompt)
        return plan

    def implement(self) -> list:
        """Full implementation: get plan from Claude, apply it, track changes."""
        # Step 1: Get implementation plan from Claude
        plan = self.generate_plan()
        print(f"\nImplementation plan received ({len(plan)} chars)")

        # Step 2: Get step-by-step instructions
        steps = self._get_implementation_steps(plan)

        # Step 3: Apply changes
        applied_changes = []
        for step in steps:
            change = self._apply_step(step)
            if change:
                applied_changes.append(change)
                self.changes.append(change)

        print(f"Applied {len(applied_changes)} changes across {len(set(c.file_path for c in applied_changes))} files")
        return applied_changes

    def _build_plan_prompt(self) -> str:
        """Build the prompt for Claude to generate implementation plan."""
        repo_structure = self._get_repo_structure()

        prompt = f"""You are a careful code implementer. Your task is to read a case guide and generate a detailed, step-by-step implementation plan.

CASE NUMBER: {self.case_number}

CASE GUIDE:
{self._indent(self.guide_text, 4)}

REPOSITORY STRUCTURE (first 2 levels):
{self._indent(repo_structure, 4)}

TASK:
Based on the guide above, generate a detailed implementation plan that:
1. Lists each file that needs to be created or modified
2. For each file, explains EXACTLY what changes are needed
3. Identifies the logical order to make changes (dependencies)
4. Includes steps to verify changes (tests, builds, etc)
5. Flags any external dependencies or credentials needed

Output format:
# Implementation Plan for Case {self.case_number}

## Changes Required
- File: path/to/file.ext
  - What: description of change
  - Why: why this change is needed
  - Dependencies: other files that must change first (if any)

## Verification Steps
- Step 1: ...
- Step 2: ...

## Notes
- Any warnings or gotchas
"""
        return prompt

    def _get_implementation_steps(self, plan: str) -> list:
        """Extract implementation steps from the plan."""
        # Ask Claude to convert plan into executable steps
        prompt = f"""Based on this implementation plan, generate a detailed step-by-step script of EXACT changes to make.

For each file change, output:

FILE: path/to/file
ACTION: create | modify | delete
DESCRIPTION: one line
```
<the exact code/content to write>
```

Plan:
{plan}

Generate the exact steps now, one file at a time:
"""
        response = self._call_claude(prompt)

        # Parse response into steps
        steps = self._parse_steps(response)
        return steps

    def _apply_step(self, step: dict) -> Change:
        """Apply a single implementation step to the repo."""
        file_path = step.get("file")
        action = step.get("action", "modify").lower()
        content = step.get("content", "")
        description = step.get("description", "")

        full_path = self.workspace.repo_dir / file_path

        if action == "create":
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  ✓ Created: {file_path}")

        elif action == "modify":
            if not full_path.exists():
                raise ValueError(f"File does not exist: {file_path}")
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  ✓ Modified: {file_path}")

        elif action == "delete":
            if full_path.exists():
                full_path.unlink()
            print(f"  ✓ Deleted: {file_path}")

        # Generate diff
        diff = self._get_file_diff(file_path)

        return Change(
            file_path=file_path,
            description=description,
            diff=diff,
            content_after=content,
        )

    def _get_file_diff(self, file_path: str) -> str:
        """Get git diff for a file."""
        result = subprocess.run(
            ["git", "diff", file_path],
            cwd=self.workspace.repo_dir,
            capture_output=True,
            text=True,
        )
        return result.stdout or "(new file)"

    def _get_repo_structure(self, max_depth: int = 2) -> str:
        """Get a text representation of repo structure (first N levels)."""
        lines = []

        def walk(path: Path, prefix: str = "", depth: int = 0):
            if depth > max_depth:
                return
            if path.name.startswith("."):
                return

            try:
                items = sorted(path.iterdir())
            except PermissionError:
                return

            for item in items:
                if item.name.startswith("."):
                    continue
                indent = "  " * depth
                if item.is_dir():
                    lines.append(f"{indent}{item.name}/")
                    walk(item, indent, depth + 1)
                else:
                    lines.append(f"{indent}{item.name}")

        walk(self.workspace.repo_dir)
        return "\n".join(lines[:100])  # Limit output

    def _parse_steps(self, response: str) -> list:
        """Parse Claude's step-by-step response into structured steps."""
        steps = []
        current_step = {}
        current_content = []
        in_code_block = False

        for line in response.split("\n"):
            if line.startswith("FILE:"):
                if current_step:
                    current_step["content"] = "\n".join(current_content).strip()
                    steps.append(current_step)
                current_step = {"file": line.replace("FILE:", "").strip()}
                current_content = []
                in_code_block = False

            elif line.startswith("ACTION:"):
                current_step["action"] = line.replace("ACTION:", "").strip()

            elif line.startswith("DESCRIPTION:"):
                current_step["description"] = line.replace("DESCRIPTION:", "").strip()

            elif line.strip().startswith("```"):
                in_code_block = not in_code_block

            elif in_code_block:
                current_content.append(line)

        if current_step:
            current_step["content"] = "\n".join(current_content).strip()
            steps.append(current_step)

        return [s for s in steps if s.get("file")]

    def _call_claude(self, prompt: str) -> str:
        """Call claude CLI with prompt via stdin."""
        agent_arg = []
        if self.cfg["claude"]["agent"]:
            agent_arg = ["--agent", self.cfg["claude"]["agent"]]

        model_arg = []
        if self.cfg["claude"]["model"]:
            model_arg = ["--model", self.cfg["claude"]["model"]]

        cmd = ["claude", "-p"] + model_arg + agent_arg
        cmd.extend(self.cfg["claude"]["extra_args"])

        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.cfg["claude"]["timeout"],
            )
        except subprocess.TimeoutExpired:
            sys.exit(f"Claude call timed out after {self.cfg['claude']['timeout']}s")

        if result.returncode != 0:
            sys.exit(f"Claude call failed:\n{result.stderr}")

        return result.stdout

    @staticmethod
    def _indent(text: str, spaces: int) -> str:
        """Indent text by N spaces."""
        indent = " " * spaces
        return "\n".join(indent + line for line in text.split("\n"))
