# Performance Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce feed_readiness.py execution time by 50-70% via uptime query batching and connection reuse.

**Architecture:** Replace per-publisher uptime queries with batched queries that fetch all publishers in a single SQL call per session. Move ClickHouse client creation outside the per-feed loop so connections are reused across feed evaluations within each worker thread.

**Tech Stack:** Python, clickhouse_connect, ThreadPoolExecutor, pytest

---

### Task 1: Add batched 1s-window uptime function

**Files:**

- Modify: `lib/uptime_core.py`
- Test: `tests/lib/test_uptime_core.py`

**Step 1: Write the failing test**

Add to `tests/lib/test_uptime_core.py` after the `TestComputeUptime1sWindow` class:

```python
class TestBatchComputeUptime1sWindow:
    def test_returns_dict_keyed_by_publisher_id(self) -> None:
        from lib.uptime_core import batch_compute_uptime_1s_window

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)
        total_seconds = int((end - start).total_seconds())

        uptime_pct_55 = 98.0
        uptime_pct_71 = 42.7

        # Batched query returns one row per publisher
        client = _make_client([
            (55, 23000, 23000, total_seconds, 23000 / total_seconds, uptime_pct_55),
            (71, 10000, 10000, total_seconds, 10000 / total_seconds, uptime_pct_71),
        ])

        result = batch_compute_uptime_1s_window(
            client=client,
            publisher_ids=[55, 71],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert isinstance(result, dict)
        assert set(result.keys()) == {55, 71}
        assert result[55]["uptime_pct"] == pytest.approx(uptime_pct_55, abs=0.01)
        assert result[55]["seconds_with_data"] == 23000
        assert result[71]["uptime_pct"] == pytest.approx(uptime_pct_71, abs=0.01)

    def test_missing_publisher_gets_zero_uptime(self) -> None:
        from lib.uptime_core import batch_compute_uptime_1s_window

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)
        total_seconds = int((end - start).total_seconds())

        # Only publisher 55 has data; publisher 71 absent from results
        client = _make_client([
            (55, 23000, 23000, total_seconds, 23000 / total_seconds, 98.0),
        ])

        result = batch_compute_uptime_1s_window(
            client=client,
            publisher_ids=[55, 71],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert result[71]["uptime_pct"] == 0.0
        assert result[71]["seconds_with_data"] == 0
        assert result[71]["total_seconds"] == total_seconds
        assert result[71]["updates_total"] == 0

    def test_empty_publisher_list_returns_empty_dict(self) -> None:
        from lib.uptime_core import batch_compute_uptime_1s_window

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)

        client = _make_client([])

        result = batch_compute_uptime_1s_window(
            client=client,
            publisher_ids=[],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert result == {}

    def test_single_publisher_matches_original_function(self) -> None:
        from lib.uptime_core import batch_compute_uptime_1s_window

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 30, 10)

        client = _make_client([(55, 50, 10, 10, 5.0, 100.0)])

        result = batch_compute_uptime_1s_window(
            client=client,
            publisher_ids=[55],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert result[55]["uptime_pct"] == 100.0
        assert result[55]["seconds_with_data"] == 10
        assert result[55]["total_seconds"] == 10
        assert result[55]["updates_total"] == 50
```

**Step 2: Run test to verify it fails**

Run: `cd /home/mariobern/integration-benchmarking && python -m pytest tests/lib/test_uptime_core.py::TestBatchComputeUptime1sWindow -v`
Expected: FAIL with `ImportError: cannot import name 'batch_compute_uptime_1s_window'`

**Step 3: Write implementation**

Add to `lib/uptime_core.py` after `compute_uptime_1s_window()` (after line 129):

