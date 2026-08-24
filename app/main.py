"""case-wizard: single-page desktop dashboard. No tabs, no separate setup
screen, no forms except where a real submit action needs one. Everything
that's actually broken shows an inline fix right where the status is;
everything else stays out of the way."""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

from settings import load_config, save_config, clear_secrets, DEFAULTS
from checks import run_health_check, get_startup_issues
from progress import ProgressReporter
from crm_playwright import check_login_headless as check_crm_login_dom, reset_profile as reset_crm_profile, ensure_crm_tab_open
from azdo_check import check_azdo_access

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent

st.set_page_config(page_title="case-wizard", page_icon="🧙", layout="wide")

config = load_config()


# ---------------------------------------------------------------------------
# One-time startup: run every check exactly once per session, with live
# progress, then cache the results. Nothing below this block ever
# re-triggers a check on its own - every rerun (typing, clicking) just
# reads what's already in session_state, so interacting with the page
# never silently relaunches a browser or re-hits an API in the background.
# ---------------------------------------------------------------------------
if "checks_done" not in st.session_state:
    _ph = st.empty()
    _lines = []

    def _report(label, status):
        icon = "✅" if status is True else ("❌" if status is False else "⏳")
        _lines.append(f"{icon} {label}")
        _ph.markdown("**🧙 Starting case-wizard...**\n\n" + "\n\n".join(_lines))

    health = run_health_check(config, on_check=lambda name, r: _report(name, r["status"]))
    critical, _ = get_startup_issues(health)

    crm_result = (health["CRM Browser Tab"]["status"], health["CRM Browser Tab"]["message"])

    if config.get("azdo_org_url") and config.get("azdo_pat"):
        _report("Azure DevOps API", None)
        try:
            ado_result = check_azdo_access(config["azdo_org_url"], config["azdo_pat"])
        except Exception as e:
            ado_result = (False, f"API error: {e}")
    else:
        ado_result = (False, "Not configured")

    st.session_state.checks_done = True
    st.session_state.health = health
    st.session_state.critical = critical
    st.session_state.crm_result = crm_result
    st.session_state.ado_result = ado_result
    _ph.empty()

health = st.session_state.health
critical = st.session_state.critical
crm_status, crm_msg = st.session_state.crm_result
ado_status, ado_msg = st.session_state.ado_result


def recheck_everything():
    with st.spinner("Rechecking..."):
        new_health = run_health_check(config)
        new_critical, _ = get_startup_issues(new_health)
        st.session_state.health = new_health
        st.session_state.critical = new_critical
        st.session_state.crm_result = check_crm_login_dom(config.get("crm_url"))
        if config.get("azdo_org_url") and config.get("azdo_pat"):
            try:
                st.session_state.ado_result = check_azdo_access(config["azdo_org_url"], config["azdo_pat"])
            except Exception as e:
                st.session_state.ado_result = (False, f"API error: {e}")
    st.rerun()


def get_output_path(stage_id, case_num):
    """Path to the human-readable output file for a stage."""
    if stage_id == "brief":
        return PROJECT_ROOT / "case-brief" / "case-briefs" / f"case-{case_num}.md"
    if stage_id == "guide":
        return PROJECT_ROOT / "case-guide" / "case-guides" / f"case-{case_num}-for-dummies.md"
    if stage_id == "solve":
        return PROJECT_ROOT / "case-solve" / "case-solves" / f"case-{case_num}" / "VERIFICATION_CHECKLIST.md"
    return None


def get_stage_status(case_num):
    """Whether each stage's output exists, and when it was last written (or
    None if it doesn't exist yet). This says "a file is there", not "this
    ran just now" - the two are shown differently (see ran_this_session)."""
    if not case_num:
        return {"brief": None, "guide": None, "solve": None}
    result = {}
    for stage_id in ["brief", "guide", "solve"]:
        path = get_output_path(stage_id, case_num)
        result[stage_id] = datetime.fromtimestamp(path.stat().st_mtime) if path.exists() else None
    return result


def _icon(v):
    return "✅" if v is True else ("❌" if v is False else "⏳")


