"""Core benchmark evaluation logic for Pyth Lazer feeds.

Extracted from quick_benchmark.py to enable reuse by feed_readiness.py
and other scripts without importing the CLI layer.

Functions:
    get_feed_metadata          - Fetch symbol + exponent from ClickHouse
    evaluate_session_for_all_publishers - Extended-hours session evaluation
    evaluate_overnight_for_all_publishers - Overnight (publisher 32) eval
    evaluate_feed_two_queries  - Main entry point for feed-level evaluation
    list_asset_classes_in_csv  - Scan CSV for asset class counts
    process_csv                - CSV batch processor with parallel execution
"""

from __future__ import annotations

import csv
import statistics
import time
from bisect import bisect_left
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from lib.config import (
    get_clients,
    load_config,
    normalize_asset_class,
)
from lib.models import (
    BenchmarkResult,
    ExtendedHoursMetrics,
    OvernightMetrics,
    OVERNIGHT_REFERENCE_PUBLISHER_ID,
    PublisherFeedMetrics,
    TradingSession,
)
from lib.sql_filters import (
    REGULAR_MIN_OBSERVATIONS,
    SESSION_MIN_OBSERVATIONS,
    get_benchmark_columns,
    get_benchmark_table,
    get_extended_hours_filter_sql,
    get_market_hours_filter_sql,
    get_overnight_hours_filter_sql,
)
from lib.statistics import compute_statistical_metrics
from lib.thresholds import passes_benchmark


def find_nearest_benchmark(
    sorted_ts: list,
    benchmark_by_ts: dict,
    target_ts,
    tolerance_seconds: int = 60,
) -> tuple | None:
    """Find nearest benchmark within tolerance. Returns (price, spread) or None."""
    if not sorted_ts:
        return None

    idx = bisect_left(sorted_ts, target_ts)
    candidates = []
    if idx < len(sorted_ts):
        candidates.append(sorted_ts[idx])
    if idx > 0:
        candidates.append(sorted_ts[idx - 1])

    best = min(candidates, key=lambda t: abs((t - target_ts).total_seconds()))
    if abs((best - target_ts).total_seconds()) <= tolerance_seconds:
        return benchmark_by_ts[best]
    return None


def list_asset_classes_in_csv(csv_path: Path) -> dict[str, int]:
    """Scan CSV and return asset class (mode) counts."""

    asset_class_counts: Counter[str] = Counter()
    with open(csv_path) as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not row[0].strip():
                continue
            if len(row) < 3:
                continue
            mode = row[2].strip()
            asset_class_counts[mode] += 1
    return dict(asset_class_counts)


def get_feed_metadata(
    client_lazer, feed_id: int
) -> tuple[Optional[str], Optional[int]]:
    """Get symbol and exponent for a feed from metadata table."""

    query = f"""
        SELECT symbol, exponent
        FROM feeds_metadata_latest
        FINAL
        WHERE pyth_lazer_id = {feed_id}
          AND exponent IS NOT NULL
        ORDER BY updated_at DESC
        LIMIT 1
    """
    result = client_lazer.query(query)
    if result.result_rows:
        return result.result_rows[0][0], result.result_rows[0][1]
    return None, None