```python
def batch_compute_uptime_1s_window(
    client,
    publisher_ids: list[int],
    feed_id: int,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[int, dict]:
    """
    Compute 1s-window uptime for multiple publishers in a single query.

    Returns dict keyed by publisher_id with same structure as compute_uptime_1s_window.
    Publishers with no data get zero-uptime entries.
    """
    if not publisher_ids:
        return {}

    total_seconds = int((end_utc - start_utc).total_seconds())
    start_str = start_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")

    pub_list = ", ".join(str(pid) for pid in publisher_ids)

    query = f"""
        WITH
            parseDateTimeBestEffort('{start_str}') AS start_time,
            parseDateTimeBestEffort('{end_str}') AS end_time,
            dateDiff('second', start_time, end_time) AS total_seconds,
            per_second AS (
                SELECT
                    publisher_id,
                    toStartOfSecond(publish_time) AS second_start,
                    count() AS update_count
                FROM publisher_updates
                PREWHERE price_feed_id = {feed_id}
                    AND publisher_id IN ({pub_list})
                WHERE publish_time >= start_time
                    AND publish_time < end_time
                GROUP BY publisher_id, second_start
            )
        SELECT
            publisher_id,
            sum(update_count) AS updates_total,
            count() AS seconds_with_data,
            total_seconds,
            if(total_seconds = 0, 0, updates_total / total_seconds) AS updates_per_second,
            if(total_seconds = 0, 0, seconds_with_data * 100.0 / total_seconds) AS uptime_pct
        FROM per_second
        GROUP BY publisher_id, total_seconds
        ORDER BY publisher_id
    """
    result = client.query(query)

    results_by_pub: dict[int, dict] = {}
    for row in result.result_rows:
        pid = int(row[0])
        results_by_pub[pid] = {
            "uptime_pct": float(row[5] or 0),
            "seconds_with_data": int(row[2] or 0),
            "total_seconds": int(row[3] or 0),
            "updates_total": int(row[1] or 0),
            "updates_per_second": float(row[4] or 0),
        }

    # Fill in zero-uptime for publishers with no data
    for pid in publisher_ids:
        if pid not in results_by_pub:
            results_by_pub[pid] = {
                "uptime_pct": 0.0,
                "seconds_with_data": 0,
                "total_seconds": max(0, total_seconds),
                "updates_total": 0,
                "updates_per_second": 0.0,
            }

    return results_by_pub
```

**Step 4: Run test to verify it passes**

Run: `cd /home/mariobern/integration-benchmarking && python -m pytest tests/lib/test_uptime_core.py::TestBatchComputeUptime1sWindow -v`
Expected: PASS

**Step 5: Run all existing uptime tests to check for regressions**

Run: `cd /home/mariobern/integration-benchmarking && python -m pytest tests/lib/test_uptime_core.py -v`
Expected: All existing tests still PASS

**Step 6: Commit**

```bash
git add lib/uptime_core.py tests/lib/test_uptime_core.py
git commit -m "feat: add batch_compute_uptime_1s_window for batched uptime queries"
```

---

### Task 2: Add batched gap-based uptime function

**Files:**

- Modify: `lib/uptime_core.py`
- Test: `tests/lib/test_uptime_core.py`

**Step 1: Write the failing test**

Add to `tests/lib/test_uptime_core.py` after `TestBatchComputeUptime1sWindow`:

