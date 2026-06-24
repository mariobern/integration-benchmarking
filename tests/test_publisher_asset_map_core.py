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

    def test_sorted_by_publisher_then_class(self):
        summary = build_summary(_rows())
        keys = [(r["publisher_id"], r["asset_class"]) for r in summary]
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
            # publisher_id, feed_id, update_count, asset_type, symbol
            (32, 1163, 100, "equity", "AAPL"),
            (32, 345, 20, "metal", "XAU/USD"),
            (11, 999, 5, "equity", "VOD.L"),
            (11, 888, 3, None, None),  # no metadata -> unknown / blank
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

    def test_foreign_equity_country(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        vod = [r for r in rows if r.feed_id == 999][0]
        assert vod.asset_class == "equity-gb"

    def test_missing_metadata_is_unknown(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        orphan = [r for r in rows if r.feed_id == 888][0]
        assert orphan.asset_class == "unknown"
        assert orphan.symbol == ""

    def test_missing_publisher_name_is_blank(self):
        client = _FakeClient(
            name_rows=[],
            feed_rows=[(7, 1, 1, "fx", "EUR/USD")],
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
