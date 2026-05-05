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


def find_session_block(feed_block: str, session_name: str) -> tuple[int, int] | None:
    """Locate the {…} of the session entry with the given name.

    `feed_block` is the raw text of a single feed object (as returned
    by find_feed_block). Returns bounds relative to `feed_block`.
    """
    pattern = re.compile(rf'"session":\s*"{re.escape(session_name)}"')
    match = pattern.search(feed_block)
    if match is None:
        return None

    # Start one char before match.start() so the opening '"' of "session"
    # doesn't toggle in_string=True at the start of the backward walk.
    pos = match.start() - 1
    depth = 0
    in_string = False
    while pos >= 0:
        c = feed_block[pos]
        if in_string:
            if c == '"' and (pos == 0 or feed_block[pos - 1] != "\\"):
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
    close_idx = find_matching_close(feed_block, pos)
    if close_idx is None:
        return None
    return (pos, close_idx + 1)


def find_publisher_array_span(block: str) -> tuple[int, int] | None:
    """Locate the [ … ] value of `allowedPublisherIds` within `block`.

    Returns (start, end) where start points at `[` and end is one past
    the closing `]`. None if the field is absent.
    """
    match = re.search(r'"allowedPublisherIds":\s*\[', block)
    if match is None:
        return None
    open_idx = match.end() - 1  # position of '['
    close_idx = find_matching_close(block, open_idx)
    if close_idx is None:
        return None
    return (open_idx, close_idx + 1)


def find_int_field_span(block: str, key: str) -> tuple[int, int] | None:
    """Locate the integer value of `"key": N` within `block`.

    Returns the byte span of the digit characters only (no surrounding
    whitespace, no comma). None if missing.
    """
    pattern = re.compile(rf'"{re.escape(key)}":\s*(-?\d+)')
    match = pattern.search(block)
    if match is None:
        return None
    return (match.start(1), match.end(1))


def find_string_field_span(block: str, key: str) -> tuple[int, int] | None:
    """Locate the quoted string value of `"key": "..."` within `block`.

    Returns the byte span INCLUDING the surrounding double quotes.
    None if missing.
    """
    pattern = re.compile(rf'"{re.escape(key)}":\s*("[^"\\]*(?:\\.[^"\\]*)*")')
    match = pattern.search(block)
    if match is None:
        return None
    return (match.start(1), match.end(1))
