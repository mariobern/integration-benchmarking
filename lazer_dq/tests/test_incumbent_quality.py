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

import numpy as np

import lazer_dq.incumbent_quality as iq
from lazer_dq.min_pub_common import FeedSession


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


ALWAYS_OPEN = "UTC;O,O,O,O,O,O,O;"


def _args(extra=()):
    args = iq.parse_args(
        [
            "--config",
            "unused.json",
            "--start-date",
            "2026-07-06",
            "--end-date",
            "2026-07-07",
            "--min-obs",
            "50",
            *extra,
        ]
    )
    from datetime import datetime, timezone

    args.start_utc = datetime(2026, 7, 6, tzinfo=timezone.utc)
    args.end_utc = datetime(2026, 7, 7, tzinfo=timezone.utc)
    return args


def _minutes(n):
    return pd.date_range("2026-07-06 00:00", periods=n, freq="1min", tz="UTC")


def _seconds(n):
    return pd.date_range("2026-07-06 00:00:00", periods=n, freq="1s", tz="UTC")


class FakeClient:
    """Dispatches query_df by query shape (activity / aggregate / per-second)."""

    def __init__(self, activity, aggregate, per_second):
        self.activity = activity
        self.aggregate = aggregate
        self.per_second = per_second

    def query_df(self, query, parameters=None):
        if "price_feeds" in query:
            return self.aggregate.copy()
        if "toStartOfMinute" in query:
            return self.activity.copy()
        return self.per_second.copy()


def _peer_fixture():
    """Crypto feed: incumbents 10 (good), 11 (bad), 12 (silent); candidate 30 (good)."""
    n = 200
    secs = _seconds(n)
    agg_prices = 100.0 + np.arange(n) % 10  # range 9 > 0
    aggregate = pd.DataFrame({"ts": secs, "price": agg_prices})
    frames = []
    for pid, prices in (
        (10, agg_prices),  # identical -> PASS
        (11, agg_prices + 50.0),  # nrmse ~5.5 -> FAIL
        (30, agg_prices),  # candidate, identical -> PASS
    ):
        frames.append(pd.DataFrame({"ts": secs, "publisher_id": pid, "price": prices}))
    per_second = pd.concat(frames, ignore_index=True)
    mins = _minutes(60)
    activity = pd.DataFrame(
        {
            "minute": list(mins) * 3,
            "publisher_id": [10] * 60 + [11] * 60 + [30] * 60,
            "n_updates": 1,
        }
    )
    fs = FeedSession(
        feed_id=99,
        symbol="Crypto.TEST/USD",
        asset_type="crypto",
        session="REGULAR",
        allowed=frozenset({10, 11, 12}),
        effective_min_pub=2,
        schedule_str=ALWAYS_OPEN,
    )
    return FakeClient(activity, aggregate, per_second), fs


def test_evaluate_feed_peer_path_verdicts():
    client, fs = _peer_fixture()
    args = _args(["--include-candidates"])
    report, summary, flagged = iq.evaluate_feed(
        client, [fs], args, excluded={0}, production_pubs={10, 11, 12, 30}
    )
    by_pid = {(r["publisher_id"], r["publisher_role"]): r for r in report}
    assert by_pid[(10, "incumbent")]["verdict"] == "PASS"
    assert by_pid[(11, "incumbent")]["verdict"] == "FAIL"
    assert by_pid[(12, "incumbent")]["verdict"] == "NO_DATA"
    assert by_pid[(30, "candidate")]["verdict"] == "PASS"
    assert all(r["quality_path"] == "peer" for r in report)
    (s,) = summary
    assert s["n_incumbents"] == 3 and s["n_pass"] == 1 and s["n_fail"] == 1
    assert s["n_no_data"] == 1 and s["all_pass"] is False
    assert s["n_candidates"] == 1 and s["n_candidates_pass"] == 1
    # flagged: failing incumbents (FAIL + NO_DATA) but not the passing candidate
    flagged_keys = {(r["publisher_id"], r["verdict"]) for r in flagged}
    assert flagged_keys == {(11, "FAIL"), (12, "NO_DATA")}


def test_evaluate_feed_peer_path_without_candidates_flag():
    client, fs = _peer_fixture()
    args = _args()
    report, summary, _ = iq.evaluate_feed(
        client, [fs], args, excluded={0}, production_pubs={10, 11, 12, 30}
    )
    assert {r["publisher_role"] for r in report} == {"incumbent"}
    assert summary[0]["n_candidates"] == 0


