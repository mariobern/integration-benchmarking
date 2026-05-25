#!/usr/bin/env python3
"""Apply a dq_summary 'allowed' sheet to after.json.

Reads the 'allowed' sheet of a dq_summary_<cluster>_<date>.xlsx (produced by
lazer_dq/summarize_feeds.py) and edits a Lazer config (after.json / after_1.json)
in place: per-(feed, session) it promotes COMING_SOON feeds to STABLE on their
DQ-vetted publisher lists, and additively adds missing sessions to already-live
(STABLE) feeds without disturbing their live sessions.

Run:
    python3 -m lazer_dq.apply_allowed_to_config \
        --xlsx dq_summary_lazer-prod_2026-05-20.xlsx \
        --config after_1.json --dry-run

See docs/apply_allowed_to_config.md and
docs/superpowers/specs/2026-05-26-apply-dq-summary-to-config-design.md.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from lib.json_surgery import find_feed_block, find_session_block  # noqa: F401

# Session names, in after.json order.
SESSION_ORDER = ["REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT"]

# Publisher 0 (aggregate sentinel) + Lazer publishers. summarize_feeds excludes
# {0} ∪ .Test but NOT Lazer ids, so we strip them defensively here.
EXCLUDED_PUBLISHERS = {0, 1, 9, 13, 15}


def _parse_ids_cell(cell) -> list[int] | None:
    """Extract publisher ids from an 'allowedPublisherIds' cell.

    The cell is either '(no data)'/None or the paste-ready fragment
    '"allowedPublisherIds": [ 41, 69 ],'. Returns a list of ints, or None
    when there is no list.
    """
    if cell is None:
        return None
    text = str(cell)
    if not text.startswith('"allowedPublisherIds"'):
        return None
    m = re.search(r"\[(.*?)\]", text)
    if not m:
        return None
    inner = m.group(1).strip()
    if not inner:
        return []
    return [int(x) for x in inner.split(",") if x.strip()]


def parse_allowed_sheet(path) -> dict[int, dict]:
    """Parse the 'allowed' sheet, grouped by feed_id.

    Returns {feed_id: {"aggregate": list[int]|None,
                       "sessions": {SESSION: list[int]|None}}}.
    Rows that are not genuine data rows are skipped: those whose Feed ID column
    is not an int (title, header, dividers), and the bare-integer "Feeds skipped"
    footer rows (whose Session cell is empty).
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if "allowed" not in wb.sheetnames:
        raise ValueError(f"workbook {path} has no 'allowed' sheet")
    ws = wb["allowed"]

    feeds: dict[int, dict] = {}
    for row in ws.iter_rows(values_only=True):
        if not row or not isinstance(row[0], int):
            continue
        session = row[1]
        # Only genuine data rows register a feed. This ignores the bare-integer
        # "Feeds skipped (no data for any mode):" footer rows that summarize_feeds
        # writes with an empty Session cell.
        if session != "(aggregate)" and session not in SESSION_ORDER:
            continue
        feed_id = row[0]
        ids = _parse_ids_cell(row[2])
        entry = feeds.setdefault(
            feed_id,
            {"aggregate": None, "sessions": {s: None for s in SESSION_ORDER}},
        )
        if session == "(aggregate)":
            entry["aggregate"] = ids
        else:
            entry["sessions"][session] = ids
    return feeds
