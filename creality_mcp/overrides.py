"""Turn `{key: value}` setting overrides into CrealityPrint CLI flags.

The CLI fails with no result.json on an unknown flag, so every key is checked first.
"""

import difflib

# Keys an override may never set: the slicer runs `post_process` scripts after the slice,
# and `filename_format` can name an output path outside the job folder.
BLOCKED_KEYS = frozenset({"post_process", "filename_format"})


class OverrideError(ValueError):
    pass


def build_override_flags(
    overrides: dict[str, str | int | float | bool], known_keys: set[str]
) -> list[str]:
    flags = []
    for key in sorted(overrides):
        if key in BLOCKED_KEYS:
            raise OverrideError(f"setting '{key}' cannot be overridden")
        if key not in known_keys:
            close = difflib.get_close_matches(key, sorted(known_keys), n=5, cutoff=0.6)
            hint = f"; close: {', '.join(close)}" if close else ""
            raise OverrideError(f"unknown setting '{key}'{hint}")
        value = overrides[key]
        text = ("1" if value else "0") if isinstance(value, bool) else str(value)
        if any(ch in text for ch in ";\n\r"):
            raise OverrideError(f"value for '{key}' may not contain ';' or a line break")
        flags.append(f"--{key.replace('_', '-')}={text}")
    return flags
