"""
case-wizard backend: Flask app that orchestrates the three automation stages.

Provides REST API endpoints for:
- Starting a case automation workflow
- Streaming live progress updates via WebSockets
- Retrieving results (guide, implementation, verification)
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from threading import Thread

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Global state for tracking active workflows
workflows = {}


class WorkflowManager:
    """Manages a single case automation workflow."""

    def __init__(self, case_number, room_id):
        self.case_number = case_number
        self.room_id = room_id
        self.status = "initializing"
        self.stages = {
            "brief": {"status": "pending", "output": "", "complete": False},
            "guide": {"status": "pending", "output": "", "complete": False},
            "solve": {"status": "pending", "output": "", "complete": False},
        }
        self.results = {}
        self.error = None
        self.start_time = datetime.now()

    def emit_update(self, stage, message, status="running"):
        """Emit a live update to the frontend."""
        self.stages[stage]["output"] += message + "\n"
        self.stages[stage]["status"] = status
        socketio.emit(
            "workflow_update",
            {
                "case_number": self.case_number,
                "stage": stage,
                "message": message,
                "status": status,
                "timestamp": datetime.now().isoformat(),
            },
            room=self.room_id,
        )

    def run_stage(self, stage_name, command, cwd=None):
        """Run a stage and stream output."""
        try:
            self.emit_update(stage_name, f"Starting {stage_name}...", "running")

            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=600,
            )

            if result.returncode == 0:
                self.emit_update(stage_name, f"✓ {stage_name} completed", "complete")
                self.stages[stage_name]["complete"] = True
                self.stages[stage_name]["output"] = result.stdout
                return True
            else:
                error_msg = f"✗ {stage_name} failed: {result.stderr}"
                self.emit_update(stage_name, error_msg, "error")
                self.error = error_msg
                return False

        except subprocess.TimeoutExpired:
            error_msg = f"✗ {stage_name} timed out"
            self.emit_update(stage_name, error_msg, "error")
            self.error = error_msg
            return False
        except Exception as e:
            error_msg = f"✗ {stage_name} error: {str(e)}"
            self.emit_update(stage_name, error_msg, "error")
            self.error = error_msg
            return False

    def run_workflow(self):
        """Execute the full three-stage workflow."""
        try:
            # Stage 1: case-brief
            brief_dir = PROJECT_ROOT / "case-brief"
            if not self.run_stage(
                "brief",
                [
                    sys.executable,
                    "case_brief.py",
                    self.case_number,
                    "--no-open",
                ],
                cwd=brief_dir,
            ):
                return

            # Stage 2: case-guide
            guide_dir = PROJECT_ROOT / "case-guide"
            if not self.run_stage(
                "guide",
                [
                    sys.executable,
                    "case_guide.py",
                    self.case_number,
                    "--no-open",
                ],
                cwd=guide_dir,
            ):
                return

            # Stage 3: case-solve
            solve_dir = PROJECT_ROOT / "case-solve"
            if not self.run_stage(
                "solve",
                [
                    sys.executable,
                    "case_solve.py",
                    self.case_number,
                    "--no-open",
                ],
                cwd=solve_dir,
            ):
                return

            # All stages complete
            self.status = "complete"
            socketio.emit(
                "workflow_complete",
                {
                    "case_number": self.case_number,
                    "duration": (datetime.now() - self.start_time).total_seconds(),
                },
                room=self.room_id,
            )

        except Exception as e:
            self.error = str(e)
            self.status = "error"
            self.emit_update("workflow", f"Workflow error: {e}", "error")


# REST API Endpoints


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})


@app.route("/api/workflow/start", methods=["POST"])
def start_workflow():
    """Start a new case automation workflow."""
    data = request.json
    case_number = data.get("case_number", "").upper().strip()

    if not case_number:
        return jsonify({"error": "case_number required"}), 400

    # Create workflow instance
    room_id = f"workflow_{case_number}_{datetime.now().timestamp()}"
    workflow = WorkflowManager(case_number, room_id)
    workflows[room_id] = workflow

    # Start workflow in background thread
    thread = Thread(target=workflow.run_workflow, daemon=True)
    thread.start()

    return jsonify(
        {
            "status": "started",
            "case_number": case_number,
            "room_id": room_id,
            "timestamp": datetime.now().isoformat(),
        }
    )


@app.route("/api/workflow/<room_id>/status", methods=["GET"])
def get_status(room_id):
    """Get current workflow status."""
    workflow = workflows.get(room_id)
    if not workflow:
        return jsonify({"error": "workflow not found"}), 404

    return jsonify(
        {
            "case_number": workflow.case_number,
            "status": workflow.status,
            "stages": workflow.stages,
            "error": workflow.error,
            "elapsed": (datetime.now() - workflow.start_time).total_seconds(),
        }
    )


@app.route("/api/results/<case_number>", methods=["GET"])
def get_results(case_number):
    """Get results for a completed case."""
    brief_file = PROJECT_ROOT / "case-brief" / "case-briefs" / f"case-{case_number}.md"
    guide_file = (
        PROJECT_ROOT
        / "case-guide"
        / "case-guides"
        / f"case-{case_number}-for-dummies.md"
    )
    checklist_file = (
        PROJECT_ROOT / "case-solve" / "case-solves" / f"case-{case_number}"
    )

    results = {
        "case_number": case_number,
        "files": {
            "brief": str(brief_file) if brief_file.exists() else None,
            "guide": str(guide_file) if guide_file.exists() else None,
            "checklist": str(checklist_file / "VERIFICATION_CHECKLIST.md")
            if checklist_file.exists()
            else None,
        },
    }

    # Read content if files exist
    if brief_file.exists():
        with open(brief_file, "r", encoding="utf-8") as f:
            results["brief_content"] = f.read()

    if guide_file.exists():
        with open(guide_file, "r", encoding="utf-8") as f:
            results["guide_content"] = f.read()

    return jsonify(results)


# WebSocket Events


@socketio.on("connect")
def handle_connect():
    """Handle client connection."""
    print(f"Client connected: {request.sid}")
    emit("response", {"data": "Connected to case-wizard"})


@socketio.on("join")
def on_join(data):
    """Join a workflow room for updates."""
    room = data.get("room_id")
    join_room(room)
    emit("response", {"data": f"Joined room {room}"})


@socketio.on("disconnect")
def handle_disconnect():
    """Handle client disconnection."""
    print(f"Client disconnected: {request.sid}")


@app.route("/", methods=["GET"])
def index():
    """Serve a simple health check page."""
    return """
    <h1>case-wizard Backend</h1>
    <p>REST API: /api/health, /api/workflow/start, /api/workflow/{room_id}/status</p>
    <p>WebSocket: ws://localhost:5000</p>
    """


if __name__ == "__main__":
    print("Starting case-wizard backend on http://localhost:5000")
    socketio.run(app, debug=True, host="0.0.0.0", port=5000)
