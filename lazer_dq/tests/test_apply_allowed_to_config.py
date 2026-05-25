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


from lazer_dq.apply_allowed_to_config import filter_publishers, get_min_publishers


def test_filter_publishers_strips_zero_and_lazer():
    kept, removed = filter_publishers([0, 1, 9, 13, 15, 24, 35, 42])
    assert kept == [24, 35, 42]
    assert removed == [0, 1, 9, 13, 15]


def test_filter_publishers_keeps_sorted_unique():
    kept, removed = filter_publishers([42, 24, 24, 35])
    assert kept == [24, 35, 42]
    assert removed == []


def test_get_min_publishers_defaults():
    assert get_min_publishers("REGULAR", 10) == 3
    assert get_min_publishers("PRE_MARKET", 10) == 2
    assert get_min_publishers("POST_MARKET", 10) == 2
    assert get_min_publishers("OVER_NIGHT", 10) == 1


def test_get_min_publishers_regular_low_count_rule():
    assert get_min_publishers("REGULAR", 5) == 2
    assert get_min_publishers("REGULAR", 1) == 2
    assert get_min_publishers("REGULAR", 6) == 3


from lazer_dq.apply_allowed_to_config import (
    set_top_level_allowed,
    set_top_level_min_publishers,
    overwrite_session,
    add_session,
    SCHEDULE_TEMPLATES,
)


def test_set_top_level_allowed_replaces_array_before_marketschedules():
    block = (
        '{\n      "allowedPublisherIds": [\n        1,\n        2\n      ],\n'
        '      "marketSchedules": [ {"allowedPublisherIds": [9], '
        '"session": "REGULAR"} ]\n}'
    )
    out = set_top_level_allowed(block, [24, 35])
    # Top-level array (before marketSchedules) replaced; session array untouched.
    assert '"allowedPublisherIds": [ 24, 35 ]' in out
    assert '"allowedPublisherIds": [9]' in out
    assert out.index("[ 24, 35 ]") < out.index("[9]")


def test_set_top_level_min_publishers_targets_field_after_marketschedules():
    # Mirrors after.json: a session minPublishers appears BEFORE the top-level one.
    block = (
        '{\n      "allowedPublisherIds": [ 1 ],\n'
        '      "marketSchedules": [ {\n'
        '          "minPublishers": 3,\n'
        '          "session": "REGULAR"\n'
        "        } ],\n"
        '      "minPublishers": 3,\n'
        '      "state": "STABLE"\n}'
    )
    out = set_top_level_min_publishers(block, 1)
    data = json.loads(out)
    assert data["minPublishers"] == 1  # top-level changed
    assert data["marketSchedules"][0]["minPublishers"] == 3  # session untouched


def test_overwrite_session_replaces_ids_and_minpub():
    block = (
        '{ "marketSchedules": [ {\n'
        '          "allowedPublisherIds": [ 1, 2, 3 ],\n'
        '          "minPublishers": 3,\n'
        '          "session": "REGULAR"\n'
        "        } ] }"
    )
    out = overwrite_session(block, "REGULAR", [24, 35, 42])
    assert '"allowedPublisherIds": [ 24, 35, 42 ]' in out
    assert '"minPublishers": 2' in out  # 3 publishers => REGULAR low-count => 2
    assert '"session": "REGULAR"' in out


def test_overwrite_session_handles_null_array():
    block = (
        '{ "marketSchedules": [ {\n'
        '          "allowedPublisherIds": null,\n'
        '          "minPublishers": 3,\n'
        '          "session": "PRE_MARKET"\n'
        "        } ] }"
    )
    out = overwrite_session(block, "PRE_MARKET", [24, 35])
    assert '"allowedPublisherIds": [ 24, 35 ]' in out
    assert "null" not in out
    assert '"minPublishers": 2' in out


def test_add_session_inserts_entry_with_benchmark_mapping():
    block = (
        '{ "marketSchedules": [\n'
        "        {\n"
        '          "allowedPublisherIds": [ 11 ],\n'
        '          "marketSchedule": "X",\n'
        '          "minPublishers": 3,\n'
        '          "session": "REGULAR"\n'
        "        }\n"
        "      ]\n}"
    )
    bench = {"datascope_ric": {"identifiers": [{"identifier": "AAPL.O"}]}}
    out = add_session(block, "PRE_MARKET", [24, 35], bench)
    # Still valid JSON after the insert.
    data = json.loads(out)
    sessions = {s["session"]: s for s in data["marketSchedules"]}
    assert set(sessions) == {"REGULAR", "PRE_MARKET"}
    pre = sessions["PRE_MARKET"]
    assert pre["allowedPublisherIds"] == [24, 35]
    assert pre["minPublishers"] == 2  # PRE_MARKET default
    assert pre["benchmarkMapping"] == bench
    assert pre["marketSchedule"] == SCHEDULE_TEMPLATES["PRE_MARKET"]
    # REGULAR untouched.
    assert sessions["REGULAR"]["allowedPublisherIds"] == [11]
