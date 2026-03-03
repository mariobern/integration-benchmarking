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
