"""Surgical text operations on after.json without losing formatting.

All locators operate on raw JSON text and return byte spans (start, end)
where `end` is exclusive (Python slice semantics).
"""

import re

_OPEN_TO_CLOSE = {"{": "}", "[": "]"}


def find_matching_close(text: str, open_idx: int) -> int | None:
    """Return the index of the `}` or `]` matching the open bracket at
    `open_idx`. Respects JSON string literals and escape sequences.
    Returns None if `open_idx` is not on an open bracket or the input
    is unbalanced.
    """
    if open_idx >= len(text) or text[open_idx] not in _OPEN_TO_CLOSE:
        return None

    stack: list[str] = []
    in_string = False
    i = open_idx
    while i < len(text):
        c = text[i]
        if in_string:
            if c == "\\":
                i += 2  # skip the next char regardless
                continue
            if c == '"':
                in_string = False
        else:
            if c == '"':
                in_string = True
            elif c in _OPEN_TO_CLOSE:
                stack.append(_OPEN_TO_CLOSE[c])
            elif c in ("}", "]"):
                if not stack or stack[-1] != c:
                    return None
                stack.pop()
                if not stack:
                    return i
        i += 1
    return None


def find_feed_block(raw: str, feed_id: int) -> tuple[int, int] | None:
    """Locate the {…} of the feed with the given feedId.

    Returns (start, end) where start is the opening '{' and end is one
    past the matching '}'. None if feedId not found.
    """
    pattern = re.compile(rf'"feedId":\s*{feed_id}\s*[,\n}}]')
    match = pattern.search(raw)
    if match is None:
        return None

    # Walk backwards from just before the match to find the enclosing '{'.
    # We skip match.start() itself because it points at the opening '"' of
    # "feedId" — entering string mode there would invert the in/out logic for
    # the rest of the backward scan.
    pos = match.start() - 1
    depth = 0
    in_string = False
    while pos >= 0:
        c = raw[pos]
        if in_string:
            if c == '"' and (pos == 0 or raw[pos - 1] != "\\"):
                in_string = False
            pos -= 1
            continue
        if c == '"':
            in_string = True
        elif c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                break
            depth -= 1
        pos -= 1

    if pos < 0:
        return None

    close_idx = find_matching_close(raw, pos)
    if close_idx is None:
        return None
    return (pos, close_idx + 1)
