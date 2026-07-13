import numpy as np
import pandas as pd
import pytest

from lazer_dq.min_pub_common import FeedSession
from lazer_dq.qualify_candidates import (
    activity_pct,
    engine_gate,
    engine_mode_for,
    projected_worst_minute,
    select_candidates,
)


def _fs(asset_type, symbol, session):
    return FeedSession(
        feed_id=1,
        symbol=symbol,
        asset_type=asset_type,
        session=session,
        allowed=frozenset(),
        effective_min_pub=1,
        schedule_str=None,
    )


def test_engine_mode_for_mapping():
    assert engine_mode_for(_fs("fx", "FX.EUR/USD", "REGULAR")) == "fx"
    assert engine_mode_for(_fs("metal", "Metal.XAU/USD", "REGULAR")) == "metals"
    assert (
        engine_mode_for(_fs("commodity", "Commodities.CL/USD", "REGULAR"))
        == "commodity"
    )
    assert (
        engine_mode_for(_fs("rates", "Rates.US10Y", "REGULAR")) == "us-treasuries-yield"
    )
    assert (
        engine_mode_for(_fs("equity", "Equity.US.AAPL/USD", "REGULAR")) == "us-equities"
    )
    assert (
        engine_mode_for(_fs("equity", "Equity.US.AAPL/USD", "PRE_MARKET"))
        == "us-equities-pre"
    )
    assert (
        engine_mode_for(_fs("equity", "Equity.US.AAPL/USD", "OVER_NIGHT"))
        == "us-equities-overnight"
    )
    assert (
        engine_mode_for(_fs("equity", "Equity.HK.0700/HKD", "REGULAR")) == "hk-equities"
    )
    assert (
        engine_mode_for(_fs("equity", "Equity.JP.7203/JPY", "REGULAR")) == "jp-equities"
    )
    assert (
        engine_mode_for(_fs("equity", "Equity.KR.005930/KRW", "REGULAR"))
        == "kr-equities"
    )
    assert (
        engine_mode_for(_fs("equity", "Equity.IN.RELIANCE/INR", "REGULAR"))
        == "in-equities"
    )
    # Non-REGULAR sessions on single-mode foreign markets -> peer path
    assert engine_mode_for(_fs("equity", "Equity.JP.7203/JPY", "PRE_MARKET")) is None
    # No engine support -> peer path
    assert engine_mode_for(_fs("crypto", "Crypto.BTC/USD", "REGULAR")) is None
    assert engine_mode_for(_fs("equity", "Equity.CN.600519/CNY", "REGULAR")) is None
    assert engine_mode_for(_fs("funding-rate", "FundingRate.X/USD", "REGULAR")) is None


def test_engine_gate_with_and_without_configured_thresholds():
    row_good = {
        "rmse_over_spread": "0.5",
        "hit_rate_0.1pct": "95",
        "n_observations": "5000",
        "pass_fail": "fail",
        "nrmse": "0.03",
    }
    row_bad = {
        "rmse_over_spread": "5.0",
        "hit_rate_0.1pct": "95",
        "n_observations": "5000",
        "pass_fail": "pass",
        "nrmse": "0.2",
    }
    # us-equities has configured thresholds (max_ros 1.0, min_hit 80) -> uses them
    assert engine_gate(row_good, "us-equities", min_obs=1000) is True
    assert engine_gate(row_bad, "us-equities", min_obs=1000) is False
    # observation floor always applies
    thin = dict(row_good, n_observations="10")
    assert engine_gate(thin, "us-equities", min_obs=1000) is False


