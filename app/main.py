"""case-wizard: Streamlit desktop app for case automation."""
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

import streamlit as st

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent
CONFIG_FILE = HERE / ".streamlit_config.json"

st.set_page_config(page_title="case-wizard", page_icon="🧙", layout="wide")


def load_config():
    """Load saved configuration."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except:
            return {}
    return {}


def save_config(config):
    """Save configuration."""
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def check_env_var(key, config_key):
    """Check if env var or config has a value."""
    if os.environ.get(key):
        return True
    config = load_config()
    return bool(config.get(config_key))


def show_config_wizard():
    """Show initial configuration wizard."""
    st.title("🧙 case-wizard Setup")
    st.markdown("**First run setup.** Enter your configuration below.")

    config = load_config()

    with st.form("config_form"):
        st.markdown("### Azure DevOps")
        st.caption("Required for gathering case context")

        org_url = st.text_input(
            "Organization URL",
            value=config.get("azdo_org_url", ""),
            placeholder="https://dev.azure.com/yourorg",
            help="Your Azure DevOps org URL"
        )

        azdo_pat = st.text_input(
            "Personal Access Token (PAT)",
            value=config.get("azdo_pat", ""),
            type="password",
            placeholder="Enter your ADO PAT",
            help="Create at https://dev.azure.com/{org}/_usersSettings/tokens"
        )

        st.markdown("### Claude")
        st.caption("Required for guide generation and implementation")

        claude_key = st.text_input(
            "Claude API Key",
            value=config.get("claude_api_key", ""),
            type="password",
            placeholder="sk-...",
            help="Get at https://console.anthropic.com"
        )

        st.markdown("### Optional")

        ado_project = st.text_input(
            "Azure DevOps Project (optional)",
            value=config.get("azdo_project", ""),
            placeholder="Leave empty to search all projects",
        )

        submitted = st.form_submit_button("✅ Save & Continue", type="primary", use_container_width=True)

    if submitted:
        if not org_url or not azdo_pat or not claude_key:
            st.error("❌ Please fill in all required fields (Azure DevOps and Claude)")
            return False

        config = {
            "azdo_org_url": org_url,
            "azdo_pat": azdo_pat,
            "claude_api_key": claude_key,
            "azdo_project": ado_project or None,
        }
        save_config(config)

        # Set env vars for this session
        os.environ["AZDO_PAT"] = azdo_pat
        os.environ["CLAUDE_API_KEY"] = claude_key

        st.session_state.config_complete = True
        st.rerun()

    return False


def run_stage_with_env(stage_id, stage_name, cmd_args, cwd, env):
    """Run a stage with environment variables."""
    container = st.container(border=True)
    with container:
        col_status, col_time = st.columns([3, 1])
        with col_status:
            st.markdown(f"#### {stage_name}")

        status_ph = st.empty()
        progress_ph = st.empty()
        output_ph = st.empty()

        status_ph.markdown("🔄 Running...")
        progress_ph.progress(0.5)

        try:
            result = subprocess.run(
                [sys.executable] + cmd_args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )

            if result.returncode == 0:
                status_ph.markdown("✅ Complete")
                progress_ph.progress(1.0)
                if result.stdout:
                    with output_ph.expander("📋 Output"):
                        st.code(result.stdout, language="text")
                return True
            else:
                status_ph.markdown("❌ Error")
                with output_ph.expander("📋 Error"):
                    st.code(result.stderr, language="text")
                return False
        except subprocess.TimeoutExpired:
            status_ph.markdown("❌ Timeout")
            return False
        except Exception as e:
            status_ph.markdown(f"❌ Error: {str(e)}")
            return False


def show_main_app():
    """Show main workflow interface."""
    st.title("🧙 case-wizard")
    st.caption("Gather → Guide → Solve. Three stages of case automation.")

    # Settings button
    col1, col2 = st.columns([4, 1])
    with col2:
        if st.button("⚙️ Settings", use_container_width=True):
            st.session_state.show_settings = not st.session_state.get("show_settings", False)

    if st.session_state.get("show_settings"):
        with st.expander("Settings", expanded=True):
            config = load_config()
            with st.form("settings_form"):
                org_url = st.text_input("ADO Org URL", value=config.get("azdo_org_url", ""))
                ado_project = st.text_input("ADO Project (optional)", value=config.get("azdo_project", "") or "")
                azdo_pat = st.text_input("ADO PAT", type="password", value=config.get("azdo_pat", ""))
                claude_key = st.text_input("Claude API Key", type="password", value=config.get("claude_api_key", ""))

                if st.form_submit_button("💾 Save Settings", use_container_width=True):
                    config = {
                        "azdo_org_url": org_url,
                        "azdo_pat": azdo_pat,
                        "claude_api_key": claude_key,
                        "azdo_project": ado_project or None,
                    }
                    save_config(config)
                    os.environ["AZDO_PAT"] = azdo_pat
                    os.environ["CLAUDE_API_KEY"] = claude_key
                    st.success("✅ Settings saved!")
                    st.session_state.show_settings = False
                    st.rerun()

    # Main workflow
    with st.container():
        st.markdown("### Start a Case")
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

    if "workflow_started" not in st.session_state:
        st.session_state.workflow_started = False

    if start_button:
        st.session_state.workflow_started = True
        st.session_state.case_number = case_number
        st.session_state.start_time = datetime.now()

    if st.session_state.workflow_started:
        case_num = st.session_state.case_number
        config = load_config()

        # Build environment with config
        env = os.environ.copy()
        env["AZDO_PAT"] = config.get("azdo_pat", "")
        env["CLAUDE_API_KEY"] = config.get("claude_api_key", "")
        if config.get("azdo_org_url"):
            env["AZDO_ORG_URL"] = config.get("azdo_org_url")
        if config.get("azdo_project"):
            env["AZDO_PROJECT"] = config.get("azdo_project")

        st.markdown("### Pipeline Status")

        stages = [
            ("brief", "📋 Gather Brief", ["case_brief.py", case_num, "--no-open"]),
            ("guide", "📖 Generate Guide", ["case_guide.py", case_num, "--no-open"]),
            ("solve", "⚙️ Auto-Implement", ["case_solve.py", case_num]),
        ]

        stage_dirs = {
            "brief": PROJECT_ROOT / "case-brief",
            "guide": PROJECT_ROOT / "case-guide",
            "solve": PROJECT_ROOT / "case-solve",
        }

        if "workflow_thread" not in st.session_state:
            def run_workflow():
                try:
                    for stage_id, stage_name, cmd_args in stages:
                        success = run_stage_with_env(
                            stage_id, stage_name, cmd_args,
                            cwd=stage_dirs[stage_id],
                            env=env,
                        )
                        if not success:
                            break
                    else:
                        st.success("✅ Workflow complete!")
                except Exception as e:
                    st.error(f"Error: {e}")

            import threading
            thread = threading.Thread(target=run_workflow, daemon=True)
            thread.start()
            st.session_state.workflow_thread = thread
            st.rerun()


# Main logic
if st.session_state.get("config_complete") is None:
    config = load_config()
    if not config.get("azdo_pat") or not config.get("claude_api_key") or not config.get("azdo_org_url"):
        st.session_state.config_complete = False
    else:
        st.session_state.config_complete = True

if not st.session_state.get("config_complete"):
    show_config_wizard()
else:
    # Set env vars from config
    config = load_config()
    os.environ["AZDO_PAT"] = config.get("azdo_pat", "")
    os.environ["CLAUDE_API_KEY"] = config.get("claude_api_key", "")
    if config.get("azdo_org_url"):
        os.environ["AZDO_ORG_URL"] = config.get("azdo_org_url")
    if config.get("azdo_project"):
        os.environ["AZDO_PROJECT"] = config.get("azdo_project")

    show_main_app()
