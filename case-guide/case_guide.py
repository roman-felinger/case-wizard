#!/usr/bin/env python3
"""Turn a case brief into a plain-language "Case <code> for Dummies" walkthrough.

A companion to case-brief, but a fully independent project -- it doesn't
import case-brief's code, it just reads the Markdown brief case-brief's
case_brief.py already wrote (case-brief/case-briefs/case-<code>.md by
default) and, unless --skip-ado, re-queries Azure DevOps itself for one
level of extra depth on each related branch/PR the brief mentions: commit
messages, changed file paths, and review-thread comments -- context the
brief's own summary doesn't include.

All of that -- the brief plus the extra ADO detail -- plus (unless disabled)
the most recent previous guide as a house-style example and a sample of
this project's other recent completed PRs as a convention reference, gets
handed to one headless `claude` call that writes the actual guide: the
clone/branch commands to get set up, what's already been tried (if
anything), a concrete plan for what still needs developing, and how to
verify/ship it. That call runs as case-guide-writer, a project-scoped
Claude Code agent (.claude/agents/case-guide-writer.md) with its own
brevity/house-style/convention-matching skills -- --no-agent falls back to
claude's plain default persona.

Needs the `claude` CLI (Claude Code) installed and already logged in --
this just shells out to it once, non-interactively. Azure DevOps needs the
same self-service PAT case-brief uses (see case-brief/README.md); skip that
whole step with --skip-ado if you don't have one set up here (this also
skips the other-recent-PRs convention sample, which needs the same ADO
access).

If a guide already exists for this case and is newer than the brief, this
skips straight to opening it instead of re-spending an Azure DevOps search
and a claude call -- pass --force to regenerate anyway.

Examples:
    python case_guide.py T2611845
    python case_guide.py T2611845 --skip-ado          # brief content only, no live re-query
    python case_guide.py T2611845 --model opus
    python case_guide.py T2611845 --no-open
    python case_guide.py T2611845 --force              # regenerate even if already up to date
    python case_guide.py T2611845 --show-prompt         # print the assembled prompt, don't call claude
    python case_guide.py T2611845 --claude-arg="--permission-mode" --claude-arg="default"
"""
import argparse
import copy
import glob
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ado_api, writer

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

DEFAULTS = {
    "brief_dir": "../case-brief/case-briefs",
    "output_dir": "./case-guides",
    "open_in_vscode": True,
    "azure_devops": {
        "org_url": None,
        "project": None,
        "pat_env_var": "AZDO_PAT",
        "max_prs": ado_api.DEFAULT_MAX_PRS,
        "style_pr_sample": 5,
    },
    "claude": {
        "model": None,
        "extra_args": [],
        "timeout": 600,
        "max_ado_detail_chars": 20000,
        "agent": "case-guide-writer",
        "example_count": 1,
        "max_example_chars": 4000,
    },
}


def _deep_merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _strip_comments(cfg):
    """config.example.json documents settings with leading-underscore keys
    (e.g. "_comment") at the top level and inside its known nested blocks --
    drop any of those after merging so they don't ride along inside the
    dicts handed to ado_api.* (which don't expect them, and would leak them
    into anything that ever logs/serializes those dicts verbatim). DEFAULTS
    only ever nests one level deep, so there's no need for a general
    recursive walk here."""
    for d in (cfg, cfg.get("azure_devops", {}), cfg.get("claude", {})):
        for key in [k for k in d if isinstance(k, str) and k.startswith("_")]:
            del d[key]
    return cfg


def load_config(path=CONFIG_PATH):
    cfg = copy.deepcopy(DEFAULTS)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            _deep_merge(cfg, json.load(f))
    return _strip_comments(cfg)


def _sanitize_case_number(case_number):
    """Case numbers only ever need to contain word characters, dots and
    dashes -- the same rule writer.UNSAFE_CHARS enforces on the output
    side, shared here so it can't drift out of sync between the two.
    Stripping anything else before it's used to build a filesystem path or
    glob pattern closes off path traversal / glob-metacharacter tricks via
    a mistyped or malicious case code."""
    return writer.UNSAFE_CHARS.sub("", case_number)