# ---------------------------------------------------------------------------
# Sidebar: settings and help live here, permanently reachable, never in the
# way of the dashboard itself.
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ Settings")

    with st.expander("Normal", expanded=False):
        crm_url_setting = st.text_input("CRM URL", value=config.get("crm_url", ""))
        org_url_setting = st.text_input("ADO Organization URL", value=config.get("azdo_org_url", ""))
        pat_setting = st.text_input("ADO PAT", value=config.get("azdo_pat", ""), type="password")
        open_vscode_setting = st.checkbox("Open results in VS Code", value=config.get("open_in_vscode", True))
        if st.button("💾 Save", key="save_normal"):
            config.update({
                "crm_url": crm_url_setting,
                "azdo_org_url": org_url_setting,
                "azdo_pat": pat_setting,
                "open_in_vscode": open_vscode_setting,
            })
            save_config(config)
            st.session_state.checks_done = False  # re-verify against new values
            st.rerun()
        if st.button("🗑️ Clear all secrets", key="clear_secrets"):
            clear_secrets()
            st.session_state.clear()
            st.rerun()

    with st.expander("Advanced", expanded=False):
        run_tests_setting = st.checkbox("Run tests", value=config.get("run_tests", False))
        run_lint_setting = st.checkbox("Run lint", value=config.get("run_lint", False))
        run_build_setting = st.checkbox("Run build", value=config.get("run_build", False))
        skip_ado_setting = st.checkbox("Skip ADO search", value=config.get("skip_ado", False))
        style_prs_setting = st.checkbox("Include style PRs", value=config.get("include_style_prs", True))
        max_prs_setting = st.number_input("Max PRs", value=config.get("max_prs", 20), min_value=5, max_value=100)
        model_options = [None, "opus", "sonnet"]
        model_setting = st.selectbox(
            "Claude model", model_options,
            index=model_options.index(config.get("claude_model")) if config.get("claude_model") in model_options else 0,
        )
        timeout_setting = st.number_input("Timeout (sec)", value=config.get("claude_timeout", 600), min_value=60, max_value=3600)
        st.caption("Solve always commits as it goes and never pushes - nothing to toggle there.")
        if st.button("💾 Save", key="save_advanced"):
            config.update({
                "run_tests": run_tests_setting,
                "run_lint": run_lint_setting,
                "run_build": run_build_setting,
                "skip_ado": skip_ado_setting,
                "include_style_prs": style_prs_setting,
                "max_prs": int(max_prs_setting),
                "claude_model": model_setting,
                "claude_timeout": int(timeout_setting),
            })
            save_config(config)
            st.success("Saved")

    st.markdown("### ❓ Help")
    with st.expander("Requirements & troubleshooting", expanded=False):
        st.markdown("""
        **Setup**
        1. Install [Claude Code](https://claude.com/claude-code), then `claude login`
        2. Create an Azure DevOps [PAT](https://dev.azure.com/_usersSettings/tokens)
           (scopes: Code Read, Project and Team Read)
        3. Log in to CRM below when prompted

        **CRM not logging in?** Click "Log in to CRM" below - a dedicated browser
        window opens (not your normal browser). If it flashes and closes instantly,
        click "Reset session" first.

        **ADO invalid?** Check the org URL format and that the PAT hasn't expired.

        **A stage fails?** Check the "Full Output" expander under that stage after
        it fails - the real error is usually there.
        """)


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------
st.title("🧙 case-wizard")

all_ok = all(v is True for v in [
    health["Python 3.8+"]["status"],
    health["Git"]["status"],
    health["Claude CLI"]["status"],
    health["Claude Logged In"]["status"],
    crm_status,
    ado_status,
])

col_status, col_recheck = st.columns([6, 1])
with col_status:
    if all_ok:
        st.success("✅ All systems ready — Python · Git · Claude · CRM · ADO")
    else:
        st.write(
            f"{_icon(health['Python 3.8+']['status'])} Python &nbsp;&nbsp;"
            f"{_icon(health['Git']['status'])} Git &nbsp;&nbsp;"
            f"{_icon(health['Claude CLI']['status'] and health['Claude Logged In']['status'])} Claude &nbsp;&nbsp;"
            f"{_icon(crm_status)} CRM &nbsp;&nbsp;"
            f"{_icon(ado_status)} ADO",
            unsafe_allow_html=True,
        )
with col_recheck:
    if st.button("↻ Recheck", use_container_width=True):
        recheck_everything()

