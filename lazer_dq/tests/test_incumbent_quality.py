from pathlib import Path

import pandas as pd
import pytest

from lazer_dq.incumbent_quality import (
    FLAGGED_COLUMNS,
    REPORT_COLUMNS,
    SUMMARY_COLUMNS,
    discover_candidates,
    ensure_new_format,
    load_audit_classifications,
    parse_args,
    resume_done_feed_ids,
    summarize_session,
    verdict_from_engine,
    verdict_from_peer,
)


def test_column_contracts():
    assert REPORT_COLUMNS == [
        "feed_id",
        "symbol",
        "session",
        "publisher_id",
        "publisher_role",
        "quality_path",
        "engine_mode",
        "benchmark_date",
        "activity_pct",
        "rmse_over_spread",
        "hit_rate",
        "nrmse",
        "n_obs",
        "verdict",
        "reason",
    ]
    assert SUMMARY_COLUMNS == [
        "feed_id",
        "symbol",
        "session",
        "asset_type",
        "quality_path",
        "n_incumbents",
        "n_pass",
        "n_fail",
        "n_no_data",
        "n_no_benchmark",
        "all_pass",
        "n_candidates",
        "n_candidates_pass",
        "audit_classification",
    ]
    assert FLAGGED_COLUMNS == [
        "feed_id",
        "symbol",
        "session",
        "publisher_id",
        "publisher_role",
        "verdict",
        "reason",
        "detail",
    ]


def test_ensure_new_format_rejects_feed_level_publishers():
    old = {"feeds": [{"feedId": 1, "allowedPublisherIds": [1, 2]}]}
    with pytest.raises(ValueError, match="old-format"):
        ensure_new_format(old)
    new = {"feeds": [{"feedId": 1, "marketSchedules": [{"session": "REGULAR"}]}]}
    ensure_new_format(new)  # no raise


def test_discover_candidates_excludes_allowed_nonproduction_and_excluded():
    matrix_pubs = {1, 2, 3, 4, 5}
    production = {1, 2, 3, 4}
    allowed = frozenset({1})
    excluded = {2}
    assert discover_candidates(matrix_pubs, production, allowed, excluded) == [3, 4]


def test_verdict_from_peer_mapping():
    assert verdict_from_peer(
        {"reason": "pass", "passed": True, "n_observations": 5000}
    ) == ("PASS", "pass")
    assert verdict_from_peer(
        {"reason": "fail_quality", "passed": False, "n_observations": 5000}
    ) == ("FAIL", "fail_quality")
    assert verdict_from_peer(
        {"reason": "insufficient_obs", "passed": False, "n_observations": 0}
    ) == ("NO_DATA", "no_submissions")
    assert verdict_from_peer(
        {"reason": "insufficient_obs", "passed": False, "n_observations": 10}
    ) == ("NO_DATA", "insufficient_obs")
    assert verdict_from_peer(
        {"reason": "zero_range", "passed": False, "n_observations": 5000}
    ) == ("NO_BENCHMARK", "zero_range")


def test_verdict_from_engine_mapping():
    good = {
        "rmse_over_spread": "0.0001",
        "hit_rate_0.1pct": "100",
        "n_observations": "5000",
        "nrmse": "0.0001",
        "pass_fail": "pass",
    }
    bad = {
        "rmse_over_spread": "999",
        "hit_rate_0.1pct": "0",
        "n_observations": "5000",
        "nrmse": "9.9",
        "pass_fail": "fail",
    }
    thin = dict(good, n_observations="3")
    assert verdict_from_engine(None, "us-equities", 1000) == (
        "NO_DATA",
        "no_engine_row",
    )
    assert verdict_from_engine(good, "us-equities", 1000) == ("PASS", "pass")
    assert verdict_from_engine(bad, "us-equities", 1000) == ("FAIL", "fail_quality")
    assert verdict_from_engine(thin, "us-equities", 1000) == (
        "NO_DATA",
        "insufficient_obs",
    )


def _row(role, verdict):
    return {"publisher_role": role, "verdict": verdict}


def test_summarize_session_counts_roles_separately():
    rows = [
        _row("incumbent", "PASS"),
        _row("incumbent", "FAIL"),
        _row("incumbent", "NO_DATA"),
        _row("incumbent", "NO_BENCHMARK"),
        _row("candidate", "PASS"),
        _row("candidate", "FAIL"),
    ]
    s = summarize_session(rows)
    assert s == {
        "n_incumbents": 4,
        "n_pass": 1,
        "n_fail": 1,
        "n_no_data": 1,
        "n_no_benchmark": 1,
        "all_pass": False,
        "n_candidates": 2,
        "n_candidates_pass": 1,
    }
    s_all = summarize_session([_row("incumbent", "PASS")])
    assert s_all["all_pass"] is True
    assert summarize_session([])["all_pass"] is False


def test_load_audit_classifications(tmp_path):
    p = tmp_path / "audit.csv"
    p.write_text(
        "feed_id,symbol,session,classification\n"
        "1,Crypto.A/USD,REGULAR,OK\n"
        "2,Crypto.B/USD,PRE_MARKET,WARN\n"
        "3,DEPRECATED X,,SKIPPED_DEPRECATED\n"
    )
    m = load_audit_classifications(p)
    assert m[(1, "REGULAR")] == "OK"
    assert m[(2, "PRE_MARKET")] == "WARN"
    assert (3, "") not in m  # NaN session rows are skipped


def test_resume_done_feed_ids(tmp_path):
    p = tmp_path / "incumbent_quality_summary.csv"
    assert resume_done_feed_ids(p) == set()
    p.write_text("feed_id,symbol\n1,X\n1,X\n7,Y\n")
    assert resume_done_feed_ids(p) == {1, 7}


def test_parse_args_defaults():
    args = parse_args(
        ["--config", "c.json", "--start-date", "2026-07-08", "--end-date", "2026-07-15"]
    )
    assert args.include_candidates is False
    assert args.workers == 8
    assert args.min_obs == 1000
    assert args.peer_nrmse_auto == 0.05
    assert args.peer_nrmse_cond == 0.15
    assert args.peer_hit_rate == 85.0
    assert args.peer_days == 2
    assert args.cluster == "lazer-prod"
    assert args.output_dir == "output_csv"
    assert args.audit_csv is None
