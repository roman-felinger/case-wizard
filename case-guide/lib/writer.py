"""Writes the generated guide to disk and optionally opens it in VS Code --
same small convention case-brief's lib/report.py uses, kept as its own tiny
copy here since this project is deliberately independent of case-brief's code."""
import os
import re
import shutil
import subprocess

# The one rule for "safe to use as a filesystem path component" this
# project relies on -- shared with case_guide.py's _sanitize_case_number
# so the same character class can't drift out of sync between the input
# side (reading a brief) and the output side (writing a guide).
UNSAFE_CHARS = re.compile(r"[^\w.-]+")


def _safe_name(text):
    return UNSAFE_CHARS.sub("_", str(text)).strip("_") or "unlabeled"


def guide_filename(filename_stem):
    """The filename write_and_open would use for this stem, without
    actually writing anything -- lets a caller check whether a guide
    already exists (e.g. for skip-if-unchanged) before doing the work to
    regenerate one."""
    return f"{_safe_name(filename_stem)}.md"


def open_editor(path):
    """Open path in VS Code if it's on PATH -- silently does nothing
    otherwise. Split out from write_and_open so a caller that decides not
    to regenerate an already-up-to-date guide can still open it."""
    # shutil.which resolves the real executable (following PATHEXT, so
    # this finds VS Code's code.cmd shim on Windows too) -- avoids needing
    # shell=True just to get PATHEXT resolution.
    code_exe = shutil.which("code")
    if code_exe:
        subprocess.run([code_exe, path], check=False)


def write_and_open(text, output_dir, filename_stem, open_in_vscode=True):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, guide_filename(filename_stem))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")

    if open_in_vscode:
        open_editor(path)

    return path
