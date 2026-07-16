"""Tests for lazer_dq.active_pub_distribution pure functions."""
import numpy as np

from lazer_dq.active_pub_distribution import (
    concentration_metrics,
    encode_hist,
    histogram_pcts,
    skew_metrics,
)


def test_histogram_pcts_and_encode():
    counts = np.array([3, 4, 4, 5, 5, 5, 5, 5])
    hist = histogram_pcts(counts)
    assert hist == {3: 12.5, 4: 25.0, 5: 62.5}
    assert encode_hist(hist) == "3:12.50;4:25.00;5:62.50"


def test_histogram_all_zero_minutes():
    assert encode_hist(histogram_pcts(np.zeros(4, dtype=int))) == "0:100.00"


def test_histogram_empty():
    assert histogram_pcts(np.array([], dtype=int)) == {}
    assert encode_hist({}) == ""


def test_skew_metrics():
    counts = np.array([2, 3, 4, 5, 5, 5, 5, 5, 5, 5])
    m = skew_metrics(counts, min_pub=3)
    assert m["open_minutes"] == 10
    assert m["pct_minutes_le_min"] == 20.0  # 2 and 3
    assert m["pct_minutes_le_min_plus_1"] == 30.0  # 2, 3 and 4
    assert m["p10_active"] == 2.9  # linear interpolation
    assert m["median_active"] == 5.0
    assert m["p90_active"] == 5.0
    assert m["worst_minute_active"] == 2


def test_concentration_uniform():
    m = concentration_metrics({1: 100, 2: 100, 3: 100, 4: 100})
    assert m["effective_publishers"] == 4.0
    assert m["top1_share_pct"] == 25.0
    assert m["top3_share_pct"] == 75.0


def test_concentration_dominated():
    m = concentration_metrics({1: 80, 2: 10, 3: 10, 4: 0})
    assert m["effective_publishers"] == round(1 / 0.66, 2)  # hhi = .64+.01+.01
    assert m["top1_share_pct"] == 80.0
    assert m["top3_share_pct"] == 100.0


def test_concentration_no_updates():
    assert concentration_metrics({1: 0, 2: 0}) == {
        "effective_publishers": 0.0,
        "top1_share_pct": 0.0,
        "top3_share_pct": 0.0,
    }
