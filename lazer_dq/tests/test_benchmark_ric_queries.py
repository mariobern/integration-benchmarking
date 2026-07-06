"""Verify the engine builds RIC-keyed benchmark queries per mode.

Drives main() with a single shared mock ClickHouse client that records every
SQL string. Benchmark tables return empty, so the engine exits rc=2 after the
benchmark query is built and captured.
"""
import json
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest


def _metadata_df():
    market_schedules = json.dumps(
        [
            {
                "session": s,
                "benchmarkMapping": {
                    "datascope_ric": {
                        "identifiers": [
                            {"identifier": r, "validFrom": "1970-01-01T00:00:00Z"}
                        ]
                    }
                },
            }
            for s, r in [
                ("REGULAR", "AAPL.O"),
                ("PRE_MARKET", "AAPL.O"),
                ("POST_MARKET", "AAPL.O"),
                ("OVER_NIGHT", "AAPL.BLUE"),
            ]
        ]
    )
    return pd.DataFrame(
        {
            "feed_id": [123],
            "symbol": ["Equity.US.AAPL/USD"],
            "exponent": [-5],
            "market_schedules": [market_schedules],
            "updated_at": [pd.Timestamp("2026-05-19 00:00:00")],
        }
    )


def _run_and_capture(engine, monkeypatch, tmp_path, mode, metadata_df=None):
    sql_log = []
    md = metadata_df if metadata_df is not None else _metadata_df()

    def query_df(sql, *a, **k):
        sql_log.append(sql)
        if "feeds_metadata_latest" in sql:
            return md
        if "publisher_updates" in sql:
            return pd.DataFrame(
                {
                    "publisher_id": [1],
                    "feed_id": [123],
                    "publisher_price": [10_000_000.0],
                    "publisher_timestamp": [pd.Timestamp("2026-05-19 14:00:00")],
                }
            )
        return pd.DataFrame()  # price_feeds + all benchmark tables empty

    client = MagicMock()
    client.query_df.side_effect = query_df
    monkeypatch.setattr(engine.clickhouse_connect, "get_client", lambda **kw: client)
    monkeypatch.setattr(
        engine.yaml,
        "safe_load",
        lambda _f: {
            "clickhouse": {"host": "x", "user": "x", "password": "x"},
            "lazer_clickhouse_prod": {"host": "x", "user": "x", "password": "x"},
            "analytics_clickhouse": {"host": "x", "user": "x", "password": "x"},
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_feed_standalone",
            "--feed-id",
            "123",
            "--date",
            "2026-05-19",
            "--mode",
            mode,
            "--cluster",
            "lazer-prod",
            "--start-time",
            "13:30:00",
            "--end-time",
            "20:00:00",
            "--output-path",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        engine.main()
    return sql_log, exc.value.code


@pytest.fixture
def engine():
    from lazer_dq import evaluate_feed_standalone as e

    return e


def _benchmark_sql(sql_log):
    hits = [s for s in sql_log if "benchmark_data" in s]
    assert hits, "no benchmark query was issued"
    return hits[-1]


@pytest.mark.parametrize(
    "mode,expected_ric,expected_table",
    [
        ("fx", "AAPL.O", "datascope_fx_benchmark_data"),
        ("metals", "AAPL.O", "datascope_fx_benchmark_data"),
        ("us-equities", "AAPL.O", "datascope_global_equities_benchmark_data"),
        ("hk-equities", "AAPL.O", "datascope_global_equities_benchmark_data"),
        ("us-equities-pre", "AAPL.O", "datascope_global_equities_benchmark_data"),
        ("us-equities-post", "AAPL.O", "datascope_global_equities_benchmark_data"),
        (
            "us-equities-overnight",
            "AAPL.BLUE",
            "datascope_global_equities_benchmark_data",
        ),
        ("us-equities-on", "AAPL.BLUE", "datascope_global_equities_benchmark_data"),
        ("us-futures", "AAPL.O", "datascope_futures_benchmark_data"),
        ("us-treasuries-yield", "AAPL.O", "datascope_us_treasury_benchmark_data"),
        ("us-treasuries-price", "AAPL.O", "datascope_us_treasury_benchmark_data"),
    ],
)
def test_benchmark_query_keys_on_ric(
    engine, monkeypatch, tmp_path, mode, expected_ric, expected_table
):
    sql_log, code = _run_and_capture(engine, monkeypatch, tmp_path, mode)
    assert code == 2
    sql = _benchmark_sql(sql_log)
    assert f"ric = '{expected_ric}'" in sql
    assert expected_table in sql
    assert "pyth_lazer_id = " not in sql


def test_futures_qualifier_filter_broadened(engine, monkeypatch, tmp_path):
    sql_log, _ = _run_and_capture(engine, monkeypatch, tmp_path, "us-futures")
    sql = _benchmark_sql(sql_log)
    assert "'%SBL[OFFBK_TYPE]%'" in sql
    assert "'%SYS[OFFBK_TYPE]%'" in sql
    assert "'%Spread Price|Spread Volume[USER]%'" in sql


def test_treasuries_price_selects_price(engine, monkeypatch, tmp_path):
    sql_log, _ = _run_and_capture(engine, monkeypatch, tmp_path, "us-treasuries-price")
    sql = _benchmark_sql(sql_log)
    assert "price as benchmark_price" in sql
    assert "yield as benchmark_price" not in sql


def test_treasuries_yield_selects_yield(engine, monkeypatch, tmp_path):
    sql_log, _ = _run_and_capture(engine, monkeypatch, tmp_path, "us-treasuries-yield")
    sql = _benchmark_sql(sql_log)
    assert "yield as benchmark_price" in sql


def test_missing_ric_soft_skips(engine, monkeypatch, tmp_path, capsys):
    # market_schedules with only a coinpaprika_symbol -> no datascope_ric.
    md = _metadata_df()
    md.loc[0, "market_schedules"] = json.dumps(
        [
            {
                "session": "REGULAR",
                "benchmarkMapping": {
                    "coinpaprika_symbol": {
                        "identifiers": [
                            {
                                "identifier": "btc-bitcoin",
                                "validFrom": "1970-01-01T00:00:00Z",
                            }
                        ]
                    }
                },
            }
        ]
    )
    sql_log, code = _run_and_capture(
        engine, monkeypatch, tmp_path, "fx", metadata_df=md
    )
    assert code == 2
    out = capsys.readouterr().out
    assert "No datascope RIC configured" in out
    assert not [s for s in sql_log if "benchmark_data" in s]  # never queried benchmark
