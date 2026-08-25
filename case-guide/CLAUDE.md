# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```
..\.venv\Scripts\Activate.ps1   # from case-guide/, on Windows -- repo root's venv has everything

python case_guide.py T2611845                 # full run: needs a brief already written by case-brief, and the claude CLI on PATH
python case_guide.py T2611845 --model opus    # use a different model for this run
python case_guide.py -h                       # full flag list
```

Requires a brief already at `../case-brief/case-briefs/case-<code>.md` (run
case-brief's `case_brief.py <code>` first) and the `claude` CLI installed + logged in
-- every run calls `claude`, there's no dry/preview mode.

```
python -m unittest discover -s tests -v   # from case-guide/ -- 88 tests, mocked, no network
python -m pytest tests                    # equivalent, if pytest is installed
```

Deliberately not exhaustive — covers what's worth locking in with a test rather than
eyeballing: the case-number sanitizer, the brief-lookup traversal guard and
ambiguous-match safety, the config-comment stripper, `lib/ado_api.py`'s
raise-vs-swallow auth-error policy and silent-truncation warnings (mocked), and
`lib/repo_suggest.py`'s fuzzy-match ambiguity guard and confirmed-beats-guessed merge
(`tests/test_repo_suggest.py`, plus `_extract_customer`/`_extract_case_title`'s
brief-parsing in `tests/test_case_guide.py`). Low-risk rendering/formatting branches
are skipped rather than testing every one. What no test here can cover (see
TODO.md): a real `claude` call and a live Azure DevOps org.

## Architecture

Independent from case-brief at the business-logic level — reading the case's data is
a filesystem contract (this reads the Markdown file `case_brief.py` already wrote),
and `lib/ado_api.py` here is a deliberate standalone copy of case-brief's own module
for its search/query logic, not an import (see TODO.md's resolved "duplication" entry
for what's shared vs. not); a fix to case-brief's `find_related`/pagination/
error-handling does not automatically reach this copy and vice versa. What both
copies' PAT-auth-header construction *does* share is the repo-root `shared/` package
(`shared/ado_auth.py`, also used by case-brief) — that piece is pure, stable, and
was byte-for-byte identical across both before being extracted, unlike the search
logic above. (A third copy in `app/azdo_check.py` also shared it once, before the
Streamlit desktop app was scrapped entirely -- see the "Scrap the Streamlit desktop
app" commit; `app/` has no Python source left today.) `lib/repo_suggest.py` is the same
independent-copy story as `ado_api.py`'s search logic, one level newer:
case-brief used to own repo-suggestion (guess/render a clone-able repo + branch name)
and render it as its own "Useful Commands" brief section; that moved here (see
case-brief/CLAUDE.md) since this project is the one that actually needs it for the
guide's "Get set up" step, and case-brief's brief is meant to be just the facts.

**Repo suggestion (`lib/repo_suggest.py::resolve_suggested_repos`)** decides which
repo(s)/branch to suggest, even when Azure DevOps found zero matching branches/PRs
yet (the common case for a brand-new case). There's no manual override (no `--repo`
flag, no `customer_repo_map`) — it's purely a fuzzy-match of the case's customer name
against ADO project names, then repo names, via `difflib.SequenceMatcher`
(`best_fuzzy_match` requires the top match to both clear a threshold *and* beat the
runner-up by a margin — an ambiguous guess is treated as no guess, since it would
suggest the wrong repo silently). Since this project only has the finished brief
Markdown to work with (no CRM data of its own), `case_guide.py::_extract_customer` /
`_extract_case_title` pull the customer name and case title back out of it by regex,
relying on case-brief's `lib/report.py` always rendering them in the same fixed spot
(first `### ` heading, and the `- **Customer:** ...` bullet right after it) — a
missing customer renders as report.py's `—` placeholder, which `_extract_customer`
treats as "no customer" rather than a literal name to fuzzy-match against.
`gather_suggested_repo` merges this guess with any confirmed match from this run's
own live Azure DevOps search (`lib/repo_suggest.py::merge_confirmed_and_guessed`,
same "confirmed beats guessed" priority case-brief's report.py used to apply).
`lib/repo_suggest.py::format_suggested_repo` renders the result as its own prompt
section (`--- SUGGESTED REPO/BRANCH ---`) rather than a finished "Get set up" heading
— `claude` still writes that section's actual prose from it.

**A guessed repo is never presented as confirmed, at two layers:**
`format_suggested_repo` tags each auto-matched entry inline ("⚠️ guessed from
customer name...") in the prompt itself, and `PROMPT_TEMPLATE`'s step 2 instructs
`claude` to carry that tag into its own "Get set up" prose verbatim. Neither of those
is a hard guarantee on its own -- `claude` could still paraphrase the warning away --
so `case_guide.py::_add_guess_warning` is the actual guarantee: after `call_claude`
returns, if `repo_suggest.any_guessed(suggested_repos)` is true, it force-inserts a
standalone warning block right after the guide's title, independent of whatever
`claude` did with the prompt's hint. This only fires when a repo came from the fuzzy
customer-name match (`source == "auto-match"`) -- a repo confirmed via this run's own
Azure DevOps search never gets it.

`.claude/agents/case-guide-writer.md` is the persona the headless `claude` call runs
as (step 7 below) — a normal, project-scoped Claude Code agent file, editable
independently of `case_guide.py`; its Markdown body is the actual system prompt.

**Pipeline (`main` in `case_guide.py`):**

1. `find_brief` locates the brief by exact filename match on the sanitized case
   number, falling back to a unique substring glob match; ambiguous/missing matches
   are reported rather than guessed. `_sanitize_case_number` reuses
   `writer.UNSAFE_CHARS` (same character allowlist as the output-filename sanitizer)
   specifically to close off path-traversal via a malicious/mistyped case code before
   it reaches a filesystem path or glob pattern.
2. `gather_ado_detail` re-runs the same branch/PR search case-brief does, then
   fetches one level deeper per hit — commit messages, changed files, review
   comments — via `_enrich_branch`/`_enrich_pr` run concurrently through a
   `ThreadPoolExecutor` (`ado_api.MAX_WORKERS`), sharing one `requests.Session` with
   the initial search. `ado_api.AdoAuthError` (401/403) is deliberately NOT swallowed
   like other request failures — an expired/under-scoped PAT is treated as a hard
   error rather than silently reported as "no related work found", since the two are
   very different claims to make to someone picking up a case. If `azure_devops.org_url`
   isn't configured, this just yields that as the error -- there's no skip flag.
3. `format_ado_detail` renders that into Markdown, folding any partial-search warnings
   (capped PR listing, a branch whose commit fetch failed, etc.) into a visible "this
   search may be incomplete" note rather than presenting a partial result as complete.
4. `_truncate` caps the assembled ADO-detail text at the fixed `MAX_ADO_DETAIL_CHARS`
   (visibly, with an omitted-character count) before it goes into the prompt — a case
   with heavy branch/PR activity has no other size bound on what gets inlined. Same
   helper (with a different `label`/limit) caps the house-style example below at
   `MAX_EXAMPLE_CHARS`. Both are fixed constants, not configurable -- no CLI flag ever
   existed for either.
5. One more context source feeds the same prompt, following the same "explain why
   it's empty rather than silently omitting" policy as step 3: `find_example_guide`
   picks the most recently written other guide in `output_dir` (`--no-example` /
   `claude.example_count=0` disables) as a tone/structure anchor —
   `format_example_guide` is explicit it's not to be treated as source material.
   (An earlier version of this step also sampled the target project's other recent
   completed PRs as a branch/reviewer/naming convention reference
   (`gather_style_prs`/`ado_api.get_recent_prs`) — removed since it rarely changed
   the guide's advice enough to justify the extra live ADO call; `case-guide-writer`'s
   own house-style knowledge covers that ground now.)
6. `gather_suggested_repo` (see "Repo suggestion" above) resolves the repo/branch to
   suggest for step 2 of the guide ("Get set up"), and
   `repo_suggest.format_suggested_repo` renders it into its own prompt section.
7. `build_prompt` fills `PROMPT_TEMPLATE` (brief + suggested repo/branch + live ADO
   detail + house-style example, one fixed 5-section guide structure) and
   `call_claude` shells out to `claude -p` non-interactively, piping the prompt on
   stdin. Resolved via `shutil.which` (not `shell=True`) so `--claude-arg` values
   can't be re-parsed/expanded by cmd.exe. The call runs as the `case-guide-writer`
   project-scoped agent (`.claude/agents/case-guide-writer.md` — brevity, house-style,
   and convention-matching skills; `tools: Read` since Claude Code refuses a
   zero-tool agent, tighter than today's unrestricted default toolset) via
   `--agent`, with `cwd=HERE` so the agent file resolves regardless of the caller's
   own working directory — `--no-agent` / `claude.agent=null` falls back to claude's
   plain default persona. No `--permission-mode` is set by default since the task is
   pure text generation with everything already inlined — a
   `subprocess.run(..., timeout=...)` is still there as a safety net in case an
   unexpected permission prompt ever hangs it.
8. `_looks_like_guide` is a loose sanity check (leading `#`, case number in the
   first 200 chars) on `claude`'s output — used only to print a warning, never to
   block writing the file; a human judges the actual content.

**Skip-if-unchanged:** if a guide already exists and is newer than its brief,
`main` opens the existing guide instead of re-spending an ADO search + a `claude`
call. There's no override flag -- delete the existing guide file to force a
regenerate.

**Config merge order** mirrors case-brief: `DEFAULTS` → `config.json` (deep-merged,
then `strip_comments` drops any leading-underscore documentation keys like
`_comment` so they don't leak into dicts handed to `ado_api.*`) → CLI flags.
`azure_devops.pat_env_var`/`max_prs`/`style_pr_sample`, `customer_repo_map`, and
`open_in_vscode` were all removed as config keys -- fixed to a hardcoded constant,
a fixed sample size, no override, and always-on respectively, since none of them
had ever actually been changed from their default.
`_resolve_extra_args` is the one exception to "flags always win": `--no-claude-extra-args`
must be able to say "run with zero extra args," which a plain `action="append"` flag
can never express since it can only add, not replace-with-nothing.
