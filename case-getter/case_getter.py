#!/usr/bin/env python3
"""Finds every CRM case relevant to whoever is signed in -- not just brand
new ones -- runs case-brief + case-guide (the first two stages) for
whichever ones actually need it, and prints a triage list of *all* of them,
sorted by implementation difficulty. A run never comes back with "nothing
to do" just because nothing changed since last time: there is a real triage
list to see -- what's relevant right now -- even on a day nothing is new.

"Relevant" = a case that's still Active and either (a) still owned by the
CRM's default unassigned-case team ("Helpdesk e-mail" -- see case-brief's
lib/crm_scrape.py::DEFAULT_UNASSIGNED_TEAM_NAME), i.e. nobody has claimed it
yet, or (b) already owned by whoever is signed in -- i.e. yours already, not
someone else's. Accessible to whoever is signed in needs no extra filter of
its own: the Dataverse Web API only ever returns what that user's security
role can see (see case-brief's CLAUDE.md section).

Every relevant case is included in the output, but only some are actually
(re)processed:
  - "new" -- no brief on disk yet (case-brief/briefs/brief-<code>.md).
  - "stale" -- a brief exists, but the CRM record changed since it was
    generated (see is_stale) -- report.build_markdown stamps a hidden "as
    of" marker into every brief, which this script compares against a
    fresh CRM modifiedon on each run. A brief with no marker (predates this
    feature, or was hand-edited) is left alone rather than guessed at.
  - everything else already has an up-to-date brief/guide and is left
    alone -- its existing title/customer/difficulty (already on disk) is
    read back for the triage list rather than regenerated.
New/stale cases get exactly what `python case_wizard.py all <code>
--stop-after guide` would do for it, one case at a time via the same two
scripts as subprocesses -- a failure on one case is reported and does not
stop the rest of the run. This script talks to Dataverse exactly once (the
listing query) -- case-brief's/case-guide's own scripts do their normal
per-case lookups (CRM, Azure DevOps) themselves.

Every run also writes a Markdown report of what it found (title/customer/
difficulty/ownership, same as the console summary) to case-getter/gets/,
one file per run -- see write_report/build_report_markdown.

--sort orders the triage list by implementation difficulty (easiest first
by default) instead of just processing order -- see sort_rows. Applies to
both a full run's summary and a --dry-run listing: a case that already has
a guide from a previous run has a real difficulty to sort by even before
this run touches it; a genuinely new case sorts last until it's processed.

Examples:
    python case_getter.py                 # brief + guide every new/stale case, list everything relevant
    python case_getter.py --dry-run        # just list what's relevant, no writes
    python case_getter.py --limit 3        # cap how many new/stale cases to process this run
    python case_getter.py --sort hardest   # triage list ordered hardest-first instead of easiest-first
"""
import argparse
import datetime
import glob
import html
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CASE_BRIEF_DIR = os.path.join(ROOT, "case-brief")

sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, CASE_BRIEF_DIR)

from shared.console import enable_utf8_console
from shared.safe_name import safe_name

enable_utf8_console()  # this script prints Unicode (case titles, customer names); see shared/console.py

# case-brief's own script, imported rather than only ever shelled out to --
# list_relevant_cases (added alongside this tool) is the one piece of logic
# genuinely shared between the two: both need the same Dataverse
# connection/CRM_ORIGIN case-brief already owns. Everything else about
# running a stage still goes through a subprocess (see run_stage), same as
# case_wizard.py -- so each stage stays independently invocable/dependency-
# isolated; this import is purely for the listing query.
import case_brief

BRIEF_SCRIPT = os.path.join(CASE_BRIEF_DIR, "case_brief.py")
GUIDE_SCRIPT = os.path.join(ROOT, "case-guide", "case_guide.py")
BRIEF_DIR = os.path.join(CASE_BRIEF_DIR, "briefs")
GUIDE_DIR = os.path.join(ROOT, "case-guide", "guides")
# Where this script's own run reports land -- one per run, not one per case
# (case-brief's/case-guide's own briefs/guides are per case; this
# is the one thing case-getter itself produces).
REPORT_DIR = os.path.join(HERE, "gets")


