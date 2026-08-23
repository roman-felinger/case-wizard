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
                org_url = st.text_input(
                    "Azure DevOps Org URL",
                    value=config.get("azdo_org_url", ""),
                )

                azdo_pat = st.text_input(
                    "ADO PAT",
                    value=config.get("azdo_pat", ""),
                    type="password",
                )

                open_vscode = st.checkbox(
                    "Open results in VS Code",
                    value=config.get("open_in_vscode", True),
                )

                col1, col2 = st.columns(2)
                with col1:
                    if st.form_submit_button("💾 Save"):
                        config.update({
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
    st.caption("Keep a browser tab open with Dynamics 365 CRM (logged in)")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🔗 Open CRM", use_container_width=True, key="open_crm_btn"):
            import webbrowser
            webbrowser.open("https://apps.dynamics.com")
            st.success("✓ Opening Dynamics 365 in your browser... Log in and keep the tab open")
    with col2:
        st.caption(" ")
    with col3:
        crm_ready_check = st.checkbox(
            "✅ Logged in to CRM",
            value=False,
            key="crm_checkbox",
            help="Check this after opening CRM and signing in"
        )

    st.divider()

    # Configuration form for ADO and other settings
    with st.form("config_form"):
        # Store CRM status from checkbox
        crm_ready = st.session_state.get("crm_checkbox", False)

        # Azure DevOps Section
        st.markdown("#### 🔑 Azure DevOps Access")
        st.caption("Your organization URL and personal access token")

        org_url = st.text_input(
            "Organization URL",
            value=config.get("azdo_org_url", ""),
            placeholder="https://dev.azure.com/myorg",
            key="org_url_input",
            help="Your Azure DevOps organization (e.g., https://dev.azure.com/contoso)"
        )

        col1, col2 = st.columns([3, 1])
        with col1:
            azdo_pat = st.text_input(
                "Personal Access Token (PAT)",
                value=config.get("azdo_pat", ""),
                type="password",
                key="pat_input",
                placeholder="Paste your PAT here",
                help="Token with Code (Read) and Project and Team (Read) scopes. Never share!"
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

        st.divider()

        # Show warnings that need attention
        if warnings:
            st.markdown("#### ⚠️ Warnings")
            for check_name, message in warnings:
                st.markdown(f"- **{check_name}:** {message}")

        st.divider()

        # Submit buttons
        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button(
                "✅ Complete Setup",
                type="primary",
                use_container_width=True
            )
        with col2:
            st.button("❌ Exit Setup", disabled=True, use_container_width=True)

        # Process form submission
        if submit:
            errors = []

            if not org_url:
                errors.append("Azure DevOps Organization URL is required")
            if not azdo_pat:
                errors.append("Personal Access Token is required")
            if not st.session_state.get("crm_checkbox", False):
                errors.append("Please confirm you have Dynamics 365 CRM tab open and logged in")

            if errors:
                st.error("**Please fix these before continuing:**\n" + "\n".join(f"- {e}" for e in errors))
            else:
                # Save configuration
                new_config = dict(DEFAULTS)
                new_config["azdo_org_url"] = org_url
                new_config["azdo_pat"] = azdo_pat
                save_config(new_config)

                st.success("✅ Setup complete! Restarting app...")
                st.session_state.config_complete = True
                import time
                time.sleep(1)
                st.rerun()

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

if st.session_state.get("config_complete") is None:
    config = load_config()
    st.session_state.config_complete = bool(
        config.get("azdo_pat") and config.get("azdo_org_url")
    )  # Project auto-detected from context

if not st.session_state.get("config_complete"):
    show_config_wizard()
else:
    show_main_app()
