import csv
import io
import json
import subprocess
import sys

import pytest

# --- Sample CSV data (multi-date, with extended sessions) ---

SAMPLE_CSV_HEADER = (
    "feed_id,symbol,date,mode,fully_passing_count,target_pub_count,"
    "median_nrmse,median_hit_rate,median_uptime_pct,fully_passing_publishers,"
    "premarket_ready,premarket_fully_passing_count,premarket_fully_passing_publishers,"
    "afterhours_ready,afterhours_fully_passing_count,afterhours_fully_passing_publishers,"
    "overnight_ready,overnight_fully_passing_count,overnight_fully_passing_publishers"
)

SAMPLE_CSV_ROWS = [
    # Feed 100: us-equities, date 1 — regular pubs: 12;19;20;21;22;43
    "100,Equity.US.AAPL/USD,2026-02-27,us-equities,6,4,0.01,99.0,99.95,"
    "12;19;20;21;22;43,True,3,19;21;22,True,2,19;22,False,0,",
    # Feed 100: us-equities, date 2 — regular pubs: 12;19;21;22;44 (20 and 43 dropped, 44 added)
    "100,Equity.US.AAPL/USD,2026-03-02,us-equities,5,4,0.01,99.0,99.95,"
    "12;19;21;22;44,True,2,19;22,True,3,19;22;44,True,2,29;41,",
    # Feed 200: metals, single date — regular only
    "200,Metal.XAG/USD,2026-02-27,metals,4,4,0.02,98.0,99.90," "12;19;20;22,,,,,,,,",
    # Feed 300: us-equities, single date — has test publishers (43) and lazer (13)
    "300,Equity.US.MSFT/USD,2026-02-27,us-equities,5,4,0.01,99.0,99.95,"
    "12;13;19;22;43,,,,,,,,",
]

SAMPLE_CSV = SAMPLE_CSV_HEADER + "\n" + "\n".join(SAMPLE_CSV_ROWS) + "\n"


def test_parse_summary_csv_groups_by_feed():
    from update_config_from_summary import parse_summary_csv

    rows = parse_summary_csv(io.StringIO(SAMPLE_CSV))

    # Should have 3 feeds
    assert set(rows.keys()) == {100, 200, 300}

    # Feed 100 has 2 dates
    assert len(rows[100]) == 2

    # Feed 200 has 1 date
    assert len(rows[200]) == 1


def test_parse_summary_csv_parses_publishers():
    from update_config_from_summary import parse_summary_csv

    rows = parse_summary_csv(io.StringIO(SAMPLE_CSV))

    # Feed 100, first row: regular publishers
    row0 = rows[100][0]
    assert row0["fully_passing_publishers"] == "12;19;20;21;22;43"
    assert row0["mode"] == "us-equities"
    assert row0["feed_id"] == "100"


def test_parse_summary_csv_from_file(tmp_path):
    from update_config_from_summary import parse_summary_csv

    csv_file = tmp_path / "summary.csv"
    csv_file.write_text(SAMPLE_CSV)

    with open(csv_file) as f:
        rows = parse_summary_csv(f)
    assert 100 in rows
    assert 200 in rows


# --- Excluded publisher sets (for reference in tests) ---

EXCLUDED_TEST = {
    23,
    25,
    27,
    30,
    31,
    33,
    36,
    38,
    39,
    40,
    43,
    46,
    47,
    49,
    51,
    53,
    56,
    58,
    60,
    61,
    63,
    66,
    68,
    70,
}
EXCLUDED_LAZER = {1, 9, 13, 15}


def test_parse_publisher_list():
    from update_config_from_summary import _parse_publisher_list

    assert _parse_publisher_list("12;19;20;21;22") == {12, 19, 20, 21, 22}
    assert _parse_publisher_list("") == set()
    assert _parse_publisher_list("42") == {42}


def test_parse_publisher_list_filters_excluded():
    from update_config_from_summary import _parse_publisher_list, EXCLUDED_PUBLISHERS

    # 43 is a test publisher, 13 is Lazer.Hermes
    result = _parse_publisher_list("12;13;19;22;43")
    filtered = result - EXCLUDED_PUBLISHERS
    assert filtered == {12, 19, 22}


def test_compute_feed_publishers_single_date():
    from update_config_from_summary import compute_feed_publishers

    rows = [
        {
            "mode": "us-equities",
            "fully_passing_publishers": "12;19;20;21;22;43",
            "premarket_fully_passing_publishers": "19;21;22",
            "afterhours_fully_passing_publishers": "19;22",
            "overnight_fully_passing_publishers": "",
        }
    ]
    result = compute_feed_publishers(rows)

    # 43 is excluded (test publisher)
    assert result["regular"] == sorted([12, 19, 20, 21, 22])
    assert result["premarket"] == sorted([19, 21, 22])
    assert result["afterhours"] == sorted([19, 22])
    assert result["overnight"] == []
    assert result["mode"] == "us-equities"


def test_compute_feed_publishers_intersection_across_dates():
    from update_config_from_summary import compute_feed_publishers

    rows = [
        {
            "mode": "us-equities",
            "fully_passing_publishers": "12;19;20;21;22;43",
            "premarket_fully_passing_publishers": "19;21;22",
            "afterhours_fully_passing_publishers": "19;22",
            "overnight_fully_passing_publishers": "",
        },
        {
            "mode": "us-equities",
            "fully_passing_publishers": "12;19;21;22;44",
            "premarket_fully_passing_publishers": "19;22",
            "afterhours_fully_passing_publishers": "19;22;44",
            "overnight_fully_passing_publishers": "29;41",
        },
    ]
    result = compute_feed_publishers(rows)

    # Intersection: date1 {12,19,20,21,22} ∩ date2 {12,19,21,22,44} = {12,19,21,22}
    assert result["regular"] == [12, 19, 21, 22]
    # Intersection: {19,21,22} ∩ {19,22} = {19,22}
    assert result["premarket"] == [19, 22]
    # Intersection: {19,22} ∩ {19,22,44} = {19,22}
    assert result["afterhours"] == [19, 22]
    # Intersection: {} ∩ {29,41} = {} (first date was empty)
    assert result["overnight"] == []


