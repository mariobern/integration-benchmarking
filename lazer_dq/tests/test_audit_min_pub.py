import numpy as np
import pandas as pd

from lazer_dq.audit_min_pub import (
    active_counts_for_session,
    audit_metrics,
    classify,
    longest_true_run,
)


def test_longest_true_run():
    assert longest_true_run(np.array([], dtype=bool)) == 0
    assert longest_true_run(np.array([False, False])) == 0
    assert longest_true_run(np.array([True, True, False, True])) == 2
    assert longest_true_run(np.array([True] * 5)) == 5


def test_audit_metrics_counts_and_runs():
    # min_pub = 2: below=1 minute (count 1), at=2 minutes (count 2),
    # at min+1=1 minute (count 3), above=2 minutes (count 4).
    counts = np.array([1, 2, 2, 3, 4, 4])
    m = audit_metrics(counts, min_pub=2, prolonged_threshold=3)
    assert m["open_minutes"] == 6
    assert m["minutes_below_min"] == 1
    assert m["minutes_at_min"] == 2
    assert m["minutes_at_min_plus_1"] == 1
    assert m["longest_run_le_min"] == 3  # [1, 2, 2]
    assert m["longest_run_le_min_plus_1"] == 4  # [1, 2, 2, 3]
    assert m["median_active"] == 2.5
    assert m["worst_minute_active"] == 1
    assert m["prolonged"] is True  # run of 3 at <= min_pub meets threshold 3


def test_classify():
    critical = {"minutes_below_min": 0, "minutes_at_min": 5, "minutes_at_min_plus_1": 0}
    warn = {"minutes_below_min": 0, "minutes_at_min": 0, "minutes_at_min_plus_1": 2}
    ok = {"minutes_below_min": 0, "minutes_at_min": 0, "minutes_at_min_plus_1": 0}
    assert classify(critical) == "CRITICAL"
    assert classify(warn) == "WARN"
    assert classify(ok) == "OK"


def test_classify_critical_on_below_min_only():
    """CRITICAL when only minutes_below_min > 0 (at_min = 0, at_min_plus_1 = 0)."""
    metrics = {"minutes_below_min": 3, "minutes_at_min": 0, "minutes_at_min_plus_1": 0}
    assert classify(metrics) == "CRITICAL"


def test_active_counts_only_allowed_and_zero_fills_missing_minutes():
    idx = pd.date_range("2026-07-06 13:30", periods=4, freq="1min", tz="UTC")
    mask = pd.Series([True, True, True, False], index=idx)
    per_minute = {
        idx[0]: {1, 2, 99},  # 99 not allowed -> count 2
        idx[2]: {1},
        # idx[1] missing entirely -> count 0
        idx[3]: {1, 2},  # masked out (session closed)
    }
    counts = active_counts_for_session(per_minute, mask, allowed=frozenset({1, 2}))
    assert counts.tolist() == [2, 0, 1]


class FakeResult:
    def __init__(self, rows):
        self.result_rows = rows


class FakeClient:
    """Returns canned (minute, [publisher_ids]) rows for any query."""

    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def query(self, q, parameters=None):
        self.queries.append((q, parameters))
        return FakeResult(self._rows)


def test_fetch_per_minute_publishers_builds_utc_dict():
    from datetime import datetime, timezone

    from lazer_dq.audit_min_pub import fetch_per_minute_publishers

    t0 = datetime(2026, 7, 6, 13, 30, tzinfo=timezone.utc)
    client = FakeClient([(t0.replace(tzinfo=None), [1, 2])])
    out = fetch_per_minute_publishers(
        client, 10, t0, datetime(2026, 7, 6, 13, 40, tzinfo=timezone.utc)
    )
    key = pd.Timestamp("2026-07-06 13:30", tz="UTC")
    assert out == {key: {1, 2}}
    # Parameterized query, feed scoped, ACCEPTED-only
    q, params = client.queries[0]
    assert "status = 'ACCEPTED'" in q
    assert params["feed_id"] == 10


def test_audit_feed_malformed_schedule_yields_no_schedule():
    """Malformed schedule_str yields NO_SCHEDULE; valid sibling still gets metrics."""
    from datetime import datetime, timezone

    from lazer_dq.audit_min_pub import audit_feed
    from lazer_dq.min_pub_common import FeedSession

    start_utc = datetime(2026, 7, 6, tzinfo=timezone.utc)
    end_utc = datetime(2026, 7, 7, tzinfo=timezone.utc)

    # Canned per-minute data: one minute with publishers [3, 4, 5]
    t0 = start_utc.replace(hour=13, minute=30)
    client = FakeClient([(t0.replace(tzinfo=None), [3, 4, 5])])

    # Session 1: valid schedule (REGULAR hours)
    fs_valid = FeedSession(
        feed_id=100,
        symbol="Test.X",
        asset_type="fx",
        session="REGULAR",
        allowed=frozenset({3, 4, 5}),
        effective_min_pub=1,
        schedule_str="UTC;O,O,O,O,O,O,O",  # Always open
    )

    # Session 2: malformed schedule string
    fs_malformed = FeedSession(
        feed_id=100,
        symbol="Test.X",
        asset_type="fx",
        session="EXTENDED",
        allowed=frozenset({1, 2}),
        effective_min_pub=1,
        schedule_str="not-a-schedule",
    )

    rows = audit_feed(client, [fs_valid, fs_malformed], start_utc, end_utc, 30)

    # Should have 2 rows
    assert len(rows) == 2

    # Row 1: valid session, has metrics
    assert rows[0]["session"] == "REGULAR"
    assert rows[0]["classification"] in ("OK", "CRITICAL", "WARN")
    assert "open_minutes" in rows[0]
    assert "median_active" in rows[0]
    assert rows[0]["open_minutes"] > 0

    # Row 2: malformed, yields NO_SCHEDULE (no metrics)
    assert rows[1]["session"] == "EXTENDED"
    assert rows[1]["classification"] == "NO_SCHEDULE"
    # NO_SCHEDULE row has no metrics columns (or they should be absent)
    assert "open_minutes" not in rows[1]
