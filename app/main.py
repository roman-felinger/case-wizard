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
from crm_playwright import check_login_headless as check_crm_login_dom, reset_profile as reset_crm_profile
from shutdown_watcher import start_once as start_shutdown_watcher
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
                st.caption("**Run Build**")
                st.caption("✅" if config.get("run_build") else "❌")

        st.caption("💡 Edit parameters in ⚙️ Settings")

    # Solve acts on a real repo (clones it, creates a branch, commits) -
    # confirm which one *here*, in the app, instead of case_solve.py
    # blocking on an interactive terminal prompt it'll never get an
    # answer to when launched as a subprocess.
    repo_url = ""
    if stage_id == "solve":
        st.divider()
        st.markdown("### Confirm Repository")
        case_num_now = st.session_state.get("case_number", "")
        repo_key = f"repo_url_{case_num_now}" if case_num_now else "repo_url_pending"
        repo_url = st.text_input(
            "Git clone URL",
            value=st.session_state.get(repo_key, ""),
            placeholder="https://dev.azure.com/org/project/_git/repo",
            key="solve_repo_url_input",
            help="case-solve clones this, creates a case/<number> branch on it, and commits there. Nothing is pushed automatically."
        )
        st.session_state[repo_key] = repo_url
        if not repo_url:
            st.caption("⚠️ Required before running Solve - paste the repo's git clone URL")

    st.divider()

    # Run button
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        run_disabled = stage_id == "solve" and not repo_url
        run_button = st.button(
            f"▶ Run {stage_name}",
            key=f"run_{stage_id}",
            type="primary",
            use_container_width=True,
            disabled=run_disabled,
        )

    with col2:
        if is_complete:
            st.button(
                "✅ Done",
                key=f"done_{stage_id}",
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

        # Advanced Settings only actually take effect via these CLI flags -
        # each stage script reads its config from config.json + CLI args,
        # not from environment variables (get_env_dict's vars are for the
        # ADO PAT specifically, which lib/ado_api.py does read from env).
        cmd = [f"{cmd_name}.py", case_num, "--no-open"]

        if stage_id == "brief":
            if config.get("skip_ado"):
                cmd.append("--skip-ado")
            if config.get("azdo_org_url"):
                cmd += ["--org-url", config["azdo_org_url"]]
            if config.get("max_prs"):
                cmd += ["--max-prs", str(config["max_prs"])]

        elif stage_id == "guide":
            if config.get("skip_ado"):
                cmd.append("--skip-ado")
            if config.get("azdo_org_url"):
                cmd += ["--org-url", config["azdo_org_url"]]
            if config.get("claude_model"):
                cmd += ["--model", config["claude_model"]]
            if config.get("claude_timeout"):
                cmd += ["--timeout", str(config["claude_timeout"])]
            if not config.get("include_style_prs", True):
                cmd.append("--no-style-prs")

        elif stage_id == "solve":
            cmd += ["--repo", repo_url, "--yes"]
            if config.get("azdo_org_url"):
                cmd += ["--org-url", config["azdo_org_url"]]
            if not config.get("run_tests"):
                cmd.append("--skip-tests")
            if not config.get("run_lint"):
                cmd.append("--skip-lint")
            if not config.get("run_build"):
                cmd.append("--skip-build")

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

                # The outer wait must allow at least as long as the
                # configured claude call itself (case-solve alone defaults
                # to 900s for that call), plus slack for everything else
                # the stage does (clone, ADO queries, tests/lint/build).
                outer_timeout = max(600, config.get("claude_timeout", 600) + 300)
                returncode = process.wait(timeout=outer_timeout)

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
                process.kill()
                process.wait()  # reap it - don't leave a zombie/orphan behind
                reporter.error("Timeout", f"Operation took over {outer_timeout}s")
                st.error(f"❌ {stage_name} timed out after {outer_timeout}s and was stopped")
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
                    skip_ado = st.checkbox("Skip ADO search", value=config.get("skip_ado", False))
                    include_style = st.checkbox("Include style PRs", value=config.get("include_style_prs", True))

                st.caption("💡 Solve always commits its changes as it goes (never pushes) - nothing to toggle there")

                max_prs = st.number_input("Max PRs", value=config.get("max_prs", 20), min_value=5, max_value=100)
                claude_model = st.selectbox("Claude model", [None, "opus", "sonnet"],
                    index=0 if not config.get("claude_model") else (1 if config.get("claude_model") == "opus" else 2))
                timeout = st.number_input("Timeout (sec)", value=config.get("claude_timeout", 600), min_value=60, max_value=3600)

                if st.form_submit_button("💾 Save Advanced"):
                    config.update({
                        "run_tests": run_tests,
                        "run_lint": run_lint,
                        "run_build": run_build,
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

        # CRM: DOM-based check against case-wizard's own persistent
        # profile (see crm_playwright.py) - actually reflects real login
        # state, not just whether the URL is publicly reachable.
        st.session_state.crm_check_result = check_crm_login_dom(config.get("crm_url"))

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

    # PREFLIGHT: system checks (real status, not a stub) + service checks
    py_ok = health.get("Python 3.8+", {}).get("status")
    git_ok = health.get("Git", {}).get("status")
    claude_ok = health.get("Claude CLI", {}).get("status")
    claude_login_ok = health.get("Claude Logged In", {}).get("status")

    crm_result = st.session_state.get("crm_check_result")
    ado_result = st.session_state.get("ado_check_result")
    crm_ok = crm_result[0] if crm_result else None
    ado_ok = ado_result[0] if ado_result else None

    all_green = all(v is True for v in [py_ok, git_ok, claude_ok, claude_login_ok, crm_ok, ado_ok])

    def _icon(v):
        return "✅" if v is True else ("❌" if v is False else "⏳")

    if all_green:
        # Nothing needs attention - one compact line, no setup UI in sight.
        col1, col2 = st.columns([5, 1])
        with col1:
            st.success(
                f"✅ All systems ready — Python · Git · Claude · CRM · ADO"
            )
        with col2:
            if st.button("↻ Recheck", use_container_width=True, key="recheck_all_btn"):
                with st.spinner("Rechecking..."):
                    st.session_state.crm_check_result = check_crm_login_dom(config.get("crm_url"))
                    if config.get("azdo_org_url") and config.get("azdo_pat"):
                        try:
                            ado_ok2, ado_msg2 = check_azdo_access(config["azdo_org_url"], config["azdo_pat"])
                            st.session_state.ado_check_result = (ado_ok2, ado_msg2)
                        except Exception as e:
                            st.session_state.ado_check_result = (False, f"API error: {str(e)}")
                st.rerun()
    else:
        st.markdown("### 🛫 Preflight Checks")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.caption("**Python**")
            st.markdown(_icon(py_ok))
        with col2:
            st.caption("**Git**")
            st.markdown(_icon(git_ok))
        with col3:
            st.caption("**Claude CLI**")
            st.markdown(_icon(claude_ok))
        with col4:
            st.caption("**Claude Working**")
            st.markdown(_icon(claude_login_ok))

        st.divider()
        st.markdown("### 🔌 Service Checks")
        col1, col2, col3, col4 = st.columns([1, 1.5, 1, 1.5])

        with col1:
            st.markdown("**CRM:**")
            st.markdown(_icon(crm_ok))
        with col2:
            if st.button("↻ Recheck CRM", use_container_width=True, key="recheck_crm_btn"):
                with st.spinner("Checking CRM login..."):
                    st.session_state.crm_check_result = check_crm_login_dom(config.get("crm_url"))
                st.rerun()

        with col3:
            st.markdown("**ADO:**")
            st.markdown(_icon(ado_ok))
        with col4:
            if st.button("↻ Recheck ADO", use_container_width=True, key="recheck_ado_btn"):
                if config.get("azdo_org_url") and config.get("azdo_pat"):
                    try:
                        ado_ok2, ado_msg2 = check_azdo_access(config["azdo_org_url"], config["azdo_pat"])
                        st.session_state.ado_check_result = (ado_ok2, ado_msg2)
                    except Exception as e:
                        st.session_state.ado_check_result = (False, f"API error: {str(e)}")
                st.rerun()

        # Only surface controls for whatever is actually broken
        if crm_ok is not True:
            col1, col2, col3 = st.columns([2.5, 1, 1])
            with col1:
                st.warning(f"❌ CRM: {crm_result[1] if crm_result else 'Not checked yet'}")
            with col2:
                if st.button("🔑 Log in to CRM", use_container_width=True, key="crm_login_btn"):
                    # Detached background process - doesn't block Streamlit.
                    # Auto-closes itself the moment login is detected.
                    subprocess.Popen(
                        [sys.executable, str(HERE / "crm_playwright.py"), "--login", config.get("crm_url", "")],
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                    )
                    st.info("🌐 Browser window opened - log in there. It closes itself when done, then click Recheck CRM.")
            with col3:
                if st.button("♻️ Reset session", use_container_width=True, key="crm_reset_btn",
                             help="Use this if login keeps failing instantly - clears a stuck browser lock"):
                    with st.spinner("Resetting CRM session..."):
                        reset_crm_profile()
                    st.success("Reset done - try 'Log in to CRM' again.")

        if ado_ok is not True:
            st.warning(f"❌ ADO: {ado_result[1] if ado_result else 'Not checked yet'}")

        if claude_login_ok is not True:
            st.warning(f"❌ Claude: {health.get('Claude Logged In', {}).get('message', 'Not working')}")

        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("↻ Recheck All", use_container_width=True, key="recheck_all_btn"):
                with st.spinner("Rechecking..."):
                    st.session_state.crm_check_result = check_crm_login_dom(config.get("crm_url"))
                    if config.get("azdo_org_url") and config.get("azdo_pat"):
                        try:
                            ado_ok2, ado_msg2 = check_azdo_access(config["azdo_org_url"], config["azdo_pat"])
                            st.session_state.ado_check_result = (ado_ok2, ado_msg2)
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

    # What's Missing - only ever visible for the thing(s) actually
    # missing. Anything already working (CRM login, etc.) shows nothing.
    st.markdown("### ⚠️ What's Missing")

    # Reuse the result from the Step 1 health panel above (same DOM
    # check) instead of launching a second browser for the same thing.
    if "wizard_crm_result" not in st.session_state:
        crm_health = health.get("CRM Browser Tab", {})
        st.session_state.wizard_crm_result = (crm_health.get("status"), crm_health.get("message", "Not checked"))

    crm_status, crm_msg = st.session_state.wizard_crm_result
    crm_ready = crm_status is True
    crm_url = config.get("crm_url", "https://artex-crm.crm4.dynamics.com/")

    if not crm_ready:
        st.markdown("#### 🌐 Dynamics 365 CRM")
        crm_url = st.text_input(
            "Your CRM URL",
            value=crm_url,
            placeholder="https://yourorg-crm.crm.dynamics.com/",
            key="crm_url_input",
            help="Your organization's Dynamics 365 CRM URL"
        )
        st.warning(f"❌ CRM: {crm_msg}")
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            if st.button("🔑 Log in to CRM", use_container_width=True, key="wizard_crm_login_btn"):
                subprocess.Popen(
                    [sys.executable, str(HERE / "crm_playwright.py"), "--login", crm_url],
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                )
                st.info("🌐 Browser window opened - log in there, then click Recheck.")
        with col2:
            if st.button("↻ Recheck", use_container_width=True, key="wizard_crm_recheck_btn"):
                with st.spinner("Checking CRM login..."):
                    st.session_state.wizard_crm_result = check_crm_login_dom(crm_url)
                st.rerun()
        with col3:
            if st.button("♻️ Reset session", use_container_width=True, key="wizard_crm_reset_btn",
                         help="Use this if login keeps failing instantly"):
                with st.spinner("Resetting..."):
                    reset_crm_profile()
                st.success("Reset done - try 'Log in to CRM' again.")
        st.divider()

    # Azure DevOps Section - one button, does both check and save
    st.markdown("#### 🔑 Azure DevOps Access")

    azdo_status = st.session_state.get("azdo_status")
    azdo_verified = azdo_status[0] is True if azdo_status else False

    if azdo_verified:
        st.success(f"✅ ADO: {azdo_status[1]}")
    else:
        # A real st.form is the only thing that fully stops a rerun on
        # every keystroke/blur/Enter - fields inside it only commit their
        # values (and trigger one rerun) on the explicit submit click.
        with st.form("azdo_form", border=False):
            org_url = st.text_input(
                "Organization URL",
                value=config.get("azdo_org_url", ""),
                placeholder="https://dev.azure.com/myorg",
                help="Your Azure DevOps organization (e.g., https://dev.azure.com/myorg)"
            )
            azdo_pat = st.text_input(
                "Personal Access Token (PAT)",
                value=config.get("azdo_pat", ""),
                type="password",
                placeholder="Paste your PAT here",
                help=(
                    "Needs Code (Read) and Project and Team (Read) scopes.\n\n"
                    "**How to create one:**\n"
                    "1. Go to: https://dev.azure.com/{org}/_usersSettings/tokens\n"
                    "2. Click **New Token**\n"
                    "3. Name: `case-wizard`\n"
                    "4. Scopes: Code (Read), Project and Team (Read)\n"
                    "5. Copy and paste it here"
                )
            )
            submitted = st.form_submit_button("🔌 Check Connection", use_container_width=True)

        if submitted:
            if org_url and azdo_pat:
                with st.spinner("Testing Azure DevOps API..."):
                    try:
                        success, message = check_azdo_access(org_url, azdo_pat)
                    except Exception as e:
                        success, message = False, f"Check failed: {e}"
                st.session_state.azdo_status = (success, message)
                if success:
                    # Works - save immediately, no separate confirm step
                    try:
                        new_config = dict(DEFAULTS)
                        new_config["azdo_org_url"] = org_url
                        new_config["azdo_pat"] = azdo_pat
                        new_config["crm_url"] = crm_url
                        save_config(new_config)
                    except Exception as e:
                        st.session_state.azdo_status = (False, f"Connected, but failed to save: {e}")
            else:
                st.session_state.azdo_status = (False, "Enter URL and PAT first")
            st.rerun()

        if azdo_status and azdo_status[0] is not True:
            st.error(f"❌ ADO: {azdo_status[1]}")

    # Once both CRM and ADO are confirmed, there's nothing left to
    # configure - go straight to the main app, no extra "finish" click.
    if crm_ready and azdo_verified:
        st.session_state.config_complete = True
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
start_shutdown_watcher()

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
