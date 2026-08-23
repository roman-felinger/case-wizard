"""Verification: run tests, lint, build checks."""

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CheckResult:
    """Result of a single verification check."""

    name: str  # e.g., "pytest", "black", "cargo build"
    passed: bool
    output: str  # stdout/stderr
    duration_ms: int = 0


@dataclass
class VerificationResults:
    """Overall verification results."""

    checks: list = field(default_factory=list)
    total_checks: int = 0
    passed_checks: int = 0

    def add(self, result: CheckResult):
        """Add a check result."""
        self.checks.append(result)
        self.total_checks += 1
        if result.passed:
            self.passed_checks += 1

    def summary(self) -> str:
        """Generate summary text."""
        failed = [c for c in self.checks if not c.passed]
        lines = [f"Verification Results: {self.passed_checks}/{self.total_checks} passed"]
        if failed:
            lines.append("\nFailed checks:")
            for c in failed:
                lines.append(f"  ✗ {c.name}")
        return "\n".join(lines)


class Verifier:
    """Runs verification checks: tests, lint, build."""

    def __init__(self, workspace, cfg: dict):
        self.workspace = workspace
        self.cfg = cfg
        self.repo_dir = workspace.repo_dir

    def run_all_checks(self) -> VerificationResults:
        """Run all available verification checks."""
        results = VerificationResults()

        if self.cfg.get("run_tests"):
            self._run_tests(results)

        if self.cfg.get("run_build"):
            self._run_build(results)

        if self.cfg.get("run_lint"):
            self._run_lint(results)

        return results

    def _run_tests(self, results: VerificationResults) -> None:
        """Auto-detect and run tests."""
        print("\n[Verification] Running tests...")

        # Python: pytest or unittest
        if (self.repo_dir / "tests").exists() or list(
            self.repo_dir.glob("test_*.py")
        ):
            if (self.repo_dir / "pytest.ini").exists() or (
                self.repo_dir / "pyproject.toml"
            ).exists():
                self._run_check(
                    "pytest",
                    ["python", "-m", "pytest", "tests", "-v"],
                    results,
                )
            else:
                self._run_check(
                    "unittest",
                    ["python", "-m", "unittest", "discover", "-s", "tests", "-v"],
                    results,
                )

        # Node.js: npm test
        if (self.repo_dir / "package.json").exists():
            self._run_check(
                "npm test",
                ["npm", "test"],
                results,
            )

        # Rust: cargo test
        if (self.repo_dir / "Cargo.toml").exists():
            self._run_check(
                "cargo test",
                ["cargo", "test"],
                results,
            )

        # .NET: dotnet test
        if list(self.repo_dir.glob("**/*.csproj")):
            self._run_check(
                "dotnet test",
                ["dotnet", "test"],
                results,
            )

    def _run_build(self, results: VerificationResults) -> None:
        """Auto-detect and run build."""
        print("\n[Verification] Running build...")

        # Python: setup.py
        if (self.repo_dir / "setup.py").exists():
            self._run_check(
                "python setup.py build",
                ["python", "setup.py", "build"],
                results,
            )

        # Node.js: npm build
        if (self.repo_dir / "package.json").exists():
            # Check if build script exists
            try:
                result = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=self.repo_dir,
                    capture_output=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    self._run_check(
                        "npm run build",
                        ["npm", "run", "build"],
                        results,
                    )
            except subprocess.TimeoutExpired:
                pass

        # Rust: cargo build
        if (self.repo_dir / "Cargo.toml").exists():
            self._run_check(
                "cargo build",
                ["cargo", "build"],
                results,
            )

        # .NET: dotnet build
        if list(self.repo_dir.glob("**/*.csproj")):
            self._run_check(
                "dotnet build",
                ["dotnet", "build"],
                results,
            )

    def _run_lint(self, results: VerificationResults) -> None:
        """Auto-detect and run linting."""
        print("\n[Verification] Running lint checks...")

        # Python: pylint, flake8, black
        if list(self.repo_dir.glob("**/*.py")):
            # Try black (formatter check)
            self._run_check(
                "black --check",
                ["black", ".", "--check"],
                results,
                optional=True,
            )

            # Try pylint
            self._run_check(
                "pylint",
                ["python", "-m", "pylint", "*.py"],
                results,
                optional=True,
            )

        # JavaScript: eslint
        if (self.repo_dir / ".eslintrc").exists() or (
            self.repo_dir / ".eslintrc.json"
        ).exists():
            self._run_check(
                "eslint",
                ["npm", "run", "lint"],
                results,
                optional=True,
            )

        # Rust: clippy
        if (self.repo_dir / "Cargo.toml").exists():
            self._run_check(
                "cargo clippy",
                ["cargo", "clippy"],
                results,
                optional=True,
            )

    def _run_check(
        self,
        name: str,
        cmd: list,
        results: VerificationResults,
        optional: bool = False,
    ) -> None:
        """Run a single check command."""
        try:
            result = subprocess.run(
                cmd,
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )

            passed = result.returncode == 0
            output = result.stdout + result.stderr

            results.add(CheckResult(name=name, passed=passed, output=output))

            status = "✓" if passed else "✗"
            print(f"  {status} {name}")

            if not passed and not optional:
                print(f"     Output: {output[:200]}...")

        except subprocess.TimeoutExpired:
            results.add(
                CheckResult(
                    name=name,
                    passed=False,
                    output="Command timed out",
                )
            )
            print(f"  ✗ {name} (timeout)")

        except FileNotFoundError:
            # Command not available
            if not optional:
                results.add(
                    CheckResult(
                        name=name,
                        passed=False,
                        output=f"Command not found: {cmd[0]}",
                    )
                )