def test_compute_feed_publishers_overnight_both_dates():
    from update_config_from_summary import compute_feed_publishers

    rows = [
        {
            "mode": "us-equities",
            "fully_passing_publishers": "12;19;22",
            "premarket_fully_passing_publishers": "",
            "afterhours_fully_passing_publishers": "",
            "overnight_fully_passing_publishers": "29;41;32",
        },
        {
            "mode": "us-equities",
            "fully_passing_publishers": "12;19;22",
            "premarket_fully_passing_publishers": "",
            "afterhours_fully_passing_publishers": "",
            "overnight_fully_passing_publishers": "29;41",
        },
    ]
    result = compute_feed_publishers(rows)

    # Intersection of overnight: {29,41,32} ∩ {29,41} = {29,41}
    assert result["overnight"] == [29, 41]


def test_compute_feed_publishers_non_equities_ignores_extended():
    from update_config_from_summary import compute_feed_publishers

    rows = [
        {
            "mode": "metals",
            "fully_passing_publishers": "12;19;20;22",
            "premarket_fully_passing_publishers": "",
            "afterhours_fully_passing_publishers": "",
            "overnight_fully_passing_publishers": "",
        }
    ]
    result = compute_feed_publishers(rows)

    assert result["regular"] == [12, 19, 20, 22]
    assert result["premarket"] == []
    assert result["afterhours"] == []
    assert result["overnight"] == []
    assert result["mode"] == "metals"


def test_compute_feed_publishers_top_level_is_union():
    from update_config_from_summary import compute_feed_publishers

    rows = [
        {
            "mode": "us-equities",
            "fully_passing_publishers": "12;19;22",
            "premarket_fully_passing_publishers": "19;44",
            "afterhours_fully_passing_publishers": "22;54",
            "overnight_fully_passing_publishers": "29;41",
        }
    ]
    result = compute_feed_publishers(rows)

    # Top-level = union of all sessions
    assert result["top_level"] == sorted([12, 19, 22, 44, 54, 29, 41])


# --- Sample after.json structures ---

SAMPLE_CONFIG_EQUITIES = {
    "feeds": [
        {
            "allowedPublisherIds": [1, 2, 3, 13, 14, 15],
            "expiryTime": "5.000000000s",
            "exponent": -5,
            "feedId": 100,
            "isEnabledInShard": True,
            "kind": "PRICE",
            "marketSchedules": [
                {
                    "allowedPublisherIds": [1, 2, 3, 14],
                    "marketSchedule": "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;0101/C",
                    "minPublishers": 3,
                    "session": "REGULAR",
                },
                {
                    "allowedPublisherIds": [1, 2],
                    "marketSchedule": "America/New_York;0400-0930,0400-0930,0400-0930,0400-0930,0400-0930,C,C;0101/C",
                    "minPublishers": 2,
                    "session": "PRE_MARKET",
                },
            ],
            "metadata": {
                "asset_type": "equity",
                "name": "AAPL",
                "nasdaq_symbol": "AAPL",
                "quote_currency": "USD",
            },
            "minChannel": {"rate": "0.050000000s"},
            "minPublishers": 1,
            "state": "COMING_SOON",
            "symbol": "Equity.US.AAPL/USD",
        },
        {
            "allowedPublisherIds": [1, 2, 3],
            "feedId": 200,
            "kind": "PRICE",
            "marketSchedules": [
                {
                    "marketSchedule": "America/New_York;0000-1700&1800-2400,0000-1700&1800-2400,0000-1700&1800-2400,0000-1700&1800-2400,0000-1700,C,1800-2400;",
                    "session": "REGULAR",
                }
            ],
            "metadata": {
                "asset_type": "metal",
                "name": "XAGUSD",
                "quote_currency": "USD",
            },
            "minPublishers": 3,
            "state": "STABLE",
            "symbol": "Metal.XAG/USD",
        },
        {
            "allowedPublisherIds": [1, 2, 3],
            "feedId": 300,
            "kind": "PRICE",
            "marketSchedules": [
                {
                    "marketSchedule": "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;0101/C",
                    "session": "REGULAR",
                }
            ],
            "metadata": {
                "asset_type": "equity",
                "name": "MSFT",
                "nasdaq_symbol": "MSFT",
                "quote_currency": "USD",
            },
            "minChannel": {"rate": "0.050000000s"},
            "minPublishers": 100,
            "state": "COMING_SOON",
            "symbol": "Equity.US.MSFT/USD",
        },
    ]
}


def test_find_feed_block_locates_feed():
    from update_config_from_summary import _find_feed_block

    raw = json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2)
    bounds = _find_feed_block(raw, 100)
    assert bounds is not None
    start, end = bounds
    block = raw[start:end]
    assert '"feedId": 100' in block
    assert '"name": "AAPL"' in block


def test_find_feed_block_returns_none_for_missing():
    from update_config_from_summary import _find_feed_block

    raw = json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2)
    assert _find_feed_block(raw, 999) is None