def find_brief(brief_dir, case_number):
    """The exact case-<code>.md case-brief would have written, or -- in
    case the case code was typed slightly differently than the brief's
    filename -- a unique substring match. Ambiguous or missing matches are
    reported rather than guessed."""
    safe_number = _sanitize_case_number(case_number)
    brief_dir_real = os.path.realpath(brief_dir)

    def _within_brief_dir(path):
        return os.path.commonpath([brief_dir_real, os.path.realpath(path)]) == brief_dir_real

    exact = os.path.join(brief_dir, f"case-{safe_number}.md")
    if os.path.exists(exact) and _within_brief_dir(exact):
        return exact
    matches = sorted(
        m for m in glob.glob(os.path.join(brief_dir, f"*{safe_number}*.md"))
        if _within_brief_dir(m)
    )
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(os.path.basename(m) for m in matches)
        sys.exit(f"Multiple briefs match {case_number!r} in {brief_dir}: {names}\nPass the exact case code from one of these filenames.")
    return None


def find_example_guide(output_dir, exclude_filename, count=1):
    """The `count` most recently written guide(s) already in output_dir,
    excluding the one this run would itself write -- a house-style anchor
    for tone/structure, not case-specific content (the prompt is explicit
    that its facts aren't to be reused). Returns None on the very first
    guide ever written (nothing to anchor to yet) or when the directory
    doesn't exist."""
    if not count or not os.path.isdir(output_dir):
        return None
    candidates = [
        p for p in glob.glob(os.path.join(output_dir, "*.md"))
        if os.path.basename(p) != exclude_filename
    ]
    if not candidates:
        return None
    candidates.sort(key=os.path.getmtime, reverse=True)
    texts = []
    for path in candidates[:count]:
        with open(path, "r", encoding="utf-8") as f:
            texts.append(f.read().strip())
    return "\n\n---\n\n".join(texts)


def format_example_guide(example_text):
    if not example_text:
        return "_No previous guide exists yet -- this is the first one, so there's no house-style example to match._"
    return example_text


def _enrich_branch(azure_cfg, session, b):
    """Adds commit messages to one branch dict from find_related. Returns
    (enriched_branch, warning_or_None) rather than raising on a non-auth
    failure, so one bad branch doesn't sink the whole (possibly
    concurrent) enrichment pass."""
    print(f"  Fetching commits for branch {b['project']}/{b['repo']}: {b['branch']}...")
    try:
        commits = ado_api.get_branch_commits(azure_cfg, b["project"], b["repo"], b["branch"], session=session)
    except ado_api.AdoAuthError:
        raise
    except Exception as e:
        print(f"    Could not fetch commits for this branch: {e}", file=sys.stderr)
        return {**b, "commits": []}, f"couldn't fetch commits for branch {b['project']}/{b['repo']}: {b['branch']} ({e})"
    return {**b, "commits": commits}, None


def _enrich_pr(azure_cfg, session, pr):
    """Same as _enrich_branch, for one PR dict from find_related."""
    print(f"  Fetching detail for PR {pr['project']}/{pr['repo']} !{pr['id']}...")
    try:
        extra = ado_api.get_pr_details(azure_cfg, pr["project"], pr["repo"], pr["id"], session=session)
    except ado_api.AdoAuthError:
        raise
    except Exception as e:
        print(f"    Could not fetch detail for this PR: {e}", file=sys.stderr)
        return {**pr, "commits": [], "files": [], "comments": []}, f"couldn't fetch detail for PR {pr['project']}/{pr['repo']} !{pr['id']} ({e})"
    return {**pr, **extra}, None


def gather_ado_detail(cfg, case_number):
    """Re-runs case-brief's branch/PR search, then fetches one level deeper
    per hit (commits, files, review comments) via a thread pool sharing
    find_related's session. Returns (detail_or_None, error_or_None) --
    detail's "warnings" list is how format_ado_detail flags a partial
    search instead of presenting it as complete. AdoAuthError (expired/
    under-scoped PAT) is a hard error, not a warning: nothing it returned
    can be trusted as complete.
    """
    azure_cfg = cfg["azure_devops"]
    if not azure_cfg.get("org_url"):
        return None, "no Azure DevOps org URL configured (set azure_devops.org_url in config.json or pass --org-url)"

    try:
        session = ado_api.open_session(azure_cfg)
        branches, pull_requests, warnings = ado_api.find_related(azure_cfg, case_number, session=session)
    except Exception as e:
        return None, str(e)

    detail = {"branches": [], "pull_requests": [], "warnings": list(warnings)}
    try:
        with ThreadPoolExecutor(max_workers=ado_api.MAX_WORKERS) as pool:
            for enriched, warning in pool.map(lambda b: _enrich_branch(azure_cfg, session, b), branches):
                detail["branches"].append(enriched)
                if warning:
                    detail["warnings"].append(warning)
            for enriched, warning in pool.map(lambda pr: _enrich_pr(azure_cfg, session, pr), pull_requests):
                detail["pull_requests"].append(enriched)
                if warning:
                    detail["warnings"].append(warning)
    except ado_api.AdoAuthError as e:
        return None, str(e)

    return detail, None


