from datetime import datetime, timezone

import numpy as np
import pandas as pd

from lazer_dq.active_min_pub import (
    HISTOGRAM_COLUMNS,
    RESULT_COLUMNS,
    classify,
    derive_asset_type,
    distribution_stats,
    histogram_rows,
    masked_counts,
)
from lazer_dq.min_pub_common import FeedSession as _FS


def test_distribution_stats_basic():
    # min_pub = 2. Values: two updates at floor (<=2), one at floor+1 (==3), rest above.
    # NOTE: adjusted from the brief's [2,2,3,4,4,4,5,5,6,10] (median 4.0, not 4.5
    # as asserted) to [2,2,3,4,4,5,5,5,6,10], which preserves n=10, min=2,
    # pct_at_floor=20.0, pct_at_floor_1=30.0 while making median==4.5 true.
    counts = np.array([2, 2, 3, 4, 4, 5, 5, 5, 6, 10])
    s = distribution_stats(counts, min_pub=2)
    assert s["n_updates"] == 10
    assert s["min"] == 2
    assert s["median"] == 4.5
    # pct_at_floor: publisher_count <= 2 -> 2/10 = 20.0
    assert s["pct_at_floor"] == 20.0
    # pct_at_floor_1: publisher_count <= 3 -> 3/10 = 30.0
    assert s["pct_at_floor_1"] == 30.0
    # percentiles are numpy linear-interp values
    assert s["p1"] == float(np.percentile(counts, 1))
    assert s["p5"] == float(np.percentile(counts, 5))


def test_distribution_stats_empty():
    s = distribution_stats(np.array([], dtype=int), min_pub=2)
    assert s["n_updates"] == 0
    assert s["min"] == 0
    assert s["pct_at_floor"] == 0.0
    assert s["pct_at_floor_1"] == 0.0
    assert s["median"] == 0.0


def _stats(n_updates, pct_at_floor, pct_at_floor_1):
    return {
        "n_updates": n_updates,
        "pct_at_floor": pct_at_floor,
        "pct_at_floor_1": pct_at_floor_1,
    }


def test_classify_no_data_before_everything():
    s = _stats(0, 0.0, 0.0)
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "NO_DATA"


def test_classify_low_sample_below_min_updates():
    s = _stats(99, 50.0, 50.0)  # would be CRITICAL if it had samples
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "LOW_SAMPLE"


def test_classify_critical_at_threshold():
    s = _stats(500, 1.0, 1.0)  # exactly at critical_pct
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "CRITICAL"


def test_classify_warn_only_when_floor_untouched():
    s = _stats(500, 0.0, 5.0)  # never at floor, but >=warn_pct at floor+1
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "WARN"


def test_classify_ok():
    s = _stats(500, 0.0, 4.9)  # below warn_pct at floor+1
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "OK"


def test_classify_min_updates_boundary_is_low_sample_exclusive():
    # n_updates == min_updates is NOT low sample (>= passes)
    s_at = _stats(100, 0.0, 0.0)
    assert classify(s_at, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "OK"
    s_below = _stats(100, 2.0, 2.0)
    assert (
        classify(s_below, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "CRITICAL"
    )


def test_result_columns_contract():
    assert RESULT_COLUMNS == [
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
        "pct_at_floor",
        "pct_at_floor_1",
        "verdict",
    ]


def test_masked_counts_keeps_only_open_minutes():
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)  # Tuesday
    end = datetime(2026, 7, 15, tzinfo=timezone.utc)
    # REGULAR NY 0930-1600 -> 13:30-20:00 UTC (EDT = UTC-4 in July).
    sched = "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;"
    rows = [
        (datetime(2026, 7, 14, 13, 30, 0, 500000), 5),  # 13:30 UTC open -> keep
        (datetime(2026, 7, 14, 13, 30, 0, 900000), 4),  # same minute, keep
        (datetime(2026, 7, 14, 12, 0, 0), 2),  # 12:00 UTC pre-open -> drop
        (datetime(2026, 7, 14, 20, 0, 0), 3),  # 20:00 UTC == close (exclusive) -> drop
        (datetime(2026, 7, 14, 19, 59, 0), 7),  # 19:59 UTC open -> keep
    ]
    counts = masked_counts(rows, sched, start, end)
    assert sorted(counts.tolist()) == [4, 5, 7]


def test_masked_counts_overnight_midnight_crossing():
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, tzinfo=timezone.utc)
    # OVER_NIGHT NY 0000-0400 & 2000-2400 -> UTC 04:00-08:00 & 00:00-04:00 (EDT).
    sched = (
        "America/New_York;"
        "0000-0400&2000-2400,0000-0400&2000-2400,0000-0400&2000-2400,"
        "0000-0400&2000-2400,0000-0400,C,2000-2400;"
    )
    rows = [
        (datetime(2026, 7, 14, 5, 0, 0), 2),  # NY 01:00 -> in 0000-0400 -> keep
        (
            datetime(2026, 7, 14, 1, 0, 0),
            9,
        ),  # NY 21:00 (prev day) -> in 2000-2400 -> keep
        (datetime(2026, 7, 14, 12, 0, 0), 5),  # NY 08:00 -> daytime -> drop
    ]
    counts = masked_counts(rows, sched, start, end)
    assert sorted(counts.tolist()) == [2, 9]


