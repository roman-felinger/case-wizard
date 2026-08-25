"""
Progress reporting for case_brief.py.

Prints one JSON line per update to stdout: {"operation", "status", "detail"}.
The Streamlit app (app/main.py's run_button block) reads this subprocess's
stdout line-by-line and parses each line as JSON to drive the live progress
display. Anything not valid JSON is shown as raw output instead, so plain
prints still work - this just makes the structured, per-step version
case-wizard expects.
"""
import json
import sys


def progress(operation: str, status: str = "running", detail: str = ""):
    """Emit one progress update."""
    print(json.dumps({
        "operation": operation,
        "status": status,
        "detail": detail,
    }), flush=True)


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
