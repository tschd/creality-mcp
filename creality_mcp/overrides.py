"""Turn `{key: value}` setting overrides into CrealityPrint CLI flags.

The CLI fails with no result.json on an unknown flag, so every key is checked first.
"""

import difflib

# Keys an override may never set: the slicer runs `post_process` scripts after the slice,
# `filename_format` can name an output path outside the job folder, and the rest are preset
# metadata (changing them would only mislabel the result).
BLOCKED_KEYS = frozenset(
    {
        "post_process",
        "filename_format",
        "compatible_printers",
        "compatible_printers_condition",
        "from",
        "inherits",
        "instantiation",
        "is_custom_defined",
        "name",
        "setting_id",
        "type",
        "version",
    }
)


class OverrideError(ValueError):
    pass


def build_override_flags(
    overrides: dict[str, str | int | float | bool], known_keys: set[str]
) -> list[str]:
    flags = []
    for key in sorted(overrides):
        if key in BLOCKED_KEYS or key.endswith("_settings_id"):
            raise OverrideError(f"setting '{key}' cannot be overridden")
        if key not in known_keys:
            close = difflib.get_close_matches(key, sorted(known_keys), n=5, cutoff=0.6)
            hint = f"; close: {', '.join(close)}" if close else ""
            raise OverrideError(f"unknown setting '{key}'{hint}")
        value = overrides[key]
        text = ("1" if value else "0") if isinstance(value, bool) else str(value)
        if any(ch in text for ch in ";\n\r\x00"):
            raise OverrideError(f"value for '{key}' may not contain ';', a line break or NUL")
        flags.append(f"--{key.replace('_', '-')}={text}")
    return flags
