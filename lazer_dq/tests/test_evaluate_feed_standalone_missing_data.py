"""Regression tests for the missing-data paths in evaluate_feed_standalone.

These exercise the three pre-existing latent bugs that HK-equities feeds
surfaced (commit 7a99c14):

  1. ric/ticker/symbol must be defined even when their normal assignment
     branch did not run (no UnboundLocalError).
  2. The Price Feed fetch must not call query_df(None) when no channel
     returned rows.
  3. An empty benchmark DataFrame must trigger a clean rc=2 exit with a
     diagnostic line, not a downstream KeyError in the merge.

The tests mock both ClickHouse clients so no real connection is needed.
"""
import sys
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest


def _mock_client_factory():
    """Returns a MagicMock client whose query_df dispatches by SQL substring.

    - feeds_metadata_latest -> a single equity row (so ticker is computed)
    - publisher_updates     -> a single non-empty row (so the publisher
                                branch runs and df_publisher_data is set)
    - price_feeds           -> empty (so the for-else runs and the guard
                                we added for lazer_feed_query=None kicks in)
    - any benchmark table   -> empty (the path we want to verify)
    """

    def query_df(sql, *args, **kwargs):
        if "feeds_metadata_latest" in sql:
            return pd.DataFrame(
                {
                    "feed_id": [123],
                    "symbol": ["Equity.US.AAPL/USD"],
                    "exponent": [-5],
                    "updated_at": [pd.Timestamp("2026-05-19 00:00:00")],
                }
            )
        if "publisher_updates" in sql:
            return pd.DataFrame(
                {
                    "publisher_id": [1],
                    "feed_id": [123],
                    "publisher_price": [10_000_000.0],
                    "publisher_timestamp": [pd.Timestamp("2026-05-19 14:00:00")],
                }
            )
        # All other queries (price_feeds + every benchmark table) return empty.
        return pd.DataFrame()

    client = MagicMock()
    client.query_df.side_effect = query_df
    return client


@pytest.fixture
def patched_engine(monkeypatch, tmp_path):
    """Patch clickhouse + yaml so we can drive main() without a real DB."""
    from lazer_dq import evaluate_feed_standalone as engine

    monkeypatch.setattr(
        engine.clickhouse_connect,
        "get_client",
        lambda **kw: _mock_client_factory(),
    )
    monkeypatch.setattr(
        engine.yaml,
        "safe_load",
        lambda _f: {
            "clickhouse": {"host": "x", "user": "x", "password": "x"},
            "lazer_clickhouse_prod": {"host": "x", "user": "x", "password": "x"},
            "analytics_clickhouse": {"host": "x", "user": "x", "password": "x"},
        },
    )
    return engine, tmp_path


@pytest.mark.parametrize(
    "mode,start_time,end_time",
    [
        ("us-equities", "13:30:00", "20:00:00"),
        ("us-equities-pre", "12:30:00", "13:30:00"),
        ("us-equities-post", "20:30:00", "21:30:00"),
        ("us-equities-overnight", "00:00:00", "01:00:00"),
        ("hk-equities", "01:30:00", "02:30:00"),
    ],
)
def test_empty_benchmark_exits_2_with_diagnostic(
    patched_engine, monkeypatch, capsys, mode, start_time, end_time
):
    """Regression: empty benchmark data -> clean rc=2, not KeyError/UnboundLocal.

    Covers commit 7a99c14 across every mode that goes through the
    global-equities query branch. Without the fix:
      - us-equities*  would crash on `print(... ric ...)` (UnboundLocalError)
                       or on the downstream merge (KeyError).
      - us-equities-overnight additionally crashes because its SQL
        interpolates `{ticker}.BLUE` and the empty-print line references
        an unbound `ric`.
    """
    engine, tmp_path = patched_engine

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
            start_time,
            "--end-time",
            end_time,
            "--output-path",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        engine.main()

    assert (
        exc_info.value.code == 2
    ), f"expected clean rc=2 from empty-benchmark guard, got {exc_info.value.code}"

    out = capsys.readouterr().out
    assert "No benchmark data available" in out
    assert f"mode={mode}" in out
    # ric is None because no normal RIC mapping path ran; the diagnostic
    # must still render without raising.
    assert "ric=" in out
