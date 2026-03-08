"""Core single-publisher benchmark evaluation logic.

Extracted from publisher_benchmark.py. Evaluates one publisher at a time
against benchmark data (Datascope) or a reference publisher (overnight).

Functions:
    get_symbols_for_feeds       - Batch symbol lookup for feed IDs
    evaluate_session_metrics    - Single-publisher extended-hours session
    evaluate_overnight_session  - Single-publisher overnight vs publisher 32
    evaluate_publisher_feed     - Main entry: one publisher, one feed, one date
    process_csv                 - CSV batch processor (single publisher)
    extract_publisher_id_from_filename - Parse publisher_{id}_feeds.csv
"""

from __future__ import annotations

import csv
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from lib.benchmark_core import get_feed_metadata
from lib.config import (
    get_clients,
    load_config,
    normalize_asset_class,
)
from lib.models import (
    ExtendedHoursMetrics,
    OvernightMetrics,
    OVERNIGHT_REFERENCE_PUBLISHER_ID,
    PublisherBenchmarkResult,
    TradingSession,
)
from lib.sql_filters import (
    get_benchmark_columns,
    get_benchmark_table,
    get_extended_hours_filter_sql,
    get_market_hours_filter_sql,
    get_overnight_hours_filter_sql,
    get_qualifier_filter_sql,
)
from lib.statistics import compute_statistical_metrics
from lib.thresholds import passes_benchmark


def extract_publisher_id_from_filename(filename: str) -> Optional[int]:
    """Extract publisher ID from filename pattern publisher_{id}_feeds.csv."""
    match = re.match(r"publisher_(\d+)_feeds\.csv", filename)
    if match:
        return int(match.group(1))
    return None


def get_symbols_for_feeds(
    client_lazer, feed_ids: list[int]
) -> dict[int, Optional[str]]:
    """Batch query symbols for multiple feed IDs."""
    if not feed_ids:
        return {}

    feed_ids_str = ",".join(map(str, feed_ids))
    query = f"""
        SELECT pyth_lazer_id, symbol
        FROM feeds_metadata_latest
        FINAL
        WHERE pyth_lazer_id IN ({feed_ids_str})
    """
    result = client_lazer.query(query)
    return {row[0]: row[1] for row in result.result_rows}