```python
class TestBatchComputeUptime200msGap:
    def test_returns_dict_keyed_by_publisher_id(self) -> None:
        from lib.uptime_core import batch_compute_uptime_200ms_gap

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 31, 0)
        total_ms = 60000

        # Batched query returns one row per publisher
        # Columns: publisher_id, total_updates, max_gap_ms, gaps_over_threshold,
        #          consecutive_downtime_ms, start_gap_ms, end_gap_ms,
        #          total_time_ms, total_downtime_ms
        client = _make_client([
            (55, 1000, 150, 0, 0, 0, 0, total_ms, 0),
            (71, 500, 5000, 3, 8000, 1000, 1000, total_ms, 10000),
        ])

        result = batch_compute_uptime_200ms_gap(
            client=client,
            publisher_ids=[55, 71],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert isinstance(result, dict)
        assert set(result.keys()) == {55, 71}
        assert result[55]["uptime_pct"] == 100.0
        assert result[55]["updates_total"] == 1000
        expected_71_uptime = (total_ms - 10000) / total_ms * 100.0
        assert result[71]["uptime_pct"] == pytest.approx(expected_71_uptime, abs=0.01)
        assert result[71]["total_downtime_ms"] == 10000

    def test_missing_publisher_gets_zero_uptime(self) -> None:
        from lib.uptime_core import batch_compute_uptime_200ms_gap

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 31, 0)
        total_ms = 60000

        client = _make_client([
            (55, 1000, 150, 0, 0, 0, 0, total_ms, 0),
        ])

        result = batch_compute_uptime_200ms_gap(
            client=client,
            publisher_ids=[55, 71],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert result[71]["uptime_pct"] == 0.0
        assert result[71]["updates_total"] == 0
        assert result[71]["total_downtime_ms"] == total_ms

    def test_empty_publisher_list(self) -> None:
        from lib.uptime_core import batch_compute_uptime_200ms_gap

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 31, 0)

        client = _make_client([])

        result = batch_compute_uptime_200ms_gap(
            client=client,
            publisher_ids=[],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert result == {}

    def test_custom_gap_threshold(self) -> None:
        from lib.uptime_core import batch_compute_uptime_200ms_gap

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 31, 0)
        total_ms = 60000

        client = _make_client([
            (55, 1000, 80, 0, 0, 0, 0, total_ms, 0),
        ])

        result = batch_compute_uptime_200ms_gap(
            client=client,
            publisher_ids=[55],
            feed_id=922,
            start_utc=start,
            end_utc=end,
            gap_threshold_ms=100,
        )

        assert result[55]["uptime_pct"] == 100.0
```

**Step 2: Run test to verify it fails**

Run: `cd /home/mariobern/integration-benchmarking && python -m pytest tests/lib/test_uptime_core.py::TestBatchComputeUptime200msGap -v`
Expected: FAIL with `ImportError: cannot import name 'batch_compute_uptime_200ms_gap'`

**Step 3: Write implementation**

Add to `lib/uptime_core.py` after `compute_uptime_200ms_gap()` (after line 260):

