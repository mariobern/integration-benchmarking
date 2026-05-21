"""Unit tests for evaluate_feeds_bulk.

All tests mock subprocess.run so no real engine ever executes.
"""
import sys
from unittest.mock import MagicMock

import pytest

from lazer_dq.evaluate_feeds_bulk import (
    compute_times_from_mode,
    run_standalone,
    process_csv,
    main,
)


# ---------- compute_times_from_mode ----------


def test_time_computation_us_equities_pre():
    # 2026-05-04 is EDT (UTC-4): 08:30 NY -> 12:30 UTC, 09:30 NY -> 13:30 UTC.
    assert compute_times_from_mode("2026-05-04", "us-equities-pre") == (
        "12:30:00",
        "13:30:00",
    )


def test_time_computation_us_equities_post():
    # EDT: 16:30 NY -> 20:30 UTC, 17:30 NY -> 21:30 UTC.
    assert compute_times_from_mode("2026-05-04", "us-equities-post") == (
        "20:30:00",
        "21:30:00",
    )


def test_time_computation_us_equities_overnight():
    # EDT: 20:00 NY -> 00:00 UTC (next day), 21:00 NY -> 01:00 UTC.
    # The function returns HH:MM:SS only; the date-rollover is handled downstream
    # by the engine when it builds full timestamps from --date + --start-time.
    assert compute_times_from_mode("2026-05-04", "us-equities-overnight") == (
        "00:00:00",
        "01:00:00",
    )


def test_time_computation_default_mode():
    # 2026-12-15 is EST (UTC-5): 09:30 NY -> 14:30 UTC, 10:30 NY -> 15:30 UTC.
    # "us-equities" (and any unknown mode) hits the default branch.
    assert compute_times_from_mode("2026-12-15", "us-equities") == (
        "14:30:00",
        "15:30:00",
    )


def test_time_computation_hk_equities():
    # HKT is fixed UTC+8 year-round (no DST): 09:30 HKT -> 01:30 UTC, 10:30 HKT -> 02:30 UTC.
    assert compute_times_from_mode("2026-05-04", "hk-equities") == (
        "01:30:00",
        "02:30:00",
    )


def test_time_computation_hk_equities_winter():
    # No DST in HK — winter date must produce identical UTC times as summer.
    assert compute_times_from_mode("2026-12-15", "hk-equities") == (
        "01:30:00",
        "02:30:00",
    )


def test_time_computation_hk_equities_case_insensitive():
    # mode_lower normalization should accept mixed-case input.
    assert compute_times_from_mode("2026-05-04", "HK-Equities") == (
        "01:30:00",
        "02:30:00",
    )


# ---------- run_standalone ----------


def test_argv_construction(monkeypatch):
    """run_standalone builds the exact argv expected by evaluate_feed_standalone."""
    captured = []

    def fake_run(argv, check=False):
        captured.append(argv)
        return MagicMock(returncode=0)

    monkeypatch.setattr("lazer_dq.evaluate_feeds_bulk.subprocess.run", fake_run)

    ok = run_standalone(
        feed_id="1021",
        date="2026-05-04",
        mode="us-equities",
        cluster="lazer-prod",
        start_time="13:30:00",
        end_time="14:30:00",
        output_path="dq_reports",
        target_pub_count=4,
    )

    assert ok is True
    assert len(captured) == 1
    assert captured[0] == [
        sys.executable,
        "-m",
        "lazer_dq.evaluate_feed_standalone",
        "--feed-id",
        "1021",
        "--date",
        "2026-05-04",
        "--mode",
        "us-equities",
        "--cluster",
        "lazer-prod",
        "--start-time",
        "13:30:00",
        "--end-time",
        "14:30:00",
        "--output-path",
        "dq_reports",
        "--target-pub-count",
        "4",
    ]


# ---------- process_csv: parsing & override behavior ----------


def _patch_subprocess(monkeypatch, returncodes=None):
    """Helper: patch subprocess.run, return list that captures argvs.

    `returncodes` is a list of return codes to yield in order; if None, all 0.
    """
    captured = []
    rc_iter = iter(returncodes or [])

    def fake_run(argv, check=False):
        captured.append(argv)
        try:
            rc = next(rc_iter)
        except StopIteration:
            rc = 0
        return MagicMock(returncode=rc)

    monkeypatch.setattr(
        "lazer_dq.evaluate_feeds_bulk.subprocess.run",
        fake_run,
    )
    return captured


