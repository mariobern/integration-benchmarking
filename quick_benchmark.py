#!/usr/bin/env python3
"""
Fast benchmark evaluation script for Lazer feeds.

This script provides a quick pass/fail assessment for Lazer publisher data quality
against benchmark data (Datascope). It uses SQL aggregation in ClickHouse to avoid
pulling millions of rows into Python.

Pass/Fail Criteria:
- A publisher PASSES if: rmse_over_spread <= 1.0
- A feed is READY if: passing_publisher_count >= target_publisher_count

Usage:
    python quick_benchmark.py --csv price_id_list.csv
    python quick_benchmark.py --feed-id 327 --date 2025-10-06 --mode fx
"""

import argparse
import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import clickhouse_connect
import yaml


@dataclass
class BenchmarkResult:
    """Result of a single feed benchmark evaluation."""

    feed_id: int
    date: str
    mode: str
    symbol: Optional[str]
    ready: bool
    target_pub_count: int
    passing_pub_count: int
    failing_pub_count: int
    passing_publishers: list[int]
    failing_publishers: list[int]
    error: Optional[str] = None
    execution_time_ms: int = 0


def load_config() -> dict:
    """Load database configuration from config.yaml."""
    config_path = Path("config.yaml")
    if not config_path.exists():
        raise FileNotFoundError(
            "config.yaml not found. Copy config.yaml.sample to config.yaml and fill in credentials."
        )
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_clients(config: dict) -> tuple:
    """Create ClickHouse clients for Lazer and Analytics databases."""
    lazer_cfg = config["lazer_clickhouse_prod"]
    analytics_cfg = config["analytics_clickhouse"]

    # Cloud ClickHouse instances may need longer timeouts, especially when idle
    connect_timeout = 60  # seconds
    send_receive_timeout = 300  # seconds

    client_lazer = clickhouse_connect.get_client(
        host=lazer_cfg["host"],
        username=lazer_cfg["user"],
        password=lazer_cfg["password"],
        secure=True,
        connect_timeout=connect_timeout,
        send_receive_timeout=send_receive_timeout,
    )

    client_analytics = clickhouse_connect.get_client(
        host=analytics_cfg["host"],
        username=analytics_cfg["user"],
        password=analytics_cfg["password"],
        secure=True,
        connect_timeout=connect_timeout,
        send_receive_timeout=send_receive_timeout,
    )

    return client_lazer, client_analytics


def get_feed_metadata(client_lazer, feed_id: int) -> tuple[Optional[str], Optional[int]]:
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


def evaluate_feed_fast(
    client_lazer,
    client_analytics,
    feed_id: int,
    date: str,
    mode: str,
    target_pub_count: int = 4,
    tolerance_seconds: int = 60,
) -> BenchmarkResult:
    """
    Evaluate a feed using SQL aggregation for fast pass/fail determination.

    This performs the RMSE calculation directly in ClickHouse using ASOF JOIN,
    avoiding the need to pull millions of rows into Python.
    """
    start_time = time.time()

    # Get feed metadata
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

    # Determine benchmark table based on mode
    if mode in ("fx", "metals"):
        benchmark_table = "datascope_fx_benchmark_data"
    else:
        benchmark_table = "datascope_global_equities_benchmark_data"

    # Price divisor from exponent (e.g., exponent=-5 means divide by 100000)
    divisor = 10 ** abs(exponent)

    # Single optimized query that:
    # 1. Joins publisher data with benchmark data using ASOF JOIN
    # 2. Computes RMSE and mean spread per publisher
    # 3. Returns pass/fail status directly
    query = f"""
        WITH
            -- Publisher data with adjusted prices
            publisher_data AS (
                SELECT
                    publisher_id,
                    publish_time,
                    price / {divisor} AS publisher_price
                FROM publisher_updates
                WHERE price_feed_id = {feed_id}
                  AND toDate(publish_time) = '{date}'
                  AND (status = 'ACCEPTED' OR (status = 'REJECTED' AND status_reason = 'UNAUTHORIZED'))
                  AND price IS NOT NULL
            ),

            -- Benchmark data (require bid/ask for spread calculation)
            benchmark_data AS (
                SELECT
                    date_time AS benchmark_time,
                    COALESCE(price, (bid_price + ask_price) / 2) AS benchmark_price,
                    ask_price - bid_price AS spread
                FROM {benchmark_table}
                WHERE toDate(date_time) = '{date}'
                  AND pyth_lazer_id = {feed_id}
                  AND bid_price IS NOT NULL
                  AND ask_price IS NOT NULL
            ),

            -- ASOF JOIN to align timestamps (find nearest benchmark for each publisher update)
            aligned AS (
                SELECT
                    p.publisher_id,
                    p.publisher_price,
                    b.benchmark_price,
                    b.spread,
                    abs(toInt64(p.publish_time) - toInt64(b.benchmark_time)) AS time_diff_us
                FROM publisher_data p
                ASOF LEFT JOIN benchmark_data b
                ON 1 = 1 AND p.publish_time >= b.benchmark_time
                WHERE b.benchmark_price IS NOT NULL
                  AND time_diff_us <= {tolerance_seconds * 1_000_000}
            ),

            -- Compute metrics per publisher
            publisher_metrics AS (
                SELECT
                    publisher_id,
                    count() AS n_observations,
                    sqrt(avg(pow(publisher_price - benchmark_price, 2))) AS rmse,
                    avg(spread) AS mean_spread,
                    sqrt(avg(pow(publisher_price - benchmark_price, 2))) / nullIf(avg(spread), 0) AS rmse_over_spread
                FROM aligned
                GROUP BY publisher_id
                HAVING n_observations >= 100  -- Minimum observations threshold
            )

        SELECT
            publisher_id,
            n_observations,
            rmse,
            mean_spread,
            rmse_over_spread,
            rmse_over_spread <= 1.0 AS passes
        FROM publisher_metrics
        ORDER BY rmse_over_spread ASC
    """

    try:
        result = client_analytics.query(query)
        rows = result.result_rows

        passing_publishers = []
        failing_publishers = []

        for row in rows:
            publisher_id = row[0]
            passes = row[5]
            if passes:
                passing_publishers.append(publisher_id)
            else:
                failing_publishers.append(publisher_id)

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


