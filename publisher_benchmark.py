#!/usr/bin/env python3
"""
Single-publisher benchmark evaluation script for Lazer feeds.

This script evaluates a SINGLE publisher's data quality against benchmark data (Datascope).
It is significantly faster than quick_benchmark.py because it only queries and evaluates
one publisher instead of all publishers.

The publisher ID is extracted from the input filename pattern: publisher_{id}_feeds.csv

Pass/Fail Criteria:
- A publisher PASSES if: rmse_over_spread <= 1.0

Usage:
    python publisher_benchmark.py --csv publisher_55_feeds.csv
    python publisher_benchmark.py --csv feeds.csv --publisher-id 55
"""

import argparse
import csv
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import clickhouse_connect
import yaml


# Asset class normalization mapping (CSV value -> canonical value)
ASSET_CLASS_ALIASES = {
    "metal": "metals",
    "metals": "metals",
    "equity-us": "us-equities",
    "us-equities": "us-equities",
    "fx": "fx",
    "commodity": "commodity",
    "crypto": "crypto",
    "crypto-redemption-rate": "crypto-redemption-rate",
    "funding-rate": "funding-rate",
    "rates": "rates",
    "nav": "nav",
}

# Asset classes that have benchmark data available
BENCHMARKABLE_ASSET_CLASSES = {"fx", "metals", "us-equities", "commodity"}


@dataclass
class PublisherBenchmarkResult:
    """Result of a single publisher's benchmark evaluation for one feed."""

    publisher_id: int
    feed_id: int
    date: str
    mode: str
    symbol: Optional[str]
    passes: bool
    n_observations: int
    rmse: Optional[float]
    mean_spread: Optional[float]
    rmse_over_spread: Optional[float]
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


def extract_publisher_id_from_filename(filename: str) -> Optional[int]:
    """Extract publisher ID from filename pattern publisher_{id}_feeds.csv."""
    match = re.match(r"publisher_(\d+)_feeds\.csv", filename)
    if match:
        return int(match.group(1))
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


def normalize_asset_class(asset_class: str) -> str:
    """Normalize asset class name to canonical form."""
    return ASSET_CLASS_ALIASES.get(asset_class.lower(), asset_class.lower())


def get_clients(config: dict) -> tuple:
    """Create ClickHouse clients for Lazer and Analytics databases."""
    lazer_cfg = config["lazer_clickhouse_prod"]
    analytics_cfg = config["analytics_clickhouse"]

    connect_timeout = 60
    send_receive_timeout = 300

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