def test_engine_gate_tier_thresholds_for_fx_metals_commodity_treasuries():
    # fx (regular tier: nrmse<0.01 auto, or nrmse<0.05 & hit>=95)
    fx_pass = {"n_observations": "5000", "nrmse": "0.03", "hit_rate_0.1pct": "96"}
    assert engine_gate(fx_pass, "fx", min_obs=1000) is True
    # conditional needs hit>=95; hit=90 fails unless nrmse<0.01 auto-pass
    fx_fail = {"n_observations": "5000", "nrmse": "0.03", "hit_rate_0.1pct": "90"}
    assert engine_gate(fx_fail, "fx", min_obs=1000) is False
    fx_auto = {"n_observations": "5000", "nrmse": "0.005", "hit_rate_0.1pct": "0"}
    assert engine_gate(fx_auto, "fx", min_obs=1000) is True

    # us-treasuries-yield uses the same regular tier as fx
    treasuries_pass = {
        "n_observations": "5000",
        "nrmse": "0.03",
        "hit_rate_0.1pct": "96",
    }
    assert engine_gate(treasuries_pass, "us-treasuries-yield", min_obs=1000) is True
    treasuries_fail = {
        "n_observations": "5000",
        "nrmse": "0.03",
        "hit_rate_0.1pct": "90",
    }
    assert engine_gate(treasuries_fail, "us-treasuries-yield", min_obs=1000) is False

    # metals/commodity (relaxed tier: nrmse<0.05 auto, or nrmse<0.15 & hit>=85)
    metals_auto = {"n_observations": "5000", "nrmse": "0.03", "hit_rate_0.1pct": "90"}
    assert engine_gate(metals_auto, "metals", min_obs=1000) is True
    commodity_cond = {
        "n_observations": "5000",
        "nrmse": "0.12",
        "hit_rate_0.1pct": "86",
    }
    assert engine_gate(commodity_cond, "commodity", min_obs=1000) is True
    commodity_fail = {
        "n_observations": "5000",
        "nrmse": "0.12",
        "hit_rate_0.1pct": "80",
    }
    assert engine_gate(commodity_fail, "commodity", min_obs=1000) is False

    # observation floor still applies for tier-gated modes
    thin = dict(fx_pass, n_observations="10")
    assert engine_gate(thin, "fx", min_obs=1000) is False


def test_engine_gate_unknown_mode_falls_back_to_engine_pass_fail():
    row_bad = {
        "rmse_over_spread": "5.0",
        "hit_rate_0.1pct": "95",
        "n_observations": "5000",
        "pass_fail": "pass",
        "nrmse": "0.2",
    }
    row_good = {
        "rmse_over_spread": "0.5",
        "hit_rate_0.1pct": "95",
        "n_observations": "5000",
        "pass_fail": "fail",
        "nrmse": "0.03",
    }
    # some future/unknown mode not in ENGINE_MODE_THRESHOLDS or TIER_GATED_MODES
    assert engine_gate(row_bad, "some-future-mode", min_obs=1000) is True
    assert engine_gate(row_good, "some-future-mode", min_obs=1000) is False


def _matrix_and_mask():
    """3 open minutes; pubs 1,2 always active; pub 7 active 2/3; pub 8 active 1/3."""
    minutes = pd.date_range("2026-07-06 13:30", periods=3, freq="1min", tz="UTC")
    rows = []
    for m in minutes:
        rows += [(m, 1, 5), (m, 2, 5)]
    rows += [(minutes[0], 7, 5), (minutes[1], 7, 5)]
    rows += [(minutes[2], 8, 5)]
    matrix = pd.DataFrame(rows, columns=["minute", "publisher_id", "n_updates"])
    mask = pd.Series(True, index=minutes)
    return matrix, mask


def test_activity_pct():
    matrix, mask = _matrix_and_mask()
    assert activity_pct(matrix, mask, 1) == pytest.approx(1.0)
    assert activity_pct(matrix, mask, 7) == pytest.approx(2 / 3)
    assert activity_pct(matrix, mask, 99) == 0.0


def test_projected_worst_minute():
    matrix, mask = _matrix_and_mask()
    assert projected_worst_minute(matrix, mask, {1, 2}) == 2
    # adding pub 7 helps minutes 0-1 but minute 2 stays at 2
    assert projected_worst_minute(matrix, mask, {1, 2, 7}) == 2
    assert projected_worst_minute(matrix, mask, {1, 2, 7, 8}) == 3


def test_select_candidates_stops_at_target_and_reports_shortfall():
    matrix, mask = _matrix_and_mask()
    allowed = frozenset({1, 2})
    # min_pub=1, target margin 2 -> need worst-minute >= 3
    passers = [
        {"candidate_publisher_id": 7, "sort_metric": 0.1},
        {"candidate_publisher_id": 8, "sort_metric": 0.2},
    ]
    selected, projected = select_candidates(
        passers, matrix, mask, allowed, min_pub=1, target_margin=2
    )
    assert selected == [7, 8]  # 7 alone leaves worst at 2 -> also takes 8
    assert projected == 3
    # unreachable target: min_pub=4 needs worst >= 6, only 4 pubs exist
    selected2, projected2 = select_candidates(
        passers, matrix, mask, allowed, min_pub=4, target_margin=2
    )
    assert selected2 == [7, 8]
    assert projected2 == 3  # best achievable; caller flags still_below_target
