from lib.publisher_asset_map_core import (
    PublisherFeedRow,
    build_matrix,
    build_summary,
    day_window,
    fetch_publisher_feeds,
    fetch_publisher_names,
)


def _rows():
    return [
        PublisherFeedRow(32, "Blueocean.Production", 1163, "AAPL", "equity-us", 100),
        PublisherFeedRow(32, "Blueocean.Production", 1164, "MSFT", "equity-us", 50),
        PublisherFeedRow(32, "Blueocean.Production", 345, "XAU/USD", "metal", 20),
        PublisherFeedRow(11, "Amber.Production", 345, "XAU/USD", "metal", 7),
    ]


class TestDayWindow:
    def test_basic_day(self):
        assert day_window("2026-06-23") == (
            "2026-06-23 00:00:00",
            "2026-06-24 00:00:00",
        )

    def test_month_rollover(self):
        assert day_window("2026-06-30") == (
            "2026-06-30 00:00:00",
            "2026-07-01 00:00:00",
        )


class TestBuildSummary:
    def test_groups_by_publisher_and_class(self):
        summary = build_summary(_rows())
        assert {
            "publisher_id": 32,
            "publisher_name": "Blueocean.Production",
            "asset_class": "equity-us",
            "session": "all",
            "feed_count": 2,
            "total_updates": 150,
        } in summary

    def test_metal_rollup(self):
        summary = build_summary(_rows())
        metal_32 = [
            r
            for r in summary
            if r["publisher_id"] == 32 and r["asset_class"] == "metal"
        ]
        assert metal_32[0]["feed_count"] == 1
        assert metal_32[0]["total_updates"] == 20
        assert metal_32[0]["session"] == "all"

    def test_sorted_by_publisher_then_class(self):
        summary = build_summary(_rows())
        keys = [(r["publisher_id"], r["asset_class"], r["session"]) for r in summary]
        assert keys == sorted(keys)


class TestBuildMatrix:
    def test_columns_are_sorted_classes(self):
        cols, _ = build_matrix(_rows())
        assert cols == ["equity-us", "metal"]

    def test_absent_class_is_zero(self):
        _, matrix = build_matrix(_rows())
        amber = [r for r in matrix if r["publisher_id"] == 11][0]
        assert amber["equity-us"] == 0
        assert amber["metal"] == 1

    def test_feed_counts(self):
        _, matrix = build_matrix(_rows())
        blue = [r for r in matrix if r["publisher_id"] == 32][0]
        assert blue["equity-us"] == 2
        assert blue["metal"] == 1


class _FakeResult:
    def __init__(self, rows):
        self.result_rows = rows


class _FakeClient:
    """Returns names rows for the names query, feed rows otherwise."""

    def __init__(self, name_rows, feed_rows):
        self._name_rows = name_rows
        self._feed_rows = feed_rows
        self.last_params = None

    def query(self, sql, parameters=None):
        self.last_params = parameters
        if "publishers_metadata_latest" in sql:
            return _FakeResult(self._name_rows)
        return _FakeResult(self._feed_rows)


def _client():
    return _FakeClient(
        name_rows=[(32, "Blueocean.Production"), (11, "Amber.Production")],
        feed_rows=[
            # publisher_id, feed_id, update_count, asset_type, symbol, session
            (32, 1163, 100, "equity", "Equity.US.AAPL/USD", "regular"),
            (32, 345, 20, "metal", "XAU/USD", "all"),
            (11, 999, 5, "equity", "Equity.HK.0700/HKD", "all"),
            (11, 888, 3, None, None, "all"),  # no metadata -> unknown / blank
        ],
    )


class TestFetchPublisherNames:
    def test_builds_id_to_name_map(self):
        names = fetch_publisher_names(_client())
        assert names == {32: "Blueocean.Production", 11: "Amber.Production"}

    def test_null_publisher_name_becomes_empty(self):
        client = _FakeClient(name_rows=[(7, None)], feed_rows=[])
        assert fetch_publisher_names(client) == {7: ""}