def evaluate_session_for_all_publishers(
    client_lazer,
    client_analytics,
    feed_id: int,
    date: str,
    mode: str,
    divisor: float,
    benchmark_table: str,
    session: TradingSession,
    min_observations: int = SESSION_MIN_OBSERVATIONS,
    hit_rate_threshold: float = 95,
    tolerance_seconds: int = 60,
) -> dict[int, ExtendedHoursMetrics]:
    """Evaluate one extended-hours session for all publishers in a feed."""

    price_col, bid_col, ask_col = get_benchmark_columns(mode)
    publisher_time_filter = get_extended_hours_filter_sql(session, date, "publish_time")
    benchmark_time_filter = get_extended_hours_filter_sql(session, date, "date_time")

    publisher_query = f"""
        SELECT
            publisher_id,
            toStartOfSecond(publish_time) AS ts_second,
            avg(price) / {divisor} AS avg_price,
            count() AS update_count
        FROM publisher_updates
        WHERE price_feed_id = {feed_id}
          AND toDate(publish_time) = '{date}'
          AND (status = 'ACCEPTED' OR (status = 'REJECTED' AND status_reason = 'UNAUTHORIZED'))
          AND price IS NOT NULL
          {publisher_time_filter}
        GROUP BY publisher_id, ts_second
        ORDER BY publisher_id, ts_second
    """

    benchmark_query = f"""
        SELECT
            toStartOfSecond(date_time) AS ts_second,
            avg(COALESCE({price_col}, ({bid_col} + {ask_col}) / 2)) AS avg_price,
            avg(CASE WHEN {ask_col} IS NOT NULL AND {bid_col} IS NOT NULL
                     THEN {ask_col} - {bid_col} ELSE NULL END) AS avg_spread
        FROM {benchmark_table}
        WHERE toDate(date_time) = '{date}'
          AND pyth_lazer_id = {feed_id}
          AND ({bid_col} IS NOT NULL AND {ask_col} IS NOT NULL
               OR {price_col} IS NOT NULL)
          {benchmark_time_filter}
        GROUP BY ts_second
        ORDER BY ts_second
    """

    try:
        pub_result = client_lazer.query(publisher_query)
        if not pub_result.result_rows:
            return {}

        all_publishers = {row[0] for row in pub_result.result_rows}

        bench_result = client_analytics.query(benchmark_query)
        if not bench_result.result_rows:
            return {
                pub_id: ExtendedHoursMetrics(
                    session=session,
                    n_observations=0,
                    rmse=None,
                    mean_spread=None,
                    rmse_over_spread=None,
                    nrmse=None,
                    hit_rate=None,
                    benchmark_price_range=None,
                    passes=False,
                    error="No benchmark data for session",
                )
                for pub_id in all_publishers
            }

        benchmark_by_ts = {
            row[0]: (row[1], row[2])
            for row in bench_result.result_rows
            if row[1] is not None
        }
        sorted_bench_ts = sorted(benchmark_by_ts.keys())

        publisher_metrics: dict[int, dict[str, list[float]]] = {
            pub_id: {
                "squared_errors": [],
                "spreads": [],
                "pct_diffs": [],
                "benchmark_prices": [],
            }
            for pub_id in all_publishers
        }

        for pub_id, ts, pub_price, _ in pub_result.result_rows:
            match = find_nearest_benchmark(
                sorted_bench_ts, benchmark_by_ts, ts, tolerance_seconds
            )
            if match is None:
                continue

            bench_price, spread = match
            diff = pub_price - bench_price
            pct_diff = abs(diff / bench_price) * 100 if bench_price else 0

            metrics = publisher_metrics[pub_id]
            metrics["squared_errors"].append(diff**2)
            if spread is not None:
                metrics["spreads"].append(spread)
            metrics["pct_diffs"].append(pct_diff)
            metrics["benchmark_prices"].append(bench_price)

        results: dict[int, ExtendedHoursMetrics] = {}
        session_name = session.value

        for pub_id in sorted(all_publishers):
            metrics = publisher_metrics[pub_id]
            n_observations = len(metrics["squared_errors"])

            if n_observations < min_observations:
                error_msg = (
                    "No matched benchmark observations for session"
                    if n_observations == 0
                    else f"Insufficient observations ({n_observations} < {min_observations})"
                )
                results[pub_id] = ExtendedHoursMetrics(
                    session=session,
                    n_observations=n_observations,
                    rmse=None,
                    mean_spread=None,
                    rmse_over_spread=None,
                    nrmse=None,
                    hit_rate=None,
                    benchmark_price_range=None,
                    passes=False,
                    error=error_msg,
                )
                continue

            rmse = (sum(metrics["squared_errors"]) / n_observations) ** 0.5
            n_spreads = len(metrics["spreads"])
            mean_spread = sum(metrics["spreads"]) / n_spreads if n_spreads > 0 else None

            benchmark_range = max(metrics["benchmark_prices"]) - min(
                metrics["benchmark_prices"]
            )
            nrmse = rmse / benchmark_range if benchmark_range > 0 else None

            hits_within_10bps = sum(1 for pct in metrics["pct_diffs"] if pct <= 0.1)
            hit_rate = (hits_within_10bps / n_observations) * 100

            rmse_over_spread = (
                rmse / mean_spread if mean_spread and mean_spread > 0 else None
            )

            pub_passes = passes_benchmark(
                nrmse=nrmse,
                hit_rate=hit_rate,
                session=session_name,
                mode=mode,
                hit_rate_override=hit_rate_threshold
                if hit_rate_threshold != 95
                else None,
            )

            results[pub_id] = ExtendedHoursMetrics(
                session=session,
                n_observations=n_observations,
                rmse=rmse,
                mean_spread=mean_spread,
                rmse_over_spread=rmse_over_spread,
                nrmse=nrmse,
                hit_rate=hit_rate,
                benchmark_price_range=benchmark_range,
                passes=pub_passes,
                error=None,
            )

        return results

    except Exception as e:
        return (
            {
                pub_id: ExtendedHoursMetrics(
                    session=session,
                    n_observations=0,
                    rmse=None,
                    mean_spread=None,
                    rmse_over_spread=None,
                    nrmse=None,
                    hit_rate=None,
                    benchmark_price_range=None,
                    passes=False,
                    error=str(e),
                )
                for pub_id in all_publishers
            }
            if "all_publishers" in locals()
            else {}
        )