def test_cli_time_override_bypasses_mode_computation(tmp_path, monkeypatch):
    """When start_time_override and end_time_override are given, mode-derived times are ignored."""
    csv = tmp_path / "input.csv"
    # us-equities-pre would normally compute 12:30/13:30 UTC; override must win.
    csv.write_text("1021, 2026-05-04, us-equities-pre\n")
    captured = _patch_subprocess(monkeypatch)

    process_csv(
        csv_file=csv,
        cluster="lazer-prod",
        start_time_override="18:00:00",
        end_time_override="19:00:00",
        output_path="dq_reports",
        target_pub_count=4,
    )

    assert len(captured) == 1
    argv = captured[0]
    assert argv[argv.index("--start-time") + 1] == "18:00:00"
    assert argv[argv.index("--end-time") + 1] == "19:00:00"


def test_csv_skips_blank_lines(tmp_path, monkeypatch):
    csv = tmp_path / "input.csv"
    csv.write_text(
        "1021, 2026-05-04, us-equities\n" "\n" "   \n" "3226, 2026-05-04, us-equities\n"
    )
    captured = _patch_subprocess(monkeypatch)

    process_csv(
        csv_file=csv,
        cluster="lazer-prod",
        start_time_override=None,
        end_time_override=None,
        output_path="dq_reports",
        target_pub_count=4,
    )

    assert len(captured) == 2  # only the two non-blank rows


def test_csv_skips_short_rows(tmp_path, monkeypatch):
    csv = tmp_path / "input.csv"
    csv.write_text(
        "1021, 2026-05-04, us-equities\n"
        "foobar\n"  # 1 column — skip
        "3226, 2026-05-04\n"  # 2 columns — skip
        "3227, 2026-05-04, us-equities\n"
    )
    captured = _patch_subprocess(monkeypatch)

    process_csv(
        csv_file=csv,
        cluster="lazer-prod",
        start_time_override=None,
        end_time_override=None,
        output_path="dq_reports",
        target_pub_count=4,
    )

    assert len(captured) == 2  # only the two complete rows


def test_csv_tolerates_whitespace(tmp_path, monkeypatch):
    """MV_Mario_1.csv-style leading spaces in cells are stripped."""
    csv = tmp_path / "input.csv"
    csv.write_text("  1021 ,  2026-05-04  ,  us-equities  \n")
    captured = _patch_subprocess(monkeypatch)

    process_csv(
        csv_file=csv,
        cluster="lazer-prod",
        start_time_override=None,
        end_time_override=None,
        output_path="dq_reports",
        target_pub_count=4,
    )

    assert len(captured) == 1
    argv = captured[0]
    assert argv[argv.index("--feed-id") + 1] == "1021"
    assert argv[argv.index("--date") + 1] == "2026-05-04"
    assert argv[argv.index("--mode") + 1] == "us-equities"


# ---------- main: exit codes and summary ----------


def test_exit_code_zero_on_all_success(tmp_path, monkeypatch):
    csv = tmp_path / "input.csv"
    csv.write_text("1021, 2026-05-04, us-equities\n" "3226, 2026-05-04, us-equities\n")
    _patch_subprocess(monkeypatch)  # all returncodes default to 0
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluate_feeds_bulk", "--csv", str(csv), "--cluster", "lazer-prod"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_exit_code_one_on_any_failure(tmp_path, monkeypatch):
    csv = tmp_path / "input.csv"
    csv.write_text(
        "1021, 2026-05-04, us-equities\n"
        "3226, 2026-05-04, us-equities\n"
        "3227, 2026-05-04, us-equities\n"
    )
    # second row fails, others succeed — confirms batch continues past failure
    captured = _patch_subprocess(monkeypatch, returncodes=[0, 1, 0])
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluate_feeds_bulk", "--csv", str(csv), "--cluster", "lazer-prod"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    assert len(captured) == 3  # all rows attempted


def test_summary_line_counts(tmp_path, monkeypatch, capsys):
    csv = tmp_path / "input.csv"
    csv.write_text("1021, 2026-05-04, us-equities\n" "3226, 2026-05-04, us-equities\n")
    _patch_subprocess(monkeypatch, returncodes=[1, 0])  # first fails, second ok
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluate_feeds_bulk", "--csv", str(csv), "--cluster", "lazer-prod"],
    )

    with pytest.raises(SystemExit):
        main()

    captured = capsys.readouterr()
    assert "Processed 2 feeds: 1 succeeded, 1 failed." in captured.out
    assert "1021@2026-05-04" in captured.out


def test_csv_missing_file_exits_1(tmp_path, monkeypatch):
    nonexistent = tmp_path / "nope.csv"
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluate_feeds_bulk", "--csv", str(nonexistent), "--cluster", "lazer-prod"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
