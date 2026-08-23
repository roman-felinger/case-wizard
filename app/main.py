"""case-wizard: Streamlit desktop app for case automation."""
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

import streamlit as st

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent
CONFIG_FILE = HERE / ".streamlit_config.json"
SERVICE_NAME = "case-wizard"


def load_config():
    """Load configuration (secrets from keyring, settings from file)."""
    config = {}

    # Try keyring first (secure)
    if KEYRING_AVAILABLE:
        for key in ["azdo_pat", "claude_api_key"]:
            value = keyring.get_password(SERVICE_NAME, key)
            if value:
                config[key] = value

    # Load non-secret settings from file
    if CONFIG_FILE.exists():
        try:
            file_config = json.loads(CONFIG_FILE.read_text())
            # Only load non-secret settings
            for key in ["azdo_org_url", "azdo_project"]:
                if key in file_config:
                    config[key] = file_config[key]
        except:
            pass

    return config


def save_config(config):
    """Save configuration securely.

    Secrets go to OS Credential Manager (Windows), Keychain (Mac), or Secret Service (Linux).
    Non-secrets go to JSON file.
    """
    # Save secrets to keyring (secure OS storage)
    if KEYRING_AVAILABLE:
        if config.get("azdo_pat"):
            keyring.set_password(SERVICE_NAME, "azdo_pat", config["azdo_pat"])
        if config.get("claude_api_key"):
            keyring.set_password(SERVICE_NAME, "claude_api_key", config["claude_api_key"])
    else:
        # Fallback to JSON if keyring not available (not ideal)
        st.warning("⚠️ keyring not available. Secrets stored in plain text. Consider reinstalling.")

    # Save non-secret settings to JSON
    file_config = {
        "azdo_org_url": config.get("azdo_org_url"),
        "azdo_project": config.get("azdo_project"),
    }
    CONFIG_FILE.write_text(json.dumps(file_config, indent=2))


