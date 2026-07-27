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


def find_object_field_span(block: str, key: str) -> tuple[int, int] | None:
    """Locate the {…} value of an object-valued field `key` within `block`.

    Returns (start, end) where start is the opening '{' and end is one past
    the matching '}'. None if the field is absent.
    """
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\{{', block)
    if match is None:
        return None
    open_idx = match.end() - 1
    close_idx = find_matching_close(block, open_idx)
    if close_idx is None:
        return None
    return (open_idx, close_idx + 1)


def find_metadata_block(block: str) -> tuple[int, int] | None:
    """Locate the {…} value of the feed-level `metadata` object within
    `block` (the raw text of a single feed object).

    Returns (start, end) where start is the opening '{' and end is one
    past the matching '}'. None if the field is absent.
    """
    return find_object_field_span(block, "metadata")


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


def find_number_field_span(block: str, key: str) -> tuple[int, int] | None:
    """Locate the numeric value of `"key": N` within `block`, int or decimal.

    Returns the span of the literal only. `find_int_field_span` matches just
    `-?\\d+`, so pointed at `0.5` it would return the `0` and a splice would
    corrupt the value — use this helper for any field that may be fractional.
    """
    pattern = re.compile(rf'"{re.escape(key)}":\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)')
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


def find_ric_identifier_spans(block: str) -> list[tuple[int, int, str]]:
    """Locate every `"identifier"` string value inside any
    `datascope_ric.identifiers[]` array within `block`.

    Returns (start, end, current_value) per slot in document order.
    `start..end` covers the value INCLUDING the surrounding double quotes.
    """
    out: list[tuple[int, int, str]] = []
    for dm in re.finditer(r'"datascope_ric"\s*:\s*\{', block):
        dr_open = dm.end() - 1
        dr_close = find_matching_close(block, dr_open)
        if dr_close is None:
            continue
        dr_block = block[dr_open : dr_close + 1]
        ids_match = re.search(r'"identifiers"\s*:\s*\[', dr_block)
        if ids_match is None:
            continue
        ids_open_rel = ids_match.end() - 1
        ids_close_rel = find_matching_close(dr_block, ids_open_rel)
        if ids_close_rel is None:
            continue
        ids_block = dr_block[ids_open_rel : ids_close_rel + 1]
        for m in re.finditer(
            r'"identifier"\s*:\s*("[^"\\]*(?:\\.[^"\\]*)*")', ids_block
        ):
            abs_start = dr_open + ids_open_rel + m.start(1)
            abs_end = dr_open + ids_open_rel + m.end(1)
            value = block[abs_start + 1 : abs_end - 1]
            out.append((abs_start, abs_end, value))
    out.sort(key=lambda t: t[0])
    return out


def insert_field_after_open_brace(block: str, field_text: str) -> str:
    """Insert `field_text` (e.g. '"allowedPublisherIds": [ 80 ],') as a new
    line right after the block's opening '{', indented to match the block's
    existing fields.

    `field_text` must carry its own trailing comma; a session entry always has
    at least the "session" field after the insertion point, so the comma is
    always valid.
    """
    brace = block.index("{")
    m = re.search(r'\n(\s*)"', block)
    if m:
        indent = m.group(1)
        nl = block.index("\n", brace)
        return block[: nl + 1] + indent + field_text + "\n" + block[nl + 1 :]
    # single-line fallback: '{ <field> ...'
    return block[: brace + 1] + " " + field_text + block[brace + 1 :]


def insert_field_before_session(block: str, field_text: str) -> str:
    """Insert `field_text` (e.g. '"minPublishers": 3,') on its own line just
    before the block's "session" key — the canonical position for
    minPublishers (...marketSchedule, minPublishers, session). Falls back to
    insert_field_after_open_brace when no "session" key exists.
    """
    m = re.search(r'\n(\s*)"session"\s*:', block)
    if m is None:
        return insert_field_after_open_brace(block, field_text)
    indent = m.group(1)
    pos = m.start() + 1  # just after the newline preceding the "session" line
    return block[:pos] + indent + field_text + "\n" + block[pos:]


def insert_field_before_close_brace(block: str, field_text: str) -> str:
    """Insert `field_text` as the LAST field of `block`'s outermost object.

    `field_text` must NOT carry a trailing comma — the comma is appended to the
    current last field's line instead. This is the inserter for
    `stalePriceFilter`, which sorts after `session` and so is always last in a
    session entry. Multi-line `field_text` must already carry the indentation
    of its continuation lines; only the first line is indented here.
    """
    close = block.rindex("}")
    head = block[:close]
    tail = block[close:]
    close_indent = head[head.rindex("\n") + 1 :] if "\n" in head else ""
    m = re.search(r'\n(\s*)"', block)
    indent = m.group(1) if m else close_indent + "  "
    body = head.rstrip()
    separator = "" if body.endswith("{") else ","
    return body + separator + "\n" + indent + field_text + "\n" + close_indent + tail


def delete_object_field(block: str, key: str) -> str:
    """Delete `"key": { … }` from `block`, including the comma that precedes it.

    The object-valued sibling of `delete_scalar_field`. Assumes the field is the
    LAST field of its object (true for `stalePriceFilter`), so the comma to
    remove sits before the field rather than after it. Deleting the only field
    leaves a valid empty object. Returns `block` unchanged when `key` is absent.
    """
    span = find_object_field_span(block, key)
    if span is None:
        return block
    key_match = re.search(rf'"{re.escape(key)}"\s*:\s*\{{', block)
    start = key_match.start()
    end = span[1]
    # Walk back over the field's indentation, the newline before it, and the
    # comma that terminated the previous field.
    i = start - 1
    while i >= 0 and block[i] in " \t":
        i -= 1
    if i >= 0 and block[i] == "\n":
        i -= 1
        while i >= 0 and block[i] in " \t":
            i -= 1
    if i >= 0 and block[i] == ",":
        i -= 1
    return block[: i + 1] + block[end:]


def find_marketschedules_end(block: str) -> int:
    """Return the offset just past the marketSchedules array's closing ']',
    or 0 when the block has no marketSchedules array. Used to scope feed-level
    minPublishers lookups to the tail of a feed block (the feed-level value
    sits AFTER marketSchedules in the canonical layout)."""
    idx = block.find('"marketSchedules":')
    if idx < 0:
        return 0
    open_idx = block.find("[", idx)
    if open_idx < 0:
        return 0
    close = find_matching_close(block, open_idx)
    return 0 if close is None else close + 1


def delete_scalar_field(block: str, key: str) -> str:
    """Delete the entire physical line of a top-level int or quoted-string
    field `"key": <value>,` from `block`, including its trailing comma.

    Matches from the newline that precedes the field's indentation through the
    trailing comma, so the field's whole line is removed and surrounding
    formatting stays intact. Assumes the field is NOT the last field in its
    object (so it carries a trailing comma) — true for the feed-level
    `exchangeId` (always followed by more feed fields) and a session's
    `marketSchedule` (always followed by `"session"`). Returns `block`
    unchanged when `key` is absent.
    """
    pattern = re.compile(
        rf'\n[ \t]*"{re.escape(key)}"\s*:\s*'
        rf'(?:"[^"\\]*(?:\\.[^"\\]*)*"|-?\d+)[ \t]*,'
    )
    m = pattern.search(block)
    if m is None:
        return block
    return block[: m.start()] + block[m.end() :]
