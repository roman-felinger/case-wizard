"""Small helpers shared across case-wizard's independent CLI tools
(case-brief, case-guide, case-solve, app).

Kept intentionally tiny: only code that is pure, stable, and byte-for-byte
identical across the tools lives here (console encoding, config-dict
merge/strip mechanics, ADO Basic-auth header construction, "open in VS Code
if it's on PATH", filesystem-safe filenames). Each tool's higher-level logic
-- ADO search/query behavior, config *shapes*, CLI flags -- stays local and
independent, per each tool's own CLAUDE.md/TODO.md. If a change here would
alter behavior rather than just remove duplication, it belongs in the
specific tool instead.
"""
