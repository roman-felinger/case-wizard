"""Workspace management: clone repo, create branch, install dependencies."""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Workspace:
    """Workspace context for a single case solve."""

    case_number: str
    repo_url: str
    repo_dir: Path  # The cloned repo
    case_dir: Path  # The case-solve output dir
    branch_name: str  # The feature branch name


class WorkspaceManager:
    """Manages workspace setup: cloning, branching, dependencies."""

    def __init__(self, case_number: str, repo_url: str, solves_dir: Path):
        self.case_number = case_number
        self.repo_url = repo_url
        self.solves_dir = Path(solves_dir)

    def setup(self) -> Workspace:
        """Set up workspace: clone repo, create case directory, create branch."""
        # Create case-solve directory
        case_dir = self._create_case_dir()

        # Clone or fetch repo
        repo_dir = self._setup_repo()

        # Create branch
        branch_name = self._create_branch(repo_dir)

        # Install dependencies
        self._install_dependencies(repo_dir)

        return Workspace(
            case_number=self.case_number,
            repo_url=self.repo_url,
            repo_dir=repo_dir,
            case_dir=case_dir,
            branch_name=branch_name,
        )

    def _create_case_dir(self) -> Path:
        """Create case-specific output directory."""
        case_dir = self.solves_dir / f"case-{self.case_number}"
        case_dir.mkdir(parents=True, exist_ok=True)
        return case_dir

    def _setup_repo(self) -> Path:
        """Clone repo or fetch existing clone."""
        # Determine repo name from URL
        repo_name = self.repo_url.split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        repo_dir = self.solves_dir / "repos" / repo_name
        repo_dir.parent.mkdir(parents=True, exist_ok=True)

        if repo_dir.exists():
            # Fetch latest
            print(f"  Fetching latest from {self.repo_url}...")
            self._run_cmd(["git", "fetch"], cwd=repo_dir)
        else:
            # Clone
            print(f"  Cloning {self.repo_url}...")
            self._run_cmd(["git", "clone", self.repo_url, str(repo_dir)])

        return repo_dir

    def _create_branch(self, repo_dir: Path) -> str:
        """Create feature branch, switch to it."""
        branch_name = f"case/{self.case_number}"

        # Ensure we're on main/master/develop
        current = self._get_current_branch(repo_dir)
        if current != branch_name:
            # Delete local branch if it exists (clean slate)
            self._run_cmd(
                ["git", "branch", "-D", branch_name],
                cwd=repo_dir,
                check=False,  # OK if branch doesn't exist
            )

            # Create and switch
            self._run_cmd(
                ["git", "checkout", "-b", branch_name],
                cwd=repo_dir,
            )

        return branch_name

    def _install_dependencies(self, repo_dir: Path) -> None:
        """Auto-detect and install dependencies."""
        # Python
        if (repo_dir / "requirements.txt").exists():
            print("  Found requirements.txt, installing dependencies...")
            venv = repo_dir / ".venv"
            if not venv.exists():
                self._run_cmd(
                    ["python", "-m", "venv", str(venv)],
                    cwd=repo_dir,
                )
            # Activate and install (use pip directly)
            python_exe = venv / "Scripts" / "python.exe"
            self._run_cmd(
                [str(python_exe), "-m", "pip", "install", "-r", "requirements.txt"],
                cwd=repo_dir,
            )

        # Node.js
        if (repo_dir / "package.json").exists():
            print("  Found package.json, installing dependencies...")
            self._run_cmd(["npm", "install"], cwd=repo_dir)

        # .NET
        if (repo_dir / "packages.config").exists() or list(repo_dir.glob("**/*.csproj")):
            print("  Found .csproj files, running dotnet restore...")
            self._run_cmd(["dotnet", "restore"], cwd=repo_dir)

        # Rust
        if (repo_dir / "Cargo.toml").exists():
            print("  Found Cargo.toml, running cargo build...")
            self._run_cmd(["cargo", "build"], cwd=repo_dir)

    @staticmethod
    def _get_current_branch(repo_dir: Path) -> str:
        """Get current branch name."""
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        return result.stdout.strip()

    @staticmethod
    def _run_cmd(cmd, cwd=None, check=True):
        """Run a command, exit on error if check=True."""
        # encoding="utf-8" (with errors="replace") because pip/npm/cargo
        # output commonly includes Unicode (progress glyphs, checkmarks)
        # that Windows' default console/pipe codepage can't decode.
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if check and result.returncode != 0:
            sys.exit(
                f"Command failed: {' '.join(cmd)}\n"
                f"Exit code: {result.returncode}\n"
                f"stderr: {result.stderr}"
            )
        return result