def test_masked_counts_empty_rows():
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, tzinfo=timezone.utc)
    sched = "UTC;O,O,O,O,O,O,O"
    assert masked_counts([], sched, start, end).tolist() == []


from lazer_dq.active_min_pub import fetch_feed_rows


class FakeResult:
    def __init__(self, rows):
        self.result_rows = rows


class ChannelClient:
    """Returns rows only for a specific channel; records queried channels."""

    def __init__(self, rows_by_channel):
        self._rows_by_channel = rows_by_channel
        self.channels_tried = []

    def query(self, sql, parameters=None):
        chan = parameters["channel"]
        self.channels_tried.append(chan)
        return FakeResult(self._rows_by_channel.get(chan, []))


def test_fetch_feed_rows_uses_lowest_channel_with_data():
    t = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    client = ChannelClient({2: [(t.replace(tzinfo=None), 5)]})  # only chan 2 has data
    rows = fetch_feed_rows(client, 100, t, datetime(2026, 7, 15, tzinfo=timezone.utc))
    assert rows == [(t.replace(tzinfo=None), 5)]
    assert client.channels_tried == [1, 2]  # stopped at 2, never tried 3


def test_fetch_feed_rows_no_data_returns_empty():
    client = ChannelClient({})  # no channel has data
    rows = fetch_feed_rows(
        client,
        100,
        datetime(2026, 7, 14, tzinfo=timezone.utc),
        datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    assert rows == []
    assert client.channels_tried == [1, 2, 3]


def test_fetch_feed_rows_query_is_parameterized_and_scoped():
    client = ChannelClient({1: [(datetime(2026, 7, 14, 13, 30), 5)]})
    fetch_feed_rows(
        client,
        321,
        datetime(2026, 7, 14, tzinfo=timezone.utc),
        datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    # last query used channel 1 and feed 321
    from lazer_dq.active_min_pub import PRICE_FEEDS_QUERY

    assert "price_feeds" in PRICE_FEEDS_QUERY
    assert "publisher_count" in PRICE_FEEDS_QUERY
    assert "publisher_updates" not in PRICE_FEEDS_QUERY


from lazer_dq.active_min_pub import analyze_feed
from lazer_dq.min_pub_common import FeedSession


def _regular_session(feed_id=100, min_pub=2):
    return FeedSession(
        feed_id=feed_id,
        symbol="Equity.US.TEST/USD",
        asset_type="equity-us",
        session="REGULAR",
        allowed=frozenset({1, 2, 3, 4, 5}),
        effective_min_pub=min_pub,
        schedule_str="UTC;O,O,O,O,O,O,O",  # always open -> no masking effect
    )


def test_analyze_feed_one_row_per_session_with_verdict():
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, tzinfo=timezone.utc)
    # 200 updates all well above floor -> OK; feed_id 100, channel 1 has data.
    t = datetime(2026, 7, 14, 13, 30)
    rows = [(t, 5)] * 200
    client = ChannelClient({1: rows})
    summary, hist = analyze_feed(
        client,
        [_regular_session()],
        start,
        end,
        critical_pct=1.0,
        warn_pct=5.0,
        min_updates=100,
    )
    assert len(summary) == 1
    r = summary[0]
    assert set(r.keys()) == set(RESULT_COLUMNS)
    assert r["session"] == "REGULAR"
    assert r["n_updates"] == 200
    assert r["verdict"] == "OK"
    # histogram: all 200 updates at publisher_count 5 -> one bucket
    assert len(hist) == 1
    assert set(hist[0].keys()) == set(HISTOGRAM_COLUMNS)
    assert hist[0]["publisher_count"] == 5
    assert hist[0]["n_updates"] == 200
    assert hist[0]["session"] == "REGULAR"


def test_analyze_feed_no_data_when_no_channel_has_rows():
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, tzinfo=timezone.utc)
    client = ChannelClient({})  # empty
    summary, hist = analyze_feed(client, [_regular_session()], start, end, 1.0, 5.0, 100)
    assert summary[0]["verdict"] == "NO_DATA"
    assert summary[0]["n_updates"] == 0
    assert hist == []  # no updates -> no histogram rows