def _pick_style_project(azure_cfg, detail):
    """Which project to sample get_recent_prs from: the one explicitly
    configured, or -- if the case's own matched branches/PRs all resolve to
    exactly one -- that one. Returns (project, reason_if_none) rather than
    guessing among several candidate projects when there's no configured
    default and the case's own related work spans more than one."""
    if azure_cfg.get("project"):
        return azure_cfg["project"], None
    projects = {b["project"] for b in (detail or {}).get("branches", [])}
    projects |= {pr["project"] for pr in (detail or {}).get("pull_requests", [])}
    if len(projects) == 1:
        return next(iter(projects)), None
    if not projects:
        return None, "no related branches/PRs to infer a project from, and azure_devops.project isn't configured"
    return None, f"the case's related work spans multiple projects ({', '.join(sorted(projects))}) with no azure_devops.project configured to disambiguate"


def gather_style_prs(cfg, detail):
    """A sample of the target project's other recent completed PRs (see
    ado_api.get_recent_prs) -- purely a style/convention reference, so
    failures here are never fatal to the run: any problem just yields
    (None, reason) and the prompt says plainly why the section is empty,
    same transparency policy as format_ado_detail's warnings."""
    azure_cfg = cfg["azure_devops"]
    sample_size = azure_cfg.get("style_pr_sample", 0)
    if not sample_size:
        return None, "disabled (azure_devops.style_pr_sample is 0)"
    if not azure_cfg.get("org_url"):
        return None, "no Azure DevOps org URL configured"

    project, reason = _pick_style_project(azure_cfg, detail)
    if not project:
        return None, reason

    exclude_ids = {pr["id"] for pr in (detail or {}).get("pull_requests", [])}
    try:
        prs = ado_api.get_recent_prs(azure_cfg, project, exclude_ids=exclude_ids, top=sample_size)
    except ado_api.AdoAuthError as e:
        return None, str(e)
    except Exception as e:
        return None, f"couldn't fetch a PR sample for project {project} ({e})"
    if not prs:
        return None, f"no other completed PRs found in project {project}"
    return prs, None


def format_style_prs(prs, reason):
    if not prs:
        return f"_No style-reference PRs available ({reason})._"
    lines = ["### Other recent completed PRs in this project (style/convention reference only)"]
    for pr in prs:
        reviewers = ", ".join(pr["reviewers"]) if pr["reviewers"] else "—"
        lines.append(
            f"- **{pr['repo']} !{pr['id']}: {pr.get('title') or '—'}** "
            f"({pr['source_branch']} -> {pr['target_branch']}, by {pr.get('created_by') or '—'}, "
            f"reviewers: {reviewers})"
        )
    return "\n".join(lines)


def format_ado_detail(detail, ado_error):
    if ado_error:
        return f"_Could not fetch live Azure DevOps detail: {ado_error}. Falling back to whatever the brief above already shows._"

    warnings = (detail or {}).get("warnings") or []
    if not detail or not (detail["branches"] or detail["pull_requests"]):
        # A capped/partial search can miss real related work entirely,
        # which is worth flagging even when nothing matched -- "nothing
        # found" and "didn't fully search" are very different claims.
        suffix = f" ({'; '.join(warnings)})" if warnings else ""
        return f"_No related branches or pull requests found in Azure DevOps for this case{suffix}._"

    lines = []
    if detail["branches"]:
        lines.append("### Related branches -- live detail")
        for b in detail["branches"]:
            lines.append(f"- **{b['project']}/{b['repo']}: {b['branch']}**")
            for c in b["commits"]:
                lines.append(f"  - commit: {c}")
            if not b["commits"]:
                lines.append("  - _(no commits found)_")
    if detail["pull_requests"]:
        lines.append("### Related pull requests -- live detail")
        for pr in detail["pull_requests"]:
            lines.append(f"- **{pr['project']}/{pr['repo']} !{pr['id']}: {pr.get('title') or '—'}** ({pr.get('status') or '—'}, by {pr.get('created_by') or '—'})")
            for c in pr.get("commits", []):
                lines.append(f"  - commit: {c}")
            for f in pr.get("files", []):
                lines.append(f"  - changed: {f}")
            for c in pr.get("comments", []):
                lines.append(f"  - review comment -- {c}")
    if warnings:
        bullets = "\n".join(f"- {w[0].upper() + w[1:]}." for w in warnings)
        lines.append(f"\n_Note -- this search may be incomplete:_\n{bullets}")
    return "\n".join(lines)