def test_evaluate_feed_zero_range_aggregate_is_no_benchmark():
    client, fs = _peer_fixture()
    client.aggregate = pd.DataFrame(
        {"ts": _seconds(200), "price": [100.0] * 200}  # flat -> zero_range
    )
    args = _args()
    report, summary, _ = iq.evaluate_feed(
        client, [fs], args, excluded={0}, production_pubs={10, 11, 12}
    )
    active = [r for r in report if r["publisher_id"] in (10, 11)]
    assert all(r["verdict"] == "NO_BENCHMARK" for r in active)
    assert all(r["reason"] == "zero_range" for r in active)


def test_evaluate_feed_no_schedule_soft_skip():
    client, fs0 = _peer_fixture()
    fs = FeedSession(
        feed_id=fs0.feed_id,
        symbol=fs0.symbol,
        asset_type=fs0.asset_type,
        session=fs0.session,
        allowed=fs0.allowed,
        effective_min_pub=fs0.effective_min_pub,
        schedule_str=None,
    )
    args = _args()
    report, summary, flagged = iq.evaluate_feed(
        client, [fs], args, excluded={0}, production_pubs=set()
    )
    assert report == []
    assert summary[0]["quality_path"] == "none"
    assert summary[0]["all_pass"] is False
    assert flagged[0]["reason"] == "no_schedule"


def test_evaluate_feed_engine_path(monkeypatch):
    n_mins = 60
    activity = pd.DataFrame(
        {
            "minute": list(_minutes(n_mins)) * 2,
            "publisher_id": [20] * n_mins + [21] * n_mins,
            "n_updates": 1,
        }
    )
    client = FakeClient(activity, pd.DataFrame(), pd.DataFrame())
    fs = FeedSession(
        feed_id=42,
        symbol="Equity.US.TEST/USD",
        asset_type="equity",
        session="REGULAR",
        allowed=frozenset({20, 21, 22}),
        effective_min_pub=2,
        schedule_str=ALWAYS_OPEN,
    )
    monkeypatch.setattr(iq, "run_engine", lambda *a, **k: "ok")
    stats = [
        {
            "publisher_id": "20",
            "rmse_over_spread": "0.0001",
            "hit_rate_0.1pct": "100",
            "n_observations": "5000",
            "nrmse": "0.0001",
            "pass_fail": "pass",
        },
        {
            "publisher_id": "21",
            "rmse_over_spread": "999",
            "hit_rate_0.1pct": "0",
            "n_observations": "5000",
            "nrmse": "9.9",
            "pass_fail": "fail",
        },
    ]
    monkeypatch.setattr(iq, "load_stats", lambda *a, **k: stats)
    args = _args()
    report, summary, flagged = iq.evaluate_feed(
        client, [fs], args, excluded={0}, production_pubs={20, 21}
    )
    by_pid = {r["publisher_id"]: r for r in report}
    assert by_pid[20]["verdict"] == "PASS"
    assert by_pid[21]["verdict"] == "FAIL"
    assert by_pid[22]["verdict"] == "NO_DATA"  # incumbent absent from stats
    assert by_pid[20]["quality_path"] == "engine"
    assert by_pid[20]["engine_mode"] == "us-equities"
    assert by_pid[20]["benchmark_date"] != ""
    (s,) = summary
    assert (s["n_pass"], s["n_fail"], s["n_no_data"]) == (1, 1, 1)


def test_evaluate_feed_engine_no_data_is_no_benchmark(monkeypatch):
    activity = pd.DataFrame(columns=["minute", "publisher_id", "n_updates"])
    client = FakeClient(activity, pd.DataFrame(), pd.DataFrame())
    fs = FeedSession(
        feed_id=42,
        symbol="Equity.US.TEST/USD",
        asset_type="equity",
        session="REGULAR",
        allowed=frozenset({20}),
        effective_min_pub=1,
        schedule_str=ALWAYS_OPEN,
    )
    monkeypatch.setattr(iq, "run_engine", lambda *a, **k: "skipped")
    args = _args()
    report, summary, _ = iq.evaluate_feed(
        client, [fs], args, excluded={0}, production_pubs={20}
    )
    assert report[0]["verdict"] == "NO_BENCHMARK"
    assert report[0]["reason"] == "no_engine_data"
