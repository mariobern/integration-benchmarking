# Research PRs #264 & #265 Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add US equities qualifier filter and aggregate feed (publisher 0) evaluation to feed_readiness.py and quick_benchmark.py.

**Architecture:** Two independent features. (1) New `get_qualifier_filter_sql(mode)` in sql_filters.py, injected into all benchmark queries. (2) New `query_aggregate_feed()` in benchmark_core.py, integrated into `evaluate_feed_two_queries()` with publisher 0 excluded from passing counts. Both features thread through the existing process_csv/process_work_items call chains via new parameters.

**Tech Stack:** Python 3, ClickHouse SQL, pytest, existing lib/ modules

---

## Task 1: Add `get_qualifier_filter_sql()` to sql_filters.py

**Files:**
- Modify: `lib/sql_filters.py:192` (append after `get_benchmark_columns`)
- Test: `tests/lib/test_sql_filters.py`

**Step 1: Write the failing tests**

Add to `tests/lib/test_sql_filters.py`:

```python
from lib.sql_filters import get_qualifier_filter_sql

# ---------------------------------------------------------------------------
# get_qualifier_filter_sql
# ---------------------------------------------------------------------------
class TestGetQualifierFilterSql:
    def test_us_equities_returns_filter(self):
        sql = get_qualifier_filter_sql("us-equities")
        assert "qualifiers" in sql
        assert "CON[IRGCOND]" in sql
        assert "ODD[IRGCOND]" in sql
        assert "378[IRGCOND]" in sql
        assert "2315[IRGCOND]" in sql
        assert "DAP[IRGCOND]" in sql
        assert "PD_" in sql

    def test_us_equities_allows_null_qualifiers(self):
        sql = get_qualifier_filter_sql("us-equities")
        assert "qualifiers IS NULL" in sql

    def test_fx_returns_empty(self):
        assert get_qualifier_filter_sql("fx") == ""

    def test_metals_returns_empty(self):
        assert get_qualifier_filter_sql("metals") == ""

    def test_commodity_returns_empty(self):
        assert get_qualifier_filter_sql("commodity") == ""

    def test_us_treasuries_returns_empty(self):
        assert get_qualifier_filter_sql("us-treasuries") == ""

    def test_equity_us_alias(self):
        """equity-us should also get the filter."""
        sql = get_qualifier_filter_sql("equity-us")
        assert "qualifiers" in sql
```

**Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate && python3 -m pytest tests/lib/test_sql_filters.py::TestGetQualifierFilterSql -v
```

Expected: FAIL — `ImportError: cannot import name 'get_qualifier_filter_sql'`

**Step 3: Write the implementation**

Add to `lib/sql_filters.py` after the `get_benchmark_columns` function (after line 191):

```python
def get_qualifier_filter_sql(mode: str) -> str:
    """Return SQL WHERE clause to exclude irregular trade qualifiers.

    Only applies to US equities benchmark data. Other asset classes
    return an empty string (no filtering).
    """
    if mode not in ("us-equities", "equity-us"):
        return ""

    return """
          AND (
            qualifiers IS NULL
            OR (
                qualifiers NOT LIKE '%CON[IRGCOND]%'
                AND qualifiers NOT LIKE '%ODD[IRGCOND]%'
                AND qualifiers NOT LIKE '%378[IRGCOND]%'
                AND qualifiers NOT LIKE '%2315[IRGCOND]%'
                AND qualifiers NOT LIKE '%DAP[IRGCOND]%'
                AND NOT match(qualifiers, 'PD_[A-Za-z0-9_]*')
            )
          )"""