class TestFetchPublisherFeeds:
    def test_categorizes_and_names(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        aapl = [r for r in rows if r.feed_id == 1163][0]
        assert aapl.asset_class == "equity-us"
        assert aapl.publisher_name == "Blueocean.Production"
        assert aapl.update_count == 100
        assert aapl.session == "regular"

    def test_foreign_equity_country(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        hk = [r for r in rows if r.feed_id == 999][0]
        assert hk.asset_class == "equity-hk"
        assert hk.session == "all"

    def test_missing_metadata_is_unknown(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        orphan = [r for r in rows if r.feed_id == 888][0]
        assert orphan.asset_class == "unknown"
        assert orphan.symbol == ""
        assert orphan.session == "all"

    def test_missing_publisher_name_is_blank(self):
        client = _FakeClient(
            name_rows=[],
            feed_rows=[(7, 1, 1, "fx", "EUR/USD", "all")],
        )
        rows = fetch_publisher_feeds(client, "2026-06-23")
        assert rows[0].publisher_name == ""

    def test_passes_day_window_params(self):
        client = _client()
        fetch_publisher_feeds(client, "2026-06-23")
        assert client.last_params["start"] == "2026-06-23 00:00:00"
        assert client.last_params["end"] == "2026-06-24 00:00:00"

    def test_asset_class_filter_equity_country(self):
        rows = fetch_publisher_feeds(
            _client(), "2026-06-23", asset_class_filter="equity-us"
        )
        assert {r.feed_id for r in rows} == {1163}

    def test_asset_class_filter_plain(self):
        rows = fetch_publisher_feeds(
            _client(), "2026-06-23", asset_class_filter="metal"
        )
        assert {r.feed_id for r in rows} == {345}


import csv  # noqa: E402
from pathlib import Path  # noqa: E402

from lib.publisher_asset_map_core import write_outputs  # noqa: E402


def test_write_outputs_creates_three_csvs(tmp_path: Path):
    rows = [
        PublisherFeedRow(32, "Blueocean.Production", 1163, "AAPL", "equity-us", 100),
        PublisherFeedRow(32, "Blueocean.Production", 345, "XAU/USD", "metal", 20),
        PublisherFeedRow(11, "Amber.Production", 345, "XAU/USD", "metal", 7),
    ]
    paths = write_outputs(rows, "2026-06-23", tmp_path)

    assert [p.name for p in paths] == [
        "publisher_asset_map_2026-06-23.csv",
        "publisher_asset_map_summary_2026-06-23.csv",
        "publisher_asset_map_matrix_2026-06-23.csv",
    ]
    for p in paths:
        assert p.exists()

    with open(paths[0]) as f:
        detail = list(csv.DictReader(f))
    assert detail[0] == {
        "publisher_id": "11",
        "publisher_name": "Amber.Production",
        "feed_id": "345",
        "symbol": "XAU/USD",
        "asset_class": "metal",
        "session": "all",
        "update_count": "7",
    }

    with open(paths[2]) as f:
        matrix = list(csv.DictReader(f))
    assert matrix[0]["publisher_id"] == "11"
    assert matrix[0]["equity-us"] == "0"
    assert matrix[0]["metal"] == "1"


def test_feeds_by_asset_class_counts_distinct_feeds():
    from lib.publisher_asset_map_core import feeds_by_asset_class

    rows = [
        PublisherFeedRow(32, "Blueocean.Production", 345, "XAU/USD", "metal", 20),
        PublisherFeedRow(11, "Amber.Production", 345, "XAU/USD", "metal", 7),
        PublisherFeedRow(32, "Blueocean.Production", 1163, "AAPL", "equity-us", 100),
    ]
    # feed 345 is shared by two publishers -> counted once
    assert feeds_by_asset_class(rows) == {"equity-us": 1, "metal": 1}


def test_summary_splits_us_equity_by_session():
    rows = [
        PublisherFeedRow(
            28,
            "MEMX.Production",
            1163,
            "Equity.US.AAPL/USD",
            "equity-us",
            100,
            "regular",
        ),
        PublisherFeedRow(
            28,
            "MEMX.Production",
            1163,
            "Equity.US.AAPL/USD",
            "equity-us",
            40,
            "premarket",
        ),
        PublisherFeedRow(
            28,
            "MEMX.Production",
            1164,
            "Equity.US.MSFT/USD",
            "equity-us",
            60,
            "regular",
        ),
    ]
    summary = build_summary(rows)
    reg = [r for r in summary if r["session"] == "regular"][0]
    pre = [r for r in summary if r["session"] == "premarket"][0]
    assert reg["feed_count"] == 2 and reg["total_updates"] == 160
    assert pre["feed_count"] == 1 and pre["total_updates"] == 40


class TestSessionSql:
    def test_bounds_from_constants(self):
        from lib.publisher_asset_map_core import _et_session_bounds

        assert _et_session_bounds() == (240, 570, 960, 1200)

    def test_session_case_sql_has_labels_and_bounds(self):
        from lib.publisher_asset_map_core import session_case_sql

        sql = session_case_sql("pu.publish_time", "fm.symbol")
        for token in ("multiIf", "America/New_York", "Equity.US.%", "fm.symbol"):
            assert token in sql
        for label in (
            "'all'",
            "'premarket'",
            "'regular'",
            "'afterhours'",
            "'overnight'",
        ):
            assert label in sql
        for bound in ("240", "570", "960", "1200"):
            assert bound in sql


def test_feeds_by_session_us_equity_only():
    from lib.publisher_asset_map_core import feeds_by_session

    rows = [
        PublisherFeedRow(
            28,
            "MEMX.Production",
            1163,
            "Equity.US.AAPL/USD",
            "equity-us",
            100,
            "regular",
        ),
        PublisherFeedRow(
            28,
            "MEMX.Production",
            1163,
            "Equity.US.AAPL/USD",
            "equity-us",
            40,
            "premarket",
        ),
        PublisherFeedRow(
            28,
            "MEMX.Production",
            1164,
            "Equity.US.MSFT/USD",
            "equity-us",
            60,
            "regular",
        ),
        # non-US-equity rows are ignored
        PublisherFeedRow(
            11, "Amber.Production", 999, "Equity.HK.0700/HKD", "equity-hk", 9, "all"
        ),
        PublisherFeedRow(1, "Lazer.Binance", 1, "Crypto.BTC/USD", "crypto", 5, "all"),
    ]
    # premarket: feed 1163; regular: feeds 1163 + 1164 (distinct)
    assert feeds_by_session(rows) == {"premarket": 1, "regular": 2}


def test_matrix_counts_us_equity_feed_once_across_sessions():
    from lib.publisher_asset_map_core import build_matrix

    rows = [
        PublisherFeedRow(
            28,
            "MEMX.Production",
            1163,
            "Equity.US.AAPL/USD",
            "equity-us",
            100,
            "regular",
        ),
        PublisherFeedRow(
            28,
            "MEMX.Production",
            1163,
            "Equity.US.AAPL/USD",
            "equity-us",
            40,
            "premarket",
        ),
        PublisherFeedRow(
            28,
            "MEMX.Production",
            1164,
            "Equity.US.MSFT/USD",
            "equity-us",
            60,
            "overnight",
        ),
    ]
    classes, matrix = build_matrix(rows)
    assert classes == ["equity-us"]
    # feed 1163 appears in two sessions but must count once -> 2 distinct feeds total
    assert matrix[0]["equity-us"] == 2


class TestSessionProbeWindows:
    def test_count_and_width_default(self):
        from lib.publisher_asset_map_core import session_probe_windows

        ws = session_probe_windows("2026-06-23")  # interval 30, width 2
        assert len(ws) == 48
        from datetime import datetime

        s = datetime.fromisoformat(ws[0].start_utc)
        e = datetime.fromisoformat(ws[0].end_utc)
        assert (e - s).total_seconds() == 120  # 2-min wide

    def test_even_spacing(self):
        from datetime import datetime
        from lib.publisher_asset_map_core import session_probe_windows

        ws = session_probe_windows("2026-06-23")
        starts = [datetime.fromisoformat(w.start_utc) for w in ws]
        gaps = {
            (starts[i + 1] - starts[i]).total_seconds() for i in range(len(starts) - 1)
        }
        assert gaps == {1800.0}  # uniform 30-min spacing

    def test_first_window_premarket_utc(self):
        from lib.publisher_asset_map_core import session_probe_windows

        ws = session_probe_windows("2026-06-23")
        # 04:00 ET (EDT, UTC-4) -> 08:00 UTC
        assert ws[0].session == "premarket"
        assert ws[0].start_utc == "2026-06-23 08:00:00"

    def test_session_labels_across_day(self):
        from lib.publisher_asset_map_core import session_probe_windows

        ws = session_probe_windows("2026-06-23")
        # k = (ET-offset-from-04:00 in minutes) / 30
        assert ws[11].session == "regular"  # 09:30 ET
        assert ws[24].session == "afterhours"  # 16:00 ET
        assert ws[32].session == "overnight"  # 20:00 ET

    def test_overnight_crosses_into_next_utc_day(self):
        from lib.publisher_asset_map_core import session_probe_windows

        ws = session_probe_windows("2026-06-23")
        # 02:00 ET next day -> 06:00 UTC on 2026-06-24
        assert ws[44].session == "overnight"
        assert ws[44].start_utc.startswith("2026-06-24")
