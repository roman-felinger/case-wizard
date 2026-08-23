# case-guide

Takes a case code, finds the brief [case-brief](../case-brief/) already wrote
for it, pulls one level deeper on any related Azure DevOps branches/PRs it
mentions (commit messages, changed files, review comments), and asks
`claude` (Claude Code, headless) to turn all of that into a plain-language
**"Case &lt;code&gt; for Dummies"** walkthrough: how to get set up (clone +
branch), what's already been tried, what still needs developing and how, and
how to verify/ship it.

That headless call runs as **case-guide-writer**, a small project-scoped
Claude Code agent (`.claude/agents/case-guide-writer.md`) with its own
brevity/house-style/convention-matching skills -- see "House style & team
conventions" below.

Independent from case-brief -- no shared code, just reads the Markdown file
it produced. Workflow: `case-brief XYZ` first to gather the case's context,
then `case-guide XYZ` to turn that brief into the guide.

## Setup

1. **Install dependencies** (or just use the checked-in `.venv`):
   ```
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. **Install the `claude` CLI** ([Claude Code](https://claude.com/claude-code))
   and make sure you're logged in -- this script shells out to it once per run.
3. **Config is optional**, same philosophy as case-brief: every setting has a
   default and can be overridden with a flag. If you want a persistent file:
   ```
   copy config.example.json config.json
   ```
   The only thing worth setting is `azure_devops.org_url` (or pass `--org-url`)
   if you want the live branch/PR detail step -- reuses the same `AZDO_PAT`
   env var as case-brief. Without it, pass `--skip-ado` to use only what's
   already in the brief.

## Usage

```
python case_guide.py T2611845
python case_guide.py T2611845 --skip-ado         # brief content only, no live ADO re-query
python case_guide.py T2611845 --show-prompt      # print the assembled prompt, don't call claude
python case_guide.py T2611845 --model opus
python case_guide.py T2611845 --no-open
python case_guide.py T2611845 --force            # regenerate even if already up to date
python case_guide.py T2611845 --no-agent         # plain claude persona, skip case-guide-writer
python case_guide.py T2611845 --no-example       # skip the previous-guide house-style example
python case_guide.py T2611845 --no-style-prs     # skip the other-recent-PRs convention sample
```

Run `python case_guide.py -h` for the complete list of flags.

Output lands in `case-guides/case-<code>-for-dummies.md` and opens in VS Code.
If a guide already exists and is newer than its brief, a plain run just opens
it instead of re-spending an Azure DevOps search and a `claude` call --
`--force` regenerates anyway.

## House style & team conventions

Three things feed the guide-writing call beyond the case's own brief + live
ADO detail, so the result reads like this team's own conventions rather than
generic AI advice:

1. **The `case-guide-writer` agent** (`.claude/agents/case-guide-writer.md`)
   -- a normal Claude Code agent file, not Python code, so its tone/brevity
   rules are editable directly without touching `case_guide.py`. Runs the
   whole headless call via `claude -p --agent case-guide-writer`.
2. **A house-style example** -- the most recently written other guide in
   `case-guides/`, included purely as a tone/structure anchor (never as
   source material for a different case's facts). Nothing to anchor to on
   the very first guide ever written.
3. **A convention sample** -- a handful of the same Azure DevOps project's
   other recent completed PRs (branch names, target branch, reviewers), so
   "Get set up" / "How to verify and ship it" reflect how this team actually
   branches/reviews/merges instead of generic guesses. Needs the same
   `azure_devops.org_url` as the live branch/PR detail step; skipped
   whenever that is (`--skip-ado`), or on its own via `--no-style-prs`.
   The project it samples from: `azure_devops.project` if configured,
   otherwise the case's own matched branches/PRs if they all point at one
   project -- otherwise it's skipped with a stated reason rather than
   guessing among several.

All three are on by default and independently toggleable
(`--no-agent`/`--no-example`/`--no-style-prs`, or their `config.json`
equivalents -- `claude.agent`, `claude.example_count`,
`azure_devops.style_pr_sample`; see `config.example.json`).

## Testing

```
python -m unittest discover -s tests -v
```

Covers what's actually worth locking in with a test rather than eyeballing:
the case-number sanitizer, the brief-lookup path-traversal guard and
ambiguous-match safety, the config-comment stripper, the house-style-example
picker, and the ADO request layer's raise-vs-swallow policy / auth-error
handling / silent-truncation warnings / recent-PR sampling (mocked).
Deliberately skips exhaustive coverage of low-risk rendering/formatting
branches -- those are easy to eyeball with `--show-prompt`. No network
access, no dependencies beyond what's already in `requirements.txt`.

## Layout

```
case_guide.py                          CLI entry point
lib/ado_api.py                         Azure DevOps REST lookups (own copy, not shared with case-brief)
lib/writer.py                          Writes the guide + opens it in VS Code
.claude/agents/case-guide-writer.md    The guide-writer's persona -- brevity/house-style/convention skills
tests/                                  Unit tests -- python -m unittest discover -s tests
config.example.json                    Template -- copy to config.json and edit that copy (optional)
```

## Status -- v0.2

Verified so far: everything covered by `tests/` (see Testing above), plus
several real end-to-end runs against case T2611845, a live Azure DevOps org
(artexis/BTECH), and a real `claude` install -- including the
`case-guide-writer` agent, the house-style example, and the style-PR sample
all actually populating and visibly improving the output (concrete
`test`-branch/reviewer-group/title conventions pulled from real PRs, instead
of generic guesses). Two things remain genuinely untested:

- **Only one project's conventions exercised end-to-end.** BTECH's PR
  sample (target-branch + reviewer-group pattern) is confirmed to help; a
  project with very different conventions, or one where the case's related
  work spans multiple projects (`_pick_style_project`'s "skip and say why"
  branch), hasn't been exercised for real.
- **The exact `claude -p --agent` invocation** is deliberately minimal (no
  `--permission-mode` set, `tools: Read` on the agent) since the prompt is
  pure text generation with everything inlined. If a real run ever hangs, add
  a permission-mode override via `--claude-arg` (see `config.example.json`)
  rather than guessing one here.

See `TODO.md` for what's left beyond those two.
