"""
case-wizard: Standalone desktop app for case automation.

Just run: streamlit run main.py

That's it! No server management, no background processes.
"""

import subprocess
import sys
import threading
import time
from pathlib import Path
from datetime import datetime

import streamlit as st

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent

# Page config
st.set_page_config(
    page_title="case-wizard",
    page_icon="🧙",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main {
        padding: 2rem;
    }
    .stTabs [data-baseweb="tab-list"] button {
        font-size: 1rem;
        padding: 0.5rem 1rem;
    }
    .stage-box {
        border-radius: 0.5rem;
        padding: 1.5rem;
        margin: 1rem 0;
        border-left: 4px solid #3B82F6;
    }
    .stage-box.complete {
        border-left-color: #10B981;
    }
    .stage-box.error {
        border-left-color: #EF4444;
    }
    .stage-box.running {
        border-left-color: #F59E0B;
    }
</style>
""", unsafe_allow_html=True)

# Title
st.markdown("# 🧙 case-wizard")
st.markdown("**Three-stage automation for support cases: gather → guide → solve**")
st.markdown("---")

# Sidebar
with st.sidebar:
    st.markdown("## About")
    st.info("""
    **case-wizard** automates support case resolution:

    1. Gather case context (CRM, ADO, BC)
    2. Generate implementation guide
    3. Auto-implement with verification

    Just enter a case number and watch it happen!
    """)


# Main app layout
col1, col2 = st.columns([1, 2], gap="large")

with col1:
    st.markdown("### Start a Case")
    case_number = st.text_input(
        "Case Number",
        placeholder="T2611845",
        label_visibility="collapsed",
    ).upper().strip()

    if not case_number:
        st.info("Enter a case number (e.g., T2611845) and click Start")
        st.stop()

    col_start, col_clear = st.columns(2)
    with col_start:
        start_button = st.button("▶ Start", use_container_width=True, type="primary")
    with col_clear:
        clear_button = st.button("🔄 Clear", use_container_width=True)

    if clear_button:
        st.session_state.clear()
        st.rerun()

with col2:
    st.markdown("### Pipeline Status")

    # Initialize session state
    if "workflow_started" not in st.session_state:
        st.session_state.workflow_started = False
        st.session_state.stages = {
            "brief": {"status": "pending", "output": "", "start_time": None},
            "guide": {"status": "pending", "output": "", "start_time": None},
            "solve": {"status": "pending", "output": "", "start_time": None},
        }

    if start_button:
        st.session_state.workflow_started = True
        st.session_state.case_number = case_number
        st.session_state.start_time = datetime.now()

    if st.session_state.workflow_started:
        # Display stages
        stages_info = [
            ("brief", "📋 Gather Brief", "Gathering case context from CRM, ADO, BC..."),
            ("guide", "📖 Generate Guide", "Creating implementation walkthrough..."),
            ("solve", "⚙️ Auto-Implement", "Implementing changes and running verification..."),
        ]

        # Display status placeholders
        stage_containers = {}
        for stage_id, stage_name, stage_desc in stages_info:
            with st.container(border=True):
                col_status, col_time = st.columns([3, 1])
                with col_status:
                    st.markdown(f"#### {stage_name}")
                with col_time:
                    time_placeholder = st.empty()

                desc_placeholder = st.empty()
                progress_placeholder = st.empty()
                output_placeholder = st.empty()

                stage_containers[stage_id] = {
                    "status": "pending",
                    "desc": desc_placeholder,
                    "progress": progress_placeholder,
                    "output": output_placeholder,
                    "time": time_placeholder,
                }

        # Run the workflow in a separate thread
        def run_workflow():
            """Execute the three-stage workflow."""
            try:
                # Stage 1: case-brief
                run_stage(
                    "brief",
                    [sys.executable, "case_brief.py", case_number, "--no-open"],
                    PROJECT_ROOT / "case-brief",
                    stage_containers,
                )

                # Stage 2: case-guide
                run_stage(
                    "guide",
                    [sys.executable, "case_guide.py", case_number, "--no-open"],
                    PROJECT_ROOT / "case-guide",
                    stage_containers,
                )

                # Stage 3: case-solve
                run_stage(
                    "solve",
                    [sys.executable, "case_solve.py", case_number],
                    PROJECT_ROOT / "case-solve",
                    stage_containers,
                )

                st.session_state.workflow_complete = True

            except Exception as e:
                st.error(f"Workflow error: {e}")

        # Start workflow if not already started
        if "workflow_thread" not in st.session_state:
            st.session_state.workflow_thread = threading.Thread(
                target=run_workflow, daemon=True
            )
            st.session_state.workflow_thread.start()
            st.rerun()

        # Show completion message
        if st.session_state.get("workflow_complete"):
            st.success("✅ Workflow complete!")
            st.info(f"""
            Results saved to:
            - Brief: `case-brief/case-briefs/case-{case_number}.md`
            - Guide: `case-guide/case-guides/case-{case_number}-for-dummies.md`
            - Checklist: `case-solve/case-solves/case-{case_number}/VERIFICATION_CHECKLIST.md`
            """)


def run_stage(stage_id, command, cwd, containers):
    """Run a stage and update the UI."""
    container = containers[stage_id]

    # Update status to running
    st.session_state.stages[stage_id]["status"] = "running"
    st.session_state.stages[stage_id]["start_time"] = datetime.now()
    container["status"] = "running"

    container["desc"].markdown("🔄 Running...")
    container["progress"].progress(0.5)

    try:
        # Run the command
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode == 0:
            # Success
            st.session_state.stages[stage_id]["status"] = "complete"
            container["status"] = "complete"
            container["desc"].markdown("✅ Complete")
            container["progress"].progress(1.0)

            # Show output in expandable section
            with container["output"].expander("📋 View output"):
                st.code(result.stdout, language="text")
        else:
            # Error
            st.session_state.stages[stage_id]["status"] = "error"
            container["status"] = "error"
            container["desc"].markdown(f"❌ Error: {result.stderr[:100]}")

            with container["output"].expander("📋 View error"):
                st.code(result.stderr, language="text")

    except subprocess.TimeoutExpired:
        st.session_state.stages[stage_id]["status"] = "error"
        container["desc"].markdown("❌ Timeout")
    except Exception as e:
        st.session_state.stages[stage_id]["status"] = "error"
        container["desc"].markdown(f"❌ Error: {str(e)}")


# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #999; font-size: 0.85rem;">
    <p>case-wizard v2.0 | Standalone Desktop App</p>
    <p><a href="https://github.com/roman-felinger/case-wizard" target="_blank">GitHub</a></p>
</div>
""", unsafe_allow_html=True)
