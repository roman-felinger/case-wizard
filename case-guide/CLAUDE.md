# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python case_guide.py T2611845 --show-prompt   # assemble the prompt and print it -- no claude call, no ADO query cost
python case_guide.py T2611845 --skip-ado      # brief content only, skip the live ADO re-query
python case_guide.py T2611845                 # full run: needs a brief already written by case-brief, and the claude CLI on PATH
python case_guide.py T2611845 --force         # regenerate even if the guide is already newer than the brief
python case_guide.py -h                       # full flag list
```

Requires a brief already at `../case-brief/case-briefs/case-<code>.md` (run
case-brief's `case_brief.py <code>` first) and the `claude` CLI installed + logged in
for any run that doesn't use `--show-prompt`.

```
python -m unittest discover -s tests -v   # from case-guide/ -- 31 tests, mocked, no network
python -m pytest tests                    # equivalent, if pytest is installed
```

Deliberately not exhaustive — covers what's worth locking in with a test rather than
eyeballing: the case-number sanitizer, the brief-lookup traversal guard and
ambiguous-match safety, the config-comment stripper, and `lib/ado_api.py`'s
raise-vs-swallow auth-error policy and silent-truncation warnings (mocked). Low-risk
rendering/formatting branches are skipped in favor of `--show-prompt` (eyeball the
real output) rather than testing every branch. What no test here can cover (see
TODO.md): a real `claude` call and a live Azure DevOps org.

## Architecture

Independent from case-brief — **no shared imports**, only a filesystem contract: this
reads the Markdown file `case_brief.py` already wrote. `lib/ado_api.py` here is a
deliberate standalone copy of case-brief's own module, not an import — see TODO.md's
"Consider whether ... duplication is worth it" entry before changing that; a fix to
case-brief's `find_related`/pagination/error-handling does not automatically reach
this copy and vice versa.

`.claude/agents/case-guide-writer.md` is the persona the headless `claude` call runs
as (step 6 below) — a normal, project-scoped Claude Code agent file, editable
independently of `case_guide.py`; its Markdown body is the actual system prompt.

**Pipeline (`main` in `case_guide.py`):**

1. `find_brief` locates the brief by exact filename match on the sanitized case
   number, falling back to a unique substring glob match; ambiguous/missing matches
   are reported rather than guessed. `_sanitize_case_number` reuses
   `writer.UNSAFE_CHARS` (same character allowlist as the output-filename sanitizer)
   specifically to close off path-traversal via a malicious/mistyped case code before
   it reaches a filesystem path or glob pattern.
2. Unless `--skip-ado`, `gather_ado_detail` re-runs the same branch/PR search
   case-brief does, then fetches one level deeper per hit — commit messages, changed
   files, review comments — via `_enrich_branch`/`_enrich_pr` run concurrently through
   a `ThreadPoolExecutor` (`ado_api.MAX_WORKERS`), sharing one `requests.Session` with
   the initial search. `ado_api.AdoAuthError` (401/403) is deliberately NOT swallowed
   like other request failures — an expired/under-scoped PAT is treated as a hard
   error rather than silently reported as "no related work found", since the two are
   very different claims to make to someone picking up a case.
3. `format_ado_detail` renders that into Markdown, folding any partial-search warnings
   (capped PR listing, a branch whose commit fetch failed, etc.) into a visible "this
   search may be incomplete" note rather than presenting a partial result as complete.
4. `_truncate` caps the assembled ADO-detail text at `claude.max_ado_detail_chars`
   (visibly, with an omitted-character count) before it goes into the prompt — a case
   with heavy branch/PR activity has no other size bound on what gets inlined. Same
   helper (with a different `label`/`config_key`) caps the house-style example below.
5. Two more context sources feed the same prompt, both skippable and both following
   the same "explain why it's empty rather than silently omitting" policy as step 3:
   `find_example_guide` picks the most recently written other guide in `output_dir`
   (`--no-example` / `claude.example_count=0` disables) as a tone/structure anchor —
   `format_example_guide` is explicit it's not to be treated as source material.
   `gather_style_prs` → `ado_api.get_recent_prs` samples the target project's other
   recent completed PRs (`_pick_style_project` picks the project: configured, or the
   case's own single matched project, else skipped with a reason) so the guide can
   ground branch/reviewer/naming advice in this team's actual conventions instead of
   generic guesses (`--no-style-prs` / `azure_devops.style_pr_sample=0` disables;
   implied by `--skip-ado`, which never opens an ADO session at all).
6. `build_prompt` fills `PROMPT_TEMPLATE` (brief + live ADO detail + house-style
   example + style-reference PRs, one fixed 5-section guide structure) and
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
7. `_looks_like_guide` is a loose sanity check (leading `#`, "for dummies" in the
   first 200 chars) on `claude`'s output — used only to print a warning, never to
   block writing the file; a human judges the actual content.

**Skip-if-unchanged:** if a guide already exists and is newer than its brief,
`main` opens the existing guide instead of re-spending an ADO search + a `claude`
call — `--force` bypasses this.

**Config merge order** mirrors case-brief: `DEFAULTS` → `config.json` (deep-merged,
then `_strip_comments` drops any leading-underscore documentation keys like
`_comment` so they don't leak into dicts handed to `ado_api.*`) → CLI flags.
`_resolve_extra_args` is the one exception to "flags always win": `--no-claude-extra-args`
must be able to say "run with zero extra args," which a plain `action="append"` flag
can never express since it can only add, not replace-with-nothing.
