"""Feed-ID selector grammar: singles and inclusive ranges.

Examples:
    "922"                 -> {922}
    "1000-1050"           -> {1000..1050}
    "100,200,500-510"     -> {100, 200, 500..510}
"""

from __future__ import annotations


def parse_selector(text: str) -> set[int]:
    if text is None:
        return set()
    out: set[int] = set()
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            lo_s, hi_s = token.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if lo > hi:
                raise ValueError(f"selector range {token!r}: lo > hi")
            out.update(range(lo, hi + 1))
        else:
            out.add(int(token))
    return out


def parse_selector_lines(text: str) -> set[int]:
    """Parse a multi-line selector (one selector per line, '#' comments)."""
    out: set[int] = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        out |= parse_selector(line)
    return out
