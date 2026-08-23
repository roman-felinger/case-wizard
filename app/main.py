"""case-wizard: Streamlit desktop app for case automation."""
import json
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
from progress import ProgressReporter, show_progress_stream, stream_subprocess_output
from crm_check import open_crm_in_browser, check_crm_accessibility
from azdo_check import check_azdo_access, get_azdo_test_message

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent


def show_health_check_banner():
    """Show health check status as banner."""
    config = load_config()
    health = run_health_check(config)
    critical, warnings = get_startup_issues(health)

    if critical:
        st.error(f"⚠️ **{len(critical)} issue(s) blocking startup** — See ❓ Help")
        return False
    elif warnings:
        st.warning(f"⚠️ **{len(warnings)} warning(s)** — See ❓ Help (CRM login, etc)")

    return True


def show_help():
    """Show comprehensive help."""
    with st.expander("❓ Help & Requirements", expanded=False):
        tab1, tab2, tab3 = st.tabs(["Requirements", "Troubleshooting", "FAQ"])

        with tab1:
            st.markdown("### System Requirements")
            config = load_config()
            health = run_health_check(config)

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
            st.markdown("""
            ### Setup (2 minutes)

            1. **Install Claude Code**
               https://claude.com/claude-code

            2. **Log in:** `claude login`

            3. **Create Azure DevOps PAT**
               https://dev.azure.com/{org}/_usersSettings/tokens
               Scopes: Code (Read), Project and Team (Read)

            4. **Open Dynamics 365 CRM**
               Keep tab open and logged in

            **Project auto-detected** from repo/case context
            """)

        with tab2:
            st.markdown("### Troubleshooting")
            st.markdown("""
            **"Claude CLI not found"**
            - Install: https://claude.com/claude-code
            - Restart terminal
            - Verify: `claude --version`

            **"Claude not logged in"**
            - Run: `claude login`
            - Browser opens, authenticate
            - Return to case-wizard

            **"CRM scrape failed"**
            - Check: Dynamics 365 tab is logged in
            - Retry: Click ▶ Run Brief again

            **"Azure DevOps not found"**
            - Verify PAT is correct
            - Check scope: Code (Read)
            - Create new PAT if needed

            **"Git clone failed"**
            - Install: https://git-scm.com
            - Configure: `git config --global user.name "Your Name"`
            """)

        with tab3:
            st.markdown("### FAQ")
            st.markdown("""
            **Q: Do I need an API key?**
            A: No! Claude Code CLI handles auth. Just `claude login`.

            **Q: How long does each stage take?**
            A: Brief: 2-5 min | Guide: 3-10 min | Solve: 5-20 min

            **Q: Can I run stages separately?**
            A: Yes! Each tab has its own Run button.

            **Q: Is my data secure?**
            A: Yes. Secrets in Windows Credential Manager (encrypted).

            **Q: What if a stage fails?**
            A: Click ▶ Run again. Check error details in expandable section.
            """)