def evaluate_overnight_for_all_publishers(
    client_lazer,
    feed_id: int,
    date: str,
    divisor: float,
    min_observations: int = SESSION_MIN_OBSERVATIONS,
    reference_publisher_id: int = OVERNIGHT_REFERENCE_PUBLISHER_ID,
    hit_rate_threshold: float = 95,
    tolerance_seconds: int = 60,
) -> dict[int, OvernightMetrics]:
    """Evaluate all publishers against overnight reference publisher 32."""

    overnight_filter = get_overnight_hours_filter_sql(date, "publish_time")

    publisher_query = f"""
        SELECT
            publisher_id,
            toStartOfSecond(publish_time) AS ts_second,
            avg(price) / {divisor} AS avg_price,
            count() AS update_count
        FROM publisher_updates
        WHERE price_feed_id = {feed_id}
          AND toDate(publish_time) >= '{date}'
          AND (status = 'ACCEPTED' OR (status = 'REJECTED' AND status_reason = 'UNAUTHORIZED'))
          AND price IS NOT NULL
          {overnight_filter}
        GROUP BY publisher_id, ts_second
        ORDER BY publisher_id, ts_second
    """

    reference_query = f"""
        SELECT
            toStartOfSecond(publish_time) AS ts_second,
            avg(price) / {divisor} AS avg_price,
            avg(best_ask_price - best_bid_price) / {divisor} AS avg_spread,
            count() AS update_count
        FROM publisher_updates
        WHERE price_feed_id = {feed_id}
          AND publisher_id = {reference_publisher_id}
          AND toDate(publish_time) >= '{date}'
          AND (status = 'ACCEPTED' OR (status = 'REJECTED' AND status_reason = 'UNAUTHORIZED'))
          AND price IS NOT NULL
          {overnight_filter}
        GROUP BY ts_second
        ORDER BY ts_second
    """

    try:
        pub_result = client_lazer.query(publisher_query)
        if not pub_result.result_rows:
            return {}

        all_publishers = {row[0] for row in pub_result.result_rows}

        ref_result = client_lazer.query(reference_query)
        if not ref_result.result_rows:
            return {
                pub_id: OvernightMetrics(
                    n_observations=0,
                    n_reference_observations=0,
                    rmse=None,
                    mean_spread=None,
                    rmse_over_spread=None,
                    nrmse=None,
                    hit_rate=None,
                    reference_price_range=None,
                    passes=False,
                    reference_publisher_id=reference_publisher_id,
                    error=(
                        f"Cannot evaluate publisher {pub_id} against itself as reference"
                        if pub_id == reference_publisher_id
                        else f"No reference publisher {reference_publisher_id} data for overnight session"
                    ),
                )
                for pub_id in all_publishers
            }

        reference_by_ts: dict = {}
        for ts, ref_price, ref_spread, _ in ref_result.result_rows:
            if ref_price is not None:
                spread = (
                    ref_spread if ref_spread is not None and ref_spread > 0 else None
                )
                reference_by_ts[ts] = (ref_price, spread)

        sorted_ref_ts = sorted(reference_by_ts.keys())
        n_reference_observations = len(reference_by_ts)

        publisher_metrics: dict[int, dict[str, list[float]]] = {
            pub_id: {
                "squared_errors": [],
                "spreads": [],
                "pct_diffs": [],
                "reference_prices": [],
            }
            for pub_id in all_publishers
            if pub_id != reference_publisher_id
        }

        for pub_id, ts, pub_price, _ in pub_result.result_rows:
            if pub_id == reference_publisher_id:
                continue
            match = find_nearest_benchmark(
                sorted_ref_ts, reference_by_ts, ts, tolerance_seconds
            )
            if match is None:
                continue

            ref_price, spread = match
            diff = pub_price - ref_price
            pct_diff = abs(diff / ref_price) * 100 if ref_price else 0

            metrics = publisher_metrics[pub_id]
            metrics["squared_errors"].append(diff**2)
            if spread is not None:
                metrics["spreads"].append(spread)
            metrics["pct_diffs"].append(pct_diff)
            metrics["reference_prices"].append(ref_price)

        results: dict[int, OvernightMetrics] = {}
        for pub_id in sorted(all_publishers):
            if pub_id == reference_publisher_id:
                results[pub_id] = OvernightMetrics(
                    n_observations=0,
                    n_reference_observations=n_reference_observations,
                    rmse=None,
                    mean_spread=None,
                    rmse_over_spread=None,
                    nrmse=None,
                    hit_rate=None,
                    reference_price_range=None,
                    passes=False,
                    reference_publisher_id=reference_publisher_id,
                    error=f"Cannot evaluate publisher {pub_id} against itself as reference",
                )
                continue

            metrics = publisher_metrics.get(pub_id)
            if metrics is None:
                continue

            n_observations = len(metrics["squared_errors"])

            if n_observations < min_observations:
                error_msg = (
                    "No matched reference observations for overnight session"
                    if n_observations == 0
                    else f"Insufficient matched observations ({n_observations} < {min_observations})"
                )
                results[pub_id] = OvernightMetrics(
                    n_observations=n_observations,
                    n_reference_observations=n_reference_observations,
                    rmse=None,
                    mean_spread=None,
                    rmse_over_spread=None,
                    nrmse=None,
                    hit_rate=None,
                    reference_price_range=None,
                    passes=False,
                    reference_publisher_id=reference_publisher_id,
                    error=error_msg,
                )
                continue

            rmse = (sum(metrics["squared_errors"]) / n_observations) ** 0.5
            mean_spread = (
                sum(metrics["spreads"]) / len(metrics["spreads"])
                if metrics["spreads"]
                else None
            )

            reference_range = max(metrics["reference_prices"]) - min(
                metrics["reference_prices"]
            )
            nrmse = rmse / reference_range if reference_range > 0 else None

            hits_within_10bps = sum(1 for pct in metrics["pct_diffs"] if pct <= 0.1)
            hit_rate = (hits_within_10bps / n_observations) * 100

            rmse_over_spread = (
                rmse / mean_spread if mean_spread and mean_spread > 0 else None
            )

            pub_passes = passes_benchmark(
                nrmse=nrmse,
                hit_rate=hit_rate,
                session="overnight",
                mode="us-equities",
                hit_rate_override=hit_rate_threshold
                if hit_rate_threshold != 95
                else None,
            )

            results[pub_id] = OvernightMetrics(
                n_observations=n_observations,
                n_reference_observations=n_reference_observations,
                rmse=rmse,
                mean_spread=mean_spread,
                rmse_over_spread=rmse_over_spread,
                nrmse=nrmse,
                hit_rate=hit_rate,
                reference_price_range=reference_range,
                passes=pub_passes,
                reference_publisher_id=reference_publisher_id,
                error=None,
            )

        return results

    except Exception as e:
        return (
            {
                pub_id: OvernightMetrics(
                    n_observations=0,
                    n_reference_observations=0,
                    rmse=None,
                    mean_spread=None,
                    rmse_over_spread=None,
                    nrmse=None,
                    hit_rate=None,
                    reference_price_range=None,
                    passes=False,
                    reference_publisher_id=reference_publisher_id,
                    error=str(e),
                )
                for pub_id in all_publishers
            }
            if "all_publishers" in locals()
            else {}
        )


