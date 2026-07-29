from pathlib import Path

import pytest

from lazer_dq.active_min_pub_to_audit import (
    EXCLUDED_COLUMNS,
    FLAGGED_COLUMNS,
    bucket_for_row,
    parse_window_from_filename,
    target_verdicts,
    to_excluded_row,
    to_flagged_row,
)


def _row(**overrides):
    base = {
        "feed_id": "100",
        "symbol": "Equity.US.FOO/USD",
        "asset_type": "equity",
        "session": "REGULAR",
        "effective_min_pub": "2",
        "n_updates": "1000",
        "min": "1",
        "p1": "1",
        "p5": "2",
        "median": "2",
        "pct_below_par": "2.0",
        "pct_at_par": "10.0",
        "pct_at_floor": "12.0",
        "pct_at_floor_1": "20.0",
        "verdict": "BREACH",
    }
    base.update(overrides)
    return base


def test_target_verdicts_excludes_warn_by_default():
    assert target_verdicts(include_warn=False) == {"BREACH", "CRITICAL"}


def test_target_verdicts_includes_warn_when_requested():
    assert target_verdicts(include_warn=True) == {"BREACH", "CRITICAL", "WARN"}


def test_bucket_breach_at_or_above_floor_is_flagged():
    assert (
        bucket_for_row(_row(verdict="BREACH", effective_min_pub="2"), 2, False)
        == "flagged"
    )


def test_bucket_critical_above_floor_is_flagged():
    assert (
        bucket_for_row(_row(verdict="CRITICAL", effective_min_pub="3"), 2, False)
        == "flagged"
    )


def test_bucket_critical_below_floor_is_excluded():
    assert (
        bucket_for_row(_row(verdict="CRITICAL", effective_min_pub="1"), 2, False)
        == "excluded"
    )


def test_bucket_breach_below_floor_is_excluded():
    assert (
        bucket_for_row(_row(verdict="BREACH", effective_min_pub="1"), 2, False)
        == "excluded"
    )


def test_bucket_warn_dropped_when_include_warn_off():
    assert (
        bucket_for_row(_row(verdict="WARN", effective_min_pub="2"), 2, False) == "drop"
    )


def test_bucket_warn_flagged_when_include_warn_on():
    assert (
        bucket_for_row(_row(verdict="WARN", effective_min_pub="2"), 2, True)
        == "flagged"
    )


def test_bucket_warn_excluded_when_include_warn_on_and_below_floor():
    assert (
        bucket_for_row(_row(verdict="WARN", effective_min_pub="1"), 2, True)
        == "excluded"
    )


def test_bucket_ok_is_always_dropped():
    assert bucket_for_row(_row(verdict="OK", effective_min_pub="5"), 2, True) == "drop"


def test_bucket_respects_custom_floor():
    # min_pub_floor=3: a CRITICAL row at effective_min_pub=2 no longer clears the bar.
    assert (
        bucket_for_row(_row(verdict="CRITICAL", effective_min_pub="2"), 3, False)
        == "excluded"
    )


def test_to_flagged_row_breach_maps_to_critical_classification():
    row = to_flagged_row(_row(verdict="BREACH"))
    assert row["classification"] == "CRITICAL"
    assert row["source_verdict"] == "BREACH"
    assert set(row.keys()) == set(FLAGGED_COLUMNS)


def test_to_flagged_row_critical_maps_to_critical_classification():
    row = to_flagged_row(_row(verdict="CRITICAL"))
    assert row["classification"] == "CRITICAL"
    assert row["source_verdict"] == "CRITICAL"


def test_to_flagged_row_warn_maps_to_warn_classification():
    row = to_flagged_row(_row(verdict="WARN"))
    assert row["classification"] == "WARN"
    assert row["source_verdict"] == "WARN"


def test_to_flagged_row_preserves_metrics():
    row = to_flagged_row(_row(pct_at_floor="12.0", n_updates="1000"))
    assert row["pct_at_floor"] == "12.0"
    assert row["n_updates"] == "1000"
    assert row["feed_id"] == "100"
    assert row["symbol"] == "Equity.US.FOO/USD"
    assert row["session"] == "REGULAR"


def test_to_excluded_row_shape_and_reason():
    row = to_excluded_row(
        _row(verdict="CRITICAL", effective_min_pub="1"), "min_pub_floor_1"
    )
    assert set(row.keys()) == set(EXCLUDED_COLUMNS)
    assert row["reason"] == "min_pub_floor_1"
    assert row["source_verdict"] == "CRITICAL"
    assert row["effective_min_pub"] == "1"


def test_parse_window_from_filename_valid():
    stamp = parse_window_from_filename(Path("active_min_pub_2026-07-14_2026-07-22.csv"))
    assert stamp == "2026-07-14_2026-07-22"


def test_parse_window_from_filename_valid_with_directory_prefix():
    stamp = parse_window_from_filename(
        Path("output_csv/active_min_pub_2026-07-14_2026-07-22.csv")
    )
    assert stamp == "2026-07-14_2026-07-22"


def test_parse_window_from_filename_rejects_curated_snapshot():
    with pytest.raises(ValueError, match="active_min_pub_CRITICAL_2026-07-22.csv"):
        parse_window_from_filename(Path("active_min_pub_CRITICAL_2026-07-22.csv"))


def test_parse_window_from_filename_rejects_unrelated_name():
    with pytest.raises(ValueError):
        parse_window_from_filename(Path("min_pub_audit_2026-07-14_2026-07-22.csv"))
