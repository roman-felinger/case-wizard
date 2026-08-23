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
from checks import run_health_check, get_startup_issues

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent


def show_help_card():
    """Show help and requirements card."""
    with st.expander("❓ Help & Requirements", expanded=False):
        tab1, tab2, tab3 = st.tabs(["Requirements", "Troubleshooting", "FAQ"])

        with tab1:
            st.markdown("### What You Need")
            st.markdown("""
            **Before running case-wizard:**

            ✅ **Claude Code CLI**
            - Install: https://claude.com/claude-code
            - Verify: `claude --version`
            - Login: `claude login`

            ✅ **Azure DevOps**
            - Create PAT: https://dev.azure.com/{org}/_usersSettings/tokens
            - Scopes: Code (Read), Project and Team (Read)
            - Org URL: https://dev.azure.com/yourorg

            ✅ **Dynamics 365 CRM**
            - Open your CRM in browser
            - Log in to your account
            - Keep tab open while running (case-brief scrapes it)

            ✅ **Git**
            - Install from https://git-scm.com
            - Configure: `git config --global user.name "Your Name"`

            **Checklist before starting:**
            - [ ] Python installed (check: `python --version`)
            - [ ] Git installed (check: `git --version`)
            - [ ] Claude CLI installed (check: `claude --version`)
            - [ ] Claude logged in (check: `claude login`)
            - [ ] CRM browser tab open and logged in
            - [ ] Azure DevOps PAT created
            """)

        with tab2:
            st.markdown("### Troubleshooting")
            st.markdown("""
            **"Claude CLI not found"**
            - Install Claude Code: https://claude.com/claude-code
            - Restart your terminal after installing
            - Verify: `claude --version`

            **"Claude not logged in"**
            - Run: `claude login`
            - Browser will open, authenticate
            - Come back to case-wizard

            **"CRM scrape failed"**
            - Make sure your Dynamics 365 tab is logged in
            - Try again (case-brief will retry automatically)
            - Check your ADO PAT has right scopes

            **"Azure DevOps not found"**
            - Verify PAT token is correct
            - Check it has Code (Read) scope
            - Try creating a new PAT

            **"Git clone failed"**
            - Verify git is installed: `git --version`
            - Configure git: `git config --global user.name "Your Name"`
            - Check internet connection

            **"Python version error"**
            - Need Python 3.8+
            - Install from https://python.org
            - Add to PATH during installation
            """)

        with tab3:
            st.markdown("### Frequently Asked")
            st.markdown("""
            **Q: Do I need a Claude API key?**
            A: No! Claude Code CLI handles authentication. Just log in with `claude login`.

            **Q: How long does each stage take?**
            A: Brief: 2-5 min | Guide: 3-10 min | Solve: 5-20 min (depends on repo)

            **Q: Can I run stages separately?**
            A: Yes! Click individual "▶ Run" buttons or use "▶ Run All Stages".

            **Q: What if a stage fails?**
            A: Click "▶ Run" again to retry, or check error details in expandable sections.

            **Q: Is my data secure?**
            A: Yes. API keys stored in Windows Credential Manager (encrypted). Nothing sent to cloud except Claude API calls.

            **Q: Can I run multiple cases?**
            A: One at a time in the UI. You can queue them in Settings (Advanced).
            """)

        st.divider()
        st.info("💡 **Tip:** Keep this help card open while learning case-wizard!")


def show_startup_health_check():
    """Show startup health check and block if critical issues."""
    config = load_config()
    health = run_health_check(config)
    critical, warnings = get_startup_issues(health)

    st.title("🧙 case-wizard Startup Check")

    # Show all checks
    with st.container(border=True):
        st.markdown("### System Requirements")

        for check_name, result in health.items():
            col1, col2, col3 = st.columns([1, 2, 2])

            with col1:
                if result["status"] is True:
                    st.markdown("✅")
                elif result["status"] is False:
                    st.markdown("❌")
                else:
                    st.markdown("⚠️")

            with col2:
                st.markdown(f"**{check_name}**")

            with col3:
                st.caption(result["message"])

    st.divider()

    # Show help if issues exist
    if critical or warnings:
        if critical:
            st.error(f"❌ **{len(critical)} critical issue(s) blocking startup:**")
            for check_name, message in critical:
                st.markdown(f"- **{check_name}:** {message}")

                # Provide specific help
                if "Claude" in check_name:
                    st.info("👉 Install Claude Code: https://claude.com/claude-code")
                elif "Git" in check_name:
                    st.info("👉 Install Git: https://git-scm.com")
                elif "ADO" in check_name or "Azure" in check_name:
                    st.info("👉 Create PAT: https://dev.azure.com/{org}/_usersSettings/tokens")

            st.markdown("### Fix Issues, Then Refresh")
            st.markdown("After fixing issues above, press **F5** or click **Rerun** to check again.")
            st.stop()

        if warnings:
            st.warning(f"⚠️ **{len(warnings)} warning(s):**")
            for check_name, message in warnings:
                st.markdown(f"- **{check_name}:** {message}")

    st.success("✅ All systems ready! Click below to continue.")

    if st.button("▶ Continue to case-wizard", type="primary", use_container_width=True):
        st.session_state.startup_check_passed = True
        st.rerun()


