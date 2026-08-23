"""case-wizard: Streamlit desktop app for case automation."""
import os
import subprocess
import sys
from pathlib import Path

import streamlit as st

from settings import (
    load_config, save_config, clear_secrets, get_env_dict,
    KEYRING_AVAILABLE, CONFIG_FILE, DEFAULTS
)

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent


def show_config_wizard():
    """Show initial configuration wizard."""
    st.title("🧙 case-wizard Setup")

    st.markdown("""
    **First run setup.** Your secrets are stored securely:
    - 🔐 API Keys → Windows Credential Manager (encrypted in OS vault)
    - 📁 Settings → Local config file
    """)

    config = load_config()

    with st.form("config_form"):
        st.markdown("### Required Settings")

        org_url = st.text_input(
            "Azure DevOps Organization URL",
            value=config.get("azdo_org_url", ""),
            placeholder="https://dev.azure.com/yourorg",
        )

        azdo_pat = st.text_input(
            "Azure DevOps PAT",
            value=config.get("azdo_pat", ""),
            type="password",
            placeholder="Create at https://dev.azure.com/{org}/_usersSettings/tokens",
        )

        claude_key = st.text_input(
            "Claude API Key",
            value=config.get("claude_api_key", ""),
            type="password",
            placeholder="Get at https://console.anthropic.com",
        )

        st.markdown("### Optional")

        ado_project = st.text_input(
            "Azure DevOps Project",
            value=config.get("azdo_project", "") or "",
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
        config.update(DEFAULTS)
        save_config(config)
        st.session_state.config_complete = True
        st.rerun()

    return False


def show_settings_ui():
    """Show normal and advanced settings."""
    config = load_config()

    with st.expander("⚙️ Settings", expanded=False):
        # Create tabs for Normal and Advanced
        tab1, tab2 = st.tabs(["Normal", "Advanced"])

        with tab1:
            st.markdown("### Essential Settings")
            with st.form("normal_settings"):
                org_url = st.text_input(
                    "Azure DevOps Org URL",
                    value=config.get("azdo_org_url", ""),
                    help="Your Azure DevOps organization URL"
                )

                ado_project = st.text_input(
                    "Project (optional)",
                    value=config.get("azdo_project", "") or "",
                    help="Leave empty to search all projects in your org"
                )

                azdo_pat = st.text_input(
                    "ADO Personal Access Token",
                    value=config.get("azdo_pat", ""),
                    type="password",
                    help="Token with Code (Read) scope"
                )

                claude_key = st.text_input(
                    "Claude API Key",
                    value=config.get("claude_api_key", ""),
                    type="password",
                    help="API key from console.anthropic.com"
                )

                open_vscode = st.checkbox(
                    "Open results in VS Code",
                    value=config.get("open_in_vscode", True),
                    help="Automatically open output files in VS Code"
                )

                col1, col2 = st.columns(2)
                with col1:
                    if st.form_submit_button("💾 Save", use_container_width=True):
                        config.update({
                            "azdo_org_url": org_url,
                            "azdo_project": ado_project or None,
                            "azdo_pat": azdo_pat,
                            "claude_api_key": claude_key,
                            "open_in_vscode": open_vscode,
                        })
                        save_config(config)
                        st.success("✅ Settings saved!")
                        st.rerun()

                with col2:
                    if st.form_submit_button("🗑️ Clear Secrets", use_container_width=True):
                        clear_secrets()
                        st.success("✅ All secrets cleared")
                        st.session_state.config_complete = False
                        st.rerun()

        with tab2:
            st.markdown("### Performance & Behavior")
            st.caption("⚡ Defaults optimized for speed")

            with st.form("advanced_settings"):
                col1, col2 = st.columns(2)

                with col1:
                    st.markdown("**Verification**")

                    run_tests = st.checkbox(
                        "Run tests",
                        value=config.get("run_tests", False),
                        help="Run test suite after implementation (adds ~30-60 sec). OFF by default for speed."
                    )

                    run_lint = st.checkbox(
                        "Run linting",
                        value=config.get("run_lint", False),
                        help="Run linters (black, eslint, etc). OFF by default for speed."
                    )

                    run_build = st.checkbox(
                        "Run build",
                        value=config.get("run_build", False),
                        help="Run build command. OFF by default for speed."
                    )

                with col2:
                    st.markdown("**Git & Commits**")

                    auto_commit = st.checkbox(
                        "Auto-commit changes",
                        value=config.get("auto_commit", True),
                        help="Create commits automatically. ON by default (faster than manual)."
                    )

                    st.markdown("**Search & Context**")

                    skip_ado = st.checkbox(
                        "Skip Azure DevOps search",
                        value=config.get("skip_ado", False),
                        help="Skip ADO lookups (uses brief content only). OFF by default for better context."
                    )

                    max_prs = st.number_input(
                        "Max PRs per project",
                        value=config.get("max_prs", 20),
                        min_value=5,
                        max_value=100,
                        help="Fetch recent PRs for code conventions. Default: 20 (fast & useful)"
                    )

                    include_style = st.checkbox(
                        "Include style examples",
                        value=config.get("include_style_prs", True),
                        help="Include style PRs in Claude context (helps with naming conventions)"
                    )

                st.markdown("**Claude Options**")

                col1, col2 = st.columns(2)
                with col1:
                    claude_model = st.selectbox(
                        "Claude model",
                        options=[None, "opus", "sonnet"],
                        index=0 if not config.get("claude_model") else (1 if config.get("claude_model") == "opus" else 2),
                        help="Default: Claude's default (fastest). Opus: slower but more capable"
                    )

                with col2:
                    timeout = st.number_input(
                        "Claude timeout (seconds)",
                        value=config.get("claude_timeout", 600),
                        min_value=60,
                        max_value=3600,
                        help="Max time to wait for Claude response. Default: 600 (10 min)"
                    )

                if st.form_submit_button("💾 Save Advanced Settings", use_container_width=True):
                    config.update({
                        "run_tests": run_tests,
                        "run_lint": run_lint,
                        "run_build": run_build,
                        "auto_commit": auto_commit,
                        "skip_ado": skip_ado,
                        "max_prs": int(max_prs),
                        "include_style_prs": include_style,
                        "claude_model": claude_model,
                        "claude_timeout": int(timeout),
                    })
                    save_config(config)
                    st.success("✅ Advanced settings saved!")
                    st.rerun()

        # Security status
        st.divider()
        if KEYRING_AVAILABLE:
            st.info("🔐 Secrets stored in Windows Credential Manager (encrypted)")
        else:
            st.warning("⚠️ keyring module not available — secrets in plain text")


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

    # Settings button
    show_settings_ui()

    st.divider()

    # Case number input
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

    # Initialize session state
    if st.session_state.get("current_case") != case_number:
        st.session_state.current_case = case_number
        st.session_state.stage_results = {}

    st.divider()

    # Get status
    config = load_config()
    status = get_stage_status(case_number)
    env = get_env_dict(config)

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

    st.markdown(f"### Pipeline for Case `{case_number}`")

    # Checklist
    with st.container(border=True):
        completed = sum(1 for s in status.values() if s)
        total = len(status)

        col1, col2, col3 = st.columns([2, 1, 2])
        with col1:
            st.markdown("**Progress**")
        with col2:
            st.metric("", f"{completed}/{total}")
        with col3:
            if completed == total:
                st.success("✅ All complete!")
            elif completed > 0:
                st.info(f"⏳ {total - completed} remaining")
            else:
                st.warning("🚀 Ready to start")

        st.divider()

        # Stages
        for i, stage in enumerate(stages, 1):
            stage_id = stage["id"]
            is_done = status[stage_id]

            col1, col2, col3 = st.columns([0.5, 3, 2])

            with col1:
                st.markdown("✅" if is_done else f"{i}️⃣")

            with col2:
                st.markdown(f"**{stage['emoji']} {stage['name']}**")
                st.caption(stage["description"])

            with col3:
                if st.button(
                    f"▶ Run",
                    key=f"btn_{stage_id}",
                    use_container_width=True,
                    type="secondary"
                ):
                    success, output = run_stage_with_env(
                        stage_id, stage["name"], stage["cmd"], stage["cwd"], env,
                    )

                    if success:
                        st.success(f"✅ {stage['name']} complete!")
                        st.rerun()
                    else:
                        st.error(f"❌ {stage['name']} failed")
                        with st.expander("📋 Error"):
                            st.code(output, language="text")
                        st.stop()

            if i < len(stages):
                st.divider()

    # Buttons
    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        if st.button("▶ Run All Stages", type="primary", use_container_width=True):
            st.session_state.run_all = True

    with col2:
        if st.button("⏭️ Skip to Solve", use_container_width=True):
            st.session_state.run_solve_only = True

    # Run all
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
                    stage["id"], stage["name"], stage["cmd"], stage["cwd"], env,
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
                    st.error("Pipeline stopped")
                    st.session_state.run_all = False
                    st.stop()

        st.success("🎉 Full pipeline complete!")
        st.session_state.run_all = False
        st.rerun()

    # Run solve only
    if st.session_state.get("run_solve_only"):
        solve_stage = stages[2]
        st.markdown("### Running Solve Only...")
        with st.container(border=True):
            st.markdown(f"**{solve_stage['emoji']} {solve_stage['name']}**")
            status_ph = st.empty()
            progress_ph = st.progress(0.5)
            status_ph.markdown("🔄 Running...")

            success, output = run_stage_with_env(
                solve_stage["id"], solve_stage["name"],
                solve_stage["cmd"], solve_stage["cwd"], env,
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


# Main
st.set_page_config(page_title="case-wizard", page_icon="🧙", layout="wide")

if st.session_state.get("config_complete") is None:
    config = load_config()
    st.session_state.config_complete = bool(
        config.get("azdo_pat") and config.get("claude_api_key") and config.get("azdo_org_url")
    )

if not st.session_state.get("config_complete"):
    show_config_wizard()
else:
    show_main_app()
