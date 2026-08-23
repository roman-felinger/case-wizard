"""
Progress reporting for long-running operations (case-brief, case-guide, case-solve).

Streams progress messages as operations run, showing:
- Current agent/operation name
- What it's doing (current step)
- Overall progress
- Status indicators (📍 running, ✅ done, ❌ failed)
"""

import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, List

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


def log_progress(agent: str, operation: str, status: str, detail: str = "", progress_pct: int = None):
    """Emit a progress message."""
    msg = ProgressMessage(
        timestamp=datetime.now().isoformat(),
        agent=agent,
        operation=operation,
        status=status,
        detail=detail,
        progress_pct=progress_pct,
    )
    return msg


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

    def summary(self) -> dict:
        """Get a summary of all progress messages."""
        return {
            "agent": self.agent_name,
            "operation": self.operation_name,
            "messages": [asdict(m) for m in self.messages],
            "success": self.current_status == "success",
            "error": self.current_status == "error",
        }


def stream_subprocess_output(
    cmd: List[str],
    cwd: Path,
    agent_name: str,
    env: dict = None,
    timeout: int = 600,
) -> Iterator[str]:
    """
    Run a subprocess and stream its output as progress.

    Expects subprocess to output JSON progress objects, one per line:
    {"operation": "...", "status": "running|success|error", "detail": "..."}

    Falls back to printing raw lines if not JSON.
    """
    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )

        with st.spinner(f"⏳ {agent_name} running..."):
            for line in iter(process.stdout.readline, ""):
                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                # Try to parse as JSON progress message
                try:
                    data = json.loads(line)
                    if all(k in data for k in ["operation", "status"]):
                        yield json.dumps(data)
                    else:
                        yield json.dumps({
                            "operation": "Output",
                            "status": "info",
                            "detail": line,
                        })
                except json.JSONDecodeError:
                    # Not JSON, treat as raw output
                    yield json.dumps({
                        "operation": "Output",
                        "status": "info",
                        "detail": line,
                    })

        returncode = process.wait(timeout=timeout)
        if returncode != 0:
            yield json.dumps({
                "operation": f"{agent_name} completed",
                "status": "error",
                "detail": f"Exit code {returncode}",
            })

    except subprocess.TimeoutExpired:
        process.kill()
        yield json.dumps({
            "operation": f"{agent_name} timeout",
            "status": "error",
            "detail": f"Killed after {timeout}s",
        })
    except Exception as e:
        yield json.dumps({
            "operation": f"{agent_name} error",
            "status": "error",
            "detail": str(e),
        })


def show_progress_stream(messages: Iterator[str], max_lines: int = 100):
    """
    Display a stream of progress messages in real-time.

    Each line should be JSON: {"operation": "...", "status": "...", "detail": "..."}
    """
    container = st.container(border=True)
    message_list = []

    with container:
        progress_placeholder = st.empty()
        detail_placeholder = st.empty()

        for i, msg_json in enumerate(messages):
            if i >= max_lines:
                break

            try:
                msg_data = json.loads(msg_json)
            except json.JSONDecodeError:
                msg_data = {"operation": "Output", "status": "info", "detail": msg_json}

            message_list.append(msg_data)

            # Update display
            with progress_placeholder.container():
                for msg in message_list[-10:]:  # Show last 10
                    status_emoji = {
                        "running": "📍",
                        "success": "✅",
                        "error": "❌",
                        "warning": "⚠️",
                        "info": "ℹ️",
                    }.get(msg.get("status", "info"), "ℹ️")

                    operation = msg.get("operation", "")
                    detail = msg.get("detail", "")
                    progress = msg.get("progress_pct")

                    line = f"{status_emoji} {operation}"
                    if detail:
                        line += f"\n   {detail}"
                    if progress is not None:
                        line += f" — {progress}%"

                    st.markdown(line)

    return message_list


def agent_available(agent_name: str) -> bool:
    """Check if a Claude agent is available."""
    try:
        result = subprocess.run(
            ["claude", "agent", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return agent_name in result.stdout
    except Exception:
        return False


def get_available_agents() -> list:
    """List all available Claude agents."""
    try:
        result = subprocess.run(
            ["claude", "agent", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Parse agent names from output
        agents = []
        for line in result.stdout.split("\n"):
            if line.strip() and not line.startswith("Available"):
                agents.append(line.strip())
        return agents
    except Exception:
        return []
