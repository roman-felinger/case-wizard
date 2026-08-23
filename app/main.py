"""case-wizard: Streamlit desktop app for case automation."""
import subprocess
import sys
from pathlib import Path
from datetime import datetime

import streamlit as st

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent

st.set_page_config(page_title="case-wizard", page_icon="🧙", layout="wide")

st.title("🧙 case-wizard")
st.caption("Gather → Guide → Solve. Three stages of case automation.")

# Input
case_number = st.text_input(
    "Case Number", placeholder="T2611845", label_visibility="collapsed"
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

# Initialize state
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
    case_num = st.session_state.case_number

    # Display stages
    stages = [
        ("brief", "📋 Gather Brief", ["case_brief.py", case_num, "--no-open"]),
        ("guide", "📖 Generate Guide", ["case_guide.py", case_num, "--no-open"]),
        ("solve", "⚙️ Auto-Implement", ["case_solve.py", case_num]),
    ]

    containers = {}
    for stage_id, stage_name, _ in stages:
        with st.container(border=True):
            st.subheader(stage_name)
            containers[stage_id] = {
                "status": st.empty(),
                "progress": st.empty(),
                "output": st.empty(),
            }

    # Run workflow
    if "workflow_thread" not in st.session_state:
        def run_workflow():
            try:
                stage_dirs = {
                    "brief": PROJECT_ROOT / "case-brief",
                    "guide": PROJECT_ROOT / "case-guide",
                    "solve": PROJECT_ROOT / "case-solve",
                }

                for stage_id, stage_name, cmd_args in stages:
                    container = containers[stage_id]
                    container["status"].markdown("🔄 Running...")
                    container["progress"].progress(0.5)

                    result = subprocess.run(
                        [sys.executable] + cmd_args,
                        cwd=stage_dirs[stage_id],
                        capture_output=True,
                        text=True,
                        timeout=600,
                    )

                    if result.returncode == 0:
                        container["status"].markdown("✅ Complete")
                        container["progress"].progress(1.0)
                        if result.stdout:
                            with container["output"].expander("📋 Output"):
                                st.code(result.stdout, language="text")
                    else:
                        container["status"].markdown("❌ Error")
                        with container["output"].expander("📋 Error"):
                            st.code(result.stderr, language="text")
                        break

                st.success("✅ Workflow complete!")
            except Exception as e:
                st.error(f"Error: {e}")

        import threading
        thread = threading.Thread(target=run_workflow, daemon=True)
        thread.start()
        st.session_state.workflow_thread = thread
        st.rerun()
