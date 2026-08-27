#!/usr/bin/env python3
"""Turn a case brief into a plain-language, step-by-step implementation guide.

A companion to case-brief, but a fully independent project -- it doesn't
import case-brief's code, it just reads the Markdown brief case-brief's
case_brief.py already wrote (case-brief/briefs/brief-<code>.md by
default) and re-queries Azure DevOps itself for one level of extra depth on
each related branch/PR the brief mentions: commit messages, changed file
paths, and review-thread comments -- context the brief's own summary
doesn't include.

All of that -- the brief plus the extra ADO detail -- plus (unless disabled)
the most recent previous guide as a house-style example, gets handed to one
headless `claude` call that writes the actual guide: the
clone/branch commands to get set up, what's already been tried (if
anything), a concrete plan for what still needs developing, and how to
verify/ship it. That call runs as case-guide-writer, a project-scoped
Claude Code agent (.claude/agents/case-guide-writer.md) with its own
brevity/house-style/convention-matching skills -- --no-agent falls back to
claude's plain default persona.

Needs the `claude` CLI (Claude Code) installed and already logged in --
this just shells out to it once, non-interactively. Azure DevOps needs the
same self-service PAT case-brief uses (see case-brief/README.md).

If a guide already exists for this case and is newer than the brief, this
skips straight to opening it instead of re-spending an Azure DevOps search
and a claude call.

Examples:
    python case_guide.py T2611845
    python case_guide.py T2611845 --model opus
    python case_guide.py T2611845 --claude-arg="--permission-mode" --claude-arg="default"
"""
import argparse
import copy
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from shared.console import enable_utf8_console

enable_utf8_console()  # this script prints Unicode; see shared/console.py

from lib import ado_api, repo_suggest, writer
from shared.config import deep_merge, strip_comments

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

# Pure internal tuning constants -- no CLI flag ever existed for either, so
# not worth a config setting either; see _truncate.
MAX_ADO_DETAIL_CHARS = 20000
MAX_EXAMPLE_CHARS = 4000

DEFAULTS = {
    "brief_dir": "../case-brief/briefs",
    "output_dir": "./guides",
    "azure_devops": {
        "org_url": None,
        "project": None,
    },
    "claude": {
        "model": None,
        "extra_args": [],
        "timeout": 600,
        "agent": "case-guide-writer",
        "example_count": 1,
    },
}


def load_config(path=CONFIG_PATH):
    cfg = copy.deepcopy(DEFAULTS)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            deep_merge(cfg, json.load(f))
    return strip_comments(cfg)


def _sanitize_case_number(case_number):
    """Case numbers only ever need to contain word characters, dots and
    dashes -- the same rule writer.UNSAFE_CHARS enforces on the output
    side, shared here so it can't drift out of sync between the two.
    Stripping anything else before it's used to build a filesystem path or
    glob pattern closes off path traversal / glob-metacharacter tricks via
    a mistyped or malicious case code."""
    return writer.UNSAFE_CHARS.sub("", case_number)


def find_brief(brief_dir, case_number):
    """The exact brief-<code>.md case-brief would have written, or -- in
    case the case code was typed slightly differently than the brief's
    filename -- a unique substring match. Ambiguous or missing matches are
    reported rather than guessed."""
    safe_number = _sanitize_case_number(case_number)
    brief_dir_real = os.path.realpath(brief_dir)

    def _within_brief_dir(path):
        return os.path.commonpath([brief_dir_real, os.path.realpath(path)]) == brief_dir_real

    exact = os.path.join(brief_dir, f"brief-{safe_number}.md")
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


# case-brief's lib/report.py always renders a case's title as the first "### "
# heading and its customer as a "- **Customer:** ..." bullet right after it --
# a fixed enough shape (see case-brief/CLAUDE.md) to pull both back out of the
# finished brief without needing case-brief's own code (this project stays
# independent of it, filesystem contract only -- see this file's docstring).
_CASE_TITLE_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_CUSTOMER_RE = re.compile(r"^-\s+\*\*Customer:\*\*\s*(.+?)\s*$", re.MULTILINE)


