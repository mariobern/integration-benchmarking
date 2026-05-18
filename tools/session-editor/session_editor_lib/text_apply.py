"""Apply session add/remove ops to raw after.json text.

Uses text surgery (text_surgery.py) so the file's original formatting is
preserved byte-for-byte except for the spliced regions.

Key trick: for AddSession we don't synthesize a session block from scratch.
We take the feed's existing REGULAR block as a formatting template, do
field-level string substitutions on it, and splice the result back in.
This guarantees the new block matches the file's compact-array style
without us having to re-implement that formatter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .templates import (
    CANONICAL_ORDER,
    SCHEDULE_BY_SESSION,
    US_EQUITY_EXCHANGE_SUFFIXES,
)
from .text_surgery import find_feed_block, find_matching_close, find_session_block


# ---- exceptions --------------------------------------------------------------


class TextApplyError(RuntimeError):
    """Raised when a text-level edit cannot be located in raw JSON."""


# ---- public API --------------------------------------------------------------


@dataclass
class TextEdit:
    """A pending raw-text edit. Lower start = applied later (right-to-left)."""

    start: int
    end: int
    replacement: str


def apply_edits(raw: str, edits: list[TextEdit]) -> str:
    """Apply edits to `raw`. Edits must be non-overlapping; order doesn't matter."""
    # Sort right-to-left so earlier indices stay valid as we splice.
    for e in sorted(edits, key=lambda e: e.start, reverse=True):
        raw = raw[: e.start] + e.replacement + raw[e.end :]
    return raw


# ---- remove_session ----------------------------------------------------------


def plan_remove_session(raw: str, feed_id: int, session: str) -> TextEdit | None:
    """Locate the session block (and its surrounding comma) for splice-out.

    Returns None if the session is not present on the feed. Raises
    TextApplyError if the feed itself can't be located.
    """
    feed_span = find_feed_block(raw, feed_id)
    if feed_span is None:
        raise TextApplyError(f"feedId={feed_id}: not found in raw text")
    feed_start, feed_end = feed_span
    feed_text = raw[feed_start:feed_end]

    sess_rel = find_session_block(feed_text, session)
    if sess_rel is None:
        return None
    abs_start = feed_start + sess_rel[0]
    abs_end = feed_start + sess_rel[1]

    # Trim one surrounding comma + whitespace. Prefer the preceding comma
    # (most common: removing a non-first entry, and removing the last entry).
    # Fall back to the trailing comma if this is the first entry in the array.
    cut_start = abs_start
    while cut_start > 0 and raw[cut_start - 1] in " \t\n\r":
        cut_start -= 1
    if cut_start > 0 and raw[cut_start - 1] == ",":
        return TextEdit(start=cut_start - 1, end=abs_end, replacement="")

    cut_end = abs_end
    while cut_end < len(raw) and raw[cut_end] in " \t\n\r":
        cut_end += 1
    if cut_end < len(raw) and raw[cut_end] == ",":
        return TextEdit(start=abs_start, end=cut_end + 1, replacement="")

    # Sole entry in marketSchedules: no comma either side. Splice just the block.
    return TextEdit(start=abs_start, end=abs_end, replacement="")


# ---- add_session -------------------------------------------------------------


def plan_add_session(
    raw: str,
    feed_id: int,
    session: str,
    min_publishers: int,
) -> TextEdit | None:
    """Plan a text-level insertion of a new session block.

    Uses the feed's REGULAR session as a formatting template, then rewrites
    fields. Returns None if the session is already present. Raises
    TextApplyError if REGULAR is missing or marketSchedules can't be located.
    """
    feed_span = find_feed_block(raw, feed_id)
    if feed_span is None:
        raise TextApplyError(f"feedId={feed_id}: not found in raw text")
    feed_start, feed_end = feed_span
    feed_text = raw[feed_start:feed_end]

    # Already present? No-op.
    if find_session_block(feed_text, session) is not None:
        return None

    regular_rel = find_session_block(feed_text, "REGULAR")
    if regular_rel is None:
        raise TextApplyError(f"feedId={feed_id}: no REGULAR session to use as template")
    regular_block = feed_text[regular_rel[0] : regular_rel[1]]

    new_block = _rewrite_block_as_session(
        regular_block, session=session, min_publishers=min_publishers
    )

    # Locate marketSchedules array within feed_text.
    ms_array_rel = _find_market_schedules_array(feed_text)
    if ms_array_rel is None:
        raise TextApplyError(
            f"feedId={feed_id}: could not locate marketSchedules array"
        )
    ms_open_rel, ms_close_rel = ms_array_rel  # indices of '[' and ']'

    # Find insertion point: canonical order REGULAR → PRE → POST → OVER_NIGHT.
    target_idx = CANONICAL_ORDER.index(session)
    insert_after_rel = _find_insert_after_position(
        feed_text, target_idx, ms_open_rel, ms_close_rel
    )

    # Determine indentation from the existing REGULAR block's leading
    # whitespace (so the inserted block lines up).
    indent = _leading_indent(feed_text, regular_rel[0])

    if insert_after_rel is None:
        # Insert as first entry (right after the '[').
        abs_anchor = feed_start + ms_open_rel + 1
        # New block + trailing comma + indent for whatever was first before.
        replacement = "\n" + indent + new_block + ","
        return TextEdit(start=abs_anchor, end=abs_anchor, replacement=replacement)

    # Insert immediately after the existing entry at insert_after_rel.
    # That entry ends with `}`; we add ",\n<indent><new_block>".
    abs_anchor = feed_start + insert_after_rel
    replacement = ",\n" + indent + new_block
    return TextEdit(start=abs_anchor, end=abs_anchor, replacement=replacement)


