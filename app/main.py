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
            ### Setup Instructions

            **Install Claude Code**
            ```
            https://claude.com/claude-code
            ```

            **Log in to Claude**
            ```bash
            claude login
            ```

            **Create Azure DevOps PAT**
            - Go: https://dev.azure.com/{org}/_usersSettings/tokens
            - Scopes: Code (Read), Project and Team (Read)

            **Open CRM Browser Tab**
            - Log in to Dynamics 365
            - Keep tab open while running
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
            col1, col2 = st.columns(2)
            with col1:
                st.caption("**ADO Organization**")
                st.caption(config.get("azdo_org_url", "Not set"))
            with col2:
                st.caption("**ADO Project**")
                st.caption(config.get("azdo_project", "All projects"))

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
        if stage_id != "solve":
            cmd = [f"{cmd_name}.py", case_num, "--no-open"]

        with output_ph.container():
            with st.spinner(f"⏳ Running {stage_name}..."):
                try:
                    result = subprocess.run(
                        [sys.executable] + cmd,
                        cwd=stage_dirs[stage_id],
                        capture_output=True,
                        text=True,
                        timeout=600,
                        env=env,
                    )

                    if result.returncode == 0:
                        st.success(f"✅ {stage_name} completed successfully!")
                        if result.stdout:
                            with st.expander("📋 Output Details"):
                                st.code(result.stdout, language="text")
                        st.session_state.stage_complete = True
                        st.rerun()
                    else:
                        st.error(f"❌ {stage_name} failed")

                        # CRM detection
                        if stage_id == "brief" and any(x in result.stderr.lower() for x in ["crm", "auth", "login"]):
                            st.warning("""
                            💡 **Possible CRM Login Issue:**
                            - Make sure your Dynamics 365 browser tab is logged in
                            - Try again after verifying
                            """)

                        with st.expander("📋 Error Details"):
                            st.code(result.stderr, language="text")

                except subprocess.TimeoutExpired:
                    st.error(f"❌ {stage_name} timed out (10+ minutes)")
                except Exception as e:
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

                ado_project = st.text_input(
                    "Project (optional)",
                    value=config.get("azdo_project", "") or "",
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
                            "azdo_project": ado_project or None,
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
    """Show initial config wizard."""
    st.title("🧙 case-wizard Setup")

    st.markdown("""
    **Claude Code Login Required:**
    ```bash
    claude login
    ```
    """)

    config = load_config()

    with st.form("config_form"):
        org_url = st.text_input(
            "Azure DevOps Org URL",
            value=config.get("azdo_org_url", ""),
            placeholder="https://dev.azure.com/yourorg",
        )

        azdo_pat = st.text_input(
            "Azure DevOps PAT",
            value=config.get("azdo_pat", ""),
            type="password",
            placeholder="Create at dev.azure.com",
        )

        ado_project = st.text_input(
            "Project (optional)",
            value=config.get("azdo_project", "") or "",
        )

        if st.form_submit_button("✅ Continue", type="primary", use_container_width=True):
            if not org_url or not azdo_pat:
                st.error("Please fill in required fields")
                return

            config = {
                "azdo_org_url": org_url,
                "azdo_pat": azdo_pat,
                "azdo_project": ado_project or None,
            }
            config.update(DEFAULTS)
            save_config(config)
            st.session_state.config_complete = True
            st.rerun()


# Main
st.set_page_config(page_title="case-wizard", page_icon="🧙", layout="wide")

if st.session_state.get("config_complete") is None:
    config = load_config()
    st.session_state.config_complete = bool(
        config.get("azdo_pat") and config.get("azdo_org_url")
    )

if not st.session_state.get("config_complete"):
    show_config_wizard()
else:
    show_main_app()