def test_analyze_feed_malformed_schedule_yields_no_schedule():
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, tzinfo=timezone.utc)
    t = datetime(2026, 7, 14, 13, 30)
    client = ChannelClient({1: [(t, 5)] * 200})
    bad = FeedSession(
        feed_id=100,
        symbol="Equity.US.TEST/USD",
        asset_type="equity-us",
        session="PRE_MARKET",
        allowed=frozenset({1, 2}),
        effective_min_pub=2,
        schedule_str="not-a-schedule",
    )
    summary, hist = analyze_feed(client, [bad], start, end, 1.0, 5.0, 100)
    assert summary[0]["verdict"] == "NO_SCHEDULE"
    assert set(summary[0].keys()) == set(RESULT_COLUMNS)
    assert hist == []  # NO_SCHEDULE session contributes no histogram rows


from lazer_dq.active_min_pub import default_window, parse_args, summarize


def test_default_window_is_seven_full_utc_days():
    start, end = default_window()
    assert (end - start) == pd.Timedelta(days=7).to_pytimedelta()
    assert end.hour == 0 and end.minute == 0 and end.second == 0


def test_parse_args_defaults():
    args = parse_args(["--config", "lazer_newest.json"])
    assert args.config == "lazer_newest.json"
    assert args.critical_pct == 1.0
    assert args.warn_pct == 5.0
    assert args.min_updates == 100
    assert args.workers == 8


def test_summarize_tallies_by_verdict():
    rows = [
        {"verdict": "CRITICAL"},
        {"verdict": "CRITICAL"},
        {"verdict": "WARN"},
        {"verdict": "OK"},
        {"verdict": "NO_DATA"},
        {"verdict": "LOW_SAMPLE"},
    ]
    tally = summarize(rows)
    assert tally["CRITICAL"] == 2
    assert tally["WARN"] == 1
    assert tally["OK"] == 1
    assert tally["NO_DATA"] == 1
    assert tally["LOW_SAMPLE"] == 1


def test_sort_rows_critical_first_then_pct_desc():
    from lazer_dq.active_min_pub import sort_rows

    rows = [
        {"verdict": "OK", "pct_at_floor": 0.0},
        {"verdict": "CRITICAL", "pct_at_floor": 2.0},
        {"verdict": "CRITICAL", "pct_at_floor": 9.0},
        {"verdict": "NO_DATA", "pct_at_floor": 0.0},
        {"verdict": "WARN", "pct_at_floor": 0.0},
    ]
    out = sort_rows(rows)
    assert [r["verdict"] for r in out] == [
        "CRITICAL",
        "CRITICAL",
        "WARN",
        "OK",
        "NO_DATA",
    ]
    # within CRITICAL, higher pct_at_floor first
    assert out[0]["pct_at_floor"] == 9.0
    assert out[1]["pct_at_floor"] == 2.0


