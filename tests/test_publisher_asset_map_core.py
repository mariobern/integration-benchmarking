from lib.publisher_asset_map_core import (
    PublisherFeedRow,
    build_matrix,
    build_summary,
    day_window,
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