```

**Step 4: Run tests to verify they pass**

```bash
source venv/bin/activate && python3 -m pytest tests/lib/test_sql_filters.py::TestGetQualifierFilterSql -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add lib/sql_filters.py tests/lib/test_sql_filters.py
git commit -m "feat: add qualifier filter for US equities benchmark data"
```

---

## Task 2: Inject qualifier filter into benchmark_core.py

**Files:**
- Modify: `lib/benchmark_core.py` (lines 581-617 in `evaluate_feed_two_queries`, lines 126-160 in `evaluate_session_for_all_publishers`)
- Test: `tests/lib/test_benchmark_core.py`

**Step 1: Write the failing test**

Add to `tests/lib/test_benchmark_core.py`:

```python
class TestQualifierFilterInQueries:
    """Verify qualifier filter is injected into benchmark SQL for us-equities."""

    @patch("lib.benchmark_core.get_feed_metadata")
    def test_us_equities_includes_qualifier_filter(self, mock_meta):
        """When mode=us-equities, benchmark query should contain qualifier filter."""
        mock_meta.return_value = ("Equity.US.AAPL/USD", -8)

        client_lazer = _make_client([])
        client_analytics = _make_client([])

        evaluate_feed_two_queries(
            client_lazer, client_analytics,
            feed_id=327, date="2025-10-06", mode="us-equities",
        )

        # The analytics client should have been called with a query containing qualifier filter
        analytics_call = client_analytics.query.call_args
        if analytics_call:
            query_sql = analytics_call[0][0]
            assert "qualifiers" in query_sql
            assert "IRGCOND" in query_sql

    @patch("lib.benchmark_core.get_feed_metadata")
    def test_fx_excludes_qualifier_filter(self, mock_meta):
        """When mode=fx, benchmark query should NOT contain qualifier filter."""
        mock_meta.return_value = ("FX.EUR/USD", -8)

        client_lazer = _make_client([])
        client_analytics = _make_client([])

        evaluate_feed_two_queries(
            client_lazer, client_analytics,
            feed_id=327, date="2025-10-06", mode="fx",
        )

        analytics_call = client_analytics.query.call_args
        if analytics_call:
            query_sql = analytics_call[0][0]
            assert "qualifiers" not in query_sql
```

Also add import at the top of the test file:

```python
from lib.benchmark_core import evaluate_feed_two_queries
```

**Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate && python3 -m pytest tests/lib/test_benchmark_core.py::TestQualifierFilterInQueries -v
```

Expected: FAIL — qualifier filter not in query

**Step 3: Write the implementation**

In `lib/benchmark_core.py`:

1. Add import (top of file, alongside existing sql_filters imports):
```python
from lib.sql_filters import get_qualifier_filter_sql
```

2. In `evaluate_feed_two_queries()` (after line 585, where `benchmark_market_filter` is set):
```python
qualifier_filter = get_qualifier_filter_sql(mode)
```

3. In the benchmark query (line 614, after `{benchmark_market_filter}`):
```python
          {qualifier_filter}
```

4. In `evaluate_session_for_all_publishers()` — add `mode` usage:
   - The function already receives `mode` as a parameter (line 116)
   - After line 128, add: `qualifier_filter = get_qualifier_filter_sql(mode)`
   - In the benchmark query (line 157, after `{benchmark_time_filter}`), add: `{qualifier_filter}`

**Step 4: Run tests to verify they pass**

```bash
source venv/bin/activate && python3 -m pytest tests/lib/test_benchmark_core.py::TestQualifierFilterInQueries -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add lib/benchmark_core.py tests/lib/test_benchmark_core.py
git commit -m "feat: inject qualifier filter into benchmark_core queries"
```

---

## Task 3: Inject qualifier filter into publisher_eval.py

**Files:**
- Modify: `lib/publisher_eval.py` (lines 120-134 in `evaluate_session_metrics`, lines 470-484 in `evaluate_publisher_feed`)

**Step 1: Write the implementation**

In `lib/publisher_eval.py`:

1. Add import:
```python
from lib.sql_filters import get_qualifier_filter_sql
```

2. In `evaluate_session_metrics()` (around line 102, after getting price_col/bid_col/ask_col):
```python
qualifier_filter = get_qualifier_filter_sql(mode)
```
Then inject `{qualifier_filter}` after `{benchmark_time_filter}` in the benchmark query (line 131).