def evaluate_publisher_feed(
    client_lazer,
    client_analytics,
    publisher_id: int,
    feed_id: int,
    date: str,
    mode: str,
    tolerance_seconds: int = 60,
) -> PublisherBenchmarkResult:
    """
    Evaluate a single publisher's data quality for one feed.

    This is significantly faster than quick_benchmark.py because it only
    queries data for ONE publisher instead of all publishers.
    """
    start_time = time.time()

    # Get feed metadata
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

    # Determine benchmark table based on mode
    if mode in ("fx", "metals"):
        benchmark_table = "datascope_fx_benchmark_data"
    else:
        benchmark_table = "datascope_global_equities_benchmark_data"

    # Query 1: Get publisher prices aggregated by second - FILTERED TO SINGLE PUBLISHER
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
        GROUP BY ts_second
        ORDER BY ts_second
    """

    # Query 2: Get benchmark prices aggregated by second
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

        # Build benchmark lookup dict (skip rows with None values)
        benchmark_by_ts = {
            row[0]: (row[1], row[2])
            for row in bench_result.result_rows
            if row[1] is not None and row[2] is not None
        }

        # Compute metrics for this publisher
        squared_errors = []
        spreads = []

        for row in pub_result.result_rows:
            ts, pub_price, _ = row

            if ts not in benchmark_by_ts:
                continue

            bench_price, spread = benchmark_by_ts[ts]
            squared_errors.append((pub_price - bench_price) ** 2)
            spreads.append(spread)

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
        mean_spread = sum(spreads) / n_observations

        if mean_spread <= 0:
            return PublisherBenchmarkResult(
                publisher_id=publisher_id,
                feed_id=feed_id,
                date=date,
                mode=mode,
                symbol=symbol,
                passes=False,
                n_observations=n_observations,
                rmse=rmse,
                mean_spread=mean_spread,
                rmse_over_spread=None,
                error="Mean spread is zero or negative",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        rmse_over_spread = rmse / mean_spread
        passes = rmse_over_spread <= 1.0

        return PublisherBenchmarkResult(
            publisher_id=publisher_id,
            feed_id=feed_id,
            date=date,
            mode=mode,
            symbol=symbol,
            passes=passes,
            n_observations=n_observations,
            rmse=rmse,
            mean_spread=mean_spread,
            rmse_over_spread=rmse_over_spread,
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
    output_path: Path,
    max_workers: int,
    include_asset_classes: list[str] | None = None,
    exclude_asset_classes: list[str] | None = None,
) -> list[PublisherBenchmarkResult]:
    """Process feeds from CSV file with parallel execution for a single publisher."""
    config = load_config()

    # Normalize filter lists
    include_normalized = None
    if include_asset_classes:
        include_normalized = {normalize_asset_class(ac) for ac in include_asset_classes}

    exclude_normalized = set()
    if exclude_asset_classes:
        exclude_normalized = {normalize_asset_class(ac) for ac in exclude_asset_classes}

    # Read CSV
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
            feed_id, date, mode = row[0].strip(), row[1].strip(), row[2].strip()

            # Apply asset class filters
            normalized_mode = normalize_asset_class(mode)
            if include_normalized and normalized_mode not in include_normalized:
                skipped_by_filter += 1
                continue
            if normalized_mode in exclude_normalized:
                skipped_by_filter += 1
                continue

            feeds_to_process.append((int(feed_id), date, mode))

    if skipped_by_filter > 0:
        print(f"Filtered out {skipped_by_filter} feeds by asset class")
    print(f"Processing {len(feeds_to_process)} feeds for publisher {publisher_id} with {max_workers} workers...")
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

            rmse_str = f"{result.rmse_over_spread:.3f}" if result.rmse_over_spread is not None else "N/A"
            print(
                f"  [{result.execution_time_ms:>4}ms] Feed {result.feed_id} ({result.symbol or 'unknown'}): "
                f"{status} - rmse/spread={rmse_str}, n={result.n_observations}"
            )

    # Write results to CSV
    write_results_csv(results, output_path)

    return results


def write_results_csv(results: list[PublisherBenchmarkResult], output_path: Path):
    """Write benchmark results to CSV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "publisher_id",
                "feed_id",
                "date",
                "mode",
                "symbol",
                "passes",
                "n_observations",
                "rmse",
                "mean_spread",
                "rmse_over_spread",
                "error",
                "execution_time_ms",
            ]
        )

        for r in sorted(results, key=lambda x: (x.date, x.feed_id)):
            writer.writerow(
                [
                    r.publisher_id,
                    r.feed_id,
                    r.date,
                    r.mode,
                    r.symbol or "",
                    r.passes,
                    r.n_observations,
                    f"{r.rmse:.6f}" if r.rmse is not None else "",
                    f"{r.mean_spread:.6f}" if r.mean_spread is not None else "",
                    f"{r.rmse_over_spread:.6f}" if r.rmse_over_spread is not None else "",
                    r.error or "",
                    r.execution_time_ms,
                ]
            )

    print(f"\nResults written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Single-publisher benchmark evaluation for Lazer feeds (faster than quick_benchmark.py)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process feeds from publisher-specific CSV file (extracts publisher ID from filename)
  python publisher_benchmark.py --csv publisher_55_feeds.csv

  # Specify publisher ID explicitly
  python publisher_benchmark.py --csv feeds.csv --publisher-id 55

  # Custom output path
  python publisher_benchmark.py --csv publisher_55_feeds.csv --output results.csv

  # List asset classes in a CSV file
  python publisher_benchmark.py --csv publisher_55_feeds.csv --list-asset-classes

  # Include only specific asset classes
  python publisher_benchmark.py --csv publisher_55_feeds.csv --include-asset-class fx metals us-equities
""",
    )

    parser.add_argument(
        "--csv",
        type=Path,
        required=True,
        help="CSV file containing feed_id,date,mode columns",
    )
    parser.add_argument(
        "--publisher-id",
        type=int,
        help="Publisher ID to evaluate (if not extractable from filename)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output CSV path (default: publisher_{id}_benchmark_results.csv)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    parser.add_argument(
        "--include-asset-class",
        type=str,
        nargs="+",
        metavar="CLASS",
        help="Only process feeds with these asset classes (e.g., fx metals us-equities)",
    )
    parser.add_argument(
        "--exclude-asset-class",
        type=str,
        nargs="+",
        metavar="CLASS",
        help="Exclude feeds with these asset classes (e.g., crypto funding-rate)",
    )
    parser.add_argument(
        "--list-asset-classes",
        action="store_true",
        help="List unique asset classes in the CSV file and exit",
    )

    args = parser.parse_args()

    # Validate CSV file exists
    if not args.csv.exists():
        print(f"Error: CSV file '{args.csv}' not found")
        sys.exit(1)

    # Handle --list-asset-classes
    if args.list_asset_classes:
        asset_classes = list_asset_classes_in_csv(args.csv)
        total_feeds = sum(asset_classes.values())

        print(f"\nAsset classes in {args.csv}:")
        print(f"{'='*50}")
        for ac, count in sorted(asset_classes.items(), key=lambda x: -x[1]):
            normalized = normalize_asset_class(ac)
            benchmarkable = "Y" if normalized in BENCHMARKABLE_ASSET_CLASSES else "N"
            print(f"  {ac:<25} {count:>5} feeds  [benchmarkable: {benchmarkable}]")
        print(f"{'='*50}")
        print(f"  {'TOTAL':<25} {total_feeds:>5} feeds")
        print(f"\nBenchmarkable asset classes: {', '.join(sorted(BENCHMARKABLE_ASSET_CLASSES))}")
        sys.exit(0)

    # Determine publisher ID
    publisher_id = args.publisher_id
    if publisher_id is None:
        publisher_id = extract_publisher_id_from_filename(args.csv.name)
        if publisher_id is None:
            print(f"Error: Could not extract publisher ID from filename '{args.csv.name}'")
            print("Expected format: publisher_{{id}}_feeds.csv (e.g., publisher_55_feeds.csv)")
            print("Or use --publisher-id to specify explicitly")
            sys.exit(1)
        print(f"Extracted publisher ID {publisher_id} from filename")

    # Validate include/exclude don't overlap
    if args.include_asset_class and args.exclude_asset_class:
        include_set = {normalize_asset_class(ac) for ac in args.include_asset_class}
        exclude_set = {normalize_asset_class(ac) for ac in args.exclude_asset_class}
        overlap = include_set & exclude_set
        if overlap:
            parser.error(f"Asset classes cannot be both included and excluded: {overlap}")

    # Determine output path
    output_path = args.output
    if output_path is None:
        output_path = Path(f"publisher_{publisher_id}_benchmark_results.csv")

    total_start = time.time()

    results = process_csv(
        args.csv,
        publisher_id,
        output_path,
        args.workers,
        include_asset_classes=args.include_asset_class,
        exclude_asset_classes=args.exclude_asset_class,
    )

    # Summary
    total_time = time.time() - total_start
    pass_count = sum(1 for r in results if r.passes)
    error_count = sum(1 for r in results if r.error)

    print(f"\n{'='*60}")
    print(f"SUMMARY - Publisher {publisher_id}")
    print(f"{'='*60}")
    print(f"Total feeds evaluated: {len(results)}")
    print(f"PASS (rmse/spread <= 1.0): {pass_count}")
    print(f"FAIL: {len(results) - pass_count - error_count}")
    print(f"Errors: {error_count}")
    print(f"Total time: {total_time:.2f}s")
    if len(results) > 0:
        print(f"Average time per feed: {(total_time / len(results) * 1000):.0f}ms")
    else:
        print("No feeds were processed (all filtered out or empty CSV)")


if __name__ == "__main__":
    main()