def evaluate_feed_two_queries(
    client_lazer,
    client_analytics,
    feed_id: int,
    date: str,
    mode: str,
    target_pub_count: int = 4,
    tolerance_seconds: int = 60,
) -> BenchmarkResult:
    """
    Fallback evaluation using two separate queries when cross-cluster ASOF JOIN isn't available.

    This approach:
    1. Queries aggregated publisher prices (1-second buckets) from Lazer cluster
    2. Queries aggregated benchmark prices (1-second buckets) from Analytics cluster
    3. Joins and computes metrics in Python (but with much less data due to aggregation)
    """
    start_time = time.time()

    # Get feed metadata
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

    # Determine benchmark table based on mode
    if mode in ("fx", "metals"):
        benchmark_table = "datascope_fx_benchmark_data"
    else:
        benchmark_table = "datascope_global_equities_benchmark_data"

    # Query 1: Get publisher prices aggregated by second
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
        GROUP BY publisher_id, ts_second
        ORDER BY publisher_id, ts_second
    """

    # Query 2: Get benchmark prices aggregated by second
    # Require bid/ask to be present since spread is essential for RMSE/spread calculation
    benchmark_query = f"""
        SELECT
            toStartOfSecond(date_time) AS ts_second,
            avg(COALESCE(price, (bid_price + ask_price) / 2)) AS avg_price,
            avg(ask_price - bid_price) AS avg_spread
        FROM {benchmark_table}
        WHERE toDate(date_time) = '{date}'
          AND pyth_lazer_id = {feed_id}
          AND bid_price IS NOT NULL
          AND ask_price IS NOT NULL
        GROUP BY ts_second
        ORDER BY ts_second
    """

    try:
        # Execute both queries
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

        # Build benchmark lookup dict (skip rows with None values)
        benchmark_by_ts = {
            row[0]: (row[1], row[2])
            for row in bench_result.result_rows
            if row[1] is not None and row[2] is not None
        }

        # Compute metrics per publisher
        publisher_metrics = {}
        for row in pub_result.result_rows:
            pub_id, ts, pub_price, _ = row

            if ts not in benchmark_by_ts:
                continue

            bench_price, spread = benchmark_by_ts[ts]

            if pub_id not in publisher_metrics:
                publisher_metrics[pub_id] = {
                    "squared_errors": [],
                    "spreads": [],
                }

            publisher_metrics[pub_id]["squared_errors"].append(
                (pub_price - bench_price) ** 2
            )
            publisher_metrics[pub_id]["spreads"].append(spread)

        # Calculate RMSE and pass/fail for each publisher
        passing_publishers = []
        failing_publishers = []

        for pub_id, metrics in publisher_metrics.items():
            if len(metrics["squared_errors"]) < 100:
                continue

            rmse = (sum(metrics["squared_errors"]) / len(metrics["squared_errors"])) ** 0.5
            mean_spread = sum(metrics["spreads"]) / len(metrics["spreads"])

            if mean_spread > 0:
                rmse_over_spread = rmse / mean_spread
                if rmse_over_spread <= 1.0:
                    passing_publishers.append(pub_id)
                else:
                    failing_publishers.append(pub_id)

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
) -> list[BenchmarkResult]:
    """Process feeds from CSV file with parallel execution."""
    config = load_config()

    # Read CSV
    feeds_to_process = []
    with open(csv_path) as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not row[0].strip():
                continue
            if len(row) < 3:
                print(f"Warning: Skipping incomplete row: {row}")
                continue
            feed_id, date, mode = row[0].strip(), row[1].strip(), row[2].strip()
            feeds_to_process.append((int(feed_id), date, mode))

    print(f"Processing {len(feeds_to_process)} feeds with {max_workers} workers...")
    results = []

    def evaluate_single(args):
        feed_id, date, mode = args
        # Create separate client instances per thread to avoid concurrent query errors
        client_lazer, client_analytics = get_clients(config)
        # Use two-query approach (more reliable across clusters)
        return evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            feed_id,
            date,
            mode,
            target_pub_count,
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

            print(
                f"  [{result.execution_time_ms:>5}ms] Feed {result.feed_id} ({result.date}): "
                f"{status} - {result.passing_pub_count} passing, {result.failing_pub_count} failing"
            )

    # Write results to CSV
    write_results_csv(results, output_path)

    return results


def write_results_csv(results: list[BenchmarkResult], output_path: Path):
    """Write benchmark results to CSV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "feed_id",
                "date",
                "mode",
                "symbol",
                "ready",
                "target_pub_count",
                "passing_pub_count",
                "failing_pub_count",
                "passing_publishers",
                "failing_publishers",
                "error",
                "execution_time_ms",
            ]
        )

        for r in sorted(results, key=lambda x: (x.date, x.feed_id)):
            writer.writerow(
                [
                    r.feed_id,
                    r.date,
                    r.mode,
                    r.symbol or "",
                    r.ready,
                    r.target_pub_count,
                    r.passing_pub_count,
                    r.failing_pub_count,
                    ";".join(map(str, r.passing_publishers)),
                    ";".join(map(str, r.failing_publishers)),
                    r.error or "",
                    r.execution_time_ms,
                ]
            )

    print(f"\nResults written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Fast benchmark evaluation for Lazer feeds (pass/fail only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process feeds from CSV file
  python quick_benchmark.py --csv price_id_list.csv

  # Process a single feed
  python quick_benchmark.py --feed-id 327 --date 2025-10-06 --mode fx

  # Custom output path and target publisher count
  python quick_benchmark.py --csv feeds.csv --output results.csv --target-pub-count 6
""",
    )

    parser.add_argument(
        "--csv",
        type=Path,
        help="CSV file containing feed_id,date,mode columns",
    )
    parser.add_argument(
        "--feed-id",
        type=int,
        help="Single feed ID to evaluate",
    )
    parser.add_argument(
        "--date",
        help="Date for single feed evaluation (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--mode",
        choices=["fx", "metals", "us-equities"],
        help="Mode for single feed evaluation",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("quick_benchmark_results.csv"),
        help="Output CSV path (default: quick_benchmark_results.csv)",
    )
    parser.add_argument(
        "--target-pub-count",
        type=int,
        default=4,
        help="Target publisher count for feed readiness (default: 4)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.csv and (args.feed_id or args.date or args.mode):
        parser.error("Use either --csv OR (--feed-id, --date, --mode), not both")

    if not args.csv and not (args.feed_id and args.date and args.mode):
        parser.error("Either --csv or all of (--feed-id, --date, --mode) required")

    total_start = time.time()

    if args.csv:
        if not args.csv.exists():
            print(f"Error: CSV file '{args.csv}' not found")
            sys.exit(1)

        results = process_csv(
            args.csv,
            args.output,
            args.target_pub_count,
            args.workers,
        )
    else:
        # Single feed evaluation
        config = load_config()
        client_lazer, client_analytics = get_clients(config)

        result = evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            args.feed_id,
            args.date,
            args.mode,
            args.target_pub_count,
        )

        results = [result]
        write_results_csv(results, args.output)

    # Summary
    total_time = time.time() - total_start
    ready_count = sum(1 for r in results if r.ready)
    error_count = sum(1 for r in results if r.error)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Total feeds evaluated: {len(results)}")
    print(f"Ready (PASS): {ready_count}")
    print(f"Not Ready (FAIL): {len(results) - ready_count - error_count}")
    print(f"Errors: {error_count}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Average time per feed: {(total_time / len(results) * 1000):.0f}ms")


if __name__ == "__main__":
    main()
