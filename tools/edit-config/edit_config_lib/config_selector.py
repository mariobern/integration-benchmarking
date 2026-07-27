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


def _first_column(text: str) -> str:
    """Reduce CSV text to selector tokens, judging each row independently.

    The repo's benchmark CSVs carry `feed_id,date,mode` rows, so normally only
    column 1 is a selector token and the rest of the row is dropped. But the
    rule is content-sensitive, not extension-sensitive: if EVERY comma-
    separated field on a row matches the selector token pattern (`_TOKEN_
    PATTERN`), the whole row is kept — otherwise a plain `--feed-ids-from`
    list (e.g. `100-200, 205, 208, 3530`) would silently under-target to just
    column 1 when saved with a `.csv` extension instead of `.txt`. Blank lines
    and `#` comments are dropped, and a first data row whose column 1 is not a
    selector token is treated as a header.
    """
    out: list[str] = []
    seen_first_row = False
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        fields = [f.strip() for f in stripped.split(",")]
        first = fields[0]
        if not first:
            continue
        if not seen_first_row and not _TOKEN_PATTERN.match(first):
            seen_first_row = True
            continue  # header row
        seen_first_row = True
        if all(_TOKEN_PATTERN.match(f) for f in fields):
            out.extend(fields)
        else:
            out.append(first)
    return "\n".join(out)


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
    """Read selector content from a file path or '-' for stdin.

    A path ending in `.csv` is read as a CSV with content-sensitive handling:
    for each row, if all comma-separated fields match the selector token pattern,
    the whole row is kept; otherwise only column 1 is parsed. This allows
    `feed_id,date,mode` benchmark CSV files to work as targeting input, while
    still accepting plain lists saved as `.csv` (e.g., `100-200, 205, 208`).
    Every other path (and stdin) uses the strict `N` / `A-B` grammar.
    """
    import sys

    if str(path) == "-":
        return parse_selector_text(sys.stdin.read())
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".csv":
        text = _first_column(text)
    return parse_selector_text(text)