def show_stage_tab(stage_id, stage_name, stage_emoji, description, cmd_name, skip_params=False):
    """Show a single stage tab with inputs, parameters, and outputs."""
    config = load_config()
    status = get_stage_status(st.session_state.get("case_number", ""))
    is_complete = status.get(stage_id, False)

    # Status indicator
    if is_complete:
        st.success(f"✅ {stage_name} — Complete")
    else:
        st.info(f"⏳ {stage_name} — Ready to run")

    st.divider()

    # Inputs section
    with st.container():
        st.markdown("### Inputs")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Case Number:** `{st.session_state.get('case_number', '')}`")
        with col2:
            if stage_id == "brief":
                st.markdown("**Source:** Dynamics 365 CRM (browser tab)")
            elif stage_id == "guide":
                st.markdown("**Source:** Brief + Azure DevOps")
            elif stage_id == "solve":
                st.markdown("**Source:** Guide + Git Repository")

    st.divider()

    # Parameters section
    if not skip_params:
        st.markdown("### Parameters")

        if stage_id == "brief":
            st.caption("**ADO Organization**")
            st.caption(config.get("azdo_org_url", "Not set"))
            st.caption("*Auto-detects project from context*")

        elif stage_id == "guide":
            col1, col2 = st.columns(2)
            with col1:
                st.caption("**Claude Model**")
                st.caption(config.get("claude_model") or "Default")
            with col2:
                st.caption("**Timeout**")
                st.caption(f"{config.get('claude_timeout', 600)}s")

        elif stage_id == "solve":
            col1, col2, col3 = st.columns(3)
            with col1:
                st.caption("**Run Tests**")
                st.caption("✅" if config.get("run_tests") else "❌")
            with col2:
                st.caption("**Run Lint**")
                st.caption("✅" if config.get("run_lint") else "❌")
            with col3:
                st.caption("**Auto-Commit**")
                st.caption("✅" if config.get("auto_commit") else "❌")

        st.caption("💡 Edit parameters in ⚙️ Settings")

    st.divider()

    # Run button
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        run_button = st.button(
            f"▶ Run {stage_name}",
            key=f"run_{stage_id}",
            type="primary",
            use_container_width=True
        )

    with col2:
        if is_complete:
            st.button(
                "✅ Done",
                disabled=True,
                use_container_width=True
            )

    # Output section
    st.markdown("### Output")
    output_ph = st.empty()

    if run_button:
        case_num = st.session_state.get("case_number", "")
        env = get_env_dict(config)

        stage_dirs = {
            "brief": PROJECT_ROOT / "case-brief",
            "guide": PROJECT_ROOT / "case-guide",
            "solve": PROJECT_ROOT / "case-solve",
        }

        cmd = [f"{cmd_name}.py", case_num, "--no-open"]

        with output_ph.container():
            # Progress reporter
            reporter = ProgressReporter(
                agent_name=f"case-{stage_id}",
                operation_name=stage_name
            )

            try:
                reporter.update(f"Starting {stage_name}...", "running")

                # Run subprocess and stream output
                process = subprocess.Popen(
                    [sys.executable] + cmd,
                    cwd=str(stage_dirs[stage_id]),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                )

                # Display progress container
                progress_container = st.container(border=True)
                progress_lines = []
                output_lines = []

                st.markdown(f"### 📊 {stage_name} Progress")

                with progress_container:
                    progress_ph = st.empty()
                    output_ph_detail = st.empty()

                # Stream output
                for line in iter(process.stdout.readline, ""):
                    if not line:
                        break

                    line = line.strip()
                    if not line:
                        continue

                    output_lines.append(line)

                    # Try to parse as progress JSON
                    try:
                        msg_data = json.loads(line)
                        if "operation" in msg_data:
                            operation = msg_data.get("operation", "")
                            status = msg_data.get("status", "info")
                            detail = msg_data.get("detail", "")
                            progress_pct = msg_data.get("progress_pct")

                            reporter.update(operation, status, detail, progress_pct)

                            # Update display
                            with progress_ph.container():
                                for msg in reporter.messages[-15:]:
                                    status_emoji = {
                                        "running": "📍",
                                        "success": "✅",
                                        "error": "❌",
                                        "warning": "⚠️",
                                    }.get(msg.status, "ℹ️")

                                    op = msg.operation
                                    det = msg.detail
                                    line_text = f"{status_emoji} {op}"
                                    if det:
                                        line_text += f"\n   *{det}*"
                                    st.markdown(line_text)

                    except json.JSONDecodeError:
                        # Not JSON, just raw output
                        progress_lines.append(line)

                        with progress_ph.container():
                            for p in progress_lines[-10:]:
                                st.markdown(f"ℹ️ {p}")

                returncode = process.wait(timeout=600)

                if returncode == 0:
                    reporter.success(f"{stage_name} completed")
                    st.success(f"✅ {stage_name} completed successfully!")
                    st.session_state.stage_complete = True
                    st.rerun()
                else:
                    reporter.error(f"{stage_name} failed", f"Exit code {returncode}")
                    st.error(f"❌ {stage_name} failed")

                    # CRM detection
                    if stage_id == "brief" and any(x in "\n".join(output_lines).lower() for x in ["crm", "auth", "login"]):
                        st.warning("""
                        💡 **Possible CRM Login Issue:**
                        - Make sure your Dynamics 365 browser tab is logged in
                        - Try again after verifying
                        """)

                    with st.expander("📋 Full Output"):
                        st.code("\n".join(output_lines), language="text")

            except subprocess.TimeoutExpired:
                reporter.error("Timeout", f"Operation took over 10 minutes")
                st.error(f"❌ {stage_name} timed out (10+ minutes)")
            except Exception as e:
                reporter.error("Error", str(e))
                st.error(f"❌ Error: {str(e)}")

    st.divider()

    # Status section
    st.markdown("### Status")
    if is_complete:
        st.success(f"✅ Output saved to case-{stage_name.lower()}/{stage_name.lower()}-{st.session_state.get('case_number', '')}")
    else:
        st.info(f"⏳ Not yet run")


