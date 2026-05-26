"""Raw-text surgical helpers for editing protobuf-style JSON configs in place.

These locate the byte span of a feed entry (by feedId) or a session entry
(by session name) within the raw JSON text, so callers can do regex-scoped
field replacements that preserve the file's original formatting. Shared by
update_config_from_summary.py and lazer_dq/apply_allowed_to_config.py.
"""
import re


def find_feed_block(raw: str, feed_id: int) -> tuple[int, int] | None:
    """Return (start, end) byte offsets of a feed entry by feedId, or None.

    start indexes the opening '{', end is one past the matching '}'.
    String-aware backward scan for the opening brace; brace-depth forward
    scan for the close.
    """
    pattern = rf'"feedId":\s*{feed_id}\s*[,\n}}]'
    match = re.search(pattern, raw)
    if not match:
        return None

    pos = match.start()

    # Scan backward for opening { (string-aware)
    depth = 0
    start = pos - 1
    while start >= 0:
        c = raw[start]
        if c == '"':
            start -= 1
            while start >= 0 and raw[start] != '"':
                if raw[start] == "\\" and start > 0:
                    start -= 1
                start -= 1
        elif c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                break
            depth -= 1
        start -= 1

    # Scan forward from opening { for matching }
    depth = 1
    end = start + 1
    in_string = False
    while end < len(raw) and depth > 0:
        c = raw[end]
        if c == '"' and (end == 0 or raw[end - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
        end += 1

    return (start, end)


def find_session_block(block: str, session_name: str) -> tuple[int, int] | None:
    """Return (start, end) byte offsets of a session entry within a feed block.

    Matches on `"session": "<session_name>"` and brackets the enclosing { }.
    """
    pattern = rf'"session":\s*"{session_name}"'
    match = re.search(pattern, block)
    if not match:
        return None

    pos = match.start()

    # Scan backward for opening {
    depth = 0
    start = pos - 1
    while start >= 0:
        c = block[start]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                break
            depth -= 1
        start -= 1

    # Scan forward for matching }
    depth = 1
    end = start + 1
    in_string = False
    while end < len(block) and depth > 0:
        c = block[end]
        if c == '"' and (end == 0 or block[end - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
        end += 1

    return (start, end)
