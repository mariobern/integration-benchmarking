"""Tests for lazer_dq.active_pub_distribution pure functions."""
import numpy as np

from lazer_dq.active_pub_distribution import (
    concentration_metrics,
    encode_hist,
    histogram_pcts,
    skew_metrics,
)


def test_histogram_pcts_and_encode():
    counts = np.array([3, 4, 4, 5, 5, 5, 5, 5])
    hist = histogram_pcts(counts)
    assert hist == {3: 12.5, 4: 25.0, 5: 62.5}
    assert encode_hist(hist) == "3:12.50;4:25.00;5:62.50"


def test_histogram_all_zero_minutes():
    assert encode_hist(histogram_pcts(np.zeros(4, dtype=int))) == "0:100.00"


def test_histogram_empty():
    assert histogram_pcts(np.array([], dtype=int)) == {}
    assert encode_hist({}) == ""


def test_skew_metrics():
    counts = np.array([2, 3, 4, 5, 5, 5, 5, 5, 5, 5])
    m = skew_metrics(counts, min_pub=3)
    assert m["open_minutes"] == 10
    assert m["pct_minutes_le_min"] == 20.0  # 2 and 3
    assert m["pct_minutes_le_min_plus_1"] == 30.0  # 2, 3 and 4
    assert m["p10_active"] == 2.9  # linear interpolation
    assert m["median_active"] == 5.0
    assert m["p90_active"] == 5.0
    assert m["worst_minute_active"] == 2


def test_concentration_uniform():
    m = concentration_metrics({1: 100, 2: 100, 3: 100, 4: 100})
    assert m["effective_publishers"] == 4.0
    assert m["top1_share_pct"] == 25.0
    assert m["top3_share_pct"] == 75.0


def test_concentration_dominated():
    m = concentration_metrics({1: 80, 2: 10, 3: 10, 4: 0})
    assert m["effective_publishers"] == round(1 / 0.66, 2)  # hhi = .64+.01+.01
    assert m["top1_share_pct"] == 80.0
    assert m["top3_share_pct"] == 100.0


def test_concentration_no_updates():
    assert concentration_metrics({1: 0, 2: 0}) == {
        "effective_publishers": 0.0,
        "top1_share_pct": 0.0,
        "top3_share_pct": 0.0,
    }


import pandas as pd

from lazer_dq.active_pub_distribution import process_feed, session_rows
from lazer_dq.min_pub_common import FeedSession


def make_fs(**kw):
    defaults = dict(
        feed_id=1,
        symbol="Equity.US.TEST/USD",
        asset_type="equity",
        session="REGULAR",
        allowed=frozenset({10, 20, 30}),
        effective_min_pub=2,
        schedule_str="UTC;O,O,O,O,O,C,C",
    )
    defaults.update(kw)
    return FeedSession(**defaults)


def make_mask(start="2026-07-13 09:00", periods=4, open_all=True):
    idx = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    return pd.Series(open_all, index=idx)


def minute(start, offset):
    return pd.Timestamp(start, tz="UTC") + pd.Timedelta(minutes=offset)