3. In `evaluate_publisher_feed()` (around line 449, after getting benchmark_table):
```python
qualifier_filter = get_qualifier_filter_sql(mode)
```
Then inject `{qualifier_filter}` after `{benchmark_market_filter}` in the benchmark query (line 481).

4. In extended hours benchmark queries within `evaluate_publisher_feed()` — these call `evaluate_session_metrics()` which already handles the filter.

**Step 2: Run all existing tests to verify no regressions**

```bash
source venv/bin/activate && python3 -m pytest tests/ -v
```

Expected: All PASS

**Step 3: Commit**

```bash
git add lib/publisher_eval.py
git commit -m "feat: inject qualifier filter into publisher_eval queries"
```

---

## Task 4: Add `agg_metrics` field to BenchmarkResult model

**Files:**
- Modify: `lib/models.py:114` (add field to BenchmarkResult)
- Test: `tests/lib/test_models.py`

**Step 1: Write the failing test**

Add to `tests/lib/test_models.py`:

```python
class TestBenchmarkResultAggMetrics:
    def test_agg_metrics_defaults_to_none(self):
        result = BenchmarkResult(
            feed_id=1, date="2025-01-01", mode="fx", symbol=None,
            ready=True, target_pub_count=4, passing_pub_count=4,
            failing_pub_count=0, passing_publishers=[1, 2, 3, 4],
            failing_publishers=[],
        )
        assert result.agg_metrics is None

    def test_agg_metrics_can_be_set(self):
        agg = PublisherFeedMetrics(
            publisher_id=0, n_observations=1000, passes=True,
            nrmse=0.005, hit_rate=98.0,
        )
        result = BenchmarkResult(
            feed_id=1, date="2025-01-01", mode="fx", symbol=None,
            ready=True, target_pub_count=4, passing_pub_count=4,
            failing_pub_count=0, passing_publishers=[1, 2, 3, 4],
            failing_publishers=[], agg_metrics=agg,
        )
        assert result.agg_metrics.publisher_id == 0
        assert result.agg_metrics.nrmse == 0.005
```

**Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate && python3 -m pytest tests/lib/test_models.py::TestBenchmarkResultAggMetrics -v
```

Expected: FAIL — `TypeError: unexpected keyword argument 'agg_metrics'`

**Step 3: Write the implementation**

In `lib/models.py`, add after line 114 (before `execution_time_ms`):

```python
    agg_metrics: Optional[PublisherFeedMetrics] = None
```

The BenchmarkResult class should now have this field between `error` and `execution_time_ms`.

**Step 4: Run tests to verify they pass**

```bash
source venv/bin/activate && python3 -m pytest tests/lib/test_models.py::TestBenchmarkResultAggMetrics -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add lib/models.py tests/lib/test_models.py
git commit -m "feat: add agg_metrics field to BenchmarkResult model"
```

---

## Task 5: Add `query_aggregate_feed()` to benchmark_core.py

**Files:**
- Modify: `lib/benchmark_core.py` (add new function before `evaluate_feed_two_queries`)
- Test: `tests/lib/test_benchmark_core.py`

**Step 1: Write the failing tests**

Add to `tests/lib/test_benchmark_core.py`:

```python
from lib.benchmark_core import query_aggregate_feed