def show_first_time_setup():
    """Show first-time setup wizard."""
    st.title("🧙 case-wizard First-Time Setup")

    st.markdown("""
    Welcome! Let's get you set up in 3 minutes.

    ### What You'll Need
    - Azure DevOps organization and personal access token
    - (Claude Code and CRM are already checked ✅)
    """)

    with st.form("setup_wizard"):
        st.markdown("### Step 1: Azure DevOps")
        st.caption("Get your org URL from https://dev.azure.com")

        org_url = st.text_input(
            "Organization URL",
            placeholder="https://dev.azure.com/yourorg",
            help="Full URL of your Azure DevOps organization"
        )

        st.markdown("### Step 2: Personal Access Token (PAT)")
        st.caption("Create at: https://dev.azure.com/{org}/_usersSettings/tokens")

        azdo_pat = st.text_input(
            "PAT Token",
            type="password",
            placeholder="Paste your PAT here",
            help="Token with Code (Read) and Project and Team (Read) scopes"
        )

        st.markdown("### Step 3: Optional")

        ado_project = st.text_input(
            "Azure DevOps Project (optional)",
            placeholder="MyProject",
            help="Leave empty to search all projects in your org"
        )

        st.divider()

        col1, col2 = st.columns(2)
        with col1:
            submitted = st.form_submit_button("✅ Complete Setup", type="primary", use_container_width=True)
        with col2:
            st.form_submit_button("❌ Cancel", use_container_width=True, disabled=True)

    if submitted:
        if not org_url or not azdo_pat:
            st.error("Please fill in Azure DevOps org URL and PAT")
            return

        config = {
            "azdo_org_url": org_url,
            "azdo_pat": azdo_pat,
            "azdo_project": ado_project or None,
        }
        config.update(DEFAULTS)
        save_config(config)

        st.success("✅ Setup complete! Starting case-wizard...")
        st.session_state.setup_complete = True
        st.rerun()


def show_config_wizard():
    """Show initial configuration wizard."""
    st.title("🧙 case-wizard Setup")

    st.markdown("""
    **First run setup.**

    ⚠️ **You need Claude Code installed and logged in:**
    ```bash
    claude login
    ```
    Then verify: `claude --version`
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

        st.markdown("### Optional")

        ado_project = st.text_input(
            "Azure DevOps Project",
            value=config.get("azdo_project", "") or "",
            placeholder="Leave empty to search all projects",
        )

        submitted = st.form_submit_button("✅ Save & Continue", type="primary", use_container_width=True)

    if submitted:
        if not org_url or not azdo_pat:
            st.error("❌ Please fill in all required fields")
            return False

        config = {
            "azdo_org_url": org_url,
            "azdo_pat": azdo_pat,
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


def detect_crm_login_issue(output):
    """Check if output indicates CRM login issue."""
    error_indicators = [
        "no crm tab",
        "not logged in",
        "authentication",
        "unauthorized",
        "dynamics",
        "crm",
    ]
    lower_output = output.lower()
    return any(indicator in lower_output for indicator in error_indicators)


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

    # Help card at top
    show_help_card()

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

                        # Check for CRM login issue
                        if stage_id == "brief" and detect_crm_login_issue(output):
                            st.warning("""
                            💡 **Possible CRM Login Issue:**
                            - Make sure your Dynamics 365 browser tab is logged in
                            - Check you're in the right CRM instance
                            - Try again after verifying login
                            """)

                        with st.expander("📋 Error details"):
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

# Startup health check (on first load)
if st.session_state.get("startup_check_done") is None:
    st.session_state.startup_check_done = False

if not st.session_state.get("startup_check_done"):
    st.session_state.startup_check_done = True
    show_startup_health_check()

# Setup check
if st.session_state.get("setup_complete") is None:
    st.session_state.setup_complete = False

if not st.session_state.get("setup_complete"):
    config = load_config()
    if not config.get("azdo_pat") or not config.get("azdo_org_url"):
        st.session_state.setup_complete = False
    else:
        st.session_state.setup_complete = True

# Config check (old flow, kept for compatibility)
if st.session_state.get("config_complete") is None:
    config = load_config()
    st.session_state.config_complete = bool(
        config.get("azdo_pat") and config.get("azdo_org_url")
    )

# Show appropriate screen
if not st.session_state.get("setup_complete"):
    if not st.session_state.get("config_complete"):
        show_config_wizard()
    else:
        st.session_state.setup_complete = True
        st.rerun()
else:
    show_main_app()