```python
def batch_compute_uptime_200ms_gap(
    client,
    publisher_ids: list[int],
    feed_id: int,
    start_utc: datetime,
    end_utc: datetime,
    gap_threshold_ms: int = DEFAULT_GAP_THRESHOLD_MS,
) -> dict[int, dict]:
    """
    Compute gap-based uptime for multiple publishers in a single query.

    Returns dict keyed by publisher_id with same structure as compute_uptime_200ms_gap.
    Publishers with no data get zero-uptime entries.
    """
    if not publisher_ids:
        return {}

    total_ms = int((end_utc - start_utc).total_seconds() * 1000)
    start_str = start_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")

    pub_list = ", ".join(str(pid) for pid in publisher_ids)

    query = f"""
        WITH
            parseDateTimeBestEffort('{start_str}') AS start_time,
            parseDateTimeBestEffort('{end_str}') AS end_time,
            dateDiff('millisecond', start_time, end_time) AS total_time_ms,
            updates AS (
                SELECT
                    publisher_id,
                    publish_time,
                    lagInFrame(publish_time, 1) OVER (
                        PARTITION BY publisher_id ORDER BY publish_time
                    ) AS prev_time
                FROM publisher_updates
                PREWHERE price_feed_id = {feed_id}
                    AND publisher_id IN ({pub_list})
                WHERE publish_time >= start_time
                    AND publish_time <= end_time
            ),
            gaps AS (
                SELECT
                    publisher_id,
                    publish_time,
                    prev_time,
                    CASE
                        WHEN prev_time IS NOT NULL THEN
                            dateDiff('millisecond',
                                if(prev_time < start_time, start_time, prev_time),
                                publish_time)
                        ELSE 0
                    END AS gap_ms
                FROM updates
            ),
            gap_stats AS (
                SELECT
                    publisher_id,
                    count() AS total_updates,
                    min(publish_time) AS first_update,
                    max(publish_time) AS last_update,
                    max(gap_ms) AS max_gap_ms,
                    countIf(gap_ms > {gap_threshold_ms}) AS gaps_over_threshold,
                    sum(greatest(0, gap_ms - {gap_threshold_ms})) AS consecutive_downtime_ms
                FROM gaps
                GROUP BY publisher_id
            )
        SELECT
            publisher_id,
            total_updates,
            max_gap_ms,
            gaps_over_threshold,
            consecutive_downtime_ms,
            if(
                total_updates = 0,
                total_time_ms,
                greatest(0, dateDiff('millisecond', start_time, first_update) - {gap_threshold_ms})
            ) AS start_gap_ms,
            if(
                total_updates = 0,
                0,
                greatest(0, dateDiff('millisecond', last_update, end_time) - {gap_threshold_ms})
            ) AS end_gap_ms,
            total_time_ms,
            least(
                consecutive_downtime_ms +
                if(
                    total_updates = 0,
                    total_time_ms,
                    greatest(0, dateDiff('millisecond', start_time, first_update) - {gap_threshold_ms})
                ) +
                if(
                    total_updates = 0,
                    0,
                    greatest(0, dateDiff('millisecond', last_update, end_time) - {gap_threshold_ms})
                ),
                total_time_ms
            ) AS total_downtime_ms
        FROM gap_stats
        ORDER BY publisher_id
    """
    result = client.query(query)

    results_by_pub: dict[int, dict] = {}
    for row in result.result_rows:
        pid = int(row[0])
        updates_total = int(row[1] or 0)
        max_gap_ms = int(row[2]) if row[2] is not None else None
        gaps_over_threshold = int(row[3] or 0)
        total_time_ms = int(row[7] or 0)

        if updates_total == 0:
            total_downtime_ms = total_time_ms
        else:
            total_downtime_ms = int(row[8] or 0)

        uptime_pct = (
            ((total_time_ms - total_downtime_ms) / total_time_ms * 100.0)
            if total_time_ms > 0
            else 0.0
        )
        updates_per_second = (
            (updates_total / (total_time_ms / 1000.0)) if total_time_ms > 0 else 0.0
        )

        results_by_pub[pid] = {
            "uptime_pct": uptime_pct,
            "total_downtime_ms": total_downtime_ms,
            "period_length_ms": total_time_ms,
            "updates_total": updates_total,
            "updates_per_second": updates_per_second,
            "max_gap_ms": max_gap_ms,
            "gaps_over_threshold": gaps_over_threshold,
        }

    # Fill in zero-uptime for publishers with no data
    for pid in publisher_ids:
        if pid not in results_by_pub:
            results_by_pub[pid] = {
                "uptime_pct": 0.0,
                "total_downtime_ms": total_ms,
                "period_length_ms": total_ms,
                "updates_total": 0,
                "updates_per_second": 0.0,
                "max_gap_ms": None,
                "gaps_over_threshold": 0,
            }

    return results_by_pub
```

**Step 4: Run test to verify it passes**

Run: `cd /home/mariobern/integration-benchmarking && python -m pytest tests/lib/test_uptime_core.py::TestBatchComputeUptime200msGap -v`
Expected: PASS

**Step 5: Run all uptime tests**

Run: `cd /home/mariobern/integration-benchmarking && python -m pytest tests/lib/test_uptime_core.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add lib/uptime_core.py tests/lib/test_uptime_core.py
git commit -m "feat: add batch_compute_uptime_200ms_gap for batched gap-based uptime"
```

---

### Task 3: Switch evaluate_feed_uptime to use batched functions

**Files:**

- Modify: `lib/uptime_core.py` (lines 280-411, `evaluate_feed_uptime` function)
- Test: `tests/lib/test_uptime_core.py`

**Step 1: Run existing tests to capture baseline**

Run: `cd /home/mariobern/integration-benchmarking && python -m pytest tests/lib/test_uptime_core.py -v`
Expected: All PASS (this is our baseline)

**Step 2: Rewrite evaluate_feed_uptime to use batch functions**