def _extract_case_title(brief_text):
    m = _CASE_TITLE_RE.search(brief_text)
    return m.group(1) if m else None


def _extract_customer(brief_text):
    m = _CUSTOMER_RE.search(brief_text)
    if not m or m.group(1) == "—":  # report.py's placeholder for a missing value
        return None
    return m.group(1)


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
        session = ado_api.open_session()
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


def gather_suggested_repo(cfg, customer, detail):
    """Which repo(s)/branch to suggest for the guide's "Get set up" step --
    see lib/repo_suggest.py. Returns a {(project, repo): {clone_url,
    source}} dict -- possibly empty -- see
    repo_suggest.merge_confirmed_and_guessed."""
    azure_cfg = cfg["azure_devops"]
    guessed = repo_suggest.resolve_suggested_repos(ado_api, azure_cfg, customer)
    return repo_suggest.merge_confirmed_and_guessed(detail, guessed)


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


def _truncate(text, limit, label="live Azure DevOps detail"):
    """Cap text at `limit` characters, appending a visible marker instead
    of silently dropping the rest -- a case with a lot of related branch/PR
    activity (or a long house-style example guide) can otherwise inline an
    unbounded amount of text into the prompt with no sign anything was cut.
    label just keeps the marker accurate for whichever block is being
    capped."""
    if not limit or len(text) <= limit:
        return text
    omitted = len(text) - limit
    return (
        text[:limit]
        + f"\n\n_(...truncated -- {omitted} more character(s) of {label} omitted to keep the prompt a reasonable size.)_"
    )


DIFFICULTY_RUBRIC = """N/A -- Not a dev task at all: an automated/informational notification (e.g. a Business Central "environment updated successfully" or "update scheduled" e-mail that generated a case with no complaint/error/ask in it), or a pure CRM triage/closure action with no code-level work to scope. Different from "1" -- "1" is still a real (if tiny) task; N/A means there is nothing to rate on a dev-effort scale at all. Don't force these into "1" (trivial) or "9"/"10" (underspecified) just to produce a number -- both misrepresent the same situation: there's no development work here to size.
1  -- Trivial: a one-line/config value change, no real logic, obviously correct on sight.
2  -- Very small: a few lines in one file, follows an existing pattern exactly.
3  -- Small: one file/module, straightforward logic, tests follow an existing pattern.
4  -- Small-medium: a couple of files, minor new logic, needs some care but no new concepts.
5  -- Medium: multiple files, real logic, needs to understand existing code before touching it.
6  -- Medium-high: multiple modules/layers, non-trivial edge cases, meaningful new tests needed.
7  -- High: cross-cutting change touching several subsystems, or a fix in unfamiliar code, needs careful verification.
8  -- High: new abstractions/data flows, related bugs visible in the branches/PRs above, real regression risk.
9  -- Very high: ambiguous requirements or root cause unclear from the material, wide blast radius, extensive verification needed.
10 -- Highest: the case is fundamentally underspecified or needs an architecture-level decision beyond what a guide can fully spec."""


