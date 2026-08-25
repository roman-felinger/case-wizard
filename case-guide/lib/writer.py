"""Writes the generated guide to disk and optionally opens it in VS Code."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from shared.editor import open_in_editor as open_editor
from shared.safe_name import UNSAFE_CHARS, safe_name as _safe_name


def guide_filename(filename_stem):
    """The filename write_and_open would use for this stem, without
    actually writing anything -- lets a caller check whether a guide
    already exists (e.g. for skip-if-unchanged) before doing the work to
    regenerate one."""
    return f"{_safe_name(filename_stem)}.md"


def write_and_open(text, output_dir, filename_stem, open_in_vscode=True):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, guide_filename(filename_stem))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")

    if open_in_vscode:
        open_editor(path)

    return path
