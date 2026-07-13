"""Peer benchmark: candidate publisher vs the feed's own aggregate price.

Used for feeds with no Datascope benchmark (crypto, funding-rate, NAV,
redemption-rate, custom, and any equity market the DQ engine doesn't
support). Reference = price_feeds aggregate; same NRMSE / hit-rate shape as
lazer_dq/evaluate_feed_standalone.py. Circularity (the aggregate is built
from current publishers) is accepted by design — see the 2026-07-13 spec.

Prices are raw config-exponent integers on both sides of the same feed, so
exponent scaling cancels in nrmse (range-normalized) and hit rate
(ratio-based); no adjustment is applied.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PeerThresholds:
    nrmse_auto: float = 0.05
    nrmse_cond: float = 0.15
    min_hit_rate_pct: float = 85.0
    min_obs: int = 1000


def _last_per_second(df: pd.DataFrame) -> pd.Series:
    out = df.copy()
    out["second"] = out["ts"].dt.floor("1s")
    return out.groupby("second")["price"].last()


def align_per_second(pub_df: pd.DataFrame, agg_df: pd.DataFrame) -> pd.DataFrame:
    """Inner-join last-observation-per-second series from both sides."""
    if pub_df.empty or agg_df.empty:
        return pd.DataFrame(columns=["pub_price", "agg_price"])
    pub = _last_per_second(pub_df).rename("pub_price")
    agg = _last_per_second(agg_df).rename("agg_price")
    return pd.concat([pub, agg], axis=1, join="inner")


def evaluate_peer(
    pub_df: pd.DataFrame, agg_df: pd.DataFrame, thresholds: PeerThresholds
) -> dict:
    aligned = align_per_second(pub_df, agg_df)
    n = len(aligned)
    result = {
        "n_observations": n,
        "nrmse": float("nan"),
        "hit_rate_pct": float("nan"),
        "passed": False,
        "reason": "insufficient_obs",
    }
    if n < thresholds.min_obs:
        return result

    diff = aligned["pub_price"] - aligned["agg_price"]
    rmse = float(np.sqrt((diff**2).mean()))
    agg_range = float(aligned["agg_price"].max() - aligned["agg_price"].min())
    hit_rate = float(
        ((diff.abs() / aligned["agg_price"]).abs() <= 0.001).mean() * 100.0
    )
    result["hit_rate_pct"] = hit_rate
    if agg_range <= 0:
        result["reason"] = "zero_range"
        return result
    nrmse = rmse / agg_range
    result["nrmse"] = float(nrmse)

    passed = nrmse < thresholds.nrmse_auto or (
        nrmse < thresholds.nrmse_cond and hit_rate >= thresholds.min_hit_rate_pct
    )
    result["passed"] = bool(passed)
    result["reason"] = "pass" if passed else "fail_quality"
    return result
