"""UTF-8 console/pipe encoding fix.

Every case-wizard CLI prints Unicode (checkmarks, arrows, em-dashes, ...).
Windows' default console/subprocess-pipe encoding is the system ANSI
codepage (e.g. cp1250), not UTF-8, which crashes on those characters
whether the script is run directly in a terminal or piped from another
case-wizard tool's subprocess call. Call this before any such output.
"""
import sys


def enable_utf8_console():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