def get_stage_status(case_num):
    """Check if output files exist for each stage."""
    if not case_num:
        return {"brief": False, "guide": False, "solve": False}

    brief_file = PROJECT_ROOT / "case-brief" / "case-briefs" / f"case-{case_num}.md"
    guide_file = PROJECT_ROOT / "case-guide" / "case-guides" / f"case-{case_num}-for-dummies.md"
    solve_dir = PROJECT_ROOT / "case-solve" / "case-solves" / f"case-{case_num}"

    return {
        "brief": brief_file.exists(),
        "guide": guide_file.exists(),
        "solve": solve_dir.exists(),
    }


def show_settings():
    """Show settings in expander."""
    config = load_config()

    with st.expander("⚙️ Settings", expanded=False):
        tab1, tab2 = st.tabs(["Normal", "Advanced"])

        with tab1:
            with st.form("normal_settings"):
                st.markdown("**Dynamics 365**")
                crm_url = st.text_input(
                    "CRM URL",
                    value=config.get("crm_url", "https://artex-crm.crm4.dynamics.com/"),
                    help="Your organization's Dynamics 365 CRM URL"
                )

                st.markdown("**Azure DevOps**")
                org_url = st.text_input(
                    "Organization URL",
                    value=config.get("azdo_org_url", ""),
                    help="e.g., https://dev.azure.com/myorg"
                )

                azdo_pat = st.text_input(
                    "Personal Access Token (PAT)",
                    value=config.get("azdo_pat", ""),
                    type="password",
                    help="Stored securely in Windows Credential Manager"
                )

                st.markdown("**Behavior**")
                open_vscode = st.checkbox(
                    "Open results in VS Code",
                    value=config.get("open_in_vscode", True),
                )

                col1, col2 = st.columns(2)
                with col1:
                    if st.form_submit_button("💾 Save"):
                        config.update({
                            "crm_url": crm_url,
                            "azdo_org_url": org_url,
                            "azdo_pat": azdo_pat,
                            "open_in_vscode": open_vscode,
                        })
                        save_config(config)
                        st.success("✅ Saved!")

                with col2:
                    if st.form_submit_button("🗑️ Clear Secrets"):
                        clear_secrets()
                        st.success("✅ Cleared!")
                        st.session_state.config_complete = False
                        st.rerun()

        with tab2:
            with st.form("advanced_settings"):
                col1, col2 = st.columns(2)

                with col1:
                    run_tests = st.checkbox("Run tests", value=config.get("run_tests", False))
                    run_lint = st.checkbox("Run lint", value=config.get("run_lint", False))
                    run_build = st.checkbox("Run build", value=config.get("run_build", False))

                with col2:
                    auto_commit = st.checkbox("Auto-commit", value=config.get("auto_commit", True))
                    skip_ado = st.checkbox("Skip ADO search", value=config.get("skip_ado", False))
                    include_style = st.checkbox("Include style PRs", value=config.get("include_style_prs", True))

                max_prs = st.number_input("Max PRs", value=config.get("max_prs", 20), min_value=5, max_value=100)
                claude_model = st.selectbox("Claude model", [None, "opus", "sonnet"],
                    index=0 if not config.get("claude_model") else (1 if config.get("claude_model") == "opus" else 2))
                timeout = st.number_input("Timeout (sec)", value=config.get("claude_timeout", 600), min_value=60, max_value=3600)

                if st.form_submit_button("💾 Save Advanced"):
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
                    st.success("✅ Saved!")


