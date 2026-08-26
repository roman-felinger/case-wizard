"""Unit tests for lib/workspace.py: dependency-manager auto-detection
(pip/npm/dotnet/cargo based on marker files actually present in the repo),
branch-name construction and the "delete stale local branch, then create
fresh" flow, clone-vs-fetch repo setup, and the subprocess wrapper helpers.

No real git/pip/npm/cargo processes are ever run -- subprocess.run is always
mocked. Real filesystem access is limited to tempfile.TemporaryDirectory
(used only to make marker files like requirements.txt/package.json "exist"
for the .exists() checks that drive auto-detection).

Special focus: `_run_cmd` and `_get_current_branch` were given explicit
`encoding="utf-8", errors="replace"` this session because Windows' default
console/pipe codepage crashes decoding Unicode that pip/npm/cargo/git
commonly emit (progress glyphs, checkmarks). Several tests here assert the
exact kwargs passed to the mocked subprocess.run as a regression lock so
that fix can't silently regress.

Deliberately not covered: real dependency installation succeeding/failing
against an actual project, and interactions between multiple simultaneous
dependency managers in one repo beyond checking each detection is
independent and additive.

Run with: python -m unittest discover -s tests -v   (from case-solve/)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.workspace import WorkspaceManager


def _completed(returncode=0, stdout="", stderr=""):
    result = mock.Mock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class RunCmdEncodingTests(unittest.TestCase):
    """Regression lock for the Windows-codepage encoding fix."""

    def test_run_cmd_passes_utf8_encoding_and_replace_errors(self):
        with mock.patch("lib.workspace.subprocess.run", return_value=_completed()) as run:
            WorkspaceManager._run_cmd(["git", "status"], cwd=Path("/repo"))
        _, kwargs = run.call_args
        self.assertEqual(kwargs.get("encoding"), "utf-8")
        self.assertEqual(kwargs.get("errors"), "replace")
        self.assertTrue(kwargs.get("capture_output"))
        self.assertTrue(kwargs.get("text"))

    def test_get_current_branch_passes_utf8_encoding_and_replace_errors(self):
        with mock.patch(
            "lib.workspace.subprocess.run", return_value=_completed(stdout="main\n")
        ) as run:
            branch = WorkspaceManager._get_current_branch(Path("/repo"))
        self.assertEqual(branch, "main")
        _, kwargs = run.call_args
        self.assertEqual(kwargs.get("encoding"), "utf-8")
        self.assertEqual(kwargs.get("errors"), "replace")
        self.assertEqual(kwargs.get("check"), True)


class RunCmdCheckBehaviorTests(unittest.TestCase):
    def test_check_true_exits_on_nonzero_returncode(self):
        with mock.patch(
            "lib.workspace.subprocess.run",
            return_value=_completed(returncode=1, stderr="boom"),
        ):
            with self.assertRaises(SystemExit) as ctx:
                WorkspaceManager._run_cmd(["git", "clone", "x"], check=True)
        self.assertIn("boom", str(ctx.exception))

    def test_check_false_swallows_nonzero_returncode(self):
        with mock.patch(
            "lib.workspace.subprocess.run",
            return_value=_completed(returncode=1, stderr="not found, ok"),
        ):
            result = WorkspaceManager._run_cmd(["git", "branch", "-D", "x"], check=False)
        self.assertEqual(result.returncode, 1)  # no exception raised

    def test_check_true_does_not_exit_on_success(self):
        with mock.patch(
            "lib.workspace.subprocess.run", return_value=_completed(returncode=0)
        ):
            result = WorkspaceManager._run_cmd(["git", "fetch"])
        self.assertEqual(result.returncode, 0)


class SetupRepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.solves_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_clones_when_repo_not_yet_cached(self):
        mgr = WorkspaceManager("T1", "https://github.com/acme/widgets.git", self.solves_dir)
        with mock.patch.object(WorkspaceManager, "_run_cmd") as run_cmd:
            repo_dir = mgr._setup_repo()
        run_cmd.assert_called_once()
        cmd = run_cmd.call_args[0][0]
        self.assertEqual(cmd, ["git", "clone", "https://github.com/acme/widgets.git", str(repo_dir)])
        self.assertEqual(repo_dir.name, "widgets")

    def test_fetches_instead_of_cloning_when_repo_already_cached(self):
        mgr = WorkspaceManager("T1", "https://github.com/acme/widgets.git", self.solves_dir)
        cached = self.solves_dir / "repos" / "widgets"
        cached.mkdir(parents=True)
        with mock.patch.object(WorkspaceManager, "_run_cmd") as run_cmd:
            mgr._setup_repo()
        run_cmd.assert_called_once()
        cmd, kwargs = run_cmd.call_args[0], run_cmd.call_args[1]
        self.assertEqual(run_cmd.call_args[0][0], ["git", "fetch"])
        self.assertEqual(run_cmd.call_args[1]["cwd"], cached)


class CreateBranchTests(unittest.TestCase):
    def setUp(self):
        self.mgr = WorkspaceManager("T2611845", "https://x/repo.git", Path("/solves"))

    def test_branch_name_uses_case_number(self):
        with mock.patch.object(self.mgr, "_get_current_branch", return_value="case/T2611845"):
            with mock.patch.object(self.mgr, "_run_cmd") as run_cmd:
                branch = self.mgr._create_branch(Path("/repo"))
        self.assertEqual(branch, "case/T2611845")
        run_cmd.assert_not_called()  # already on the target branch, nothing to do

    def test_deletes_stale_local_branch_before_recreating(self):
        with mock.patch.object(self.mgr, "_get_current_branch", return_value="main"):
            with mock.patch.object(self.mgr, "_run_cmd") as run_cmd:
                self.mgr._create_branch(Path("/repo"))
        first_call, second_call = run_cmd.call_args_list
        self.assertEqual(first_call[0][0], ["git", "branch", "-D", "case/T2611845"])
        self.assertEqual(first_call[1].get("check"), False)  # OK if branch doesn't exist
        self.assertEqual(second_call[0][0], ["git", "checkout", "-b", "case/T2611845"])


class InstallDependenciesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.tmp.name)
        self.mgr = WorkspaceManager("T1", "https://x/repo.git", Path("/solves"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_markers_present_runs_nothing(self):
        with mock.patch.object(self.mgr, "_run_cmd") as run_cmd:
            self.mgr._install_dependencies(self.repo_dir)
        run_cmd.assert_not_called()

    def test_requirements_txt_triggers_venv_creation_and_pip_install(self):
        (self.repo_dir / "requirements.txt").write_text("requests\n")
        with mock.patch.object(self.mgr, "_run_cmd") as run_cmd:
            self.mgr._install_dependencies(self.repo_dir)
        commands = [c[0][0] for c in run_cmd.call_args_list]
        self.assertTrue(any(cmd[:3] == ["python", "-m", "venv"] for cmd in commands))
        self.assertTrue(
            any("pip" in cmd and "install" in cmd and "-r" in cmd for cmd in commands)
        )

    def test_requirements_txt_skips_venv_creation_when_venv_already_exists(self):
        (self.repo_dir / "requirements.txt").write_text("requests\n")
        (self.repo_dir / ".venv").mkdir()
        with mock.patch.object(self.mgr, "_run_cmd") as run_cmd:
            self.mgr._install_dependencies(self.repo_dir)
        commands = [c[0][0] for c in run_cmd.call_args_list]
        self.assertFalse(any(cmd[:3] == ["python", "-m", "venv"] for cmd in commands))
        # pip install still happens even though venv creation was skipped
        self.assertTrue(any("install" in cmd for cmd in commands))

    def test_package_json_triggers_npm_install_only(self):
        (self.repo_dir / "package.json").write_text("{}")
        with mock.patch.object(self.mgr, "_run_cmd") as run_cmd:
            self.mgr._install_dependencies(self.repo_dir)
        commands = [c[0][0] for c in run_cmd.call_args_list]
        self.assertIn(["npm", "install"], commands)
        self.assertEqual(len(commands), 1)

    def test_csproj_triggers_dotnet_restore(self):
        (self.repo_dir / "src").mkdir()
        (self.repo_dir / "src" / "App.csproj").write_text("<Project/>")
        with mock.patch.object(self.mgr, "_run_cmd") as run_cmd:
            self.mgr._install_dependencies(self.repo_dir)
        commands = [c[0][0] for c in run_cmd.call_args_list]
        self.assertIn(["dotnet", "restore"], commands)

    def test_packages_config_also_triggers_dotnet_restore(self):
        (self.repo_dir / "packages.config").write_text("<packages/>")
        with mock.patch.object(self.mgr, "_run_cmd") as run_cmd:
            self.mgr._install_dependencies(self.repo_dir)
        commands = [c[0][0] for c in run_cmd.call_args_list]
        self.assertIn(["dotnet", "restore"], commands)

    def test_cargo_toml_triggers_cargo_build(self):
        (self.repo_dir / "Cargo.toml").write_text("[package]\n")
        with mock.patch.object(self.mgr, "_run_cmd") as run_cmd:
            self.mgr._install_dependencies(self.repo_dir)
        commands = [c[0][0] for c in run_cmd.call_args_list]
        self.assertIn(["cargo", "build"], commands)

    def test_multiple_markers_trigger_multiple_independent_installs(self):
        (self.repo_dir / "requirements.txt").write_text("requests\n")
        (self.repo_dir / "package.json").write_text("{}")
        (self.repo_dir / ".venv").mkdir()  # skip venv creation to simplify assertion
        with mock.patch.object(self.mgr, "_run_cmd") as run_cmd:
            self.mgr._install_dependencies(self.repo_dir)
        commands = [c[0][0] for c in run_cmd.call_args_list]
        self.assertIn(["npm", "install"], commands)
        self.assertTrue(any("pip" in cmd for cmd in commands))


if __name__ == "__main__":
    unittest.main()