Replace the inner loop in `evaluate_feed_uptime()` (lines 329-389) with batch calls. The key change: instead of iterating `for publisher_id in publishers: for session in sessions: compute_uptime(...)`, iterate `for session in sessions: batch_compute_uptime(all_publishers)`.

Replace lines 329-389 in `lib/uptime_core.py` with:

```python
        publisher_uptimes: list[PublisherSessionUptime] = []
        for session_window in filtered_sessions:
            total_seconds = int(
                (session_window.end_utc - session_window.start_utc).total_seconds()
            )
            if precise:
                batch_results = batch_compute_uptime_200ms_gap(
                    client=client,
                    publisher_ids=publishers,
                    feed_id=feed_id,
                    start_utc=session_window.start_utc,
                    end_utc=session_window.end_utc,
                    gap_threshold_ms=gap_threshold_ms,
                )
                for publisher_id in publishers:
                    uptime = batch_results[publisher_id]
                    uptime_pct = uptime["uptime_pct"]
                    passes = uptime_pct >= uptime_threshold_pct
                    publisher_uptimes.append(
                        PublisherSessionUptime(
                            publisher_id=publisher_id,
                            session=session_window.session,
                            uptime_pct=uptime_pct,
                            passes=passes,
                            seconds_with_data=0,
                            total_seconds=total_seconds,
                            updates_total=uptime["updates_total"],
                            updates_per_second=uptime["updates_per_second"],
                            downtime_ms=uptime["total_downtime_ms"],
                            period_length_ms=uptime["period_length_ms"],
                            max_gap_ms=uptime["max_gap_ms"],
                            gaps_over_threshold=uptime["gaps_over_threshold"],
                        )
                    )
            else:
                batch_results = batch_compute_uptime_1s_window(
                    client=client,
                    publisher_ids=publishers,
                    feed_id=feed_id,
                    start_utc=session_window.start_utc,
                    end_utc=session_window.end_utc,
                )
                for publisher_id in publishers:
                    uptime = batch_results[publisher_id]
                    uptime_pct = uptime["uptime_pct"]
                    passes = uptime_pct >= uptime_threshold_pct
                    publisher_uptimes.append(
                        PublisherSessionUptime(
                            publisher_id=publisher_id,
                            session=session_window.session,
                            uptime_pct=uptime_pct,
                            passes=passes,
                            seconds_with_data=uptime["seconds_with_data"],
                            total_seconds=uptime["total_seconds"],
                            updates_total=uptime["updates_total"],
                            updates_per_second=uptime["updates_per_second"],
                            downtime_ms=None,
                            period_length_ms=None,
                            max_gap_ms=None,
                            gaps_over_threshold=None,
                        )
                    )
```

**Step 3: Run all existing tests to verify no regressions**

Run: `cd /home/mariobern/integration-benchmarking && python -m pytest tests/lib/test_uptime_core.py -v`

Expected: Tests in `TestEvaluateFeedUptime1sWindow` and `TestEvaluateFeedUptimePrecise` will FAIL because the mock client's `.query()` call sequence has changed — previously the function issued N separate queries (one per publisher), now it issues 1 batched query per session.

**Step 4: Update existing evaluate_feed_uptime tests for new query pattern**

The mock clients in `TestEvaluateFeedUptime1sWindow` and `TestEvaluateFeedUptimePrecise` need updating because the batched query now returns rows with `publisher_id` as the first column.

Update `test_basic_evaluation_returns_result` mock:

```python
        client = _make_multi_client(
            [
                # get_feed_symbol query
                [("Equity.US.AAPL/USD",)],
                # discover_publishers query
                [(55,)],
                # batch_compute_uptime_1s_window query (publisher_id is first column)
                [(55, 23000, 23000, total_seconds, 23000 / total_seconds, uptime_pct)],
            ]
        )
```

Update `test_publisher_fails_below_threshold` mock:

```python
        client = _make_multi_client(
            [
                [("Equity.US.AAPL/USD",)],
                [(55,)],
                [(55, 18720, 18720, total_seconds, 18720 / total_seconds, uptime_pct)],
            ]
        )
```

Update `test_custom_uptime_threshold` mock:

