import numpy as np
import pandas as pd

from lazer_dq.active_min_pub import (
    RESULT_COLUMNS,
    classify,
    distribution_stats,
)


def test_distribution_stats_basic():
    # min_pub = 2. Values: two updates at floor (<=2), one at floor+1 (==3), rest above.
    # NOTE: adjusted from the brief's [2,2,3,4,4,4,5,5,6,10] (median 4.0, not 4.5
    # as asserted) to [2,2,3,4,4,5,5,5,6,10], which preserves n=10, min=2,
    # pct_at_floor=20.0, pct_at_floor_1=30.0 while making median==4.5 true.
    counts = np.array([2, 2, 3, 4, 4, 5, 5, 5, 6, 10])
    s = distribution_stats(counts, min_pub=2)
    assert s["n_updates"] == 10
    assert s["min"] == 2
    assert s["median"] == 4.5
    # pct_at_floor: publisher_count <= 2 -> 2/10 = 20.0
    assert s["pct_at_floor"] == 20.0
    # pct_at_floor_1: publisher_count <= 3 -> 3/10 = 30.0
    assert s["pct_at_floor_1"] == 30.0
    # percentiles are numpy linear-interp values
    assert s["p1"] == float(np.percentile(counts, 1))
    assert s["p5"] == float(np.percentile(counts, 5))


def test_distribution_stats_empty():
    s = distribution_stats(np.array([], dtype=int), min_pub=2)
    assert s["n_updates"] == 0
    assert s["min"] == 0
    assert s["pct_at_floor"] == 0.0
    assert s["pct_at_floor_1"] == 0.0
    assert s["median"] == 0.0


def _stats(n_updates, pct_at_floor, pct_at_floor_1):
    return {
        "n_updates": n_updates,
        "pct_at_floor": pct_at_floor,
        "pct_at_floor_1": pct_at_floor_1,
    }


def test_classify_no_data_before_everything():
    s = _stats(0, 0.0, 0.0)
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "NO_DATA"


def test_classify_low_sample_below_min_updates():
    s = _stats(99, 50.0, 50.0)  # would be CRITICAL if it had samples
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "LOW_SAMPLE"


def test_classify_critical_at_threshold():
    s = _stats(500, 1.0, 1.0)  # exactly at critical_pct
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "CRITICAL"


def test_classify_warn_only_when_floor_untouched():
    s = _stats(500, 0.0, 5.0)  # never at floor, but >=warn_pct at floor+1
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "WARN"


def test_classify_ok():
    s = _stats(500, 0.0, 4.9)  # below warn_pct at floor+1
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "OK"


def test_classify_min_updates_boundary_is_low_sample_exclusive():
    # n_updates == min_updates is NOT low sample (>= passes)
    s_at = _stats(100, 0.0, 0.0)
    assert classify(s_at, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "OK"
    s_below = _stats(100, 2.0, 2.0)
    assert (
        classify(s_below, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "CRITICAL"
    )


def test_result_columns_contract():
    assert RESULT_COLUMNS == [
        "feed_id",
        "symbol",
        "asset_type",
        "session",
        "effective_min_pub",
        "n_updates",
        "min",
        "p1",
        "p5",
        "median",
        "pct_at_floor",
        "pct_at_floor_1",
        "verdict",
    ]