def test_session_rows_metrics_and_details():
    fs = make_fs()
    m0 = "2026-07-13 09:00"
    # minute 0: pubs 10,20 active; minute 1: only 10; minutes 2,3: nothing.
    # pub 99 is NOT allowed -> unlisted, excluded from all metrics.
    per_minute = {
        minute(m0, 0): {10: 5, 20: 1, 99: 7},
        minute(m0, 1): {10: 3},
    }
    summary, details = session_rows(fs, per_minute, make_mask(m0, periods=4))
    assert summary["note"] == ""
    assert summary["allowed_count"] == 3
    assert summary["active_pub_count"] == 2  # 10 and 20
    assert summary["never_published_count"] == 1  # 30
    assert summary["unlisted_active_count"] == 1  # 99
    assert summary["total_accepted_updates"] == 9  # 5+1+3, pub 99 excluded
    assert summary["open_minutes"] == 4
    # active counts per minute: [2, 1, 0, 0]
    assert summary["active_hist"] == "0:50.00;1:25.00;2:25.00"
    assert summary["pct_minutes_le_min"] == 100.0  # all minutes <= min_pub 2
    assert summary["worst_minute_active"] == 0
    assert summary["top1_share_pct"] == round(100.0 * 8 / 9, 2)

    assert [d["publisher_id"] for d in details] == [10, 20, 30]  # rank order
    assert [d["rank"] for d in details] == [1, 2, 3]
    d10 = details[0]
    assert d10["accepted_updates"] == 8
    assert d10["update_share_pct"] == round(100.0 * 8 / 9, 2)
    assert d10["minutes_active"] == 2
    assert d10["pct_open_minutes_active"] == 50.0
    d30 = details[2]
    assert d30["accepted_updates"] == 0
    assert d30["update_share_pct"] == 0.0


def test_session_rows_zero_open_minutes():
    summary, details = session_rows(make_fs(), {}, make_mask(open_all=False))
    assert summary["note"] == "ZERO_OPEN_MINUTES"
    assert details == []
    assert summary["allowed_count"] == 3
    assert "active_hist" not in summary


def test_session_rows_no_updates():
    summary, details = session_rows(make_fs(), {}, make_mask())
    assert summary["note"] == ""
    assert summary["active_hist"] == "0:100.00"
    assert summary["effective_publishers"] == 0.0
    assert len(details) == 3
    assert all(d["update_share_pct"] == 0.0 for d in details)


def test_process_feed_no_schedule(monkeypatch):
    import lazer_dq.active_pub_distribution as apd

    monkeypatch.setattr(apd, "fetch_per_minute_counts", lambda *a: {})
    sessions = [
        make_fs(session="PRE", schedule_str=None),
        make_fs(session="POST", schedule_str="garbage-no-semicolons"),
    ]
    summaries, details = process_feed(None, sessions, None, None)
    assert [s["note"] for s in summaries] == ["NO_SCHEDULE", "NO_SCHEDULE"]
    assert details == []


def test_process_feed_valid_schedule(monkeypatch):
    import lazer_dq.active_pub_distribution as apd

    from datetime import datetime, timezone

    monkeypatch.setattr(
        apd,
        "fetch_per_minute_counts",
        lambda *a: {minute("2026-07-13 00:00", 0): {10: 2}},
    )
    start = datetime(2026, 7, 13, tzinfo=timezone.utc)  # a Monday
    end = datetime(2026, 7, 14, tzinfo=timezone.utc)
    summaries, details = process_feed(None, [make_fs()], start, end)
    assert summaries[0]["note"] == ""
    assert summaries[0]["open_minutes"] == 1440
    assert summaries[0]["active_pub_count"] == 1
    assert len(details) == 3


from lazer_dq.active_pub_distribution import fetch_per_minute_counts, parse_args


class _StubResult:
    def __init__(self, rows):
        self.result_rows = rows


class _StubClient:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def query(self, q, parameters=None):
        self.calls.append(parameters)
        return _StubResult(self._rows)


def test_fetch_per_minute_counts_shapes_rows():
    from datetime import datetime, timezone

    ts0 = datetime(2026, 7, 13, 9, 0)
    client = _StubClient([(ts0, 10, 5), (ts0, 20, 1)])
    out = fetch_per_minute_counts(
        client,
        1,
        datetime(2026, 7, 13, tzinfo=timezone.utc),
        datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    key = pd.Timestamp("2026-07-13 09:00", tz="UTC")
    assert out == {key: {10: 5, 20: 1}}
    assert client.calls[0]["feed_id"] == 1
    assert client.calls[0]["start"] == "2026-07-13 00:00:00"


def test_parse_args_defaults():
    args = parse_args(["--config", "x.json"])
    assert args.workers == 8
    assert args.output_dir == "output_csv"
    assert not args.resume