class TestQueryAggregateFeed:
    def test_returns_data_from_channel_1(self):
        """Should return data from channel 1 if available."""
        rows = [
            (0, _make_timestamps(1)[0], 100.0, 5),
        ]
        client = _make_client(rows)
        result, channel = query_aggregate_feed(
            client, feed_id=327, date="2025-10-06",
            divisor=100000000, market_filter="",
        )
        assert result is not None
        assert channel == 1
        # Should have queried only once (channel 1 had data)
        assert client.query.call_count == 1

    def test_falls_through_to_channel_2(self):
        """If channel 1 empty, tries channel 2."""
        call_count = [0]
        def side_effect(query):
            call_count[0] += 1
            if "channel = 1" in query:
                return MockQueryResult(result_rows=[])
            return MockQueryResult(result_rows=[
                (0, _make_timestamps(1)[0], 100.0, 5),
            ])
        client = MagicMock()
        client.query.side_effect = side_effect

        result, channel = query_aggregate_feed(
            client, feed_id=327, date="2025-10-06",
            divisor=100000000, market_filter="",
        )
        assert result is not None
        assert channel == 2

    def test_returns_none_when_no_channels_have_data(self):
        """If no channels have data, returns (None, None)."""
        client = _make_client([])
        result, channel = query_aggregate_feed(
            client, feed_id=327, date="2025-10-06",
            divisor=100000000, market_filter="",
        )
        assert result is None
        assert channel is None
        assert client.query.call_count == 3  # tried all 3 channels

    def test_query_contains_price_feeds_table(self):
        """Query should reference price_feeds table."""
        client = _make_client([])
        query_aggregate_feed(
            client, feed_id=327, date="2025-10-06",
            divisor=100000000, market_filter="",
        )
        query_sql = client.query.call_args_list[0][0][0]
        assert "price_feeds" in query_sql

    def test_query_uses_publisher_id_zero(self):
        """Query should select 0 as publisher_id."""
        client = _make_client([])
        query_aggregate_feed(
            client, feed_id=327, date="2025-10-06",
            divisor=100000000, market_filter="",
        )
        query_sql = client.query.call_args_list[0][0][0]
        assert "0 AS publisher_id" in query_sql

    def test_graceful_on_exception(self):
        """If query raises, returns (None, None)."""
        client = MagicMock()
        client.query.side_effect = Exception("table not found")
        result, channel = query_aggregate_feed(
            client, feed_id=327, date="2025-10-06",
            divisor=100000000, market_filter="",
        )
        assert result is None
        assert channel is None
```

**Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate && python3 -m pytest tests/lib/test_benchmark_core.py::TestQueryAggregateFeed -v
```

Expected: FAIL — `ImportError: cannot import name 'query_aggregate_feed'`

**Step 3: Write the implementation**

Add to `lib/benchmark_core.py` before `evaluate_feed_two_queries()` (before line 544):

```python
def query_aggregate_feed(
    client_lazer,
    feed_id: int,
    date: str,
    divisor: float,
    market_filter: str,
) -> tuple:
    """Query price_feeds table as publisher 0, trying channels 1, 2, 3.

    Returns (result, channel) where result is a ClickHouse query result
    with rows of (publisher_id=0, ts_second, avg_price, update_count),
    or (None, None) if no data found on any channel.
    """
    for channel in [1, 2, 3]:
        query = f"""
            SELECT
                0 AS publisher_id,
                toStartOfSecond(publish_time) AS ts_second,
                avg(price) / {divisor} AS avg_price,
                count() AS update_count
            FROM price_feeds
            WHERE price_feed_id = {feed_id}
              AND toDate(publish_time) = '{date}'
              AND price IS NOT NULL
              AND channel = {channel}
              {market_filter}
            GROUP BY ts_second
            ORDER BY ts_second
        """
        try:
            result = client_lazer.query(query)
            if result.result_rows:
                return result, channel
        except Exception:
            return None, None
    return None, None
```

**Step 4: Run tests to verify they pass**

```bash
source venv/bin/activate && python3 -m pytest tests/lib/test_benchmark_core.py::TestQueryAggregateFeed -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add lib/benchmark_core.py tests/lib/test_benchmark_core.py
git commit -m "feat: add query_aggregate_feed() for price_feeds table"
```

---

## Task 6: Integrate publisher 0 into `evaluate_feed_two_queries()`

**Files:**
- Modify: `lib/benchmark_core.py` (lines 544-926 — signature, body, result construction)
- Test: `tests/lib/test_benchmark_core.py`

**Step 1: Write the failing tests**

Add to `tests/lib/test_benchmark_core.py`:

