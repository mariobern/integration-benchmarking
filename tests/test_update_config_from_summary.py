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


def test_modify_config_updates_top_level_publishers(tmp_path):
    from update_config_from_summary import modify_config

    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2))

    feed_publishers = {
        100: {
            "regular": [12, 19, 22],
            "premarket": [19, 22],
            "afterhours": [],
            "overnight": [],
            "top_level": [12, 19, 22],
            "mode": "us-equities",
        }
    }
    result = modify_config(str(config_file), feed_publishers, dry_run=False)

    with open(config_file) as f:
        data = json.load(f)

    feed = [f for f in data["feeds"] if f["feedId"] == 100][0]
    assert feed["state"] == "STABLE"
    assert feed["allowedPublisherIds"] == [12, 19, 22]
    assert feed["minPublishers"] == 1
    assert result["newly_stable"] == 1


def test_modify_config_updates_already_stable(tmp_path):
    from update_config_from_summary import modify_config

    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2))

    feed_publishers = {
        200: {
            "regular": [12, 19, 22],
            "premarket": [],
            "afterhours": [],
            "overnight": [],
            "top_level": [12, 19, 22],
            "mode": "metals",
        }
    }
    result = modify_config(str(config_file), feed_publishers, dry_run=False)

    with open(config_file) as f:
        data = json.load(f)

    feed = [f for f in data["feeds"] if f["feedId"] == 200][0]
    assert feed["state"] == "STABLE"  # unchanged
    assert feed["allowedPublisherIds"] == [12, 19, 22]  # updated
    assert result["updated_stable"] == 1


def test_modify_config_dry_run_no_write(tmp_path):
    from update_config_from_summary import modify_config

    config_file = tmp_path / "after.json"
    original = json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2)
    config_file.write_text(original)

    feed_publishers = {
        100: {
            "regular": [12, 19, 22],
            "premarket": [],
            "afterhours": [],
            "overnight": [],
            "top_level": [12, 19, 22],
            "mode": "us-equities",
        }
    }
    modify_config(str(config_file), feed_publishers, dry_run=True)

    assert config_file.read_text() == original


def test_modify_config_creates_backup(tmp_path):
    from update_config_from_summary import modify_config

    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2))

    feed_publishers = {
        100: {
            "regular": [12, 19, 22],
            "premarket": [],
            "afterhours": [],
            "overnight": [],
            "top_level": [12, 19, 22],
            "mode": "us-equities",
        }
    }
    modify_config(str(config_file), feed_publishers, dry_run=False)

    assert (tmp_path / "after.json.bak").exists()


def test_modify_config_warns_missing_feed(tmp_path):
    from update_config_from_summary import modify_config

    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2))

    feed_publishers = {
        999: {
            "regular": [12, 19],
            "premarket": [],
            "afterhours": [],
            "overnight": [],
            "top_level": [12, 19],
            "mode": "us-equities",
        }
    }
    result = modify_config(str(config_file), feed_publishers, dry_run=False)
    assert result["not_found"] == [999]


def test_modify_config_skips_empty_publishers(tmp_path):
    from update_config_from_summary import modify_config

    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2))

    feed_publishers = {
        100: {
            "regular": [],
            "premarket": [],
            "afterhours": [],
            "overnight": [],
            "top_level": [],
            "mode": "us-equities",
        }
    }
    result = modify_config(str(config_file), feed_publishers, dry_run=False)
    assert result["skipped_empty"] == 1


def test_modify_config_updates_regular_session_publishers(tmp_path):
    from update_config_from_summary import modify_config

    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2))

    feed_publishers = {
        100: {
            "regular": [12, 19, 22],
            "premarket": [19, 22],
            "afterhours": [],
            "overnight": [],
            "top_level": [12, 19, 22],
            "mode": "us-equities",
        }
    }
    modify_config(str(config_file), feed_publishers, dry_run=False)

    with open(config_file) as f:
        data = json.load(f)

    feed = [f for f in data["feeds"] if f["feedId"] == 100][0]
    regular = [s for s in feed["marketSchedules"] if s["session"] == "REGULAR"][0]
    assert regular["allowedPublisherIds"] == [12, 19, 22]
    assert regular["minPublishers"] == 3


def test_modify_config_updates_premarket_session_publishers(tmp_path):
    from update_config_from_summary import modify_config

    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2))

    feed_publishers = {
        100: {
            "regular": [12, 19, 22],
            "premarket": [19, 22],
            "afterhours": [],
            "overnight": [],
            "top_level": [12, 19, 22],
            "mode": "us-equities",
        }
    }
    modify_config(str(config_file), feed_publishers, dry_run=False)

    with open(config_file) as f:
        data = json.load(f)

    feed = [f for f in data["feeds"] if f["feedId"] == 100][0]
    premarket = [s for s in feed["marketSchedules"] if s["session"] == "PRE_MARKET"][0]
    assert premarket["allowedPublisherIds"] == [19, 22]
    assert premarket["minPublishers"] == 2