def _truncate(text, limit, label="live Azure DevOps detail", config_key="claude.max_ado_detail_chars"):
    """Cap text at `limit` characters, appending a visible marker instead
    of silently dropping the rest -- a case with a lot of related branch/PR
    activity (or a long house-style example guide) can otherwise inline an
    unbounded amount of text into the prompt with no sign anything was cut.
    limit=None/0 disables this. label/config_key just keep the marker
    accurate for whichever block is being capped."""
    if not limit or len(text) <= limit:
        return text
    omitted = len(text) - limit
    return (
        text[:limit]
        + f"\n\n_(...truncated -- {omitted} more character(s) of {label} omitted "
        f"to keep the prompt a reasonable size; see {config_key} in config.json.)_"
    )


PROMPT_TEMPLATE = """You are helping a support engineer who has just picked up a case and needs a \
plain-language plan to actually go solve it -- assume they may not have touched this codebase before.

Below is the full case brief (CRM details, linked Azure DevOps branches/PRs, Business Central \
context if any), plus live Azure DevOps detail on those branches/PRs (their commit messages, \
changed files, and review comments) that goes beyond what the brief itself shows.

Write a Markdown guide titled "# Case {case_number} for Dummies" a newcomer could follow start \
to finish. Cover, in this order:

1. **What this case is about** -- a plain-language summary of the customer's problem, pulled \
   from the case description below.
2. **Get set up** -- the exact `git clone` / `cd` / `git checkout -b` commands to run (use the \
   ones already suggested in the brief's Useful Commands section if present; otherwise say \
   plainly that no repo has been identified yet and what to do about it).
3. **What's already been tried** -- if there are related branches/PRs below, summarize concretely \
   what they changed (from their commit messages / changed files / review comments) and whether \
   they look finished, still in review, or abandoned. If there's nothing related, say so plainly.
4. **What still needs to be developed, and how** -- a concrete, numbered plan grounded in the \
   actual case description and whatever the related branches/PRs reveal about the codebase's \
   shape -- not generic advice. Call out open questions if the material below isn't specific \
   enough to be concrete about something.
5. **How to verify and ship it** -- how to test the fix against the case description, and how to \
   get it reviewed/merged (PR against the branch/repo from step 2).

Be concrete wherever the material below supports it; be honest about gaps rather than inventing \
detail that isn't there. Output only the Markdown guide itself, nothing else -- no preamble, no \
"here's your guide" framing.

--- CASE BRIEF ---
{brief}

--- LIVE AZURE DEVOPS DETAIL ---
{ado_detail}

--- HOUSE STYLE EXAMPLE (tone/structure reference only -- an unrelated case, don't reuse its facts) ---
{example_guide}

--- OTHER RECENT PRS IN THIS PROJECT (style/convention reference only, not related to this case) ---
{style_prs}
"""


def build_prompt(case_number, brief_text, ado_detail_text, example_guide_text, style_prs_text):
    return PROMPT_TEMPLATE.format(
        case_number=case_number,
        brief=brief_text.strip(),
        ado_detail=ado_detail_text,
        example_guide=example_guide_text,
        style_prs=style_prs_text,
    )


def _looks_like_guide(text):
    """Cheap sanity check that claude's output is actually the requested
    guide and not, say, a refusal or stray preamble that slipped past the
    "output only the guide" instruction. Deliberately loose (just the
    shape of a Markdown heading plus the requested phrase) and only ever
    used to warn, never to block writing the file -- a human can judge the
    actual content far better than this can."""
    head = text.lstrip()[:200].lower()
    return head.startswith("#") and "for dummies" in head