```python
class TestAggregateInEvaluateFeed:
    """Publisher 0 (aggregate) integration in evaluate_feed_two_queries."""

    @patch("lib.benchmark_core.query_aggregate_feed")
    @patch("lib.benchmark_core.get_feed_metadata")
    def test_agg_metrics_populated_when_data_exists(self, mock_meta, mock_agg):
        """agg_metrics should be set when aggregate feed data exists."""
        mock_meta.return_value = ("Equity.US.AAPL/USD", -8)
        divisor = 10 ** 8

        timestamps = _make_timestamps(200)
        pub_rows = [(55, ts, 150.0, 1) for ts in timestamps]
        bench_rows = [(ts, 150.0, 0.01) for ts in timestamps]

        agg_rows = [(0, ts, 150.0, 1) for ts in timestamps]
        mock_agg.return_value = (MockQueryResult(result_rows=agg_rows), 1)

        client_lazer = _make_client(pub_rows)
        client_analytics = _make_client(bench_rows)

        result = evaluate_feed_two_queries(
            client_lazer, client_analytics,
            feed_id=327, date="2025-10-06", mode="us-equities",
            include_agg=True,
        )

        assert result.agg_metrics is not None
        assert result.agg_metrics.publisher_id == 0

    @patch("lib.benchmark_core.query_aggregate_feed")
    @patch("lib.benchmark_core.get_feed_metadata")
    def test_agg_excluded_from_passing_publishers(self, mock_meta, mock_agg):
        """Publisher 0 should NOT appear in passing_publishers list."""
        mock_meta.return_value = ("Equity.US.AAPL/USD", -8)

        timestamps = _make_timestamps(200)
        pub_rows = [(55, ts, 150.0, 1) for ts in timestamps]
        bench_rows = [(ts, 150.0, 0.01) for ts in timestamps]
        agg_rows = [(0, ts, 150.0, 1) for ts in timestamps]
        mock_agg.return_value = (MockQueryResult(result_rows=agg_rows), 1)

        client_lazer = _make_client(pub_rows)
        client_analytics = _make_client(bench_rows)

        result = evaluate_feed_two_queries(
            client_lazer, client_analytics,
            feed_id=327, date="2025-10-06", mode="us-equities",
            include_agg=True,
        )

        assert 0 not in result.passing_publishers
        assert 0 not in result.failing_publishers

    @patch("lib.benchmark_core.get_feed_metadata")
    def test_no_agg_when_disabled(self, mock_meta):
        """When include_agg=False, agg_metrics should be None."""
        mock_meta.return_value = ("FX.EUR/USD", -8)

        timestamps = _make_timestamps(200)
        pub_rows = [(55, ts, 1.05, 1) for ts in timestamps]
        bench_rows = [(ts, 1.05, 0.0001) for ts in timestamps]

        client_lazer = _make_client(pub_rows)
        client_analytics = _make_client(bench_rows)

        result = evaluate_feed_two_queries(
            client_lazer, client_analytics,
            feed_id=327, date="2025-10-06", mode="fx",
            include_agg=False,
        )

        assert result.agg_metrics is None

    @patch("lib.benchmark_core.query_aggregate_feed")
    @patch("lib.benchmark_core.get_feed_metadata")
    def test_agg_failure_graceful(self, mock_meta, mock_agg):
        """If aggregate query returns no data, agg_metrics is None."""
        mock_meta.return_value = ("Equity.US.AAPL/USD", -8)
        mock_agg.return_value = (None, None)

        timestamps = _make_timestamps(200)
        pub_rows = [(55, ts, 150.0, 1) for ts in timestamps]
        bench_rows = [(ts, 150.0, 0.01) for ts in timestamps]

        client_lazer = _make_client(pub_rows)
        client_analytics = _make_client(bench_rows)

        result = evaluate_feed_two_queries(
            client_lazer, client_analytics,
            feed_id=327, date="2025-10-06", mode="us-equities",
            include_agg=True,
        )

        assert result.agg_metrics is None
        # Real publishers should still be evaluated
        assert result.passing_pub_count > 0 or result.failing_pub_count > 0
```

**Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate && python3 -m pytest tests/lib/test_benchmark_core.py::TestAggregateInEvaluateFeed -v
```

Expected: FAIL — `include_agg` parameter not recognized

**Step 3: Write the implementation**

Modify `evaluate_feed_two_queries()` in `lib/benchmark_core.py`:

1. **Add parameter** to signature (after `hit_rate_threshold`, line 556):
```python
    include_agg: bool = True,
```

2. **After the publisher + benchmark queries succeed and data is validated** (after line 659, after `sorted_bench_ts`), add aggregate feed query:
```python
        # Query aggregate feed (publisher 0) if enabled
        agg_result = None
        agg_channel = None
        if include_agg:
            agg_result, agg_channel = query_aggregate_feed(
                client_lazer, feed_id, date, divisor, publisher_market_filter,
            )
            if agg_result and agg_channel:
                print(f"  Aggregate feed: using channel {agg_channel} ({len(agg_result.result_rows):,} rows)")
```

3. **Add publisher 0 data to the metrics loop** (after line 673, after `publisher_metrics` dict init):
```python
        # Add aggregate feed rows to publisher metrics (as publisher 0)
        if agg_result and agg_result.result_rows:
            all_publishers.add(0)
            publisher_metrics[0] = {
                "squared_errors": [],
                "spreads": [],
                "benchmark_prices": [],
                "pct_diffs": [],
                "diffs": [],
                "signed_pct_diffs": [],
            }
            for _, ts, pub_price, _ in agg_result.result_rows:
                match = find_nearest_benchmark(
                    sorted_bench_ts, benchmark_by_ts, ts, tolerance_seconds
                )
                if match is None:
                    continue
                bench_price, spread = match
                diff = pub_price - bench_price
                pct_diff = abs(diff / bench_price) * 100 if bench_price else 0
                signed_pct_diff = (diff / bench_price) * 100 if bench_price else 0
                metrics = publisher_metrics[0]
                metrics["squared_errors"].append(diff**2)
                if spread is not None:
                    metrics["spreads"].append(spread)
                metrics["benchmark_prices"].append(bench_price)
                metrics["pct_diffs"].append(pct_diff)
                metrics["diffs"].append(diff)
                metrics["signed_pct_diffs"].append(signed_pct_diff)
```

4. **Extract publisher 0 metrics before pass/fail loop, skip in loop** (modify the loop at line 704):

After the per-publisher loop completes (after line 796), extract publisher 0's detail:

```python
        # Extract agg_metrics (publisher 0) — evaluated but excluded from counts
        agg_metrics_result = None
        agg_detail_idx = None
        for idx, detail in enumerate(publisher_details_internal):
            if detail.publisher_id == 0:
                agg_metrics_result = detail
                agg_detail_idx = idx
                break
        if agg_detail_idx is not None:
            publisher_details_internal.pop(agg_detail_idx)
```

Also, in the per-publisher loop (line 704), skip publisher 0 from passing/failing lists. Change the pass/fail append logic (lines 768-771) to:

```python
            if pub_id == 0:
                # Publisher 0 is aggregate — evaluated but not counted
                pass
            elif pub_passes:
                passing_publishers.append(pub_id)
            else:
                failing_publishers.append(pub_id)
```

5. **Set agg_metrics in the return** (line 917, add to BenchmarkResult constructor):
```python
            agg_metrics=agg_metrics_result,