def test_analyze_feed_none_min_pub_yields_no_min_pub():
    from datetime import datetime, timezone

    from lazer_dq.active_min_pub import analyze_feed, RESULT_COLUMNS
    from lazer_dq.min_pub_common import FeedSession

    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, tzinfo=timezone.utc)
    t = datetime(2026, 7, 14, 13, 30)
    client = ChannelClient({1: [(t, 5)] * 200})
    fs = FeedSession(
        feed_id=100,
        symbol="Equity.US.TEST/USD",
        asset_type="equity-us",
        session="REGULAR",
        allowed=frozenset({1, 2}),
        effective_min_pub=None,
        schedule_str="UTC;O,O,O,O,O,O,O",
    )
    summary, hist = analyze_feed(client, [fs], start, end, 1.0, 5.0, 100)
    assert summary[0]["verdict"] == "NO_MIN_PUB"
    assert set(summary[0].keys()) == set(RESULT_COLUMNS)
    assert hist == []  # NO_MIN_PUB session contributes no histogram rows


def test_histogram_rows_counts_per_distinct_value():
    fs = _FS(
        feed_id=1080,
        symbol="Equity.US.DIA/USD",
        asset_type="equity-us",
        session="OVER_NIGHT",
        allowed=frozenset({1, 2}),
        effective_min_pub=2,
        schedule_str="UTC;O,O,O,O,O,O,O",
    )
    counts = np.array([2, 2, 2, 3, 4, 4])
    rows = histogram_rows(fs, counts)
    # one row per distinct publisher_count, ascending
    assert [(r["publisher_count"], r["n_updates"]) for r in rows] == [
        (2, 3),
        (3, 1),
        (4, 2),
    ]
    # every row carries the full column set + feed-session identity
    for r in rows:
        assert set(r.keys()) == set(HISTOGRAM_COLUMNS)
        assert r["feed_id"] == 1080
        assert r["session"] == "OVER_NIGHT"
        assert r["effective_min_pub"] == 2


def test_derive_asset_type_splits_index_feeds():
    # .Index. feeds get a '<class>-index' asset type per underlying class
    assert derive_asset_type("Equity.Index.NVDA/USD", "equity") == "equity-index"
    assert (
        derive_asset_type("Commodities.Index.COPPER/USD", "commodity")
        == "commodity-index"
    )
    assert derive_asset_type("FX.Index.DXY/USD", "fx") == "fx-index"
    assert derive_asset_type("Metal.Index.XAU/USD", "metal") == "metal-index"
    # already-correct crypto-index is not double-suffixed
    assert derive_asset_type("Crypto.Index.EBTC/USD", "crypto-index") == "crypto-index"
    # a Crypto.Index feed mislabeled plain 'crypto' is fixed to crypto-index
    assert derive_asset_type("Crypto.Index.FOO/USD", "crypto") == "crypto-index"
    # non-index feeds are untouched
    assert derive_asset_type("Equity.US.AAPL/USD", "equity") == "equity"
    assert derive_asset_type("Equity.HK.0668/HKD", "equity") == "equity"
    assert derive_asset_type("Crypto.BTC/USD", "crypto") == "crypto"


def test_base_row_and_histogram_use_derived_asset_type():
    fs = _FS(
        feed_id=3191,
        symbol="Equity.Index.AAPL/USD",
        asset_type="equity",
        session="REGULAR",
        allowed=frozenset({1, 2}),
        effective_min_pub=1,
        schedule_str="UTC;O,O,O,O,O,O,O",
    )
    hist = histogram_rows(fs, np.array([2, 2, 3]))
    assert all(r["asset_type"] == "equity-index" for r in hist)


def test_histogram_rows_empty_when_no_counts():
    fs = _FS(
        feed_id=1,
        symbol="X",
        asset_type="fx",
        session="REGULAR",
        allowed=frozenset(),
        effective_min_pub=2,
        schedule_str="UTC;O,O,O,O,O,O,O",
    )
    assert histogram_rows(fs, np.array([], dtype=int)) == []
