"""Renders the collected case data into a Markdown brief."""
import os
import re
import subprocess


def _safe_name(text):
    return re.sub(r"[^\w.-]+", "_", str(text)).strip("_") or "unlabeled"


def _slugify(text, max_len=50):
    if not text:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


def _branch_name(case_number, title):
    case_part = _safe_name(case_number).replace("_", "-")
    slug = _slugify(title)
    return f"{case_part}-{slug}" if slug else case_part


def build_markdown(case_number, crm_results, branches, pull_requests, bc_results,
                    ado_error=None, include_bc=True, prs_truncated=False, max_prs=None,
                    suggested_repos=None):
    lines = [f"# Case {case_number}", ""]

    lines.append("## CRM Case(s)")
    if not crm_results:
        lines.append("_No CRM case tab found open in the automation Chrome window._")
    for c in crm_results:
        if c.get("error"):
            lines.append(f"- ⚠️ {c['error']} ({c.get('url')})")
            continue
        lines.append(f"### {c.get('title') or c.get('ticket_number') or c.get('id')}")
        lines.append(f"- **Ticket #:** {c.get('ticket_number') or '—'}")
        lines.append(f"- **Customer:** {c.get('customer') or '—'}")
        lines.append(f"- **Owner:** {c.get('owner') or '—'}")
        lines.append(f"- **Priority:** {c.get('priority') or '—'}")
        lines.append(f"- **Status:** {c.get('status') or '—'}")
        lines.append(f"- **Created:** {c.get('created_on') or '—'}")
        lines.append("")
        lines.append("**Description:**")
        lines.append("")
        lines.append(c.get("description") or "_(none)_")
        lines.append("")
    lines.append("")

    lines.append("## Azure DevOps — Related Branches & Pull Requests")
    if ado_error:
        lines.append(f"_Could not query Azure DevOps: {ado_error}_")
    else:
        lines.append("**Branches:**")
        if not branches:
            lines.append("_No matching branches found._")
        else:
            for b in branches:
                lines.append(f"- [{b['project']}/{b['repo']}: {b['branch']}]({b['url']})")
        lines.append("")
        lines.append("**Pull requests:**")
        if not pull_requests:
            lines.append("_No matching pull requests found._")
        else:
            for pr in pull_requests:
                lines.append(f"- [{pr['project']}/{pr['repo']} !{pr['id']}]({pr['url']}) — {pr.get('title')} ({pr.get('status')}, by {pr.get('created_by') or '—'})")
        if prs_truncated:
            lines.append("")
            lines.append(f"_Only searched the {max_prs} most recent pull requests per project (--max-prs to widen) -- an older one could be missed._")
    lines.append("")

    lines.append("## Business Central — Open Tabs")
    if not include_bc:
        lines.append("_Skipped for this brief (pass --with-bc to include it)._")
    elif not bc_results:
        lines.append("_No Business Central tab found open._")
    for bc_ in bc_results:
        lines.append(f"### {bc_.get('page_title') or bc_.get('url')}")
        lines.append(f"- **URL:** {bc_.get('url')}")
        fields = bc_.get("fields") or []
        if fields:
            for f in fields:
                lines.append(f"- **{f['label']}:** {f['value']}")
        elif bc_.get("raw_text"):
            lines.append("_No labeled fields matched — dumping visible page text instead (see lib/bc_scrape.py to improve the selector):_")
            lines.append("")
            lines.append("```")
            lines.append(bc_["raw_text"])
            lines.append("```")
        else:
            lines.append("_Nothing extracted from this page — check lib/bc_scrape.py._")
        lines.append("")
    lines.append("")

    lines.append("## Useful Commands")
    case_title = next((c.get("title") for c in crm_results if not c.get("error")), None)
    branch_name = _branch_name(case_number, case_title)

    # (project, repo) -> {clone_url, source}. Confirmed matches (a branch/PR
    # already references this case) take priority over an auto-matched guess
    # for the same repo, since setdefault only fills in what's missing.
    repos = {}
    for item in list(branches) + list(pull_requests):
        if item.get("clone_url"):
            repos.setdefault((item["project"], item["repo"]), {"clone_url": item["clone_url"], "source": "ado-search"})
    for item in (suggested_repos or []):
        key = (item["project"], item["repo"])
        if key not in repos:
            repos[key] = {"clone_url": item.get("clone_url"), "source": item.get("source", "guess")}

    if not repos:
        lines.append("_No repo identified yet. Once you know which one:_")
        lines.append("")
        lines.append("```")
        lines.append("git clone <repo-url>")
        lines.append("cd <repo-folder>")
        lines.append(f"git checkout -b {branch_name}")
        lines.append("```")
        lines.append("")
        lines.append("_Tip: set `customer_repo_map` in config.json, or pass `--repo PROJECT/REPO`, "
                      "to get this filled in automatically next time._")
    else:
        for (project, repo), info in repos.items():
            lines.append(f"**{project}/{repo}:**" + (" _(guessed from customer name — verify before using)_" if info["source"] == "auto-match" else ""))
            lines.append("")
            lines.append("```")
            if info.get("clone_url"):
                lines.append(f"git clone {info['clone_url']}")
            else:
                lines.append(f"git clone <clone-url-for-{project}/{repo}>")
            lines.append(f"cd {repo}")
            lines.append(f"git checkout -b {branch_name}")
            lines.append("```")
            lines.append("")
    lines.append("")

    lines.append("## Next Steps")
    lines.append("- [ ] Reproduce locally")
    lines.append("- [ ] Identify root cause")
    lines.append("- [ ] Implement fix")
    lines.append("- [ ] Verify against case description")
    lines.append("")

    return "\n".join(lines)


def write_and_open(markdown, output_dir, case_number, open_in_vscode=True):
    os.makedirs(output_dir, exist_ok=True)
    filename = f"case-{_safe_name(case_number)}.md"
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)

    if open_in_vscode:
        try:
            subprocess.run(["code", path], shell=True, check=False)
        except FileNotFoundError:
            pass

    return path