# ---- internals ---------------------------------------------------------------


_FIELD_SESSION_RE = re.compile(r'"session":\s*"REGULAR"')
_FIELD_SCHEDULE_RE = re.compile(r'"marketSchedule":\s*"[^"]*"')
_FIELD_MIN_PUB_RE = re.compile(r'"minPublishers":\s*\d+')
_FIELD_ALLOWED_RE = re.compile(r'"allowedPublisherIds":\s*\[[^\]]*\]', re.DOTALL)
_RIC_IDENT_RE = re.compile(r'"identifier":\s*"([^"]+)"')


def _rewrite_block_as_session(
    regular_block: str, *, session: str, min_publishers: int
) -> str:
    """Take a REGULAR session block's raw text and rewrite it as `session`."""
    out = regular_block

    # session name
    new_session_field = f'"session": "{session}"'
    new_out, n = _FIELD_SESSION_RE.subn(new_session_field, out, count=1)
    if n != 1:
        raise TextApplyError('REGULAR template missing `"session": "REGULAR"`')
    out = new_out

    # marketSchedule string
    canonical_schedule = SCHEDULE_BY_SESSION[session]
    new_sched = f'"marketSchedule": "{canonical_schedule}"'
    out = _FIELD_SCHEDULE_RE.sub(new_sched, out, count=1)

    # minPublishers
    out = _FIELD_MIN_PUB_RE.sub(f'"minPublishers": {min_publishers}', out, count=1)

    # allowedPublisherIds → empty array (preserve original "[ ]" style if used)
    # Detect whether the file uses "[ ]" (spaces) vs "[]" for empty arrays.
    empty_form = "[ ]" if "[ ]" in regular_block else "[]"
    out = _FIELD_ALLOWED_RE.sub(f'"allowedPublisherIds": {empty_form}', out, count=1)

    # OVER_NIGHT: rewrite RIC identifiers to .BLUE
    if session == "OVER_NIGHT":
        out = _rewrite_idents_to_blue(out)

    return out


def _rewrite_idents_to_blue(block: str) -> str:
    def repl(m: re.Match) -> str:
        ident = m.group(1)
        for suffix in US_EQUITY_EXCHANGE_SUFFIXES:
            if ident.endswith(suffix):
                return f'"identifier": "{ident[: -len(suffix)]}.BLUE"'
        return m.group(0)

    return _RIC_IDENT_RE.sub(repl, block)


_MARKET_SCHEDULES_KEY_RE = re.compile(r'"marketSchedules":\s*\[')


def _find_market_schedules_array(feed_text: str) -> tuple[int, int] | None:
    """Return (open_bracket_idx, close_bracket_idx) for the marketSchedules array."""
    m = _MARKET_SCHEDULES_KEY_RE.search(feed_text)
    if m is None:
        return None
    open_idx = feed_text.index("[", m.start())
    close_idx = find_matching_close(feed_text, open_idx)
    if close_idx is None:
        return None
    return (open_idx, close_idx)


def _find_insert_after_position(
    feed_text: str, target_idx: int, ms_open_rel: int, ms_close_rel: int
) -> int | None:
    """Return the relative index ONE PAST the existing entry after which the new
    session should be inserted, or None if it should be the first entry.
    """
    # Walk through marketSchedules array, finding each session entry. For each,
    # check its CANONICAL_ORDER index. The new entry goes after the last
    # existing entry with canonical_idx < target_idx.
    last_eligible_end: int | None = None
    for entry_start, entry_end, sess in _iter_session_entries(
        feed_text, ms_open_rel, ms_close_rel
    ):
        try:
            entry_idx = CANONICAL_ORDER.index(sess)
        except ValueError:
            continue
        if entry_idx < target_idx:
            last_eligible_end = entry_end
    return last_eligible_end


def _iter_session_entries(feed_text: str, ms_open: int, ms_close: int):
    """Yield (start, end, session_name) for each object inside marketSchedules."""
    i = ms_open + 1
    while i < ms_close:
        c = feed_text[i]
        if c == "{":
            end = find_matching_close(feed_text, i)
            if end is None:
                return
            entry_text = feed_text[i : end + 1]
            sess_match = re.search(r'"session":\s*"([^"]+)"', entry_text)
            sess = sess_match.group(1) if sess_match else ""
            yield i, end + 1, sess
            i = end + 1
        else:
            i += 1


def _leading_indent(feed_text: str, block_start: int) -> str:
    """Extract the run of spaces/tabs immediately preceding block_start."""
    i = block_start
    while i > 0 and feed_text[i - 1] in " \t":
        i -= 1
    return feed_text[i:block_start]
