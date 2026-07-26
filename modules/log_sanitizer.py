"""Normalize noisy third-party subprocess output for the UI."""

from __future__ import annotations


IGNORED_LINES = (
    "There are modules in AutoencoderKL that should be kept in float32: [].",
)

MOJIBAKE_REPLACEMENTS = {
    "â€”": "—",
    "â€“": "–",
    "â€™": "’",
    "â€œ": "“",
    "â€": "”",
}


def sanitize_subprocess_line(line: str) -> str:
    value = str(line or "")
    if any(message in value for message in IGNORED_LINES):
        return ""
    for broken, replacement in MOJIBAKE_REPLACEMENTS.items():
        value = value.replace(broken, replacement)
    return value