```python
        client = _make_multi_client(
            [
                [("Equity.US.AAPL/USD",)],
                [(55,)],
                [(55, 21060, 21060, total_seconds, 21060 / total_seconds, uptime_pct)],
            ]
        )
```

Update `test_multiple_publishers` mock — now ONE query returns BOTH publishers:

```python
        client = _make_multi_client(
            [
                [("Equity.US.AAPL/USD",)],
                [(55,), (71,)],
                # Single batched query returns both publishers
                [
                    (55, 23000, 23000, total_seconds, 23000 / total_seconds, 98.0),
                    (71, 10000, 10000, total_seconds, 10000 / total_seconds, 42.7),
                ],
            ]
        )
```

Update `test_precise_mode_uses_gap_method` mock — add publisher_id as first column:

```python
        client = _make_multi_client(
            [
                [("Equity.US.AAPL/USD",)],
                [(55,)],
                # batch_compute_uptime_200ms_gap: publisher_id is first column
                [(55, 23000, 150, 0, 0, 0, 0, total_ms, 0)],
            ]
        )
```

**Step 5: Run all uptime tests again**

Run: `cd /home/mariobern/integration-benchmarking && python -m pytest tests/lib/test_uptime_core.py -v`
Expected: All PASS

**Step 6: Run full test suite to check for wider regressions**

Run: `cd /home/mariobern/integration-benchmarking && python -m pytest tests/ -v --tb=short`
Expected: All PASS

**Step 7: Commit**

```bash
git add lib/uptime_core.py tests/lib/test_uptime_core.py
git commit -m "refactor: switch evaluate_feed_uptime to use batched queries

Reduces uptime queries from N*M (publishers*sessions) to M (sessions).
For a typical feed with 30 publishers and 4 sessions, this cuts
120 queries down to 4."
```

---

### Task 4: Connection reuse in readiness_core.py

**Files:**

- Modify: `lib/readiness_core.py` (lines 705-792, `process_work_items` function)

**Step 1: Move client creation outside evaluate_single**

In `lib/readiness_core.py`, the `process_work_items()` function creates clients inside `evaluate_single()` (line 731). Move client creation to a per-thread initialization using `threading.local()`.

Replace lines 726-758 in `lib/readiness_core.py`:

```python
    import threading

    thread_local = threading.local()

    def get_thread_clients():
        """Get or create ClickHouse clients for the current thread."""
        if not hasattr(thread_local, "client_lazer"):
            thread_local.client_lazer, thread_local.client_analytics = get_clients(
                config
            )
        return thread_local.client_lazer, thread_local.client_analytics

    def evaluate_single(item: tuple[int, str, str]) -> FeedReadinessResult:
        feed_id, date, mode = item
        start_time = time.time()
        try:
            client_lazer, client_analytics = get_thread_clients()
            return evaluate_feed_readiness(
                client_lazer=client_lazer,
                client_analytics=client_analytics,
                feed_id=feed_id,
                date=date,
                mode=mode,
                target_pub_count=target_pub_count,
                include_extended_hours=include_extended_hours,
                include_overnight=include_overnight,
                skip_scipy_tests=skip_scipy_tests,
                precise=precise,
                gap_threshold_ms=gap_threshold_ms,
                uptime_threshold_pct=uptime_threshold_pct,
                include_detailed=include_detailed,
                tolerance_seconds=tolerance_seconds,
                include_agg=include_agg,
            )
        except Exception as exc:
            return _make_error_result(
                feed_id=feed_id,
                date=date,
                mode=mode,
                target_pub_count=target_pub_count,
                error=str(exc),
                execution_time_ms=int((time.time() - start_time) * 1000),
                include_detailed=include_detailed,
            )
```

**Step 2: Run readiness tests**

Run: `cd /home/mariobern/integration-benchmarking && python -m pytest tests/test_readiness_core_pub0.py tests/test_readiness_summary.py -v`
Expected: All PASS (these test merge_results, not process_work_items)

**Step 3: Commit**