def evaluate_session_metrics(
    client_lazer,
    client_analytics,
    publisher_id: int,
    feed_id: int,
    date: str,
    mode: str,
    divisor: float,
    benchmark_table: str,
    publisher_time_filter: str,
    benchmark_time_filter: str,
    min_observations: int = 100,
) -> tuple[
    int,
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[str],
]:
    """Evaluate metrics for a single publisher in a single trading session.

    Returns:
        Tuple of (n_observations, rmse, mean_spread, rmse_over_spread,
                  nrmse, hit_rate, benchmark_price_range, error)
    """
    price_col, bid_col, ask_col = get_benchmark_columns(mode)
    qualifier_filter = get_qualifier_filter_sql(mode)

    publisher_query = f"""
        SELECT
            toStartOfSecond(publish_time) AS ts_second,
            avg(price) / {divisor} AS avg_price,
            count() AS update_count
        FROM publisher_updates
        WHERE price_feed_id = {feed_id}
          AND publisher_id = {publisher_id}
          AND toDate(publish_time) = '{date}'
          AND (status = 'ACCEPTED' OR (status = 'REJECTED' AND status_reason = 'UNAUTHORIZED'))
          AND price IS NOT NULL
          {publisher_time_filter}
        GROUP BY ts_second
        ORDER BY ts_second
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
          {qualifier_filter}
        GROUP BY ts_second
        ORDER BY ts_second
    """

    try:
        pub_result = client_lazer.query(publisher_query)
        bench_result = client_analytics.query(benchmark_query)

        if not pub_result.result_rows:
            return (
                0,
                None,
                None,
                None,
                None,
                None,
                None,
                "No publisher data for session",
            )

        if not bench_result.result_rows:
            return (
                0,
                None,
                None,
                None,
                None,
                None,
                None,
                "No benchmark data for session",
            )

        benchmark_by_ts = {
            row[0]: (row[1], row[2])
            for row in bench_result.result_rows
            if row[1] is not None
        }

        squared_errors = []
        spreads = []
        pct_diffs = []
        benchmark_prices = []

        for row in pub_result.result_rows:
            ts, pub_price, _ = row
            if ts not in benchmark_by_ts:
                continue
            bench_price, spread = benchmark_by_ts[ts]
            diff = pub_price - bench_price
            pct_diff = abs(diff / bench_price) * 100

            squared_errors.append(diff**2)
            if spread is not None:
                spreads.append(spread)
            pct_diffs.append(pct_diff)
            benchmark_prices.append(bench_price)

        n_observations = len(squared_errors)

        if n_observations < min_observations:
            return (
                n_observations,
                None,
                None,
                None,
                None,
                None,
                None,
                f"Insufficient observations ({n_observations} < {min_observations})",
            )

        rmse = (sum(squared_errors) / n_observations) ** 0.5
        n_spreads = len(spreads)
        mean_spread = sum(spreads) / n_spreads if n_spreads > 0 else None

        benchmark_range = max(benchmark_prices) - min(benchmark_prices)
        nrmse = rmse / benchmark_range if benchmark_range > 0 else None

        hits_within_10bps = sum(1 for pct in pct_diffs if pct <= 0.1)
        hit_rate = (hits_within_10bps / n_observations) * 100

        rmse_over_spread = (
            rmse / mean_spread if mean_spread and mean_spread > 0 else None
        )

        return (
            n_observations,
            rmse,
            mean_spread,
            rmse_over_spread,
            nrmse,
            hit_rate,
            benchmark_range,
            None,
        )

    except Exception as e:
        return (0, None, None, None, None, None, None, str(e))


