"""Parse the unified feed-ID selector grammar.

Tokens: N (single ID) or A-B (inclusive range with A <= B).
Separators: any combination of commas, whitespace, newlines.
Comments: # to end-of-line is stripped.
"""

import re
from pathlib import Path


class SelectorError(ValueError):
    """Raised on malformed selector input."""


_TOKEN_PATTERN = re.compile(r"^(\d+)(?:-(\d+))?$")


def parse_selector_text(text: str) -> set[int]:
    """Parse selector text into a set of feed IDs.

    Returns an empty set for empty input. Raises SelectorError on
    malformed tokens or descending ranges, with line number in the
    message.
    """
    result: set[int] = set()
    for line_no, line in enumerate(text.splitlines() or [text], start=1):
        comment_idx = line.find("#")
        if comment_idx >= 0:
            line = line[:comment_idx]
        for token in re.split(r"[,\s]+", line):
            if not token:
                continue
            match = _TOKEN_PATTERN.match(token)
            if not match:
                raise SelectorError(f"invalid token {token!r} on line {line_no}")
            lo = int(match.group(1))
            hi = int(match.group(2)) if match.group(2) is not None else lo
            if hi < lo:
                raise SelectorError(
                    f"range bounds out of order: {token!r} on line {line_no}"
                )
            result.update(range(lo, hi + 1))
    return result


def read_selector_file(path: str | Path) -> set[int]:
    """Read selector content from a file path or '-' for stdin."""
    import sys

    if str(path) == "-":
        return parse_selector_text(sys.stdin.read())
    return parse_selector_text(Path(path).read_text(encoding="utf-8"))