```

**Step 4: Run tests to verify they pass**

```bash
source venv/bin/activate && python3 -m pytest tests/lib/test_benchmark_core.py::TestAggregateInEvaluateFeed -v
```

Expected: All PASS

**Step 5: Run full test suite**

```bash
source venv/bin/activate && python3 -m pytest tests/ -v
```

Expected: All PASS (no regressions)

**Step 6: Commit**

```bash
git add lib/benchmark_core.py tests/lib/test_benchmark_core.py
git commit -m "feat: integrate aggregate feed (publisher 0) into evaluate_feed_two_queries"
```

---

## Task 7: Thread `include_agg` through process_csv in benchmark_core.py

**Files:**
- Modify: `lib/benchmark_core.py` (lines 945-1081 — `process_csv` signature and `evaluate_single` closure)

**Step 1: Write the implementation**

1. Add `include_agg: bool = True` parameter to `process_csv()` signature (after `hit_rate_threshold`, line 957).

2. Pass it through in `evaluate_single()` (line 1028-1040):
```python
        return evaluate_feed_two_queries(
            ...
            hit_rate_threshold=hit_rate_threshold,
            include_agg=include_agg,
        )
```

**Step 2: Run full tests**

```bash
source venv/bin/activate && python3 -m pytest tests/ -v
```

Expected: All PASS

**Step 3: Commit**

```bash
git add lib/benchmark_core.py
git commit -m "feat: thread include_agg through benchmark_core.process_csv"
```

---

## Task 8: Thread `include_agg` through readiness_core.py

**Files:**
- Modify: `lib/readiness_core.py` (lines 568-646 `evaluate_feed_readiness`, lines 692-777 `process_work_items`, lines 780-831 `process_csv`)
- Modify: `lib/readiness_core.py` (lines 228-565 `merge_results` — exclude publisher 0 from readiness buckets)

**Step 1: Write the implementation**

1. Add `include_agg: bool = True` to `evaluate_feed_readiness()` signature (after `tolerance_seconds`, line 582).

2. Pass it through to `evaluate_feed_two_queries()` (line 589-601):
```python
            benchmark_result = evaluate_feed_two_queries(
                ...
                include_detailed=True,
                include_agg=include_agg,
            )
```

3. Add `include_agg: bool = True` to `process_work_items()` signature (after `tolerance_seconds`, line 703).

4. Pass it through to `evaluate_feed_readiness()` (line 718-732):
```python
            return evaluate_feed_readiness(
                ...
                tolerance_seconds=tolerance_seconds,
                include_agg=include_agg,
            )
```

5. Add `include_agg: bool = True` to `process_csv()` signature (after `tolerance_seconds`, line 794).

6. Pass it through to `process_work_items()` call inside `process_csv()`.

7. In `merge_results()` — publisher 0 exclusion. Add at the start of the publisher classification loop (around line 294):
```python
        if publisher_id == 0:
            # Publisher 0 is the aggregate feed — skip from readiness buckets
            continue
```

**Step 2: Run full tests**

```bash
source venv/bin/activate && python3 -m pytest tests/ -v
```

Expected: All PASS

**Step 3: Commit**

```bash
git add lib/readiness_core.py
git commit -m "feat: thread include_agg through readiness_core, exclude pub 0 from readiness"
```

---

## Task 9: Add `--no-agg` CLI flag to quick_benchmark.py

**Files:**
- Modify: `quick_benchmark.py` (argparse + pass to process_csv / evaluate_feed_two_queries)

**Step 1: Write the implementation**

1. Add argument (after `--hit-rate-threshold`, around line 187):
```python
    parser.add_argument(
        "--no-agg",
        action="store_true",
        default=False,
        help="Disable aggregate feed (publisher 0) evaluation",
    )
```

2. In CSV path (around line 273-287), pass to `process_csv()`:
```python
    include_agg=not args.no_agg,
```

3. In single-feed path (around line 322-338), pass to `evaluate_feed_two_queries()`:
```python
    include_agg=not args.no_agg,
```

**Step 2: Verify**

```bash
source venv/bin/activate && python3 quick_benchmark.py --help | grep -A2 "no-agg"
```

Expected: Shows `--no-agg` with help text

**Step 3: Commit**

```bash
git add quick_benchmark.py
git commit -m "feat: add --no-agg flag to quick_benchmark.py"
```

---

## Task 10: Add `--no-agg` CLI flag to feed_readiness.py

**Files:**
- Modify: `feed_readiness.py` (argparse + pass to process_csv / process_work_items)

**Step 1: Write the implementation**

1. Add argument (after `--summary`, around line 176):
```python
    parser.add_argument(
        "--no-agg",
        action="store_true",
        default=False,
        help="Disable aggregate feed (publisher 0) evaluation",
    )