PROMPT_TEMPLATE = """You are helping a support engineer who has just picked up a case and needs a \
plain-language plan to actually go solve it -- assume they may not have touched this codebase before.

Below is the full case brief (CRM details, linked Azure DevOps branches/PRs), plus live \
Azure DevOps detail on those branches/PRs (their commit messages, changed files, and review \
comments) that goes beyond what the brief itself shows.

Write a Markdown guide titled "# Case {case_number}" a newcomer could follow start \
to finish. Cover, in this order:

1. **Readiness check** -- REQUIRED on every single guide, no exceptions, even a trivial \
   closure/triage case with no dev work at all: the very first thing after the title, before \
   the summary or anything else -- \
   `**Ready for Implementation:** Yes` or `**Ready for Implementation:** No -- <short reason>`. \
   Answer No only when the case is blocked on something a developer cannot resolve alone -- info \
   only the customer can supply, a decision or approval only a team lead/manager can make, or an \
   action that depends on another person or team. Answer Yes even when the case is difficult, \
   ambiguous, or under-specified in ways a competent developer could reasonably resolve while \
   implementing -- this line is about who has to act next, not how hard the work is.
2. **Implementation difficulty** -- ALSO REQUIRED on every single guide, no exceptions, \
   regardless of the readiness answer above and regardless of how trivial or how far outside \
   normal dev work the case turns out to be: one line, immediately after the readiness line from \
   step 1 -- nothing in between, still before the summary -- either \
   `**Implementation Difficulty:** X/10 -- <short reason>` where X is picked from the fixed \
   DIFFICULTY RUBRIC below, or `**Implementation Difficulty:** N/A -- <short reason>` for a case \
   that's an automated/informational notification or pure triage/closure with no code-level work \
   to scope at all (see the rubric's own N/A entry -- do NOT force one of these into "1" or into \
   "9"/"10" just to produce a number; both misrepresent the exact same "nothing to size" \
   situation, and doing that makes N/A-shaped cases score inconsistently from one guide to the \
   next). Use the rubric's bands/wording as given either way -- don't invent your own scale. Rate \
   it even when readiness above is No -- it's still useful once the social steps are resolved. \
   Only *after* \
   this line, if (and only if) readiness above was No, add a \
   "## Before You Start -- Social Steps" section with a concrete numbered list of what to do -- \
   e.g. "Reply to the customer asking whether X or Y is intended", "Ask your team lead whether \
   this needs manager sign-off", "Call [team/person] to confirm Z". If readiness was Yes, do not \
   add that section at all. These two status lines (readiness, then difficulty) always come as a \
   back-to-back pair right after the title, before the case summary and everything else -- the \
   Social Steps section, if there is one, comes after both, never between them and never before \
   them.
3. **What this case is about** -- a plain-language summary of the customer's problem, pulled \
   from the case description below. Comes after the two status lines (and the Social Steps \
   section, if there is one) -- you already have the full case material below before writing \
   anything, so put the two required status lines first regardless of where the summary ends up \
   landing in length.
4. **Get set up** -- the exact `git clone` / `cd` / `git checkout -b` commands to run (use the \
   suggested repo/branch below if present; otherwise say plainly that no repo has been \
   identified yet and what to do about it). If the suggested repo below is marked as guessed \
   (fuzzy-matched from the customer name, not confirmed in Azure DevOps), you MUST carry that \
   warning into this section verbatim -- never drop it or present a guess as a confirmed repo.
5. **What's already been tried** -- if there are related branches/PRs below, summarize concretely \
   what they changed (from their commit messages / changed files / review comments) and whether \
   they look finished, still in review, or abandoned. If there's nothing related, say so plainly.
6. **What still needs to be developed, and how** -- a concrete, numbered plan grounded in the \
   actual case description and whatever the related branches/PRs reveal about the codebase's \
   shape -- not generic advice. Call out open questions if the material below isn't specific \
   enough to be concrete about something.
7. **How to verify and ship it** -- how to test the fix against the case description, and how to \
   get it reviewed/merged (PR against the branch/repo from step 4).

Be concrete wherever the material below supports it; be honest about gaps rather than inventing \
detail that isn't there. Output only the Markdown guide itself, nothing else -- no preamble, no \
"here's your guide" framing.

Before you finish: double-check the guide includes BOTH the `**Ready for Implementation:**` line \
and the `**Implementation Difficulty:** X/10` line from steps 1-2 above, back-to-back, as the \
very first thing after the title -- before the summary, before everything else. Every guide \
needs both, with no exceptions -- including a case that turns out to be pure triage/closure with \
no code to write at all (that's still ratable on the rubric, typically at the low end).

--- DIFFICULTY RUBRIC (fixed bands -- use these, not your own judgment of what a number means) ---
{difficulty_rubric}

--- CASE BRIEF ---
{brief}

--- SUGGESTED REPO/BRANCH ---
{suggested_repo}

--- LIVE AZURE DEVOPS DETAIL ---
{ado_detail}

--- HOUSE STYLE EXAMPLE (tone/structure reference only -- an unrelated case, don't reuse its facts) ---
{example_guide}
"""


