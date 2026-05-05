"""Surgical text operations on after.json without losing formatting.

All locators operate on raw JSON text and return byte spans (start, end)
where `end` is exclusive (Python slice semantics).
"""


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