# Inline fixes for whatever's actually broken - nothing else shows.
if critical:
    st.error("Missing: " + ", ".join(name for name, _ in critical))
    for name, message in critical:
        st.caption(f"**{name}:** {message}")
    st.caption("Install what's missing, then click Recheck above.")

if crm_status is not True:
    col1, col2, col3 = st.columns([2.5, 1, 1])
    with col1:
        st.warning(f"CRM: {crm_msg}")
    with col2:
        if st.button("🔑 Log in to CRM", use_container_width=True):
            # The shared Chrome window is already open (app/launch.py opens
            # it at startup) - this just makes sure a CRM tab exists in it,
            # fast and synchronous. No new window; nothing to wait for here,
            # Recheck above is how login success gets noticed.
            with st.spinner("Opening CRM tab..."):
                ensure_crm_tab_open(config.get("crm_url", ""))
            st.info("Switch to the CRM tab in your case-wizard browser window, log in, then click Recheck above.")
    with col3:
        if st.button("♻️ Reset session", use_container_width=True,
                     help="Use this if login keeps failing instantly"):
            with st.spinner("Resetting..."):
                reset_crm_profile()
            st.success("Done - try Log in to CRM again.")

if ado_status is not True:
    st.warning(f"ADO: {ado_msg}")
    org_url_fix = st.text_input("Organization URL", value=config.get("azdo_org_url", ""), key="ado_fix_org")
    pat_fix = st.text_input("Personal Access Token", value=config.get("azdo_pat", ""), type="password", key="ado_fix_pat",
                             help="Needs Code (Read) and Project and Team (Read) scopes")
    if st.button("🔌 Check Connection"):
        if org_url_fix and pat_fix:
            with st.spinner("Testing Azure DevOps API..."):
                try:
                    ok, msg = check_azdo_access(org_url_fix, pat_fix)
                except Exception as e:
                    ok, msg = False, f"Check failed: {e}"
            st.session_state.ado_result = (ok, msg)
            if ok:
                config["azdo_org_url"] = org_url_fix
                config["azdo_pat"] = pat_fix
                save_config(config)
            st.rerun()
        else:
            st.error("Enter both fields first.")

st.divider()

# ---------------------------------------------------------------------------
# Case number + the three stages, always visible, always in one place.
# ---------------------------------------------------------------------------
case_number = st.text_input(
    "Case Number", placeholder="T2611845", key="case_input"
).upper().strip()
st.session_state.case_number = case_number

if not case_number:
    st.info("👈 Enter a case number to begin")
    st.stop()

status = get_stage_status(case_number)
ran_this_session = st.session_state.setdefault("ran_this_session", set())

# Each stage's prerequisite - None means always available. A stage only
# ever appears once its prerequisite's output actually exists, so the page
# only ever shows the one step you can actually take next: nothing runs
# automatically, and nothing later is even visible to click yet.
STAGES = [
    ("brief", "Brief", "📋 Gather Brief", "case_brief", "Dynamics 365 CRM + Azure DevOps", None),
    ("guide", "Guide", "📖 Generate Guide", "case_guide", "Brief + Azure DevOps → Claude walkthrough", "brief"),
    ("solve", "Solve", "⚙️ Auto-Implement", "case_solve", "Guide → clone, implement, verify, commit", "guide"),
]

