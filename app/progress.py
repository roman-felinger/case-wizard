"""
Progress reporting for long-running operations (case-brief, case-guide, case-solve).

Streams progress messages as operations run, showing:
- Current agent/operation name
- What it's doing (current step)
- Overall progress
- Status indicators (📍 running, ✅ done, ❌ failed)
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

import streamlit as st


@dataclass
class ProgressMessage:
    """A single progress update."""
    timestamp: str
    agent: str  # e.g., "case-brief", "case-guide", "case-solver"
    operation: str  # e.g., "Extracting case context", "Running tests"
    status: str  # "running" (📍), "success" (✅), "error" (❌), "warning" (⚠️)
    detail: str  # Additional info
    progress_pct: Optional[int] = None  # 0-100, if available


def format_progress_line(msg: ProgressMessage) -> str:
    """Format a progress message for display."""
    status_emoji = {
        "running": "📍",
        "success": "✅",
        "error": "❌",
        "warning": "⚠️",
    }.get(msg.status, "ℹ️")

    line = f"{status_emoji} **{msg.operation}**"
    if msg.detail:
        line += f"\n  {msg.detail}"
    if msg.progress_pct is not None:
        line += f" ({msg.progress_pct}%)"

    return line


class ProgressReporter:
    """Tracks and displays progress for a long-running operation."""

    def __init__(self, agent_name: str, operation_name: str):
        self.agent_name = agent_name
        self.operation_name = operation_name
        self.messages: List[ProgressMessage] = []
        self.container = None
        self.current_status = None

    def start_stream(self):
        """Open a container for streaming progress."""
        self.container = st.container(border=True)
        return self

    def update(self, operation: str, status: str = "running", detail: str = "", progress_pct: int = None):
        """Report a progress update."""
        msg = ProgressMessage(
            timestamp=datetime.now().isoformat(),
            agent=self.agent_name,
            operation=operation,
            status=status,
            detail=detail,
            progress_pct=progress_pct,
        )
        self.messages.append(msg)
        self.current_status = status

        # Update display
        if self.container:
            with self.container:
                st.markdown(f"### {self.agent_name.title()}: {self.operation_name}")
                for m in self.messages:
                    st.markdown(format_progress_line(m))

        return msg

    def success(self, operation: str, detail: str = ""):
        """Report successful completion of an operation."""
        return self.update(operation, "success", detail)

    def error(self, operation: str, detail: str):
        """Report an error."""
        return self.update(operation, "error", detail)

    def warning(self, operation: str, detail: str = ""):
        """Report a warning."""
        return self.update(operation, "warning", detail)