def build_prompt(case_number, brief_text, suggested_repo_text, ado_detail_text, example_guide_text):
    return PROMPT_TEMPLATE.format(
        case_number=case_number,
        brief=brief_text.strip(),
        suggested_repo=suggested_repo_text,
        ado_detail=ado_detail_text,
        example_guide=example_guide_text,
        difficulty_rubric=DIFFICULTY_RUBRIC,
    )


def _add_guess_warning(guide_text, suggested_repos):
    """Forces a visible warning right after the guide's title when any
    suggested repo came from a fuzzy customer-name match rather than a
    confirmed Azure DevOps hit -- a code-level guarantee rather than
    hoping claude's own rewrite of the Get Set Up section keeps
    format_suggested_repo's inline "(guessed...)" annotation (the prompt
    does ask it to, but a human shouldn't have to trust that held)."""
    if not repo_suggest.any_guessed(suggested_repos):
        return guide_text
    warning = (
        "> ⚠️ **Repo/branch guessed, not confirmed.** The repo suggested below was "
        "fuzzy-matched from the CRM customer name -- Azure DevOps has no branch or PR "
        "linked to this case yet. Verify it's the right repo (and pick your own branch "
        "name if the suggested one doesn't fit) before running any clone/checkout "
        "commands below.\n"
    )
    heading, sep, rest = guide_text.partition("\n")
    if not sep:
        return guide_text + "\n\n" + warning
    return f"{heading}\n\n{warning}{rest}"


def _looks_like_guide(text, case_number):
    """Cheap sanity check that claude's output is actually the requested
    guide and not, say, a refusal or stray preamble that slipped past the
    "output only the guide" instruction. Deliberately loose (just a leading
    Markdown heading mentioning the case number) and only ever used to warn,
    never to block writing the file -- a human can judge the actual content
    far better than this can."""
    head = text.lstrip()[:200].lower()
    return head.startswith("#") and str(case_number).lower() in head


_DIFFICULTY_RE = re.compile(r"(?im)\*\*Implementation Difficulty:\*\*\s*(?:\d{1,2}\s*/\s*10|N/A)")


def _has_difficulty_rating(text):
    """Same spirit as _looks_like_guide: a loose check that claude actually
    followed the "Implementation difficulty" instruction (see
    PROMPT_TEMPLATE/DIFFICULTY_RUBRIC) instead of silently dropping it. Used
    both to decide whether ensure_difficulty_rating needs to do anything,
    and as main's own final warn-only check for the rare case where every
    retry attempt still came back unparseable.

    Searches the whole text, not just a leading slice -- an earlier
    `text[:1000]` cap meant to catch a dropped line as a "not near the top"
    sanity check instead produced false negatives on a real, correctly
    written line: a verbose case summary (step 1) or an inserted "Before
    You Start -- Social Steps" section (step 3's own instruction, when
    readiness is No) can easily push the line past the first 1000
    characters even though it's exactly where the prompt asked for it. A
    false negative here isn't just a wrong warning -- ensure_difficulty_rating
    trusts it and would splice in a second, duplicate line right next to a
    perfectly good first one."""
    return bool(_DIFFICULTY_RE.search(text))


# Same marker as _DIFFICULTY_RE, but capturing the whole line (including the
# "-- <reason>" part _DIFFICULTY_RE doesn't need) -- used to pull a usable
# line back out of ensure_difficulty_rating's own retry response, not just
# to detect whether one is present.
_DIFFICULTY_LINE_RE = re.compile(r"(?im)^.*\*\*Implementation Difficulty:\*\*\s*(?:\d{1,2}\s*/\s*10|N/A).*$")

_DIFFICULTY_RETRY_ATTEMPTS = 2