def evaluate_overnight_session(
    client_lazer,
    publisher_id: int,
    feed_id: int,
    date: str,
    divisor: float,
    min_observations: int = 50,
    reference_publisher_id: int = OVERNIGHT_REFERENCE_PUBLISHER_ID,
    hit_rate_threshold: float = 95,
) -> OvernightMetrics:
    """Evaluate a publisher's overnight session data against publisher 32."""
    overnight_filter = get_overnight_hours_filter_sql(date, "publish_time")

    publisher_query = f"""
        SELECT
            toStartOfSecond(publish_time) AS ts_second,
            avg(price) / {divisor} AS avg_price,
            count() AS update_count
        FROM publisher_updates
        WHERE price_feed_id = {feed_id}
          AND publisher_id = {publisher_id}
          AND toDate(publish_time) >= '{date}'
          AND (status = 'ACCEPTED' OR (status = 'REJECTED' AND status_reason = 'UNAUTHORIZED'))
          AND price IS NOT NULL
          {overnight_filter}
        GROUP BY ts_second
        ORDER BY ts_second
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
        ref_result = client_lazer.query(reference_query)

        if not pub_result.result_rows:
            return OvernightMetrics(
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
                error=f"No publisher {publisher_id} data for overnight session",
            )

        if not ref_result.result_rows:
            return OvernightMetrics(
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
                error=f"No reference publisher {reference_publisher_id} data for overnight session",
            )

        reference_by_ts = {}
        for row in ref_result.result_rows:
            ts, ref_price, ref_spread, _ = row
            if ref_price is not None:
                spread = (
                    ref_spread if ref_spread is not None and ref_spread > 0 else None
                )
                reference_by_ts[ts] = (ref_price, spread)

        n_reference_observations = len(reference_by_ts)

        squared_errors = []
        spreads = []
        pct_diffs = []
        reference_prices = []

        for row in pub_result.result_rows:
            ts, pub_price, _ = row
            if ts not in reference_by_ts:
                continue

            ref_price, spread = reference_by_ts[ts]
            diff = pub_price - ref_price
            pct_diff = abs(diff / ref_price) * 100 if ref_price != 0 else 0

            squared_errors.append(diff**2)
            if spread is not None:
                spreads.append(spread)
            pct_diffs.append(pct_diff)
            reference_prices.append(ref_price)

        n_observations = len(squared_errors)

        if n_observations < min_observations:
            return OvernightMetrics(
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
                error=f"Insufficient matched observations ({n_observations} < {min_observations})",
            )

        rmse = (sum(squared_errors) / n_observations) ** 0.5
        mean_spread = sum(spreads) / len(spreads) if spreads else None

        reference_range = max(reference_prices) - min(reference_prices)
        nrmse = rmse / reference_range if reference_range > 0 else None

        hits_within_10bps = sum(1 for pct in pct_diffs if pct <= 0.1)
        hit_rate = (hits_within_10bps / n_observations) * 100

        rmse_over_spread = (
            rmse / mean_spread if mean_spread and mean_spread > 0 else None
        )

        overnight_passes = passes_benchmark(
            nrmse=nrmse,
            hit_rate=hit_rate,
            session="overnight",
            mode="us-equities",
            hit_rate_override=hit_rate_threshold if hit_rate_threshold != 95 else None,
        )

        return OvernightMetrics(
            n_observations=n_observations,
            n_reference_observations=n_reference_observations,
            rmse=rmse,
            mean_spread=mean_spread,
            rmse_over_spread=rmse_over_spread,
            nrmse=nrmse,
            hit_rate=hit_rate,
            reference_price_range=reference_range,
            passes=overnight_passes,
            reference_publisher_id=reference_publisher_id,
            error=None,
        )

    except Exception as e:
        return OvernightMetrics(
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


def evaluate_publisher_feed(
    client_lazer,
    client_analytics,
    publisher_id: int,
    feed_id: int,
    date: str,
    mode: str,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    skip_scipy_tests: bool = False,
    hit_rate_threshold: float = 95,
) -> PublisherBenchmarkResult:
    """Evaluate a single publisher's data quality for one feed.

    Faster than feed-level evaluation because it queries only one publisher.
    """
    start_time = time.time()
    mode = normalize_asset_class(mode)

    symbol, exponent = get_feed_metadata(client_lazer, feed_id)
    if exponent is None:
        return PublisherBenchmarkResult(
            publisher_id=publisher_id,
            feed_id=feed_id,
            date=date,
            mode=mode,
            symbol=None,
            passes=False,
            n_observations=0,
            rmse=None,
            mean_spread=None,
            rmse_over_spread=None,
            error=f"Feed metadata not found for feed_id {feed_id}",
            execution_time_ms=int((time.time() - start_time) * 1000),
        )

    divisor = 10 ** abs(exponent)
    benchmark_table = get_benchmark_table(mode, symbol)
    price_col, bid_col, ask_col = get_benchmark_columns(mode)
    qualifier_filter = get_qualifier_filter_sql(mode)

    publisher_market_filter = get_market_hours_filter_sql(mode, date, "publish_time")
    benchmark_market_filter = get_market_hours_filter_sql(mode, date, "date_time")

    publisher_query = f"""
        SELECT
            toStartOfSecond(publish_time) AS ts_second,
            avg(price) / {divisor} AS avg_price,
            count() AS update_count
        FROM publisher_updates
        WHERE price_feed_id = {feed_id}
          AND publisher_id = {publisher_id}
          AND toDate(publish_time) = '{date}'
          AND (status = 'ACCEPTED' OR (status = 'REJECTED' AND status_reason = 'UNAUTHORIZED'))
          AND price IS NOT NULL
          {publisher_market_filter}
        GROUP BY ts_second
        ORDER BY ts_second
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
          {qualifier_filter}
        GROUP BY ts_second
        ORDER BY ts_second
    """

    try:
        pub_result = client_lazer.query(publisher_query)
        bench_result = client_analytics.query(benchmark_query)

        if not pub_result.result_rows:
            return PublisherBenchmarkResult(
                publisher_id=publisher_id,
                feed_id=feed_id,
                date=date,
                mode=mode,
                symbol=symbol,
                passes=False,
                n_observations=0,
                rmse=None,
                mean_spread=None,
                rmse_over_spread=None,
                error=f"No publisher data found for publisher {publisher_id}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        if not bench_result.result_rows:
            return PublisherBenchmarkResult(
                publisher_id=publisher_id,
                feed_id=feed_id,
                date=date,
                mode=mode,
                symbol=symbol,
                passes=False,
                n_observations=0,
                rmse=None,
                mean_spread=None,
                rmse_over_spread=None,
                error="No benchmark data found",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        benchmark_by_ts = {
            row[0]: (row[1], row[2])
            for row in bench_result.result_rows
            if row[1] is not None
        }

        squared_errors = []
        spreads = []
        pct_diffs = []
        benchmark_prices = []
        diffs = []
        signed_pct_diffs = []

        for row in pub_result.result_rows:
            ts, pub_price, _ = row
            if ts not in benchmark_by_ts:
                continue

            bench_price, spread = benchmark_by_ts[ts]
            diff = pub_price - bench_price
            pct_diff = abs(diff / bench_price) * 100
            signed_pct_diff = (diff / bench_price) * 100

            squared_errors.append(diff**2)
            if spread is not None:
                spreads.append(spread)
            pct_diffs.append(pct_diff)
            benchmark_prices.append(bench_price)
            diffs.append(diff)
            signed_pct_diffs.append(signed_pct_diff)

        n_observations = len(squared_errors)

        if n_observations < 100:
            return PublisherBenchmarkResult(
                publisher_id=publisher_id,
                feed_id=feed_id,
                date=date,
                mode=mode,
                symbol=symbol,
                passes=False,
                n_observations=n_observations,
                rmse=None,
                mean_spread=None,
                rmse_over_spread=None,
                error=f"Insufficient observations ({n_observations} < 100)",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        rmse = (sum(squared_errors) / n_observations) ** 0.5
        n_spreads = len(spreads)
        mean_spread = sum(spreads) / n_spreads if n_spreads > 0 else None

        benchmark_range = max(benchmark_prices) - min(benchmark_prices)
        nrmse = rmse / benchmark_range if benchmark_range > 0 else None

        hits_within_10bps = sum(1 for pct in pct_diffs if pct <= 0.1)
        hit_rate = (hits_within_10bps / n_observations) * 100

        rmse_over_spread = (
            rmse / mean_spread if mean_spread and mean_spread > 0 else None
        )

        # Pass/fail via centralized threshold logic
        regular_passes = passes_benchmark(
            nrmse=nrmse,
            hit_rate=hit_rate,
            session="regular",
            mode=mode,
            hit_rate_override=hit_rate_threshold if hit_rate_threshold != 95 else None,
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
            stat_metrics = compute_statistical_metrics(diffs, signed_pct_diffs)

        # Extended hours sessions (US equities only)
        premarket_metrics = None
        afterhours_metrics = None

        if include_extended_hours and mode in ("us-equities", "equity-us"):
            premarket_pub_filter = get_extended_hours_filter_sql(
                TradingSession.PREMARKET, date, "publish_time"
            )
            premarket_bench_filter = get_extended_hours_filter_sql(
                TradingSession.PREMARKET, date, "date_time"
            )
            pm_result = evaluate_session_metrics(
                client_lazer,
                client_analytics,
                publisher_id,
                feed_id,
                date,
                mode,
                divisor,
                benchmark_table,
                premarket_pub_filter,
                premarket_bench_filter,
                min_observations=50,
            )
            (
                pm_n_obs,
                pm_rmse,
                pm_spread,
                pm_ros,
                pm_nrmse,
                pm_hr,
                pm_range,
                pm_err,
            ) = pm_result

            pm_passes = passes_benchmark(
                nrmse=pm_nrmse,
                hit_rate=pm_hr if pm_hr is not None else 0,
                session="premarket",
                mode=mode,
                hit_rate_override=hit_rate_threshold
                if hit_rate_threshold != 95
                else None,
            )

            premarket_metrics = ExtendedHoursMetrics(
                session=TradingSession.PREMARKET,
                n_observations=pm_n_obs,
                rmse=pm_rmse,
                mean_spread=pm_spread,
                rmse_over_spread=pm_ros,
                nrmse=pm_nrmse,
                hit_rate=pm_hr,
                benchmark_price_range=pm_range,
                passes=pm_passes,
                error=pm_err,
            )

            afterhours_pub_filter = get_extended_hours_filter_sql(
                TradingSession.AFTERHOURS, date, "publish_time"
            )
            afterhours_bench_filter = get_extended_hours_filter_sql(
                TradingSession.AFTERHOURS, date, "date_time"
            )
            ah_result = evaluate_session_metrics(
                client_lazer,
                client_analytics,
                publisher_id,
                feed_id,
                date,
                mode,
                divisor,
                benchmark_table,
                afterhours_pub_filter,
                afterhours_bench_filter,
                min_observations=50,
            )
            (
                ah_n_obs,
                ah_rmse,
                ah_spread,
                ah_ros,
                ah_nrmse,
                ah_hr,
                ah_range,
                ah_err,
            ) = ah_result

            ah_passes = passes_benchmark(
                nrmse=ah_nrmse,
                hit_rate=ah_hr if ah_hr is not None else 0,
                session="afterhours",
                mode=mode,
                hit_rate_override=hit_rate_threshold
                if hit_rate_threshold != 95
                else None,
            )

            afterhours_metrics = ExtendedHoursMetrics(
                session=TradingSession.AFTERHOURS,
                n_observations=ah_n_obs,
                rmse=ah_rmse,
                mean_spread=ah_spread,
                rmse_over_spread=ah_ros,
                nrmse=ah_nrmse,
                hit_rate=ah_hr,
                benchmark_price_range=ah_range,
                passes=ah_passes,
                error=ah_err,
            )

        # Overnight session (US equities only)
        overnight_metrics = None
        if include_overnight and mode in ("us-equities", "equity-us"):
            if publisher_id == OVERNIGHT_REFERENCE_PUBLISHER_ID:
                overnight_metrics = OvernightMetrics(
                    n_observations=0,
                    n_reference_observations=0,
                    rmse=None,
                    mean_spread=None,
                    rmse_over_spread=None,
                    nrmse=None,
                    hit_rate=None,
                    reference_price_range=None,
                    passes=False,
                    reference_publisher_id=OVERNIGHT_REFERENCE_PUBLISHER_ID,
                    error=f"Cannot evaluate publisher {publisher_id} against itself as reference",
                )
            else:
                overnight_metrics = evaluate_overnight_session(
                    client_lazer,
                    publisher_id,
                    feed_id,
                    date,
                    divisor,
                    min_observations=50,
                    hit_rate_threshold=hit_rate_threshold,
                )

        return PublisherBenchmarkResult(
            publisher_id=publisher_id,
            feed_id=feed_id,
            date=date,
            mode=mode,
            symbol=symbol,
            passes=regular_passes,
            n_observations=n_observations,
            rmse=rmse,
            mean_spread=mean_spread,
            rmse_over_spread=rmse_over_spread,
            nrmse=nrmse,
            hit_rate=hit_rate,
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
            premarket_metrics=premarket_metrics,
            afterhours_metrics=afterhours_metrics,
            overnight_metrics=overnight_metrics,
            execution_time_ms=int((time.time() - start_time) * 1000),
        )

    except Exception as e:
        return PublisherBenchmarkResult(
            publisher_id=publisher_id,
            feed_id=feed_id,
            date=date,
            mode=mode,
            symbol=symbol,
            passes=False,
            n_observations=0,
            rmse=None,
            mean_spread=None,
            rmse_over_spread=None,
            error=str(e),
            execution_time_ms=int((time.time() - start_time) * 1000),
        )


def process_csv(
    csv_path: Path,
    publisher_id: int,
    max_workers: int,
    date_override: list[str] | None = None,
    include_asset_classes: list[str] | None = None,
    exclude_asset_classes: list[str] | None = None,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    feed_id_filter: set[int] | None = None,
    skip_scipy_tests: bool = False,
    hit_rate_threshold: float = 95,
) -> list[PublisherBenchmarkResult]:
    """Process feeds from CSV file with parallel execution for a single publisher."""
    config = load_config()

    include_normalized = None
    if include_asset_classes:
        include_normalized = {normalize_asset_class(ac) for ac in include_asset_classes}

    exclude_normalized = set()
    if exclude_asset_classes:
        exclude_normalized = {normalize_asset_class(ac) for ac in exclude_asset_classes}

    feeds_raw: list[tuple[int, str, str]] = []
    skipped_by_filter = 0
    with open(csv_path) as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not row[0].strip():
                continue
            if len(row) < 3:
                print(f"Warning: Skipping incomplete row: {row}")
                continue
            feed_id, date, mode = row[0].strip(), row[1].strip(), row[2].strip()

            normalized_mode = normalize_asset_class(mode)
            if include_normalized and normalized_mode not in include_normalized:
                skipped_by_filter += 1
                continue
            if normalized_mode in exclude_normalized:
                skipped_by_filter += 1
                continue

            feeds_raw.append((int(feed_id), date, mode))

    if skipped_by_filter > 0:
        print(f"Filtered out {skipped_by_filter} feeds by asset class")

    skipped_by_feed_id = 0
    if feed_id_filter and feeds_raw:
        filtered_feeds = []
        for feed_tuple in feeds_raw:
            feed_id = feed_tuple[0]
            if feed_id in feed_id_filter:
                filtered_feeds.append(feed_tuple)
            else:
                skipped_by_feed_id += 1

        feeds_raw = filtered_feeds
        if skipped_by_feed_id > 0:
            print(
                f"Filtered out {skipped_by_feed_id} feeds by feed ID "
                f"(kept {len(feeds_raw)} matching: {', '.join(map(str, sorted(feed_id_filter)))})"
            )

    if date_override:
        unique_feed_modes = sorted({(feed_id, mode) for feed_id, _, mode in feeds_raw})
        feeds_to_process = [
            (feed_id, date_value, mode)
            for feed_id, mode in unique_feed_modes
            for date_value in date_override
        ]
        print(
            f"Applied date override: {date_override[0]} to {date_override[-1]} "
            f"({len(date_override)} date(s))"
        )
        print(
            f"Expanded {len(unique_feed_modes)} unique feed/mode pairs to "
            f"{len(feeds_to_process)} feed-date evaluations"
        )
    else:
        feeds_to_process = feeds_raw

    print(
        f"Processing {len(feeds_to_process)} feeds for publisher {publisher_id} with {max_workers} workers..."
    )
    results = []

    def evaluate_single(args):
        feed_id, date, mode = args
        client_lazer, client_analytics = get_clients(config)
        return evaluate_publisher_feed(
            client_lazer,
            client_analytics,
            publisher_id,
            feed_id,
            date,
            mode,
            include_extended_hours=include_extended_hours,
            include_overnight=include_overnight,
            skip_scipy_tests=skip_scipy_tests,
            hit_rate_threshold=hit_rate_threshold,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(evaluate_single, args): args for args in feeds_to_process
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

            status = "PASS" if result.passes else "FAIL"
            if result.error:
                status = f"ERROR: {result.error[:50]}"

            nrmse_str = f"{result.nrmse:.4f}" if result.nrmse is not None else "N/A"
            hit_rate_str = (
                f"{result.hit_rate:.1f}%" if result.hit_rate is not None else "N/A"
            )
            print(
                f"  [{result.execution_time_ms:>4}ms] Feed {result.feed_id} ({result.symbol or 'unknown'}): "
                f"{status} - nrmse={nrmse_str}, hit_rate={hit_rate_str}, n={result.n_observations}"
            )

    return results
