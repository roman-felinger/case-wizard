"""Generic config-dict helpers.

case-brief, case-guide, and case-solve each keep their own DEFAULTS shape,
config.json path, and CLI-override logic local (deliberately -- see each
tool's CLAUDE.md) -- only the pure merge/strip mechanics, identical across
all three, are shared here.
"""


def deep_merge(base, override):
    """Recursively merge override into base (in place) and return base."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def strip_comments(cfg):
    """config.example.json files document settings with leading-underscore
    keys (e.g. "_comment") -- drop any of those, at any nesting depth, after
    merging so they don't ride along inside dicts handed to code that
    doesn't expect them (and would leak them into anything that ever
    logs/serializes those dicts verbatim)."""
    if not isinstance(cfg, dict):
        return cfg
    return {
        key: strip_comments(value)
        for key, value in cfg.items()
        if not (isinstance(key, str) and key.startswith("_"))
    }
