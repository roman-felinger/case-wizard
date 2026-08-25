"""Progress reporting for case_brief.py: plain, human-readable status lines
to stdout, one per phase -- e.g. "Loading demo data..." then "OK Loaded".

Used to be a JSON-lines protocol case-wizard's Streamlit app parsed
line-by-line to drive a live progress display; that app is gone
(case-wizard is CLI-only now), so this just prints readable text, the same
way case-guide/case-solve's plain print() calls already do.
"""


def progress(operation: str, status: str = "running", detail: str = ""):
    """Emit one progress update."""
    prefix = {"success": "✓ ", "error": "✗ "}.get(status, "")
    line = f"{prefix}{operation}"
    if detail:
        line += f" -- {detail}"
    print(line, flush=True)


def progress_success(operation: str, detail: str = ""):
    """Shortcut for progress(..., status="success")."""
    progress(operation, "success", detail)


def progress_error(operation: str, detail: str = ""):
    """Shortcut for progress(..., status="error")."""
    progress(operation, "error", detail)


class Phase:
    """
    Optional context-manager form: reports "running" on entry and
    "success"/"error" automatically on exit, based on whether the block
    raised.

        with Phase("Loading demo data"):
            ...

    is equivalent to:

        progress("Loading demo data...", status="running")
        ...
        progress_success("Loading demo data")
    """

    def __init__(self, operation: str, detail: str = ""):
        self.operation = operation
        self.detail = detail

    def __enter__(self):
        progress(f"{self.operation}...", "running", self.detail)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            progress_success(self.operation)
        else:
            progress_error(self.operation, str(exc_val))
        return False  # never suppress the exception
