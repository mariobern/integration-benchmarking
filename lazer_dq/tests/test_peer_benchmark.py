import numpy as np
import pandas as pd

from lazer_dq.peer_benchmark import PeerThresholds, align_per_second, evaluate_peer


def _series(start, n_seconds, price_fn, per_second=2):
    ts, price = [], []
    base = pd.Timestamp(start, tz="UTC")
    for i in range(n_seconds):
        for j in range(per_second):
            ts.append(base + pd.Timedelta(seconds=i, milliseconds=200 * j))
            price.append(price_fn(i))
    return pd.DataFrame({"ts": ts, "price": price})


def test_align_takes_last_per_second_inner_join():
    pub = pd.DataFrame(
        {
            "ts": pd.to_datetime(
                [
                    "2026-07-06 00:00:00.100",
                    "2026-07-06 00:00:00.900",
                    "2026-07-06 00:00:02.500",
                ],
                utc=True,
            ),
            "price": [100.0, 101.0, 103.0],
        }
    )
    agg = pd.DataFrame(
        {
            "ts": pd.to_datetime(
                ["2026-07-06 00:00:00.500", "2026-07-06 00:00:01.000"], utc=True
            ),
            "price": [100.5, 102.0],
        }
    )
    aligned = align_per_second(pub, agg)
    # Only second 00 exists on both sides; last pub obs in that second is 101.0
    assert len(aligned) == 1
    assert aligned.iloc[0]["pub_price"] == 101.0
    assert aligned.iloc[0]["agg_price"] == 100.5


def test_evaluate_peer_good_publisher_passes():
    # Trending series so the range is non-trivial; publisher tracks within 0.01%.
    agg = _series("2026-07-06", 1500, lambda i: 100.0 + i * 0.01)
    pub = _series("2026-07-06", 1500, lambda i: (100.0 + i * 0.01) * 1.0001)
    result = evaluate_peer(pub, agg, PeerThresholds())
    assert result["n_observations"] == 1500
    assert result["passed"] is True
    assert result["reason"] == "pass"
    assert result["hit_rate_pct"] > 99.0


def test_evaluate_peer_bad_publisher_fails_quality():
    agg = _series("2026-07-06", 1500, lambda i: 100.0 + i * 0.01)
    # 5% off and noisy: hit rate ~0, nrmse >> cond threshold
    pub = _series("2026-07-06", 1500, lambda i: (100.0 + i * 0.01) * 1.05)
    result = evaluate_peer(pub, agg, PeerThresholds())
    assert result["passed"] is False
    assert result["reason"] == "fail_quality"


def test_evaluate_peer_insufficient_obs_and_zero_range():
    thresholds = PeerThresholds()
    small_agg = _series("2026-07-06", 10, lambda i: 100.0)
    small_pub = _series("2026-07-06", 10, lambda i: 100.0)
    r = evaluate_peer(small_pub, small_agg, thresholds)
    assert r["passed"] is False and r["reason"] == "insufficient_obs"

    flat_agg = _series("2026-07-06", 1500, lambda i: 100.0)
    flat_pub = _series("2026-07-06", 1500, lambda i: 100.0)
    r = evaluate_peer(flat_pub, flat_agg, thresholds)
    assert r["passed"] is False and r["reason"] == "zero_range"


def test_align_handles_out_of_order_timestamps():
    """Test that temporally-last row is picked even when rows are in descending time order."""
    pub = pd.DataFrame(
        {
            "ts": pd.to_datetime(
                [
                    "2026-07-06 00:00:00.900",  # Descending order within second 00
                    "2026-07-06 00:00:00.100",
                ],
                utc=True,
            ),
            "price": [999.0, 1.0],  # Later row (00.900) has price 999.0
        }
    )
    agg = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2026-07-06 00:00:00.500"], utc=True),
            "price": [100.0],
        }
    )
    aligned = align_per_second(pub, agg)
    # Should pick temporally-last pub obs in second 00, which is 00.900 with price 999.0
    assert len(aligned) == 1
    assert aligned.iloc[0]["pub_price"] == 999.0


def test_evaluate_peer_zero_agg_price_rows_count_as_miss():
    """Test that zero agg_price rows don't crash and count as misses."""
    agg = _series("2026-07-06", 1500, lambda i: 100.0 + i * 0.01)
    pub = _series("2026-07-06", 1500, lambda i: (100.0 + i * 0.01) * 1.0001)

    # Inject some zero prices into agg to test guard against division by zero
    agg_with_zeros = agg.copy()
    agg_with_zeros.loc[10:20, "price"] = 0.0

    result = evaluate_peer(pub, agg_with_zeros, PeerThresholds())

    # Should not raise and returned result should have passed as a bool
    assert isinstance(result["passed"], bool)
    # The series is still good overall (only ~11 zero rows in 1500), so it should pass
    assert result["passed"] is True