def evaluate_feed_two_queries(
    client_lazer,
    client_analytics,
    feed_id: int,
    date: str,
    mode: str,
    target_pub_count: int = 4,
    tolerance_seconds: int = 60,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    skip_scipy_tests: bool = False,
    include_detailed: bool = False,
    hit_rate_threshold: float = 95,
) -> BenchmarkResult:
    """Evaluate a feed across all publishers using aggregated one-second buckets."""

    start_time = time.time()
    mode = normalize_asset_class(mode)

    symbol, exponent = get_feed_metadata(client_lazer, feed_id)
    if exponent is None:
        return BenchmarkResult(
            feed_id=feed_id,
            date=date,
            mode=mode,
            symbol=None,
            ready=False,
            target_pub_count=target_pub_count,
            passing_pub_count=0,
            failing_pub_count=0,
            passing_publishers=[],
            failing_publishers=[],
            error=f"Feed metadata not found for feed_id {feed_id}",
            execution_time_ms=int((time.time() - start_time) * 1000),
        )

    divisor = 10 ** abs(exponent)
    benchmark_table = get_benchmark_table(mode, symbol)
    price_col, bid_col, ask_col = get_benchmark_columns(mode)

    publisher_market_filter = get_market_hours_filter_sql(mode, date, "publish_time")
    benchmark_market_filter = get_market_hours_filter_sql(mode, date, "date_time")

    publisher_query = f"""
        SELECT
            publisher_id,
            toStartOfSecond(publish_time) AS ts_second,
            avg(price) / {divisor} AS avg_price,
            count() AS update_count
        FROM publisher_updates
        WHERE price_feed_id = {feed_id}
          AND toDate(publish_time) = '{date}'
          AND (status = 'ACCEPTED' OR (status = 'REJECTED' AND status_reason = 'UNAUTHORIZED'))
          AND price IS NOT NULL
          {publisher_market_filter}
        GROUP BY publisher_id, ts_second
        ORDER BY publisher_id, ts_second
    """

    benchmark_query = f"""
        SELECT
            toStartOfSecond(date_time) AS ts_second,
            avg(COALESCE({price_col}, ({bid_col} + {ask_col}) / 2)) AS avg_price,
            avg(CASE WHEN {ask_col} IS NOT NULL AND {bid_col} IS NOT NULL
                     THEN {ask_col} - {bid_col} ELSE NULL END) AS avg_spread
        FROM {benchmark_table}
        WHERE toDate(date_time) = '{date}'
          AND pyth_lazer_id = {feed_id}
          AND ({bid_col} IS NOT NULL AND {ask_col} IS NOT NULL
               OR {price_col} IS NOT NULL)
          {benchmark_market_filter}
        GROUP BY ts_second
        ORDER BY ts_second
    """

    try:
        pub_result = client_lazer.query(publisher_query)
        bench_result = client_analytics.query(benchmark_query)

        if not pub_result.result_rows:
            return BenchmarkResult(
                feed_id=feed_id,
                date=date,
                mode=mode,
                symbol=symbol,
                ready=False,
                target_pub_count=target_pub_count,
                passing_pub_count=0,
                failing_pub_count=0,
                passing_publishers=[],
                failing_publishers=[],
                error="No publisher data found",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        if not bench_result.result_rows:
            return BenchmarkResult(
                feed_id=feed_id,
                date=date,
                mode=mode,
                symbol=symbol,
                ready=False,
                target_pub_count=target_pub_count,
                passing_pub_count=0,
                failing_pub_count=0,
                passing_publishers=[],
                failing_publishers=[],
                error="No benchmark data found",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        benchmark_by_ts = {
            row[0]: (row[1], row[2])
            for row in bench_result.result_rows
            if row[1] is not None
        }
        sorted_bench_ts = sorted(benchmark_by_ts.keys())

        all_publishers = {row[0] for row in pub_result.result_rows}
        publisher_metrics: dict[int, dict[str, list[float]]] = {
            pub_id: {
                "squared_errors": [],
                "spreads": [],
                "benchmark_prices": [],
                "pct_diffs": [],
                "diffs": [],
                "signed_pct_diffs": [],
            }
            for pub_id in all_publishers
        }

        for pub_id, ts, pub_price, _ in pub_result.result_rows:
            match = find_nearest_benchmark(
                sorted_bench_ts, benchmark_by_ts, ts, tolerance_seconds
            )
            if match is None:
                continue

            bench_price, spread = match
            diff = pub_price - bench_price

            pct_diff = abs(diff / bench_price) * 100 if bench_price else 0
            signed_pct_diff = (diff / bench_price) * 100 if bench_price else 0

            metrics = publisher_metrics[pub_id]
            metrics["squared_errors"].append(diff**2)
            if spread is not None:
                metrics["spreads"].append(spread)
            metrics["benchmark_prices"].append(bench_price)
            metrics["pct_diffs"].append(pct_diff)
            metrics["diffs"].append(diff)
            metrics["signed_pct_diffs"].append(signed_pct_diff)

        passing_publishers: list[int] = []
        failing_publishers: list[int] = []
        publisher_details_internal: list[PublisherFeedMetrics] = []

        # Determine hit_rate_override for passes_benchmark
        hr_override = hit_rate_threshold if hit_rate_threshold != 95 else None

        for pub_id in sorted(all_publishers):
            metrics = publisher_metrics[pub_id]
            n_observations = len(metrics["squared_errors"])

            if n_observations < REGULAR_MIN_OBSERVATIONS:
                error_msg = (
                    "No matched benchmark observations"
                    if n_observations == 0
                    else f"Insufficient observations ({n_observations} < {REGULAR_MIN_OBSERVATIONS})"
                )
                failing_publishers.append(pub_id)
                publisher_details_internal.append(
                    PublisherFeedMetrics(
                        publisher_id=pub_id,
                        n_observations=n_observations,
                        passes=False,
                        error=error_msg,
                    )
                )
                continue

            rmse = (sum(metrics["squared_errors"]) / n_observations) ** 0.5
            n_spreads = len(metrics["spreads"])
            mean_spread = sum(metrics["spreads"]) / n_spreads if n_spreads > 0 else None

            benchmark_range = max(metrics["benchmark_prices"]) - min(
                metrics["benchmark_prices"]
            )
            nrmse = rmse / benchmark_range if benchmark_range > 0 else None

            hits_within_10bps = sum(1 for pct in metrics["pct_diffs"] if pct <= 0.1)
            hit_rate = (hits_within_10bps / n_observations) * 100

            rmse_over_spread = (
                rmse / mean_spread if mean_spread and mean_spread > 0 else None
            )

            pub_passes = passes_benchmark(
                nrmse=nrmse,
                hit_rate=hit_rate,
                session="regular",
                mode=mode,
                hit_rate_override=hr_override,
            )

            if skip_scipy_tests:
                stat_metrics = {
                    "mean_diff": None,
                    "std_diff": None,
                    "mean_pct_diff": None,
                    "std_pct_diff": None,
                    "mae": None,
                    "t_statistic": None,
                    "t_pvalue": None,
                    "wilcoxon_statistic": None,
                    "wilcoxon_pvalue": None,
                    "normality_pvalue": None,
                    "mean_abs_z_score": None,
                }
            else:
                stat_metrics = compute_statistical_metrics(
                    metrics["diffs"], metrics["signed_pct_diffs"]
                )

            if pub_passes:
                passing_publishers.append(pub_id)
            else:
                failing_publishers.append(pub_id)

            publisher_details_internal.append(
                PublisherFeedMetrics(
                    publisher_id=pub_id,
                    n_observations=n_observations,
                    passes=pub_passes,
                    nrmse=nrmse,
                    hit_rate=hit_rate,
                    rmse=rmse,
                    mean_spread=mean_spread,
                    rmse_over_spread=rmse_over_spread,
                    benchmark_price_range=benchmark_range,
                    mean_diff=stat_metrics["mean_diff"],
                    std_diff=stat_metrics["std_diff"],
                    mean_pct_diff=stat_metrics["mean_pct_diff"],
                    std_pct_diff=stat_metrics["std_pct_diff"],
                    mae=stat_metrics["mae"],
                    t_statistic=stat_metrics["t_statistic"],
                    t_pvalue=stat_metrics["t_pvalue"],
                    wilcoxon_statistic=stat_metrics["wilcoxon_statistic"],
                    wilcoxon_pvalue=stat_metrics["wilcoxon_pvalue"],
                    normality_pvalue=stat_metrics["normality_pvalue"],
                    mean_abs_z_score=stat_metrics["mean_abs_z_score"],
                )
            )

        details_by_pub = {
            detail.publisher_id: detail for detail in publisher_details_internal
        }

        premarket_passing_count: Optional[int] = None
        premarket_failing_count: Optional[int] = None
        afterhours_passing_count: Optional[int] = None
        afterhours_failing_count: Optional[int] = None
        overnight_passing_count: Optional[int] = None
        overnight_failing_count: Optional[int] = None
        overnight_reference_publisher_id: Optional[int] = None

        if include_extended_hours and mode == "us-equities":
            premarket_results = evaluate_session_for_all_publishers(
                client_lazer,
                client_analytics,
                feed_id,
                date,
                mode,
                divisor,
                benchmark_table,
                session=TradingSession.PREMARKET,
                min_observations=SESSION_MIN_OBSERVATIONS,
                hit_rate_threshold=hit_rate_threshold,
            )
            afterhours_results = evaluate_session_for_all_publishers(
                client_lazer,
                client_analytics,
                feed_id,
                date,
                mode,
                divisor,
                benchmark_table,
                session=TradingSession.AFTERHOURS,
                min_observations=SESSION_MIN_OBSERVATIONS,
                hit_rate_threshold=hit_rate_threshold,
            )

            premarket_passing_count = sum(
                1 for m in premarket_results.values() if not m.error and m.passes
            )
            premarket_failing_count = sum(
                1 for m in premarket_results.values() if not m.error and not m.passes
            )
            afterhours_passing_count = sum(
                1 for m in afterhours_results.values() if not m.error and m.passes
            )
            afterhours_failing_count = sum(
                1 for m in afterhours_results.values() if not m.error and not m.passes
            )

            for pub_id, metrics in premarket_results.items():
                detail = details_by_pub.get(pub_id)
                if detail:
                    detail.premarket_metrics = metrics

            for pub_id, metrics in afterhours_results.items():
                detail = details_by_pub.get(pub_id)
                if detail:
                    detail.afterhours_metrics = metrics

        if include_overnight and mode == "us-equities":
            overnight_results = evaluate_overnight_for_all_publishers(
                client_lazer,
                feed_id,
                date,
                divisor,
                min_observations=SESSION_MIN_OBSERVATIONS,
                reference_publisher_id=OVERNIGHT_REFERENCE_PUBLISHER_ID,
                hit_rate_threshold=hit_rate_threshold,
            )

            overnight_passing_count = sum(
                1 for m in overnight_results.values() if not m.error and m.passes
            )
            overnight_failing_count = sum(
                1 for m in overnight_results.values() if not m.error and not m.passes
            )
            overnight_reference_publisher_id = OVERNIGHT_REFERENCE_PUBLISHER_ID

            for pub_id, metrics in overnight_results.items():
                detail = details_by_pub.get(pub_id)
                if detail:
                    detail.overnight_metrics = metrics

        nrmse_values = [
            d.nrmse
            for d in publisher_details_internal
            if d.nrmse is not None and not d.error
        ]
        hit_rate_values = [
            d.hit_rate
            for d in publisher_details_internal
            if d.hit_rate is not None and not d.error
        ]

        median_nrmse = statistics.median(nrmse_values) if nrmse_values else None
        median_hit_rate = (
            statistics.median(hit_rate_values) if hit_rate_values else None
        )

        ready = len(passing_publishers) >= target_pub_count

        return BenchmarkResult(
            feed_id=feed_id,
            date=date,
            mode=mode,
            symbol=symbol,
            ready=ready,
            target_pub_count=target_pub_count,
            passing_pub_count=len(passing_publishers),
            failing_pub_count=len(failing_publishers),
            passing_publishers=sorted(passing_publishers),
            failing_publishers=sorted(failing_publishers),
            median_nrmse=median_nrmse,
            median_hit_rate=median_hit_rate,
            publisher_details=publisher_details_internal,
            premarket_passing_count=premarket_passing_count,
            premarket_failing_count=premarket_failing_count,
            afterhours_passing_count=afterhours_passing_count,
            afterhours_failing_count=afterhours_failing_count,
            overnight_passing_count=overnight_passing_count,
            overnight_failing_count=overnight_failing_count,
            overnight_reference_publisher_id=overnight_reference_publisher_id,
            execution_time_ms=int((time.time() - start_time) * 1000),
        )

    except Exception as e:
        return BenchmarkResult(
            feed_id=feed_id,
            date=date,
            mode=mode,
            symbol=symbol,
            ready=False,
            target_pub_count=target_pub_count,
            passing_pub_count=0,
            failing_pub_count=0,
            passing_publishers=[],
            failing_publishers=[],
            error=str(e),
            execution_time_ms=int((time.time() - start_time) * 1000),
        )


def process_csv(
    csv_path: Path,
    output_path: Path,
    target_pub_count: int,
    max_workers: int,
    include_asset_classes: list[str] | None = None,
    exclude_asset_classes: list[str] | None = None,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    skip_scipy_tests: bool = False,
    include_detailed: bool = False,
    feed_id_filter: set[int] | None = None,
    hit_rate_threshold: float = 95,
    write_results_fn=None,
) -> list[BenchmarkResult]:
    """Process feeds from CSV file with parallel execution.

    Args:
        write_results_fn: Callable to write CSV output. If None, results are
            returned without writing. The caller (quick_benchmark.py) passes
            its own ``write_results_csv`` function.
    """

    config = load_config()

    include_normalized = None
    if include_asset_classes:
        include_normalized = {normalize_asset_class(ac) for ac in include_asset_classes}

    exclude_normalized = set()
    if exclude_asset_classes:
        exclude_normalized = {normalize_asset_class(ac) for ac in exclude_asset_classes}

    feeds_to_process = []
    skipped_by_filter = 0
    with open(csv_path) as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not row[0].strip():
                continue
            if len(row) < 3:
                print(f"Warning: Skipping incomplete row: {row}")
                continue

            feed_id_str, date, mode = row[0].strip(), row[1].strip(), row[2].strip()
            normalized_mode = normalize_asset_class(mode)

            if include_normalized and normalized_mode not in include_normalized:
                skipped_by_filter += 1
                continue
            if normalized_mode in exclude_normalized:
                skipped_by_filter += 1
                continue

            feeds_to_process.append((int(feed_id_str), date, mode))

    if skipped_by_filter > 0:
        print(f"Filtered out {skipped_by_filter} feeds by asset class")

    skipped_by_feed_id = 0
    if feed_id_filter is not None:
        filtered = []
        for feed_tuple in feeds_to_process:
            if feed_tuple[0] in feed_id_filter:
                filtered.append(feed_tuple)
            else:
                skipped_by_feed_id += 1
        feeds_to_process = filtered

    if skipped_by_feed_id > 0:
        keep_ids = ", ".join(str(x) for x in sorted(feed_id_filter))
        print(
            f"Filtered out {skipped_by_feed_id} feeds by feed ID "
            f"(kept {len(feeds_to_process)} matching: {keep_ids})"
        )

    print(f"Processing {len(feeds_to_process)} feeds with {max_workers} workers...")

    results = []

    def evaluate_single(args):
        feed_id, date, mode = args
        client_lazer, client_analytics = get_clients(config)
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
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(evaluate_single, args): args for args in feeds_to_process
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

            status = "READY" if result.ready else "NOT READY"
            if result.error:
                status = f"ERROR: {result.error[:50]}"

            nrmse_str = (
                f"{result.median_nrmse:.4f}"
                if result.median_nrmse is not None
                else "N/A"
            )
            hit_rate_str = (
                f"{result.median_hit_rate:.1f}%"
                if result.median_hit_rate is not None
                else "N/A"
            )

            print(
                f"  [{result.execution_time_ms:>5}ms] Feed {result.feed_id} ({result.date}): "
                f"{status} - {result.passing_pub_count} passing, {result.failing_pub_count} failing, "
                f"median_nrmse={nrmse_str}, median_hit_rate={hit_rate_str}"
            )

    if write_results_fn is not None:
        write_results_fn(
            results,
            output_path,
            include_extended_hours=include_extended_hours,
            include_overnight=include_overnight,
            include_detailed=include_detailed,
        )

    return results