_DIFFICULTY_RETRY_PROMPT = """The case guide below is missing its required "Implementation Difficulty" \
line. Using the fixed rubric below, output exactly one line and nothing else -- no preamble, no \
markdown fence, no explanation beyond what the line itself allows:

**Implementation Difficulty:** X/10 -- <short reason>

...or, if the rubric's own N/A entry applies (an automated/informational notification or pure \
triage/closure case with no code-level work to scope at all -- not the same as a genuinely \
trivial "1"):

**Implementation Difficulty:** N/A -- <short reason>

--- DIFFICULTY RUBRIC (fixed bands -- use these, not your own judgment of what a number means) ---
{difficulty_rubric}

--- CASE GUIDE ---
{guide_text}
"""


def _insert_difficulty_rating(guide_text, line):
    """Splices a recovered difficulty line into the guide at the same spot
    PROMPT_TEMPLATE asks claude to put it -- right after the Readiness
    check line if there is one (matching step 3 following step 2), \
    otherwise right after the title heading."""
    m = _READINESS_RE.search(guide_text)
    if m:
        end = guide_text.index("\n", m.end()) if "\n" in guide_text[m.end():] else len(guide_text)
        return f"{guide_text[:end]}\n{line}{guide_text[end:]}"
    heading, sep, rest = guide_text.partition("\n")
    if not sep:
        return f"{guide_text}\n\n{line}\n"
    return f"{heading}\n\n{line}\n{rest}"


def ensure_difficulty_rating(guide_text, model=None, extra_args=None, timeout=600,
                              attempts=_DIFFICULTY_RETRY_ATTEMPTS):
    """Guarantees the guide has a parseable Implementation Difficulty line
    instead of just warning when claude drops it -- a code-level guarantee,
    the same pattern _add_guess_warning already uses for the repo-guess
    warning, rather than hoping claude followed the prompt instruction.
    (Before this existed, a guide claude dropped the line from stayed
    broken forever -- case-getter would keep reprocessing the same case
    every single run trying to get a difficulty rating out of it; see its
    own CLAUDE.md section. A full case-guide rerun is a far more expensive
    way to fix the exact same one-line problem than retrying just that
    line here.)

    Each retry is a small, focused follow-up call -- just the guide text
    and the fixed rubric, asking for exactly one line back -- rather than
    regenerating the whole guide, so this stays cheap even across a few
    attempts. Still never blocks writing the file if every attempt comes
    back unparseable (see main's own warning for that remaining, very
    unlikely case) -- a human can judge the actual content far better than
    this can."""
    for _ in range(attempts):
        if _has_difficulty_rating(guide_text):
            return guide_text
        prompt = _DIFFICULTY_RETRY_PROMPT.format(
            difficulty_rubric=DIFFICULTY_RUBRIC, guide_text=guide_text[:4000],
        )
        response = call_claude(prompt, model=model, extra_args=extra_args, timeout=timeout)
        m = _DIFFICULTY_LINE_RE.search(response)
        if m:
            guide_text = _insert_difficulty_rating(guide_text, m.group(0).strip())
    return guide_text


# case-solve reads this exact line back out of the finished guide to decide
# whether to implement at all (see case-solve/CLAUDE.md's "Social readiness
# gate" section) -- a filesystem-contract shape, same pattern as
# _CASE_TITLE_RE/_CUSTOMER_RE parsing case-brief's output above. Keep this
# regex and case-solve's copy of it in sync if the wording ever changes.
_READINESS_RE = re.compile(r"(?im)\*\*Ready for Implementation:\*\*\s*(Yes|No)\b")


def _has_readiness_marker(text):
    """Same spirit as _has_difficulty_rating: a loose, warn-only check that
    claude actually answered the "Readiness check" instruction (see
    PROMPT_TEMPLATE) instead of silently dropping it -- case-solve depends
    on this line being present to know whether it's safe to implement.
    Never blocks writing the file -- a human can judge the actual content
    far better than this can. Searches the whole text, not just a leading
    slice -- see _has_difficulty_rating's docstring for why a truncated
    search produces false negatives, not just a stricter check."""
    return bool(_READINESS_RE.search(text))


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
    parser.add_argument("--brief-dir", metavar="DIR", help="Where to look for the case brief (default: config.json's brief_dir, ../case-brief/briefs)")
    parser.add_argument("--output-dir", metavar="DIR", help="Where to write the guide (default: config.json's output_dir, ./guides)")
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
    return parser