def show_config_wizard():
    """Show initial configuration wizard."""
    st.title("🧙 case-wizard Setup")

    st.markdown("""
    **First run setup.** Your secrets are stored securely:
    - 🔐 API Keys → Windows Credential Manager (encrypted in OS vault)
    - 📁 URLs → Local config file (plain text, OK)
    """)

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
            help="Create at https://dev.azure.com/{org}/_usersSettings/tokens — stored in Credential Manager"
        )

        st.markdown("### Claude")
        st.caption("Required for guide generation and implementation")

        claude_key = st.text_input(
            "Claude API Key",
            value=config.get("claude_api_key", ""),
            type="password",
            placeholder="sk-...",
            help="Get at https://console.anthropic.com — stored in Credential Manager"
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
            st.error("❌ Please fill in all required fields")
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
    """Run a stage and return success/failure."""
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
            return True, result.stdout
        else:
            return False, result.stderr
    except subprocess.TimeoutExpired:
        return False, "Timeout (600 seconds exceeded)"
    except Exception as e:
        return False, str(e)


def get_stage_status(case_num):
    """Check if output files exist for each stage."""
    brief_file = PROJECT_ROOT / "case-brief" / "case-briefs" / f"case-{case_num}.md"
    guide_file = PROJECT_ROOT / "case-guide" / "case-guides" / f"case-{case_num}-for-dummies.md"
    solve_dir = PROJECT_ROOT / "case-solve" / "case-solves" / f"case-{case_num}"

    return {
        "brief": brief_file.exists(),
        "guide": guide_file.exists(),
        "solve": solve_dir.exists(),
    }


def show_main_app():
    """Show main workflow interface."""
    st.title("🧙 case-wizard")
    st.caption("Three-stage case automation: Brief → Guide → Solve")

    # Settings button in top right
    col1, col2 = st.columns([5, 1])
    with col2:
        if st.button("⚙️", use_container_width=True, help="Edit settings"):
            st.session_state.show_settings = not st.session_state.get("show_settings", False)

    if st.session_state.get("show_settings"):
        with st.expander("Settings", expanded=True):
            config = load_config()
            with st.form("settings_form"):
                org_url = st.text_input("ADO Org URL", value=config.get("azdo_org_url", ""))
                ado_project = st.text_input("ADO Project (optional)", value=config.get("azdo_project", "") or "")
                azdo_pat = st.text_input("ADO PAT", type="password", value=config.get("azdo_pat", ""))
                claude_key = st.text_input("Claude API Key", type="password", value=config.get("claude_api_key", ""))

                col1, col2 = st.columns(2)
                with col1:
                    if st.form_submit_button("💾 Save", use_container_width=True):
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

                with col2:
                    if st.form_submit_button("🗑️ Clear All Secrets", use_container_width=True):
                        if KEYRING_AVAILABLE:
                            keyring.delete_password(SERVICE_NAME, "azdo_pat")
                            keyring.delete_password(SERVICE_NAME, "claude_api_key")
                        CONFIG_FILE.unlink(missing_ok=True)
                        st.success("✅ All secrets cleared from Credential Manager")
                        st.session_state.config_complete = False
                        st.rerun()

            st.markdown("**Security:**")
            if KEYRING_AVAILABLE:
                st.info("🔐 Secrets stored in Windows Credential Manager (encrypted in OS vault)")
            else:
                st.warning("⚠️ keyring module not available — secrets in plain text (not secure)")

        st.divider()

    # Case number input
    with st.container():
        col1, col2 = st.columns([3, 1])
        with col1:
            case_number = st.text_input(
                "Case Number",
                placeholder="T2611845",
                label_visibility="collapsed",
                key="case_input"
            ).upper().strip()
        with col2:
            if st.button("🔄 Clear", use_container_width=True):
                st.session_state.clear()
                st.rerun()

    if not case_number:
        st.info("📋 Enter a case number to start")
        st.stop()

    # Initialize session state for this case
    if st.session_state.get("current_case") != case_number:
        st.session_state.current_case = case_number
        st.session_state.stage_results = {}

    st.divider()

    # Get status of existing outputs
    status = get_stage_status(case_number)

    # Build environment
    config = load_config()
    env = os.environ.copy()
    env["AZDO_PAT"] = config.get("azdo_pat", "")
    env["CLAUDE_API_KEY"] = config.get("claude_api_key", "")
    if config.get("azdo_org_url"):
        env["AZDO_ORG_URL"] = config.get("azdo_org_url")
    if config.get("azdo_project"):
        env["AZDO_PROJECT"] = config.get("azdo_project")

    # Define stages
    stages = [
        {
            "id": "brief",
            "name": "Gather Brief",
            "emoji": "📋",
            "description": "Pull context from CRM, Azure DevOps, Business Central",
            "cmd": ["case_brief.py", case_number, "--no-open"],
            "cwd": PROJECT_ROOT / "case-brief",
        },
        {
            "id": "guide",
            "name": "Generate Guide",
            "emoji": "📖",
            "description": "Create step-by-step implementation walkthrough (Claude)",
            "cmd": ["case_guide.py", case_number, "--no-open"],
            "cwd": PROJECT_ROOT / "case-guide",
        },
        {
            "id": "solve",
            "name": "Auto-Implement",
            "emoji": "⚙️",
            "description": "Auto-apply changes, run tests, create commits",
            "cmd": ["case_solve.py", case_number],
            "cwd": PROJECT_ROOT / "case-solve",
        },
    ]

    # Show checklist header
    st.markdown(f"### Pipeline for Case `{case_number}`")

    # Checklist section
    with st.container(border=True):
        # Overall status
        completed = sum(1 for s in status.values() if s)
        total = len(status)

        col1, col2, col3 = st.columns([2, 1, 2])
        with col1:
            st.markdown("**Progress**")
        with col2:
            st.metric("", f"{completed}/{total}")
        with col3:
            if completed == total:
                st.success("✅ All stages complete!")
            elif completed > 0:
                st.info(f"⏳ {total - completed} stage(s) remaining")
            else:
                st.warning("🚀 Ready to start")

        st.divider()

        # Stages checklist with individual controls
        for i, stage in enumerate(stages, 1):
            stage_id = stage["id"]
            is_done = status[stage_id]
            is_running = st.session_state.stage_results.get(f"{stage_id}_running", False)

            # Checklist item
            col1, col2, col3 = st.columns([0.5, 3, 2])

            with col1:
                if is_done:
                    st.markdown("✅")
                elif is_running:
                    st.markdown("🔄")
                else:
                    st.markdown(f"{i}️⃣")

            with col2:
                st.markdown(f"**{stage['emoji']} {stage['name']}**")
                st.caption(stage["description"])

            with col3:
                # Run button for individual stage
                if st.button(
                    f"▶ Run {stage['name']}",
                    key=f"btn_{stage_id}",
                    use_container_width=True,
                    type="secondary" if not is_done else "secondary"
                ):
                    st.session_state.stage_results[f"{stage_id}_running"] = True
                    success, output = run_stage_with_env(
                        stage_id,
                        stage["name"],
                        stage["cmd"],
                        stage["cwd"],
                        env,
                    )

                    if success:
                        st.session_state.stage_results[stage_id] = "success"
                        st.session_state.stage_results[f"{stage_id}_running"] = False
                        st.success(f"✅ {stage['name']} complete!")
                        st.rerun()
                    else:
                        st.session_state.stage_results[stage_id] = "error"
                        st.session_state.stage_results[f"{stage_id}_running"] = False
                        st.error(f"❌ {stage['name']} failed")
                        with st.expander("📋 Error details"):
                            st.code(output, language="text")
                        st.stop()

            # Show output if it exists and is running/completed
            if st.session_state.stage_results.get(stage_id) == "success":
                with st.expander(f"ℹ️ {stage['name']} output"):
                    st.success("Stage completed successfully")
                    if st.session_state.stage_results.get(f"{stage_id}_output"):
                        st.code(st.session_state.stage_results.get(f"{stage_id}_output"), language="text")

            if i < len(stages):
                st.divider()

    # Run all button
    st.divider()
    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if st.button("▶ Run All Stages", type="primary", use_container_width=True):
            st.session_state.run_all = True

    with col2:
        if st.button("⏭️ Skip to Solve", use_container_width=True):
            st.session_state.run_solve_only = True

    # Run all pipeline if requested
    if st.session_state.get("run_all"):
        st.markdown("### Running Full Pipeline...")
        for stage in stages:
            with st.container(border=True):
                col1, col2 = st.columns([1, 4])
                with col1:
                    st.markdown(stage["emoji"])
                with col2:
                    st.markdown(f"**{stage['name']}**")

                status_ph = st.empty()
                progress_ph = st.empty()
                output_ph = st.empty()

                status_ph.markdown("🔄 Running...")
                progress_ph.progress(0.5)

                success, output = run_stage_with_env(
                    stage["id"],
                    stage["name"],
                    stage["cmd"],
                    stage["cwd"],
                    env,
                )

                if success:
                    status_ph.markdown("✅ Complete")
                    progress_ph.progress(1.0)
                    if output:
                        with output_ph.expander("📋 Output"):
                            st.code(output, language="text")
                else:
                    status_ph.markdown("❌ Error")
                    with output_ph.expander("📋 Error"):
                        st.code(output, language="text")
                    st.error("Pipeline stopped due to error")
                    st.session_state.run_all = False
                    st.stop()

        st.success("🎉 Full pipeline complete!")
        st.session_state.run_all = False
        st.rerun()

    # Run solve only if requested
    if st.session_state.get("run_solve_only"):
        solve_stage = stages[2]
        st.markdown("### Running Solve Stage Only...")
        with st.container(border=True):
            st.markdown(f"**{solve_stage['emoji']} {solve_stage['name']}**")

            status_ph = st.empty()
            progress_ph = st.progress(0.5)

            status_ph.markdown("🔄 Running...")

            success, output = run_stage_with_env(
                solve_stage["id"],
                solve_stage["name"],
                solve_stage["cmd"],
                solve_stage["cwd"],
                env,
            )

            if success:
                status_ph.markdown("✅ Complete")
                progress_ph.progress(1.0)
                st.success("Solve stage complete!")
                if output:
                    with st.expander("📋 Output"):
                        st.code(output, language="text")
            else:
                status_ph.markdown("❌ Error")
                st.error("Solve stage failed")
                with st.expander("📋 Error"):
                    st.code(output, language="text")

        st.session_state.run_solve_only = False


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
