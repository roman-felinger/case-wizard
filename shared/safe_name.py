"""The one rule for "safe to use as a filesystem path component" that
case-brief, case-guide, and case-solve all rely on for output filenames
(and, in case-guide, for sanitizing a case number before it reaches a glob
pattern) -- shared so the character class can't drift out of sync between
projects."""
import re

UNSAFE_CHARS = re.compile(r"[^\w.-]+")


def safe_name(text):
    return UNSAFE_CHARS.sub("_", str(text)).strip("_") or "unlabeled"