def main():
    args = build_parser().parse_args()
    cfg = load_config()

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

    guide_path = os.path.join(output_dir, writer.guide_filename(f"case-{args.case_number}"))
    if os.path.exists(guide_path) and os.path.getmtime(guide_path) >= os.path.getmtime(brief_path):
        print(f"{guide_path} is already up to date with the brief.")
        return

    print(f"Reading brief: {brief_path}")
    with open(brief_path, "r", encoding="utf-8") as f:
        brief_text = f.read()

    print("Fetching live Azure DevOps detail on related branches/PRs...")
    detail, ado_error = gather_ado_detail(cfg, args.case_number)
    ado_detail_text = format_ado_detail(detail, ado_error)
    ado_detail_text = _truncate(ado_detail_text, MAX_ADO_DETAIL_CHARS)

    example_text = None
    if not args.no_example:
        example_text = find_example_guide(output_dir, os.path.basename(guide_path), cfg["claude"]["example_count"])
    example_text = _truncate(
        format_example_guide(example_text), MAX_EXAMPLE_CHARS, label="the house-style example guide",
    )

    print("Working out which repo/branch to suggest...")
    customer = _extract_customer(brief_text)
    branch = repo_suggest.branch_name(args.case_number, _extract_case_title(brief_text))
    suggested_repos = gather_suggested_repo(cfg, customer, detail)
    suggested_repo_text = repo_suggest.format_suggested_repo(suggested_repos, branch)

    agent_name = None if args.no_agent else cfg["claude"]["agent"]
    prompt = build_prompt(args.case_number, brief_text, suggested_repo_text, ado_detail_text, example_text)

    model = args.model if args.model is not None else cfg["claude"]["model"]
    extra_args = _resolve_extra_args(args, cfg)
    timeout = args.timeout if args.timeout is not None else cfg["claude"]["timeout"]

    print("Asking claude to write the guide (this can take a minute)...")
    guide_text = call_claude(prompt, model=model, extra_args=extra_args, timeout=timeout, agent_name=agent_name)

    if not _looks_like_guide(guide_text, args.case_number):
        print(
            f"Warning: claude's output doesn't look like the expected \"# Case {args.case_number}\" guide "
            "(no leading heading / case number in the first 200 characters) -- writing it "
            "anyway, but take a look before trusting it.",
            file=sys.stderr,
        )
    if not _has_difficulty_rating(guide_text):
        print("The guide is missing its Implementation Difficulty line -- asking claude for just that...")
        guide_text = ensure_difficulty_rating(guide_text, model=model, extra_args=extra_args, timeout=timeout)
    if not _has_difficulty_rating(guide_text):
        # Every retry attempt in ensure_difficulty_rating still came back
        # unparseable -- very unlikely, but don't block writing the file
        # over it; a human can judge/add it far better than another retry
        # loop here could.
        print(
            "Warning: claude's output doesn't include the expected \"**Implementation Difficulty:** X/10\" "
            "line, even after retrying -- writing it anyway, but take a look before trusting it.",
            file=sys.stderr,
        )
    if not _has_readiness_marker(guide_text):
        print(
            "Warning: claude's output doesn't include the expected \"**Ready for Implementation:** "
            "Yes/No\" line -- case-solve treats a missing marker as ready by default, so double-check "
            "this guide before running case-solve on it.",
            file=sys.stderr,
        )

    guide_text = _add_guess_warning(guide_text, suggested_repos)

    path = writer.write_and_open(
        guide_text,
        output_dir,
        f"guide-{args.case_number}",
    )
    print(f"\nGuide written to {path}")


if __name__ == "__main__":
    main()
