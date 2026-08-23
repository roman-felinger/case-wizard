"""
Progress reporting for subprocesses.

Scripts (case-brief, case-guide, case-solve) can emit JSON progress messages
that the main app displays in real-time.

Usage:
    from lib.progress import progress, progress_error, progress_success

    progress("Extracting case context from CRM...", status="running")
    # ... do work ...
    progress_success("Case context extracted", detail="Case T2611845: Login timeout")

    progress_error("Azure DevOps lookup failed", detail="Check PAT token and org URL")
"""

import json
import sys
from typing import Optional


def progress(
    operation: str,
    status: str = "running",
    detail: str = "",
    progress_pct: Optional[int] = None,
):
    """Emit a progress message as JSON."""
    msg = {
        "operation": operation,
        "status": status,
        "detail": detail,
    }
    if progress_pct is not None:
        msg["progress_pct"] = progress_pct

    print(json.dumps(msg), file=sys.stdout)
    sys.stdout.flush()


def progress_success(operation: str, detail: str = ""):
    """Report successful completion."""
    progress(operation, status="success", detail=detail)


def progress_error(operation: str, detail: str = ""):
    """Report an error."""
    progress(operation, status="error", detail=detail)


def progress_warning(operation: str, detail: str = ""):
    """Report a warning."""
    progress(operation, status="warning", detail=detail)


# Context manager for phases
class Phase:
    """Context manager for reporting on a phase of work."""

    def __init__(self, name: str, detail: str = ""):
        self.name = name
        self.detail = detail

    def __enter__(self):
        progress(self.name, status="running", detail=self.detail)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            progress(self.name, status="error", detail=f"{exc_type.__name__}: {exc_val}")
            return False
        progress(self.name, status="success", detail=self.detail)
        return True


# Simple print function that doesn't break JSON parsing
def log(message: str):
    """Print a message safely (not JSON)."""
    # Prefix with "!" so app ignores it
    print(f"! {message}")
