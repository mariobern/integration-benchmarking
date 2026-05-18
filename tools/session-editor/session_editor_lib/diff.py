"""Unified diff with feed-level hunk headers.

Compares two `feeds` lists (before vs after) by emitting a JSON-formatted
diff per feed that changed. Output mirrors the style of edit-config's
diff (feedId / symbol / session-aware hunk headers).
"""

from __future__ import annotations

import difflib
import json
from typing import Any


def render_feed_diff(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Return a unified-diff string for one feed's marketSchedules block.

    Returns "" if before and after marketSchedules are identical.
    """
    before_block = json.dumps(
        before.get("marketSchedules", []), indent=2, sort_keys=False
    )
    after_block = json.dumps(
        after.get("marketSchedules", []), indent=2, sort_keys=False
    )
    if before_block == after_block:
        return ""

    feed_id = after.get("feedId", before.get("feedId", "?"))
    symbol = after.get("symbol", before.get("symbol", "?"))
    header = f"@@ feedId={feed_id} symbol={symbol} @@"

    diff_lines = list(
        difflib.unified_diff(
            before_block.splitlines(),
            after_block.splitlines(),
            fromfile=f"feedId={feed_id}/before",
            tofile=f"feedId={feed_id}/after",
            lineterm="",
            n=2,
        )
    )
    return header + "\n" + "\n".join(diff_lines)


def render_diff(before_feeds: list[dict], after_feeds: list[dict]) -> str:
    by_id_before = {f["feedId"]: f for f in before_feeds}
    by_id_after = {f["feedId"]: f for f in after_feeds}
    chunks: list[str] = []
    for fid in sorted(set(by_id_before) | set(by_id_after)):
        b = by_id_before.get(fid, {})
        a = by_id_after.get(fid, {})
        block = render_feed_diff(b, a)
        if block:
            chunks.append(block)
    return "\n\n".join(chunks)