```

2. In CSV path (around line 286-301), pass to `process_csv()`:
```python
    include_agg=not args.no_agg,
```

3. In single-feed path (around line 303-320), pass to `process_work_items()`:
```python
    include_agg=not args.no_agg,
```

**Step 2: Verify**

```bash
source venv/bin/activate && python3 feed_readiness.py --help | grep -A2 "no-agg"
```

Expected: Shows `--no-agg` with help text

**Step 3: Commit**

```bash
git add feed_readiness.py
git commit -m "feat: add --no-agg flag to feed_readiness.py"
```

---

## Task 11: Update output modules for publisher 0

**Files:**
- Modify: `lib/quick_benchmark_output.py` — include publisher 0 in CSV output rows
- Modify: `lib/readiness_output.py` — include publisher 0 in CSV output rows

**Step 1: Understand current output**

Read both output files to understand how `publisher_details` rows are written to CSV. Publisher 0 should already appear if it's in the `publisher_details` list within BenchmarkResult. The `agg_metrics` field holds it separately, so we need to re-add it to the output.

Check if publisher 0's `agg_metrics` needs to be appended back into the CSV write loop, or if keeping it in `publisher_details` and only excluding from counts is cleaner.

**Decision:** Keep publisher 0 in `publisher_details` list (don't pop it in Task 6). Instead, only exclude publisher 0 from `passing_publishers`/`failing_publishers` lists and from readiness bucket classification. This way output modules automatically include it. Update Task 6 implementation accordingly — remove the `pop` logic, and just set `agg_metrics` by reference without removing from the list.

**Step 2: Revise Task 6 approach**

Instead of popping publisher 0 from `publisher_details_internal`, keep it there for output purposes. Set `agg_metrics` by finding it in the list:

```python
        agg_metrics_result = None
        for detail in publisher_details_internal:
            if detail.publisher_id == 0:
                agg_metrics_result = detail
                break
```

No pop needed. Publisher 0 appears in CSV output automatically.

**Step 3: Verify CSV output includes publisher 0**

Run a quick manual check after integration:
```bash
source venv/bin/activate && python3 quick_benchmark.py --feed-id 327 --date 2025-10-06 --mode fx
# Check output CSV for publisher_id=0 row
```

**Step 4: Commit** (if any output changes needed)

```bash
git add lib/quick_benchmark_output.py lib/readiness_output.py
git commit -m "feat: ensure publisher 0 appears in CSV output"
```

---

## Task 12: Run full test suite and pre-commit

**Step 1: Run all tests**

```bash
source venv/bin/activate && python3 -m pytest tests/ -v
```

Expected: All PASS

**Step 2: Run pre-commit on all changed files**

```bash
pre-commit run --files lib/sql_filters.py lib/benchmark_core.py lib/publisher_eval.py lib/models.py lib/readiness_core.py quick_benchmark.py feed_readiness.py tests/lib/test_sql_filters.py tests/lib/test_benchmark_core.py tests/lib/test_models.py
```

Expected: All PASS

**Step 3: Final commit if pre-commit made formatting changes**

```bash
git add -u && git commit -m "style: apply pre-commit formatting"
```

---

## Task 13: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add qualifier filter note**

Under the "Key Gotchas" section, add:
```
- **US equities qualifier filter** — benchmark queries for `us-equities` mode filter out irregular trade conditions (IRGCOND qualifiers) from Datascope data
```

**Step 2: Add aggregate feed note**

Under the "Scripts" table or "Feed Readiness" section, add:
```
- **Aggregate feed (publisher 0)** — `feed_readiness.py` and `quick_benchmark.py` evaluate the aggregated price feed as publisher 0 by default; disable with `--no-agg`
```

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document qualifier filter and aggregate feed features"
```
