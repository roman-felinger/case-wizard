"""Open a file in VS Code if it's on PATH -- silently does nothing
otherwise. Shared by case-brief/case-guide/case-solve's "open the result"
step, which all do exactly this."""
import shutil
import subprocess


def open_in_editor(path):
    # shutil.which resolves the real executable (following PATHEXT, so this
    # finds VS Code's code.cmd shim on Windows too) -- avoids needing
    # shell=True just to get PATHEXT resolution.
    code_exe = shutil.which("code")
    if code_exe:
        subprocess.run([code_exe, str(path)], check=False)