def call_claude(prompt, model=None, extra_args=None, timeout=600, agent_name=None):
    """One-shot headless call: the prompt carries all the context Claude
    needs inline, so there's nothing here for it to read/write/run -- a
    pure text-generation task shouldn't reach for a tool at all. The
    timeout is a safety net regardless, so a script run never hangs
    forever on an unexpected permission prompt with no TTY to answer it.
    (No --permission-mode is set by default -- pass one via extra_args /
    --claude-arg if you ever hit a prompt; see config.example.json.)

    agent_name, if given, runs the whole session as that project-scoped
    .claude/agents/<agent_name>.md agent (its frontmatter/tools/system
    prompt) instead of claude's plain default -- cwd=HERE makes sure it
    resolves against this project's own .claude/agents/, regardless of
    what directory case_guide.py was invoked from.
    """
    exe = shutil.which("claude")
    if not exe:
        sys.exit("`claude` CLI not found on PATH -- install Claude Code first (https://claude.com/claude-code).")

    cmd = [exe, "-p"]
    if model:
        cmd += ["--model", model]
    if agent_name:
        cmd += ["--agent", agent_name]
    cmd += list(extra_args or [])
    try:
        # shutil.which already resolved the real executable (following
        # PATHEXT, so this finds an npm-style claude.cmd shim on Windows
        # too) -- running it directly rather than via shell=True avoids
        # cmd.exe re-parsing/expanding anything inside --claude-arg values.
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, cwd=HERE,
        )
    except FileNotFoundError:
        sys.exit(f"Found `claude` on PATH at {exe} but couldn't execute it -- check the install.")
    except subprocess.TimeoutExpired:
        sys.exit(
            f"`claude` didn't return within {timeout}s -- it may be waiting on a permission prompt "
            "with no one there to answer it. Try --claude-arg for a permission-mode flag that skips "
            "prompting (see config.example.json / `claude -h`)."
        )
    if result.returncode != 0:
        sys.exit(f"claude exited with code {result.returncode}:\n{result.stderr.strip()}")
    if not result.stdout.strip():
        sys.exit(f"claude returned no output.\nstderr:\n{result.stderr.strip()}")
    return result.stdout.strip()


def _resolve_extra_args(args, cfg):
    if args.no_claude_extra_args:
        # Deliberately ignores config's stored extra_args, but still
        # honors an explicit --claude-arg on this same invocation.
        return args.claude_args or []
    return args.claude_args if args.claude_args is not None else cfg["claude"]["extra_args"]


