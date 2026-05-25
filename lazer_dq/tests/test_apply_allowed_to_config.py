"""Unit + integration tests for apply_allowed_to_config."""
import json
from pathlib import Path

import openpyxl
import pytest

from lazer_dq.apply_allowed_to_config import parse_allowed_sheet


def _write_allowed_workbook(path: Path, rows: list[tuple]) -> None:
    """rows: list of (feed_id, session, allowed_cell, note). Builds a 2-sheet
    workbook matching summarize_feeds output (rankings sheet present but empty)."""
    wb = openpyxl.Workbook()
    wb.active.title = "rankings"  # present but unused by the reader
    ws = wb.create_sheet("allowed")
    ws.cell(row=1, column=1, value="Allowed Publishers — test — 2026-05-20")
    for i, h in enumerate(["Feed ID", "Session", "allowedPublisherIds", "Notes"], 1):
        ws.cell(row=2, column=i, value=h)
    r = 3
    for feed_id, session, allowed_cell, note in rows:
        ws.cell(row=r, column=1, value=feed_id)
        ws.cell(row=r, column=2, value=session)
        ws.cell(row=r, column=3, value=allowed_cell)
        ws.cell(row=r, column=4, value=note)
        r += 1
    wb.save(path)


def _agg(ids):
    return '"allowedPublisherIds": [ ' + ", ".join(str(i) for i in ids) + " ],"


def test_parse_allowed_sheet_reads_lists_and_no_data(tmp_path):
    xlsx = tmp_path / "dq.xlsx"
    _write_allowed_workbook(
        xlsx,
        [
            (100, "(aggregate)", _agg([24, 35, 42]), None),
            (100, "REGULAR", _agg([24, 35, 42]), "0 passed + 3 top-up (≤2×)"),
            (100, "PRE_MARKET", "(no data)", "mode missing for 2026-05-20"),
            (100, "POST_MARKET", "(no data)", "mode missing for 2026-05-20"),
            (100, "OVER_NIGHT", "(no data)", "mode missing for 2026-05-20"),
            (None, None, None, None),  # divider
            (200, "(aggregate)", "(no data)", "all sessions empty"),
            (200, "REGULAR", "(no data)", "mode missing for 2026-05-20"),
        ],
    )

    result = parse_allowed_sheet(xlsx)

    assert set(result.keys()) == {100, 200}
    assert result[100]["aggregate"] == [24, 35, 42]
    assert result[100]["sessions"]["REGULAR"] == [24, 35, 42]
    assert result[100]["sessions"]["PRE_MARKET"] is None
    assert result[200]["aggregate"] is None
    assert result[200]["sessions"]["REGULAR"] is None


def test_parse_allowed_sheet_ignores_skipped_footer_rows(tmp_path):
    xlsx = tmp_path / "dq_footer.xlsx"
    _write_allowed_workbook(
        xlsx,
        [
            (100, "(aggregate)", _agg([24, 35]), None),
            (100, "REGULAR", _agg([24, 35]), None),
            (None, None, None, None),  # divider
            # Simulated "Feeds skipped" footer: bare integer feed id, no session.
            (777, None, None, None),
        ],
    )
    result = parse_allowed_sheet(xlsx)
    assert set(result.keys()) == {100}  # 777 footer row must NOT become a feed
    assert result[100]["aggregate"] == [24, 35]
