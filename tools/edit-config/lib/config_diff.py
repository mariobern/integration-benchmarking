"""Render a list of Change records as a unified-style diff.

Each Change becomes one hunk with a custom header that names the
feedId, symbol, and (optionally) session — far more useful than raw
line numbers in a 3 MB file.
"""

from lib.config_ops import Change


def _format_publisher_list(ids: list[int]) -> str:
    return "[ " + ", ".join(str(i) for i in ids) + " ]" if ids else "[ ]"


def _hunk_header(change: Change) -> str:
    base = f"@@ feedId {change.feed_id} ({change.symbol})"
    if change.location != "top_level":
        base += f", session {change.location}"
    return base + " @@"


def _value_lines(change: Change) -> tuple[str, str]:
    """Return (before_line, after_line) formatted as JSON-ish text."""
    if change.field == "allowedPublisherIds":
        b = f'      "allowedPublisherIds": {_format_publisher_list(change.before)},'
        a = f'      "allowedPublisherIds": {_format_publisher_list(change.after)},'
    elif change.field == "minPublishers":
        b = f'      "minPublishers": {change.before},'
        a = f'      "minPublishers": {change.after},'
    elif change.field == "state":
        b = f'      "state": "{change.before}",'
        a = f'      "state": "{change.after}",'
    else:
        b = f'      "{change.field}": {change.before!r},'
        a = f'      "{change.field}": {change.after!r},'
    return b, a


def render_diff(
    changes: list[Change],
    max_hunks: int = 40,
    show_full: bool = False,
) -> str:
    """Render changes as a unified diff with custom hunk headers."""
    if not changes:
        return "(no changes)\n"

    lines: list[str] = ["--- after.json", "+++ after.json (proposed)"]
    rendered = changes if show_full else changes[:max_hunks]
    for change in rendered:
        lines.append(_hunk_header(change))
        b, a = _value_lines(change)
        lines.append(f"-{b}")
        lines.append(f"+{a}")

    if not show_full and len(changes) > max_hunks:
        remaining = len(changes) - max_hunks
        lines.append(
            f"... ({remaining} more changed lines; rerun with --show-full-diff)"
        )

    return "\n".join(lines) + "\n"