for step_num, (stage_id, stage_name, button_label, cmd_name, source_desc, prereq) in enumerate(STAGES, 1):
    if prereq and not status[prereq]:
        st.divider()
        st.info(f"🔒 Step {step_num}: {stage_name} — unlocks once {STAGES[step_num - 2][1]} is done")
        break

    st.divider()
    is_complete = status[stage_id]
    just_ran = (stage_id, case_number) in ran_this_session
    col_title, col_status_badge = st.columns([5, 1])
    with col_title:
        st.markdown(f"### Step {step_num}: {button_label.split(' ', 1)[1]}")
        st.caption(source_desc)
    with col_status_badge:
        if just_ran:
            # Actually witnessed this succeed just now, not just "a file
            # happens to be there" - see the pre-existing-output case below.
            st.markdown("✅ Just completed")
        elif is_complete:
            st.markdown(f"📄 Existing output ({is_complete.strftime('%b %d, %H:%M')})")
        else:
            st.markdown("⏳ Pending")

    repo_url = ""
    if stage_id == "solve":
        repo_key = f"repo_url_{case_number}"
        repo_url = st.text_input(
            "Git clone URL", value=st.session_state.get(repo_key, ""),
            placeholder="https://dev.azure.com/org/project/_git/repo",
            key=f"repo_input_{case_number}",
            help="Solve clones this, creates a case/<number> branch, and commits there. Nothing is pushed automatically.",
        )
        st.session_state[repo_key] = repo_url

    run_disabled = stage_id == "solve" and not repo_url
    run_button = st.button(button_label, key=f"run_{stage_id}", disabled=run_disabled)

    if is_complete:
        output_path = get_output_path(stage_id, case_number)
        # Brief/guide are full documents - too long to leave expanded by
        # default, it'd bury the button above for every other stage on
        # the page. Solve's checklist is short enough to stay open.
        with st.expander(f"View {stage_name.lower()} output", expanded=(stage_id == "solve")):
            try:
                st.markdown(output_path.read_text(encoding="utf-8"))
            except Exception as e:
                st.error(f"Couldn't read {output_path}: {e}")

    output_ph = st.empty()

    if run_button:
        env = os.environ.copy()
        if config.get("azdo_pat"):
            env["AZDO_PAT"] = config["azdo_pat"]

        stage_dirs = {
            "brief": PROJECT_ROOT / "case-brief",
            "guide": PROJECT_ROOT / "case-guide",
            "solve": PROJECT_ROOT / "case-solve",
        }

        cmd = [f"{cmd_name}.py", case_number, "--no-open"]
        if stage_id == "brief":
            # --keep-browser-open: case_brief.py normally closes the
            # automation Chrome window when it finishes - correct for
            # standalone CLI use, but that window is also the one showing
            # this dashboard (see app/launch.py), so closing it here would
            # close the app out from under you.
            cmd.append("--keep-browser-open")
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
            reporter = ProgressReporter(agent_name=f"case-{stage_id}", operation_name=stage_name)
            outer_timeout = max(600, config.get("claude_timeout", 600) + 300)
            output_lines = []
            process = None
            try:
                reporter.update(f"Starting {stage_name}...", "running")
                process = subprocess.Popen(
                    [sys.executable] + cmd,
                    cwd=str(stage_dirs[stage_id]),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )
                progress_ph = st.empty()
                raw_line_ph = st.empty()
                for line in iter(process.stdout.readline, ""):
                    line = line.strip()
                    if not line:
                        continue
                    output_lines.append(line)
                    try:
                        msg_data = json.loads(line)
                        reporter.update(
                            msg_data.get("operation", ""),
                            msg_data.get("status", "info"),
                            msg_data.get("detail", ""),
                            msg_data.get("progress_pct"),
                        )
                        with progress_ph.container():
                            for msg in reporter.messages[-15:]:
                                emoji = {"running": "📍", "success": "✅", "error": "❌", "warning": "⚠️"}.get(msg.status, "ℹ️")
                                line_text = f"{emoji} **{msg.operation}**"
                                if msg.detail:
                                    line_text += f"  \n*{msg.detail}*"
                                st.markdown(line_text)
                    except json.JSONDecodeError:
                        # A plain print from the script, not a structured
                        # milestone - shown as one small, in-place status
                        # line instead of piling up a new "Output" block
                        # per line (that's what made this noisy before).
                        raw_line_ph.caption(f"↳ {line}")

                returncode = process.wait(timeout=outer_timeout)
                if returncode == 0:
                    st.success(f"✅ {stage_name} completed")
                    ran_this_session.add((stage_id, case_number))
                    st.rerun()
                else:
                    st.error(f"❌ {stage_name} failed (exit code {returncode})")
                    if stage_id == "brief" and any(x in "\n".join(output_lines).lower() for x in ["crm", "auth", "login"]):
                        st.info("Possible CRM login issue - check the CRM status above.")
                    with st.expander("Full Output"):
                        st.code("\n".join(output_lines), language="text")
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                st.error(f"❌ {stage_name} timed out after {outer_timeout}s and was stopped")
            except Exception as e:
                st.error(f"❌ Error: {e}")