def build_parser():
    parser = argparse.ArgumentParser(
        prog="case_guide.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("case_number", help="Case code to write a guide for, e.g. T2611845 (must already have a brief -- run case-brief's case_brief.py first)")
    parser.add_argument("--brief-dir", metavar="DIR", help="Where to look for the case brief (default: config.json's brief_dir, ../case-brief/case-briefs)")
    parser.add_argument("--output-dir", metavar="DIR", help="Where to write the guide (default: config.json's output_dir, ./case-guides)")
    parser.add_argument("--skip-ado", action="store_true", help="Don't re-query Azure DevOps for extra branch/PR detail -- use only what's already in the brief")
    parser.add_argument("--org-url", metavar="URL", help="Azure DevOps org URL override, e.g. https://dev.azure.com/myorg")
    parser.add_argument("--project", metavar="NAME", help="Restrict the Azure DevOps search to one project (default: config.json's azure_devops.project, or search every project in the org)")
    parser.add_argument("--model", metavar="NAME", help="Model for the headless claude call, e.g. opus/sonnet (default: config.json's claude.model, or claude's own default)")
    parser.add_argument("--claude-arg", metavar="ARG", action="append", dest="claude_args",
                         help="Extra raw argument to pass through to the claude CLI, repeatable "
                              "(e.g. --claude-arg=\"--permission-mode\" --claude-arg=\"default\" if you hit a permission prompt)")
    parser.add_argument("--no-claude-extra-args", action="store_true",
                         help="Ignore claude.extra_args from config.json for this run (still honors an explicit --claude-arg)")
    parser.add_argument("--timeout", type=int, metavar="SECONDS", help="Give up waiting on claude after this long (default: config.json's claude.timeout, 600)")
    parser.add_argument("--no-agent", action="store_true", help="Don't run claude as the case-guide-writer agent -- plain default persona instead")
    parser.add_argument("--no-example", action="store_true", help="Don't include a previous guide as a house-style example")
    parser.add_argument("--no-style-prs", action="store_true", help="Don't sample other recent PRs in the project for convention reference")
    parser.add_argument("--show-prompt", action="store_true", help="Print the assembled prompt and exit -- doesn't call claude or write a guide")
    parser.add_argument("--force", action="store_true", help="Regenerate the guide even if it's already newer than the brief")
    parser.add_argument("--no-open", action="store_true", help="Don't open the result in VS Code")
    parser.add_argument("--config", metavar="PATH", default=CONFIG_PATH, help="Path to config.json (default: ./config.json)")
    return parser


def main():
    args = build_parser().parse_args()
    cfg = load_config(args.config)

    if args.org_url:
        cfg["azure_devops"]["org_url"] = args.org_url
    if args.project:
        cfg["azure_devops"]["project"] = args.project

    brief_dir = os.path.normpath(os.path.join(HERE, args.brief_dir or cfg["brief_dir"]))
    output_dir = os.path.normpath(os.path.join(HERE, args.output_dir or cfg["output_dir"]))

    brief_path = find_brief(brief_dir, args.case_number)
    if not brief_path:
        sys.exit(
            f"No brief found for case {args.case_number!r} in {brief_dir}.\n"
            f"Run case-brief's `python case_brief.py {args.case_number}` first to generate one, "
            "or pass --brief-dir if it's somewhere else."
        )

    guide_path = os.path.join(output_dir, writer.guide_filename(f"case-{args.case_number}-for-dummies"))
    if not args.show_prompt and not args.force and os.path.exists(guide_path):
        if os.path.getmtime(guide_path) >= os.path.getmtime(brief_path):
            print(f"{guide_path} is already up to date with the brief -- pass --force to regenerate anyway.")
            if cfg["open_in_vscode"] and not args.no_open:
                writer.open_editor(guide_path)
            return

    print(f"Reading brief: {brief_path}")
    with open(brief_path, "r", encoding="utf-8") as f:
        brief_text = f.read()

    detail = None
    ado_detail_text = "_Skipped (--skip-ado) -- using only what's already in the brief above._"
    if not args.skip_ado:
        print("Fetching live Azure DevOps detail on related branches/PRs...")
        detail, ado_error = gather_ado_detail(cfg, args.case_number)
        ado_detail_text = format_ado_detail(detail, ado_error)
    ado_detail_text = _truncate(ado_detail_text, cfg["claude"].get("max_ado_detail_chars"))

    example_text = None
    if not args.no_example:
        example_text = find_example_guide(output_dir, os.path.basename(guide_path), cfg["claude"]["example_count"])
    example_text = _truncate(
        format_example_guide(example_text), cfg["claude"].get("max_example_chars"),
        label="the house-style example guide", config_key="claude.max_example_chars",
    )

    style_prs_reason = "skipped (--skip-ado)" if args.skip_ado else "skipped (--no-style-prs)"
    style_prs_text = format_style_prs(None, style_prs_reason)
    if not args.skip_ado and not args.no_style_prs:
        print("Sampling other recent PRs in the project for style/convention reference...")
        style_prs, reason = gather_style_prs(cfg, detail)
        style_prs_text = format_style_prs(style_prs, reason)

    agent_name = None if args.no_agent else cfg["claude"]["agent"]
    prompt = build_prompt(args.case_number, brief_text, ado_detail_text, example_text, style_prs_text)

    if args.show_prompt:
        print(f"[agent: {agent_name or '(none -- plain default persona)'}]\n")
        print(prompt)
        return

    print("Asking claude to write the guide (this can take a minute)...")
    guide_text = call_claude(
        prompt,
        model=args.model if args.model is not None else cfg["claude"]["model"],
        extra_args=_resolve_extra_args(args, cfg),
        timeout=args.timeout if args.timeout is not None else cfg["claude"]["timeout"],
        agent_name=agent_name,
    )

    if not _looks_like_guide(guide_text):
        print(
            "Warning: claude's output doesn't look like the expected \"# Case ... for Dummies\" guide "
            "(no leading heading / \"for dummies\" phrase in the first 200 characters) -- writing it "
            "anyway, but take a look before trusting it.",
            file=sys.stderr,
        )

    path = writer.write_and_open(
        guide_text,
        output_dir,
        f"case-{args.case_number}-for-dummies",
        open_in_vscode=cfg["open_in_vscode"] and not args.no_open,
    )
    print(f"\nGuide written to {path}")


if __name__ == "__main__":
    main()