def test_modify_config_adds_missing_extended_sessions(tmp_path):
    """Feed 300 has only REGULAR — should add PRE_MARKET, POST_MARKET, OVER_NIGHT if publishers pass."""
    from update_config_from_summary import modify_config

    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2))

    feed_publishers = {
        300: {
            "regular": [12, 19, 22],
            "premarket": [19, 22],
            "afterhours": [19],
            "overnight": [29, 41],
            "top_level": [12, 19, 22, 29, 41],
            "mode": "us-equities",
        }
    }
    modify_config(str(config_file), feed_publishers, dry_run=False)

    with open(config_file) as f:
        data = json.load(f)

    feed = [f for f in data["feeds"] if f["feedId"] == 300][0]
    sessions = {s["session"]: s for s in feed["marketSchedules"]}

    assert "REGULAR" in sessions
    assert "PRE_MARKET" in sessions
    assert "POST_MARKET" in sessions
    assert "OVER_NIGHT" in sessions

    assert sessions["REGULAR"]["allowedPublisherIds"] == [12, 19, 22]
    assert sessions["REGULAR"]["minPublishers"] == 3
    assert sessions["PRE_MARKET"]["allowedPublisherIds"] == [19, 22]
    assert sessions["PRE_MARKET"]["minPublishers"] == 2
    assert sessions["POST_MARKET"]["allowedPublisherIds"] == [19]
    assert sessions["POST_MARKET"]["minPublishers"] == 2
    assert sessions["OVER_NIGHT"]["allowedPublisherIds"] == [29, 41]
    assert sessions["OVER_NIGHT"]["minPublishers"] == 1


def test_modify_config_does_not_add_sessions_for_non_equities(tmp_path):
    """Metals feed should not get extended sessions added."""
    from update_config_from_summary import modify_config

    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2))

    feed_publishers = {
        200: {
            "regular": [12, 19, 22],
            "premarket": [],
            "afterhours": [],
            "overnight": [],
            "top_level": [12, 19, 22],
            "mode": "metals",
        }
    }
    modify_config(str(config_file), feed_publishers, dry_run=False)

    with open(config_file) as f:
        data = json.load(f)

    feed = [f for f in data["feeds"] if f["feedId"] == 200][0]
    sessions = [s["session"] for s in feed["marketSchedules"]]
    assert sessions == ["REGULAR"]


# --- CLI integration tests ---


def _write_test_csv(tmp_path):
    """Write a test summary CSV and config, return paths."""
    csv_file = tmp_path / "summary.csv"
    csv_file.write_text(SAMPLE_CSV)
    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2))
    return csv_file, config_file


def test_cli_dry_run(tmp_path):
    csv_file, config_file = _write_test_csv(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "update_config_from_summary.py",
            "--summary",
            str(csv_file),
            "--config",
            str(config_file),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd="/home/mariobern/integration-benchmarking",
    )
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout

    # Config file unchanged
    with open(config_file) as f:
        data = json.load(f)
    feed = [f for f in data["feeds"] if f["feedId"] == 100][0]
    assert feed["state"] == "COMING_SOON"


def test_cli_real_run(tmp_path):
    csv_file, config_file = _write_test_csv(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "update_config_from_summary.py",
            "--summary",
            str(csv_file),
            "--config",
            str(config_file),
        ],
        capture_output=True,
        text=True,
        cwd="/home/mariobern/integration-benchmarking",
    )
    assert result.returncode == 0
    assert "SUMMARY" in result.stdout

    with open(config_file) as f:
        data = json.load(f)
    feed = [f for f in data["feeds"] if f["feedId"] == 100][0]
    assert feed["state"] == "STABLE"


def test_cli_missing_summary_file(tmp_path):
    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG_EQUITIES, indent=2))

    result = subprocess.run(
        [
            sys.executable,
            "update_config_from_summary.py",
            "--summary",
            str(tmp_path / "nonexistent.csv"),
            "--config",
            str(config_file),
        ],
        capture_output=True,
        text=True,
        cwd="/home/mariobern/integration-benchmarking",
    )
    assert result.returncode != 0


def test_cli_prints_summary_counts(tmp_path):
    csv_file, config_file = _write_test_csv(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "update_config_from_summary.py",
            "--summary",
            str(csv_file),
            "--config",
            str(config_file),
        ],
        capture_output=True,
        text=True,
        cwd="/home/mariobern/integration-benchmarking",
    )
    assert "Newly STABLE:" in result.stdout
    assert "Updated (already STABLE):" in result.stdout