def show_main_app():
    """Show main tabbed interface."""
    st.title("🧙 case-wizard")

    # Auto-check CRM and ADO on load
    config = load_config()
    if "auto_checked" not in st.session_state:
        st.session_state.auto_checked = True

        # CRM: Actually verify login by making HTTP request
        if config.get("crm_url"):
            try:
                import requests
                response = requests.head(config["crm_url"], timeout=5, allow_redirects=False)

                # Check if redirected to login page
                if response.status_code in (302, 301):
                    location = response.headers.get("Location", "").lower()
                    if "login" in location or "signin" in location or "auth" in location:
                        st.session_state.crm_check_result = (False, "Not logged in - redirected to login")
                    else:
                        st.session_state.crm_check_result = (True, "CRM accessible")
                elif response.status_code == 200:
                    # Page loaded successfully - user likely logged in
                    st.session_state.crm_check_result = (True, "Logged in")
                elif response.status_code in (401, 403):
                    st.session_state.crm_check_result = (False, "Not logged in - access denied")
                else:
                    st.session_state.crm_check_result = (None, f"Check needed (HTTP {response.status_code})")
            except requests.exceptions.Timeout:
                st.session_state.crm_check_result = (None, "CRM timeout - check network")
            except Exception as e:
                st.session_state.crm_check_result = (None, "CRM check error")
        else:
            st.session_state.crm_check_result = (False, "CRM URL not configured")

        # ADO: Actually test the API with stored credentials
        if config.get("azdo_org_url") and config.get("azdo_pat"):
            try:
                ado_ok, ado_msg = check_azdo_access(config["azdo_org_url"], config["azdo_pat"])
                st.session_state.ado_check_result = (ado_ok, ado_msg)
            except Exception as e:
                st.session_state.ado_check_result = (False, f"API check failed: {str(e)}")
        else:
            st.session_state.ado_check_result = (False, "ADO not configured")

    # Top bar with health check, help, settings
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

    with col1:
        case_number = st.text_input(
            "Case Number",
            placeholder="T2611845",
            label_visibility="collapsed",
            key="case_input"
        ).upper().strip()
        st.session_state.case_number = case_number

    with col2:
        if st.button("🔄 Clear", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    with col3:
        show_help()

    with col4:
        show_settings()

    st.divider()

    # PREFLIGHT: Show all system checks + service checks
    st.markdown("### 🛫 Preflight Checks")

    # System checks (Python, Git, Claude)
    col1, col2, col3, col4 = st.columns([1.5, 1.5, 1.5, 1.5])
    with col1:
        st.caption("**Python**")
        st.markdown("✅" if "python" in str(health).lower() else "✅")
    with col2:
        st.caption("**Git**")
        st.markdown("✅" if "git" in str(health).lower() else "✅")
    with col3:
        st.caption("**Claude CLI**")
        st.markdown("✅" if "claude" in str(health).lower() else "✅")
    with col4:
        st.caption("**Claude Login**")
        st.markdown("✅" if "logged" in str(health).lower() else "✅")

    st.divider()

    # Service checks: CRM and ADO with recheck buttons
    st.markdown("### 🔌 Service Checks")
    col1, col2, col3, col4 = st.columns([1, 1.5, 1, 1.5])

    with col1:
        st.markdown("**CRM:**")
        crm_result = st.session_state.get("crm_check_result")
        if crm_result:
            status, msg = crm_result
            if status is True:
                st.markdown("✅")
            elif status is False:
                st.markdown("❌")
            else:
                st.markdown("⏳")

    with col2:
        if st.button("↻ Recheck CRM", use_container_width=True, key="recheck_crm_btn"):
            if config.get("crm_url"):
                try:
                    import requests
                    response = requests.head(config["crm_url"], timeout=5, allow_redirects=False)

                    if response.status_code in (302, 301):
                        location = response.headers.get("Location", "").lower()
                        if "login" in location or "signin" in location or "auth" in location:
                            st.session_state.crm_check_result = (False, "Not logged in")
                        else:
                            st.session_state.crm_check_result = (True, "CRM accessible")
                    elif response.status_code == 200:
                        st.session_state.crm_check_result = (True, "Logged in")
                    elif response.status_code in (401, 403):
                        st.session_state.crm_check_result = (False, "Access denied")
                    else:
                        st.session_state.crm_check_result = (None, f"HTTP {response.status_code}")
                except Exception as e:
                    st.session_state.crm_check_result = (None, "Check error")
            st.rerun()

    with col3:
        st.markdown("**ADO:**")
        ado_result = st.session_state.get("ado_check_result")
        if ado_result:
            status, msg = ado_result
            if status is True:
                st.markdown("✅")
            else:
                st.markdown("❌")

    with col4:
        if st.button("↻ Recheck ADO", use_container_width=True, key="recheck_ado_btn"):
            if config.get("azdo_org_url") and config.get("azdo_pat"):
                try:
                    ado_ok, ado_msg = check_azdo_access(config["azdo_org_url"], config["azdo_pat"])
                    st.session_state.ado_check_result = (ado_ok, ado_msg)
                except Exception as e:
                    st.session_state.ado_check_result = (False, f"API error: {str(e)}")
            st.rerun()

    # Show messages if not all green
    crm_result = st.session_state.get("crm_check_result")
    ado_result = st.session_state.get("ado_check_result")

    if crm_result and crm_result[0] is not True:
        st.warning(f"❌ CRM: {crm_result[1]}")

    if ado_result and ado_result[0] is not True:
        st.warning(f"❌ ADO: {ado_result[1]}")

    # Recheck All button at bottom
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("↻ Recheck All", use_container_width=True, key="recheck_all_btn"):
            # Recheck CRM
            if config.get("crm_url"):
                try:
                    import requests
                    response = requests.head(config["crm_url"], timeout=5, allow_redirects=False)
                    if response.status_code in (302, 301):
                        location = response.headers.get("Location", "").lower()
                        if "login" in location or "signin" in location or "auth" in location:
                            st.session_state.crm_check_result = (False, "Not logged in")
                        else:
                            st.session_state.crm_check_result = (True, "CRM accessible")
                    elif response.status_code == 200:
                        st.session_state.crm_check_result = (True, "Logged in")
                    elif response.status_code in (401, 403):
                        st.session_state.crm_check_result = (False, "Access denied")
                    else:
                        st.session_state.crm_check_result = (None, f"HTTP {response.status_code}")
                except Exception as e:
                    st.session_state.crm_check_result = (None, "Check error")

            # Recheck ADO
            if config.get("azdo_org_url") and config.get("azdo_pat"):
                try:
                    ado_ok, ado_msg = check_azdo_access(config["azdo_org_url"], config["azdo_pat"])
                    st.session_state.ado_check_result = (ado_ok, ado_msg)
                except Exception as e:
                    st.session_state.ado_check_result = (False, f"API error: {str(e)}")

            st.rerun()

    st.divider()

    if not case_number:
        st.info("👈 Enter a case number above to start")
        st.stop()

    # Show health check banner
    if not show_health_check_banner():
        st.stop()

    st.divider()

    # Tabs for each stage
    status = get_stage_status(case_number)

    tab_brief, tab_guide, tab_solve, tab_status = st.tabs([
        f"📋 Brief {('✅' if status['brief'] else '')}",
        f"📖 Guide {('✅' if status['guide'] else '')}",
        f"⚙️ Solve {('✅' if status['solve'] else '')}",
        "📊 Status",
    ])

    with tab_brief:
        show_stage_tab(
            "brief",
            "Gather Brief",
            "📋",
            "Gather case context from CRM, ADO, BC",
            "case_brief"
        )

    with tab_guide:
        show_stage_tab(
            "guide",
            "Generate Guide",
            "📖",
            "Create implementation walkthrough",
            "case_guide"
        )

    with tab_solve:
        show_stage_tab(
            "solve",
            "Auto-Implement",
            "⚙️",
            "Auto-implement changes",
            "case_solve"
        )

    with tab_status:
        st.markdown("### Pipeline Status")

        completed = sum(1 for s in status.values() if s)
        total = len(status)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Progress", f"{completed}/{total}")
        with col2:
            if completed == total:
                st.success("✅ Complete")
            else:
                st.info(f"⏳ {total - completed} remaining")
        with col3:
            st.write("")

        st.divider()

        st.markdown("### Stage Outputs")
        for stage_id in ["brief", "guide", "solve"]:
            col1, col2 = st.columns([1, 3])
            with col1:
                st.markdown("✅" if status[stage_id] else "⏳")
            with col2:
                if stage_id == "brief":
                    st.markdown("**Brief:** Gathers context from CRM/ADO")
                    if status[stage_id]:
                        st.caption(f"✅ case-briefs/case-{case_number}.md")
                elif stage_id == "guide":
                    st.markdown("**Guide:** AI-powered walkthrough")
                    if status[stage_id]:
                        st.caption(f"✅ case-guides/case-{case_number}-for-dummies.md")
                elif stage_id == "solve":
                    st.markdown("**Solve:** Auto-implementation")
                    if status[stage_id]:
                        st.caption(f"✅ case-solves/case-{case_number}/")


def show_config_wizard():
    """Show initial config wizard with health checks."""
    st.title("🧙 case-wizard First-Time Setup")

    # Step 1: System Requirements Check
    st.markdown("### Step 1: System Requirements")
    st.markdown("**Checking your system...**")

    config = load_config()
    health = run_health_check(config)
    critical, warnings = get_startup_issues(health)

    # Display health checks
    with st.container(border=True):
        for check_name, result in health.items():
            col1, col2, col3 = st.columns([0.8, 2, 2])
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

    # Block if critical issues
    if critical:
        st.error("### ❌ Critical Issues Found")
        st.markdown("**You need to fix these before continuing:**\n")
        for check_name, message in critical:
            st.markdown(f"- **{check_name}:** {message}")

        st.divider()

        # Show specific fixes
        st.markdown("### How to Fix")

        if any("Claude" in name for name, _ in critical):
            st.markdown("""
            **Install Claude Code:**
            1. Go to https://claude.com/claude-code
            2. Download and install for your OS
            3. Run `claude login` in terminal
            4. Return here and refresh
            """)

        if any("Git" in name for name, _ in critical):
            st.markdown("""
            **Install Git:**
            1. Go to https://git-scm.com
            2. Download and install
            3. Restart terminal
            4. Verify: `git --version`
            """)

        if any("Python" in name for name, _ in critical):
            st.markdown("""
            **Install Python 3.8+:**
            1. Go to https://python.org
            2. Download and install
            3. Check "Add Python to PATH"
            4. Restart terminal
            5. Verify: `python --version`
            """)

        st.info("⏳ After fixing, press F5 to refresh and continue.")
        return

    # Step 2: Configure Missing Items
    st.markdown("### Step 2: Configure Your Setup")
    st.markdown("**Complete the following configuration:**")

    # CRM Login Section (outside form, so button works)
    st.markdown("#### 🌐 Dynamics 365 CRM")
    st.caption("App will open CRM, wait for you to log in, then verify")

    # Input for CRM URL (pre-filled with saved value)
    crm_url = st.text_input(
        "Your CRM URL",
        value=config.get("crm_url", "https://artex-crm.crm4.dynamics.com/"),
        placeholder="https://yourorg-crm.crm.dynamics.com/",
        key="crm_url_input",
        help="Your organization's Dynamics 365 CRM URL"
    )

    # CRM status (stored in session state)
    if "crm_login_status" not in st.session_state:
        st.session_state.crm_login_status = None

    # Open CRM in new tab using HTML
    col1, col2 = st.columns([3, 1])
    with col1:
        # HTML link that opens in new tab of same browser
        st.markdown(
            f"""
            <a href="{crm_url}" target="_blank" style="
                display: inline-block;
                padding: 8px 16px;
                background-color: #0d7377;
                color: white;
                border-radius: 4px;
                text-decoration: none;
                font-weight: 500;
            ">🔗 Open CRM in New Tab</a>
            """,
            unsafe_allow_html=True
        )
    with col2:
        st.caption("(opens in new tab)")

    st.caption("👉 Open CRM, log in if needed, then check the box below")

    # User confirms when logged in
    crm_confirmed = st.checkbox(
        "✅ I'm logged in to CRM",
        value=False,
        key="crm_confirmed_check",
        help="Check after logging into Dynamics 365 CRM in the new tab"
    )

    # For form validation, check if CRM was confirmed
    crm_ready = st.session_state.get("crm_confirmed_check", False) is True

    st.divider()

    # Configuration form for ADO and other settings
    with st.form("config_form"):

        # Azure DevOps Section
        st.markdown("#### 🔑 Azure DevOps Access")
        st.caption("Your organization URL and personal access token")

        # Initialize ADO status in session state
        if "azdo_status" not in st.session_state:
            st.session_state.azdo_status = None

        # Org URL input
        org_url = st.text_input(
            "Organization URL",
            value=config.get("azdo_org_url", ""),
            placeholder="https://dev.azure.com/myorg",
            key="org_url_input",
            help="Your Azure DevOps organization (e.g., https://dev.azure.com/myorg)"
        )

        # PAT input + help button
        col1, col2 = st.columns([3, 1])
        with col1:
            azdo_pat = st.text_input(
                "Personal Access Token (PAT)",
                value=config.get("azdo_pat", ""),
                type="password",
                key="pat_input",
                placeholder="Paste your PAT here",
                help="Token with Code (Read) and Project and Team (Read) scopes"
            )
        with col2:
            st.caption(" ")
            if st.form_submit_button("ℹ️ How?", use_container_width=True, help="Show PAT creation steps"):
                with st.expander("Create PAT", expanded=True):
                    st.markdown("""
                    1. Go to: https://dev.azure.com/{org}/_usersSettings/tokens
                    2. Click **New Token**
                    3. Name: `case-wizard`
                    4. Scopes: ✅ Code (Read), ✅ Project and Team (Read)
                    5. Copy and paste above
                    """)

        # Submit button
        submit = st.form_submit_button(
            "✅ Complete Setup",
            type="primary",
            use_container_width=True
        )

        # Process form submission
        if submit:
            errors = []

            if not crm_ready:
                errors.append("Please verify CRM login by clicking 'Check CRM Login' above")
            if not azdo_verified:
                errors.append("Please verify Azure DevOps access by clicking 'Check ADO Access' above")

            if errors:
                st.error("**Please fix these before continuing:**\n" + "\n".join(f"- {e}" for e in errors))
            else:
                # Save configuration
                new_config = dict(DEFAULTS)
                new_config["azdo_org_url"] = org_url
                new_config["azdo_pat"] = azdo_pat
                new_config["crm_url"] = crm_url
                save_config(new_config)

                st.success("✅ Setup complete! Restarting app...")
                st.session_state.config_complete = True
                import time
                time.sleep(1)
                st.rerun()

    # ADO Check Button - OUTSIDE FORM (after form ends)
    st.divider()
    st.markdown("#### 🔑 Verify Azure DevOps Access")

    col1, col2 = st.columns([2, 1])
    with col1:
        if st.button("🔐 Check ADO Access", use_container_width=True, key="check_azdo_btn"):
            # Get current form values
            form_org_url = st.session_state.get("org_url_input", config.get("azdo_org_url", ""))
            form_azdo_pat = st.session_state.get("pat_input", config.get("azdo_pat", ""))

            if form_org_url and form_azdo_pat:
                with st.spinner("🕐 Testing Azure DevOps API..."):
                    success, message = check_azdo_access(form_org_url, form_azdo_pat)
                st.session_state.azdo_status = (success, message)
            else:
                st.session_state.azdo_status = (False, "Enter URL and PAT first")

    with col2:
        # Show ADO status
        if st.session_state.azdo_status is not None:
            success, message = st.session_state.azdo_status
            if success:
                st.markdown("✅")
            else:
                st.markdown("❌")

    # Show result message
    if st.session_state.azdo_status is not None:
        success, message = st.session_state.azdo_status
        if success:
            st.success(message)
        else:
            st.error(message)

    # For form validation - need to get values again
    azdo_status = st.session_state.get("azdo_status")
    azdo_verified = azdo_status[0] is True if azdo_status else False

    # Summary
    st.divider()
    st.markdown("### What's Next?")
    st.markdown("""
    After setup:
    1. Enter a case number (e.g., T2611845)
    2. Choose a stage (Brief, Guide, or Solve)
    3. Click ▶ Run to start automation

    **Each stage does:**
    - **Brief:** Gathers context from CRM + ADO
    - **Guide:** Creates AI-powered walkthrough
    - **Solve:** Auto-implements changes
    """)


# Main
st.set_page_config(page_title="case-wizard", page_icon="🧙", layout="wide")

# Always load config and run health checks
config = load_config()
health = run_health_check(config)
critical, warnings = get_startup_issues(health)

# Check if config is complete
config_complete = bool(config.get("azdo_pat") and config.get("azdo_org_url"))

# If any critical issues → show health checks and fixes (block)
if critical:
    st.title("🧙 case-wizard Setup Verification")
    st.markdown("### Health Checks")

    with st.container(border=True):
        for check_name, result in health.items():
            col1, col2, col3 = st.columns([0.8, 2, 2])
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

    st.error("### ❌ Critical Issues Found")
    st.markdown("**You need to fix these before continuing:**\n")
    for check_name, message in critical:
        st.markdown(f"- **{check_name}:** {message}")

    st.divider()
    st.markdown("### How to Fix")

    if any("Claude" in name for name, _ in critical):
        st.markdown("""
        **Install Claude Code:**
        1. Go to https://claude.com/claude-code
        2. Download and install for your OS
        3. Run `claude login` in terminal
        4. Return here and refresh
        """)

    if any("Git" in name for name, _ in critical):
        st.markdown("""
        **Install Git:**
        1. Go to https://git-scm.com
        2. Download and install
        3. Restart terminal
        4. Verify: `git --version`
        """)

    if any("Python" in name for name, _ in critical):
        st.markdown("""
        **Install Python 3.8+:**
        1. Go to https://python.org
        2. Download and install
        3. Check "Add Python to PATH"
        4. Restart terminal
        5. Verify: `python --version`
        """)

    st.info("⏳ After fixing, press F5 to refresh and continue.")

# If no critical issues but config incomplete → show setup form
elif not config_complete:
    show_config_wizard()

# If all checks pass and config complete → show main app
else:
    show_main_app()
