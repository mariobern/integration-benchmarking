import csv
from pathlib import Path

import pytest

from lazer_dq.active_min_pub_to_audit import (
    EXCLUDED_COLUMNS,
    FLAGGED_COLUMNS,
    bucket_for_row,
    main,
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


def test_bucket_no_min_pub_row_with_blank_min_pub_is_dropped():
    # Real active_min_pub.py output can have an empty-string effective_min_pub for
    # NO_MIN_PUB/NO_SCHEDULE verdicts. This only works because the verdict-membership
    # check in bucket_for_row() runs before int(row["effective_min_pub"]) -- pin that
    # ordering so a future refactor can't silently reintroduce a ValueError crash.
    assert (
        bucket_for_row(_row(verdict="NO_MIN_PUB", effective_min_pub=""), 2, True)
        == "drop"
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


_HEADER = [
    "feed_id",
    "symbol",
    "asset_type",
    "session",
    "effective_min_pub",
    "n_updates",
    "min",
    "p1",
    "p5",
    "median",
    "pct_below_par",
    "pct_at_par",
    "pct_at_floor",
    "pct_at_floor_1",
    "verdict",
]

_FIXTURE_ROWS = [
    # feed 100: BREACH, min_pub=2 -> flagged, pct_at_floor=12.0
    [
        "100",
        "Equity.US.AAA/USD",
        "equity",
        "REGULAR",
        "2",
        "1000",
        "1",
        "1",
        "2",
        "2",
        "2.0",
        "10.0",
        "12.0",
        "20.0",
        "BREACH",
    ],
    # feed 101: CRITICAL, min_pub=3 -> flagged, pct_at_floor=5.0
    [
        "101",
        "Equity.US.BBB/USD",
        "equity",
        "REGULAR",
        "3",
        "1000",
        "3",
        "3",
        "3",
        "4",
        "0.0",
        "5.0",
        "5.0",
        "15.0",
        "CRITICAL",
    ],
    # feed 102: CRITICAL, min_pub=1 -> excluded (structurally single-source)
    [
        "102",
        "InterestRate.US10Y/USD",
        "interest-rate",
        "REGULAR",
        "1",
        "1000",
        "1",
        "1",
        "1",
        "1",
        "0.0",
        "100.0",
        "100.0",
        "100.0",
        "CRITICAL",
    ],
    # feed 103: WARN, min_pub=2 -> dropped by default, flagged when --include-warn
    [
        "103",
        "Equity.US.CCC/USD",
        "equity",
        "OVER_NIGHT",
        "2",
        "1000",
        "2",
        "2",
        "2",
        "3",
        "0.0",
        "0.0",
        "0.0",
        "8.0",
        "WARN",
    ],
    # feed 104: OK -> always dropped
    [
        "104",
        "Equity.US.DDD/USD",
        "equity",
        "REGULAR",
        "5",
        "1000",
        "5",
        "5",
        "6",
        "8",
        "0.0",
        "0.0",
        "0.0",
        "0.5",
        "OK",
    ],
]


def _write_fixture(path):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_HEADER)
        writer.writerows(_FIXTURE_ROWS)


def test_main_default_flags_breach_and_critical_only(tmp_path, capsys):
    in_path = tmp_path / "active_min_pub_2026-07-14_2026-07-22.csv"
    _write_fixture(in_path)
    out_dir = tmp_path / "out"

    rc = main(
        [
            "--active-min-pub-csv",
            str(in_path),
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0

    flagged_path = out_dir / "active_min_pub_flagged_2026-07-14_2026-07-22.csv"
    excluded_path = out_dir / "active_min_pub_excluded_2026-07-14_2026-07-22.csv"
    assert flagged_path.exists()
    assert excluded_path.exists()

    with open(flagged_path, newline="") as f:
        flagged = list(csv.DictReader(f))
    assert [r["feed_id"] for r in flagged] == ["100", "101"]  # sorted pct_at_floor desc
    assert flagged[0]["classification"] == "CRITICAL"
    assert flagged[0]["source_verdict"] == "BREACH"
    assert flagged[1]["classification"] == "CRITICAL"
    assert flagged[1]["source_verdict"] == "CRITICAL"

    with open(excluded_path, newline="") as f:
        excluded = list(csv.DictReader(f))
    assert [r["feed_id"] for r in excluded] == ["102"]
    assert excluded[0]["reason"] == "below_min_pub_floor_2"

    out = capsys.readouterr().out
    assert "Flagged 2 feed-sessions" in out
    assert "Excluded 1 feed-sessions" in out
    assert "Skipped 1 WARN rows" in out


def test_main_include_warn_adds_warn_rows(tmp_path):
    in_path = tmp_path / "active_min_pub_2026-07-14_2026-07-22.csv"
    _write_fixture(in_path)
    out_dir = tmp_path / "out"

    rc = main(
        [
            "--active-min-pub-csv",
            str(in_path),
            "--output-dir",
            str(out_dir),
            "--include-warn",
        ]
    )
    assert rc == 0

    flagged_path = out_dir / "active_min_pub_flagged_2026-07-14_2026-07-22.csv"
    with open(flagged_path, newline="") as f:
        flagged = list(csv.DictReader(f))
    feed_ids = {r["feed_id"] for r in flagged}
    assert feed_ids == {"100", "101", "103"}
    warn_row = next(r for r in flagged if r["feed_id"] == "103")
    assert warn_row["classification"] == "WARN"
    assert warn_row["source_verdict"] == "WARN"


def test_main_custom_min_pub_floor(tmp_path):
    in_path = tmp_path / "active_min_pub_2026-07-14_2026-07-22.csv"
    _write_fixture(in_path)
    out_dir = tmp_path / "out"

    rc = main(
        [
            "--active-min-pub-csv",
            str(in_path),
            "--output-dir",
            str(out_dir),
            "--min-pub-floor",
            "3",
        ]
    )
    assert rc == 0

    flagged_path = out_dir / "active_min_pub_flagged_2026-07-14_2026-07-22.csv"
    excluded_path = out_dir / "active_min_pub_excluded_2026-07-14_2026-07-22.csv"
    with open(flagged_path, newline="") as f:
        flagged = list(csv.DictReader(f))
    assert [r["feed_id"] for r in flagged] == ["101"]  # only min_pub=3 clears floor=3

    with open(excluded_path, newline="") as f:
        excluded = list(csv.DictReader(f))
    assert {r["feed_id"] for r in excluded} == {"100", "102"}  # both min_pub < 3 now


def test_main_bad_filename_errors_without_writing_output(tmp_path, capsys):
    in_path = tmp_path / "active_min_pub_CRITICAL_2026-07-22.csv"
    _write_fixture(in_path)
    out_dir = tmp_path / "out"

    rc = main(
        [
            "--active-min-pub-csv",
            str(in_path),
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 1
    assert "ERROR" in capsys.readouterr().out
    assert not out_dir.exists()


def test_main_missing_columns_errors_without_writing_output(tmp_path, capsys):
    # Real active_min_pub_*.csv files predating the BREACH/CRITICAL split lack
    # pct_below_par/pct_at_par; main() must reject them cleanly rather than crash
    # inside to_flagged_row() with a bare KeyError.
    in_path = tmp_path / "active_min_pub_2026-07-14_2026-07-22.csv"
    legacy_header = [c for c in _HEADER if c not in ("pct_below_par", "pct_at_par")]
    with open(in_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(legacy_header)
        writer.writerow(
            [
                v
                for c, v in zip(_HEADER, _FIXTURE_ROWS[0])
                if c not in ("pct_below_par", "pct_at_par")
            ]
        )
    out_dir = tmp_path / "out"

    rc = main(
        [
            "--active-min-pub-csv",
            str(in_path),
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert "pct_below_par" in out
    assert "pct_at_par" in out
    assert not out_dir.exists()


def test_main_empty_input_produces_empty_outputs_with_headers(tmp_path):
    in_path = tmp_path / "active_min_pub_2026-07-14_2026-07-22.csv"
    with open(in_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_HEADER)
    out_dir = tmp_path / "out"

    rc = main(
        [
            "--active-min-pub-csv",
            str(in_path),
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0

    flagged_path = out_dir / "active_min_pub_flagged_2026-07-14_2026-07-22.csv"
    with open(flagged_path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    assert header == FLAGGED_COLUMNS
    assert rows == []