def existing_brief_numbers(brief_dir):
    """Ticket numbers that already have a brief on disk -- the exact
    brief-<safe_name(number)>.md naming case-brief's own
    lib/report.py::write_and_open uses."""
    numbers = set()
    for path in glob.glob(os.path.join(brief_dir, "brief-*.md")):
        m = re.match(r"^brief-(.+)\.md$", os.path.basename(path))
        if m:
            numbers.add(m.group(1))
    return numbers


def _read(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# report.py's own hidden marker (build_markdown) -- the CRM record's
# modifiedon as of when that brief was generated. Same "read the fixed
# rendering shape back as a filesystem contract" tradeoff as
# _CASE_TITLE_RE/_CUSTOMER_RE/_DIFFICULTY_RE below.
_MODIFIED_ON_RE = re.compile(r"<!--\s*case-brief:crm-modified-on=(\S+?)\s*-->")


def _brief_modified_on(brief_path):
    """The CRM record's own modifiedon at the time `brief_path` was
    generated (report.build_markdown's hidden marker), or None if it can't
    be read -- the brief predates this feature, was hand-edited, or is
    simply missing."""
    text = _read(brief_path)
    if not text:
        return None
    m = _MODIFIED_ON_RE.search(text)
    return m.group(1) if m else None


def is_stale(case, brief_path):
    """True if the CRM case has been modified since its existing brief was
    generated. Both timestamps are Dataverse's own ISO-8601 UTC strings
    (e.g. "2026-08-20T12:34:56Z") in the same fixed format, so a plain
    string comparison sorts them correctly -- no datetime parsing needed.

    A case or brief this can't judge (no modifiedon from the CRM listing,
    or a brief with no marker -- written before this feature existed, or
    hand-edited) is treated as NOT stale, i.e. left alone -- case-getter
    shouldn't force-regenerate every existing brief the first time this
    check runs just because it can't prove they're current.
    """
    crm_modified = case.get("modified_on")
    if not crm_modified:
        return False
    brief_modified = _brief_modified_on(brief_path)
    if not brief_modified:
        return False
    return crm_modified > brief_modified


def find_relevant_cases(brief_dir=BRIEF_DIR):
    """(cases, warning) -- every CRM case relevant to whoever is signed in,
    right now -- not filtered down to only ones needing (re)processing.
    Each case is tagged case["is_new"] (no brief on disk at all yet) and
    case["stale"] (a brief exists, but the CRM record changed since it was
    generated -- see is_stale), so callers (main's processing loop, the
    triage summary) know which ones actually need case-brief/case-guide
    (re)run versus which already have an up-to-date brief/guide and are
    only along for the triage list.

    Exits with a clear error if the CRM listing query itself fails (team
    not found, permissions, ...) -- there's no partial result to fall back
    to in that case."""
    cases, error, truncated = case_brief.list_relevant_cases()
    if error:
        sys.exit(f"Could not list CRM cases: {error}")

    warning = None
    if truncated:
        warning = (
            f"More unassigned cases matched than this tool checks at once -- only the "
            f"newest {len(cases)} were considered. Run again after these are handled to "
            f"see the rest."
        )

    have = existing_brief_numbers(brief_dir)
    result = []
    for c in cases:
        ticket = c.get("ticket_number")
        if not ticket:
            continue
        key = safe_name(ticket)
        if key not in have:
            c["is_new"] = True
            c["stale"] = False
            result.append(c)
            continue
        c["is_new"] = False
        brief_path = os.path.join(brief_dir, f"brief-{key}.md")
        c["stale"] = is_stale(c, brief_path)
        result.append(c)
    return result, warning


def run_stage(script, case_number):
    """Same shape as case_wizard.py's own run_one -- a plain subprocess
    call, stdout/stderr inherited so the underlying stage's own progress
    output still shows up live."""
    return subprocess.run([sys.executable, script, case_number]).returncode


# The exact rendering shapes case-brief's lib/report.py and case-guide's
# PROMPT_TEMPLATE/case_guide.py always produce -- read back as a filesystem
# contract (Markdown text on disk), not by importing either stage's
# internals, so this stays a thin orchestrator rather than another place
# those two projects' rendering has to stay in sync with. Same tradeoff
# case-guide's own _extract_case_title/_extract_customer already make
# against case-brief's brief, and the same one CLAUDE.md's "Known accepted
# duplication" section documents for case-brief's and case-guide's own
# ado_api.py copies.
_CASE_TITLE_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_CUSTOMER_RE = re.compile(r"^-\s+\*\*Customer:\*\*\s*(.+?)\s*$", re.MULTILINE)
# Matches either a real "X/10" rating or case-guide's "N/A" band (an
# automated notification / pure triage-closure case with no dev work to
# size -- see case-guide's DIFFICULTY_RUBRIC) -- both are a complete,
# valid rating, not a missing one; see _extract_difficulty/_needs_processing
# for why that distinction matters (an N/A guide must not look "still
# missing a difficulty" and get endlessly reprocessed).
_DIFFICULTY_RE = re.compile(r"(?im)\*\*Implementation Difficulty:\*\*\s*(\d{1,2}\s*/\s*10|N/A)\s*(?:[-–—]{1,2}\s*)?(.*)$")


def _extract_difficulty(guide_text):
    """The "X/10 -- reason" (or "N/A -- reason") implementation-difficulty
    string out of a guide's own text, or None if there's no guide text or
    no recognizable difficulty line. Shared by summarize (a guide this run
    just wrote) and _case_to_row (a guide already on disk from a previous
    run) -- both read the exact same rendering shape back the exact same
    way.

    The separator claude actually writes between "X/10" and the reason
    isn't always the literal "--" PROMPT_TEMPLATE's own example shows --
    claude's prose defaults to a real em dash ("4/10 — reason") often
    enough that the old `-{1,2}` (ASCII hyphen only) class missed it
    entirely: the em dash then fell into the reason capture instead of
    being consumed as the separator, and got reassembled as "4/10 -- —
    reason" -- this function's own " -- " plus claude's un-stripped one.
    The character class now also matches an en dash (U+2013) and em dash
    (U+2014), not just ASCII "-", so either one is consumed the same way
    and never doubled up."""
    if not guide_text:
        return None
    m = _DIFFICULTY_RE.search(guide_text)
    if not m:
        return None
    reason = m.group(2).strip()
    return f"{m.group(1).replace(' ', '')}" + (f" -- {reason}" if reason else "")


def summarize(case_number, brief_path, guide_path):
    """Title/customer (from the brief) and implementation difficulty (from
    the guide) for one case -- exactly what print_summary lists. Works
    equally for a brief/guide this run just (re)generated and for one
    already on disk from a previous run (an up-to-date case main() left
    alone) -- either way it's just reading files. Missing/unparseable
    pieces come back None rather than raising -- a summary that's missing
    one field is still useful; failing the whole run over it would not
    be."""
    row = {"case_number": case_number, "title": None, "customer": None, "difficulty": None}

    brief_text = _read(brief_path)
    if brief_text:
        m = _CASE_TITLE_RE.search(brief_text)
        row["title"] = m.group(1) if m else None
        m = _CUSTOMER_RE.search(brief_text)
        if m and m.group(1) != "—":  # report.py's own placeholder for a missing value
            row["customer"] = m.group(1)

    row["difficulty"] = _extract_difficulty(_read(guide_path))
    return row


def _owner_label(case):
    return "Mine" if case.get("owned_by_me") else "Unassigned"


_DIFFICULTY_NUM_RE = re.compile(r"^(\d{1,2})\s*/\s*10")


def _difficulty_num(row):
    """The leading number out of a row's "difficulty" string (e.g. "7/10 --
    reason" -> 7), or None if there isn't one -- a guide that failed to
    generate, or whose difficulty line _DIFFICULTY_RE didn't recognize."""
    difficulty = row.get("difficulty")
    if not difficulty:
        return None
    m = _DIFFICULTY_NUM_RE.match(difficulty)
    return int(m.group(1)) if m else None


def sort_rows(rows, sort):
    """Reorders the triage list by implementation difficulty -- "easiest"
    first by default (build_parser's --sort), "hardest" first, or left in
    processing order ("none", an explicit opt-out). Applies to both a full
    run and a --dry-run listing: a case already guided in a previous run
    has a real difficulty to sort by even before this run touches it.

    Rows with no parseable difficulty (a brand-new case not processed yet,
    or a guide that failed to generate) always sort last, in *either*
    direction -- "unknown" isn't the same as "easiest" or "hardest", so it
    shouldn't jump to the front just because --sort hardest reverses the
    numeric comparison.
    """
    if sort == "none":
        return rows
    known = [r for r in rows if _difficulty_num(r) is not None]
    unknown = [r for r in rows if _difficulty_num(r) is None]
    known.sort(key=_difficulty_num, reverse=(sort == "hardest"))
    return known + unknown


_TABLE_HEADERS = ["Case", "Owner", "Title", "Customer", "Difficulty"]


def _difficulty_placeholder(r, dry_run):
    """Explains *why* a case has no difficulty yet, instead of one generic
    "not available" string that doesn't say what actually happened --
    which of these is true varies per row/run:
      - dry_run: nothing was ever going to be (re)generated this run.
      - skipped_limit: this case needed (re)processing, but --limit was
        reached before it got a turn (see main's own `skip` set) -- it'll
        get one on a future run, or a bigger --limit.
      - an error is already on this row (case-brief/case-guide failed --
        see main) -- shown directly rather than pointing at a separate
        Notes column (there used to be one; it was almost always empty
        and got dropped -- see "Status/Notes columns dropped" in CLAUDE.md).
      - otherwise, a guide was generated but claude either dropped the
        difficulty line or phrased it in a way _DIFFICULTY_RE didn't
        recognize -- worth a look at the guide itself."""
    if dry_run:
        return "(dry run -- not generated this run)"
    if r.get("skipped_limit"):
        return "(skipped this run -- raise --limit to include it)"
    if r.get("error"):
        return f"⚠ {r['error']}"
    return "(not found -- check the guide)"


def _table_rows(rows, dry_run):
    """Normalizes each row dict to the fixed column order _TABLE_HEADERS
    names, for _render_markdown_table."""
    return [
        [
            r["case_number"],
            _owner_label(r),
            r.get("title") or "(no title)",
            r.get("customer") or "unknown customer",
            r.get("difficulty") or _difficulty_placeholder(r, dry_run),
        ]
        for r in rows
    ]


def _format_case_lines(r, dry_run):
    """Plain-text lines for one case in the console triage output -- no
    table, no color; that's the on-disk report's job (see
    build_report_markdown/_render_markdown_table) -- a terminal can't
    reliably show a difficulty heatmap or highlight "mine" rows the way
    the report's table can. Owner still gets its own labeled line here,
    same as the report's own column -- not folded back into one combined
    tag string the way the very first version of this output did. An
    error (case-brief/case-guide failed) shows up as the Difficulty line's
    own text (see _difficulty_placeholder) rather than a separate line --
    same reasoning as the table's dropped Notes column."""
    return [
        f"- {r['case_number']}",
        f"    Owner: {_owner_label(r)}",
        f"    {r.get('title') or '(no title)'} -- {r.get('customer') or 'unknown customer'}",
        f"    Difficulty: {r.get('difficulty') or _difficulty_placeholder(r, dry_run)}",
    ]


# Excel's default red-yellow-green conditional-formatting scale (the same
# three RGB stops: #63BE7B / #FFEB84 / #F8696B) -- a familiar "low number
# looks safe, high number looks alarming" scale for a 1-10 difficulty
# rating, rather than inventing a new one. Lives only in the on-disk report
# (_render_markdown_table) -- a plain terminal can't reliably show a cell
# background across every user's setup, so the console stays plain text
# (see _format_case_lines/print_summary).
_DIFFICULTY_COLOR_STOPS = ((99, 190, 123), (255, 235, 132), (248, 105, 107))


def _difficulty_bg(num):
    """Hex background color for a 1-10 difficulty rating along
    _DIFFICULTY_COLOR_STOPS (green -> yellow -> red). None (no rating
    parsed yet -- see _difficulty_num) gets no background at all, rather
    than defaulting to one end of the scale it doesn't actually belong on."""
    if num is None:
        return None
    t = max(1, min(10, num))
    low, mid, high = _DIFFICULTY_COLOR_STOPS
    start, end, frac = (low, mid, (t - 1) / 4.5) if t <= 5.5 else (mid, high, (t - 5.5) / 4.5)
    r, g, b = (round(s + (e - s) * frac) for s, e in zip(start, end))
    return f"#{r:02x}{g:02x}{b:02x}"


def _md_cell(text):
    """Escapes a free-text cell value (case title/customer/error -- CRM or
    claude output, not trusted markup) for safe embedding in a Markdown
    table cell: HTML-escaped so a stray "<"/"&" can't be parsed as a tag/
    entity by a renderer that treats raw HTML inside a table cell as HTML
    (GFM does), and "|" escaped so it can't be mistaken for a column
    separator and break the row."""
    return html.escape(text).replace("|", "\\|")


def _render_markdown_table(headers, rows, mine_flags, difficulty_nums, urls):
    """The on-disk report's table -- an ordinary GitHub-flavored Markdown
    pipe table, the same shape as any other table in this repo's docs, not
    a raw HTML <table>. Three visual cues, all achieved without breaking
    that plain-table shape:
      - the Case cell is a clickable link to the case's own CRM record
        (plain Markdown `[T2621277](url)`, no HTML needed) when a URL is
        available -- same deep link crm_scrape's listing query already
        builds (CRM_APP_ID + forceUCI, see case-brief's own "Case link"
        handling), carried through as-is rather than rebuilt here. Only
        the visible label goes through _md_cell -- the URL itself is
        placed raw inside the link's `(...)`, since CommonMark doesn't
        require escaping "&" there (unlike inside a table cell's own
        text) and re-escaping it would corrupt the query string.
      - the Difficulty cell's background is shaded along _difficulty_bg's
        red-yellow-green scale via a small inline `<span style="...">` --
        GFM allows raw inline HTML inside a table cell, so this still
        renders as one ordinary-looking row, just with one colored cell,
        in any viewer that renders embedded HTML; a viewer that doesn't
        still shows the row fine, just without the color.
      - a case the signed-in user already owns gets its Owner cell bolded
        (plain Markdown `**Mine**`, no HTML needed) instead of a
        full-row background -- reads at a glance, and degrades to
        completely ordinary Markdown everywhere.
    mine_flags/difficulty_nums/urls are parallel lists to `rows` -- kept
    separate from the rendered string cells rather than smuggled into them,
    same reasoning as difficulty_nums vs. the rendered difficulty string
    (see _difficulty_num)."""
    case_idx = headers.index("Case")
    diff_idx = headers.index("Difficulty")
    owner_idx = headers.index("Owner")
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for cells, mine, diff_num, url in zip(rows, mine_flags, difficulty_nums, urls):
        rendered = []
        for i, cell in enumerate(cells):
            text = _md_cell(cell)
            if i == case_idx and url:
                text = f"[{text}]({url})"
            elif i == diff_idx:
                bg = _difficulty_bg(diff_num)
                if bg:
                    text = f'<span style="background:{bg};padding:1px 6px;border-radius:3px">{text}</span>'
            elif i == owner_idx and mine:
                text = f"**{text}**"
            rendered.append(text)
        lines.append("| " + " | ".join(rendered) + " |")
    return "\n".join(lines)


def print_summary(rows):
    if not rows:
        print("\nNo relevant cases found.")
        return
    processed = sum(1 for r in rows if r.get("attempted"))
    print(f"\n{len(rows)} relevant case(s) ({processed} briefed/guided this run, "
          f"{len(rows) - processed} left as-is):\n")
    for r in rows:
        print("\n".join(_format_case_lines(r, dry_run=False)))


def _case_to_row(c, guide_dir=GUIDE_DIR):
    """Normalizes one entry from find_relevant_cases (a raw CRM listing
    dict, keyed `ticket_number`) to the same {case_number, owned_by_me,
    stale, is_new, title, customer, difficulty, url} shape a fully-processed
    row already has -- used for the dry-run listing/report, which never
    (re)generates a brief/guide the way main's own processing loop does.
    difficulty is read from a guide already on disk from a previous run
    when there is one (free -- no claude call, no processing), so a
    dry-run listing still sorts meaningfully by difficulty; a case that's
    never been guided comes back with difficulty None, same as one whose
    guide failed to generate. `url` is the CRM deep link crm_scrape's own
    listing query already includes per case (see report.py's "Case link"
    handling of the same field for case-brief's own briefs) -- carried
    through as-is, not rebuilt here."""
    return {
        "case_number": c["ticket_number"],
        "owned_by_me": c.get("owned_by_me"),
        "stale": c.get("stale", False),
        "is_new": c.get("is_new", True),
        "title": c.get("title"),
        "customer": c.get("customer"),
        "difficulty": _extract_difficulty(_read(os.path.join(guide_dir, f"guide-{safe_name(c['ticket_number'])}.md"))),
        "url": c.get("url"),
    }


def build_report_markdown(rows, dry_run, timestamp):
    """Renders the same information print_summary (or the dry-run listing)
    puts on the console into a Markdown file, so a triage run leaves
    something on disk to refer back to later -- case-brief/case-guide
    already do this for their own per-case output; this is case-getter's
    own equivalent, one file per run rather than one per case.

    Every relevant case gets a row, whether or not this run actually
    (re)processed it -- Owner is its own column (see _owner_label), never
    folded into a combined tag string. Rendered as an ordinary Markdown
    table (_render_markdown_table) with a difficulty heatmap and "mine"
    row highlighting the console deliberately doesn't have (see
    print_summary/_format_case_lines) -- see that function's own docstring
    for how those are done without an HTML table. A missing difficulty
    explains why rather than showing one generic placeholder -- see
    _difficulty_placeholder."""
    kind = "dry run" if dry_run else "run"
    lines = [f"# Case-getter {kind} -- {timestamp}", ""]

    if not rows:
        lines.append("No relevant cases found.")
        return "\n".join(lines) + "\n"

    lines.append(f"Found {len(rows)} relevant case(s).")
    if dry_run:
        lines.append("")
        lines.append("_(dry run -- brief/guide not (re)generated this run)_")
    lines.append("")
    lines.append(_render_markdown_table(
        _TABLE_HEADERS, _table_rows(rows, dry_run),
        [bool(r.get("owned_by_me")) for r in rows], [_difficulty_num(r) for r in rows],
        [r.get("url") for r in rows],
    ))
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_report(markdown, output_dir, filename_timestamp):
    """Writes build_report_markdown's output to gets/get-<timestamp>.md
    -- filename_timestamp is already filesystem-safe (see main's
    strftime format), so no safe_name() pass is needed here the way
    report.write_and_open/writer.write_and_open need it for a
    CRM-supplied case number."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"get-{filename_timestamp}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)
    return path


def _needs_processing(c, guide_dir=GUIDE_DIR):
    """True if this case needs (re)processing this run: a new/stale brief
    (see is_new/stale on `c`, from find_relevant_cases/is_stale), or --
    independently -- a guide that isn't actually usable yet, even though
    its brief is already current:
      - the guide file simply doesn't exist on disk (e.g. a brief created
        by hand outside case-getter, or by a previous run whose
        case-guide call failed), or
      - it exists, but claude dropped the difficulty line entirely (see
        _DIFFICULTY_RE) -- a guide missing that line isn't "done", it's a
        guide that needs another try, the same as a guide that was never
        generated at all.
    Checking only brief staleness used to leave a case in either situation
    stuck showing "(not found -- check the guide)" forever: nothing was
    ever wrong with the *brief*, so it kept looking fully up to date and
    case-guide never got another try. Retried on every run until a
    difficulty line actually sticks -- if a specific case's content makes
    claude reliably skip that line no matter how many tries, that's worth
    noticing (it'll keep showing up as reprocessed every run) and fixing
    in case-guide's own prompt, not silently giving up on it here."""
    if c.get("is_new") or c.get("stale"):
        return True
    guide_path = os.path.join(guide_dir, f"guide-{safe_name(c['ticket_number'])}.md")
    return _extract_difficulty(_read(guide_path)) is None


def build_parser():
    parser = argparse.ArgumentParser(
        prog="case_getter.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--limit", type=int, metavar="N", help="(Re)process at most N new/stale cases this run (default: all of them)")
    parser.add_argument("--dry-run", action="store_true", help="Only list the relevant cases -- don't run brief/guide")
    parser.add_argument(
        "--sort", choices=["none", "easiest", "hardest"], default="easiest",
        help="Order the triage list by implementation difficulty (default: easiest first). "
             "Applies to both a full run and a --dry-run listing -- pass 'none' for plain processing order.",
    )
    return parser


def main():
    args = build_parser().parse_args()
    now = datetime.datetime.now()

    print("Looking up relevant CRM cases (Dataverse Web API, OAuth)...")
    cases, warning = find_relevant_cases()
    if warning:
        print(f"Warning: {warning}", file=sys.stderr)

    def _write_report(rows):
        path = write_report(
            build_report_markdown(rows, args.dry_run, now.strftime("%Y-%m-%d %H:%M:%S")),
            REPORT_DIR, now.strftime("%Y%m%d-%H%M%S"),
        )
        print(f"\nReport written to {path}")

    if not cases:
        # A genuinely empty listing -- nothing unassigned or yours, active,
        # at all -- not just "nothing new/stale to (re)process this run"
        # (that case still has a full triage list to print, see below).
        print("No relevant cases found -- nothing to do.")
        _write_report([])
        return 0

    print(f"Found {len(cases)} relevant case(s): {', '.join(c['ticket_number'] for c in cases)}")

    if args.dry_run:
        rows = sort_rows([_case_to_row(c) for c in cases], args.sort)
        print()
        for r in rows:
            print("\n".join(_format_case_lines(r, dry_run=True)))
        _write_report(rows)
        return 0

    # --limit caps how many cases actually get (re)processed this run -- a
    # case already fully up to date is free to include (just a file read),
    # so it's never counted against the limit.
    to_process = [c for c in cases if _needs_processing(c, GUIDE_DIR)]
    if args.limit is not None:
        skip = {c["ticket_number"] for c in to_process[args.limit:]}
        to_process = to_process[: args.limit]
    else:
        skip = set()

    rows = []
    for c in cases:
        number = c["ticket_number"]
        row = {
            "case_number": number, "owned_by_me": c.get("owned_by_me"),
            "stale": c.get("stale", False), "is_new": c.get("is_new", True),
            "attempted": False, "url": c.get("url"),
        }
        brief_path = os.path.join(BRIEF_DIR, f"brief-{safe_name(number)}.md")
        guide_path = os.path.join(GUIDE_DIR, f"guide-{safe_name(number)}.md")

        if number in skip:
            # Would need (re)processing, but --limit was reached first --
            # still shown in the triage list with whatever's on disk
            # (possibly nothing yet, for a brand-new case) -- flagged so
            # a missing difficulty says *why* (see _difficulty_placeholder)
            # instead of looking like an unexplained failure.
            row["skipped_limit"] = True
            row.update(summarize(number, brief_path, guide_path))
            rows.append(row)
            continue

        if not _needs_processing(c, GUIDE_DIR):
            # Already fully up to date -- no need to re-run brief/guide,
            # just read the existing files back for the triage list.
            row.update(summarize(number, brief_path, guide_path))
            rows.append(row)
            continue

        row["attempted"] = True
        print(f"\n=== {number} ===")

        needs_brief = c.get("is_new") or c.get("stale")
        if needs_brief:
            rc = run_stage(BRIEF_SCRIPT, number)
            if rc != 0 or not os.path.exists(brief_path):
                row.update({"title": c.get("title"), "customer": c.get("customer"), "difficulty": None})
                row["error"] = f"case-brief failed (exit {rc}) -- skipped case-guide"
                rows.append(row)
                continue
        # else: the brief is already current -- _needs_processing only
        # brought this case in because its guide is missing, so there's no
        # need to re-hit CRM/ADO for data that hasn't changed; go straight
        # to case-guide.

        rc = run_stage(GUIDE_SCRIPT, number)
        if rc != 0 or not os.path.exists(guide_path):
            row["error"] = f"case-guide failed (exit {rc})"

        row.update(summarize(number, brief_path, guide_path))
        rows.append(row)

    rows = sort_rows(rows, args.sort)
    print_summary(rows)
    _write_report(rows)
    return 0 if not any(r.get("error") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