```bash
git add lib/readiness_core.py
git commit -m "perf: reuse ClickHouse connections per thread in readiness_core"
```

---

### Task 5: Connection reuse in benchmark_core.py

**Files:**

- Modify: `lib/benchmark_core.py` (lines 1126-1144, `evaluate_single` inside `process_csv`)

**Step 1: Move client creation outside evaluate_single**

In `lib/benchmark_core.py`, replace the `evaluate_single` function inside `process_csv()` (around lines 1128-1144):

```python
    import threading

    thread_local = threading.local()

    def get_thread_clients():
        """Get or create ClickHouse clients for the current thread."""
        if not hasattr(thread_local, "client_lazer"):
            thread_local.client_lazer, thread_local.client_analytics = get_clients(
                config
            )
        return thread_local.client_lazer, thread_local.client_analytics

    def evaluate_single(args):
        feed_id, date, mode = args
        client_lazer, client_analytics = get_thread_clients()
        return evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            feed_id,
            date,
            mode,
            target_pub_count=target_pub_count,
            include_extended_hours=include_extended_hours,
            include_overnight=include_overnight,
            skip_scipy_tests=skip_scipy_tests,
            include_detailed=include_detailed,
            hit_rate_threshold=hit_rate_threshold,
            include_agg=include_agg,
        )
```

**Step 2: Run benchmark_core tests**

Run: `cd /home/mariobern/integration-benchmarking && python -m pytest tests/ -v --tb=short -k "benchmark"`
Expected: All PASS

**Step 3: Commit**

```bash
git add lib/benchmark_core.py
git commit -m "perf: reuse ClickHouse connections per thread in benchmark_core"
```

---

### Task 6: Connection reuse in uptime_core.py process_work_items

**Files:**

- Modify: `lib/uptime_core.py` (lines 414-499, `process_work_items` function)

**Step 1: Move client creation outside evaluate_single**

In `lib/uptime_core.py`, replace the `evaluate_single` function inside `process_work_items()` (around lines 433-448):

```python
    import threading

    thread_local = threading.local()

    def get_thread_client():
        """Get or create ClickHouse client for the current thread."""
        if not hasattr(thread_local, "client"):
            thread_local.client = get_lazer_client(config)
        return thread_local.client

    def evaluate_single(item: tuple[int, str, str]) -> FeedUptimeResult:
        feed_id, date, mode = item
        start_time_ts = time.time()
        try:
            client = get_thread_client()
            return evaluate_feed_uptime(
                client=client,
                feed_id=feed_id,
                date=date,
                mode=mode,
                include_extended_hours=include_extended_hours,
                include_overnight=include_overnight,
                precise=precise,
                gap_threshold_ms=gap_threshold_ms,
                uptime_threshold_pct=uptime_threshold_pct,
            )
        except Exception as e:
            return FeedUptimeResult(
                feed_id=feed_id,
                date=date,
                mode=mode,
                symbol=None,
                publisher_count=0,
                publisher_uptimes=[],
                error=str(e),
                execution_time_ms=int((time.time() - start_time_ts) * 1000),
            )
```

**Step 2: Run full test suite**

Run: `cd /home/mariobern/integration-benchmarking && python -m pytest tests/ -v --tb=short`
Expected: All PASS

**Step 3: Commit**

```bash
git add lib/uptime_core.py
git commit -m "perf: reuse ClickHouse connections per thread in uptime_core"
```

---

### Task 7: Pre-commit and final verification

**Step 1: Run pre-commit on all changed files**

```bash
cd /home/mariobern/integration-benchmarking
pre-commit run --files lib/uptime_core.py lib/readiness_core.py lib/benchmark_core.py tests/lib/test_uptime_core.py
```

Expected: All checks pass (black formatting, trailing whitespace, etc.)

**Step 2: Run full test suite one final time**

```bash
cd /home/mariobern/integration-benchmarking
python -m pytest tests/ -v --tb=short
```

Expected: All PASS

**Step 3: If pre-commit made formatting changes, commit them**

```bash
git add -u
git commit -m "chore: fix pre-commit formatting"
```
