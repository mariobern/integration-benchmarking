#!/usr/bin/env python3
"""
Feed-level benchmark evaluation script for Lazer feeds.

This script evaluates feed readiness across all publishers for each feed against
benchmark data (Datascope). It is the feed-level counterpart to
publisher_benchmark.py.

Pass/Fail Criteria (per publisher):
- PASS if: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 98%)
- nrmse = RMSE / (max_benchmark_price - min_benchmark_price)
- hit_rate = % of observations within 10 basis points (0.1%) of benchmark

Feed readiness:
- READY if: passing_publisher_count >= target_publisher_count

Supported features:
- Regular hours filtering for US equities (9:30 AM - 4:00 PM ET)
- Extended hours evaluation (--extended-hours)
- Overnight evaluation using publisher 32 as reference (--overnight)
- Optional statistical tests (--skip-scipy-tests)
- Detailed per-publisher output (--detailed)
- CSV feed filtering by feed ID (--filter-feed-id)
"""

import argparse
import csv
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import clickhouse_connect
import yaml


class TradingSession(Enum):
    """Trading session types for US equities."""

    REGULAR = "regular"
    PREMARKET = "premarket"
    AFTERHOURS = "afterhours"
    OVERNIGHT = "overnight"


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
    "rates": "us-treasuries",
    "nav": "nav",
    "us-treasuries": "us-treasuries",
    "treasuries": "us-treasuries",
}

# Asset classes that have benchmark data available
BENCHMARKABLE_ASSET_CLASSES = {
    "fx",
    "metals",
    "us-equities",
    "commodity",
    "us-treasuries",
}

# Futures contract month codes
FUTURES_MONTH_CODES = "FGHJKMNQUVXZ"

# US Equities market hours (EST/EDT) - Regular trading session only
US_EQUITY_MARKET_OPEN_HOUR = 9
US_EQUITY_MARKET_OPEN_MINUTE = 30
US_EQUITY_MARKET_CLOSE_HOUR = 16
US_EQUITY_MARKET_CLOSE_MINUTE = 0

# US Equities extended hours (EST/EDT)
US_EQUITY_PREMARKET_OPEN_HOUR = 4
US_EQUITY_PREMARKET_OPEN_MINUTE = 0
US_EQUITY_AFTERHOURS_CLOSE_HOUR = 20
US_EQUITY_AFTERHOURS_CLOSE_MINUTE = 0

# Overnight: 8:00 PM - 4:00 AM EST (next day)
US_EQUITY_OVERNIGHT_START_HOUR = 20
US_EQUITY_OVERNIGHT_START_MINUTE = 0
US_EQUITY_OVERNIGHT_END_HOUR = 4
US_EQUITY_OVERNIGHT_END_MINUTE = 0

# Reference publisher for overnight benchmark (Blue Ocean ATS)
OVERNIGHT_REFERENCE_PUBLISHER_ID = 32

# Observation thresholds
REGULAR_MIN_OBSERVATIONS = 100
SESSION_MIN_OBSERVATIONS = 50


@dataclass
class ExtendedHoursMetrics:
    """Metrics for a single extended hours session (pre-market or after-hours)."""

    session: TradingSession
    n_observations: int
    rmse: Optional[float]
    mean_spread: Optional[float]
    rmse_over_spread: Optional[float]
    nrmse: Optional[float]
    hit_rate: Optional[float]
    benchmark_price_range: Optional[float]
    passes: bool
    error: Optional[str] = None


@dataclass
class OvernightMetrics:
    """Metrics for overnight session using publisher 32 as benchmark."""

    n_observations: int
    n_reference_observations: int
    rmse: Optional[float]
    mean_spread: Optional[float]
    rmse_over_spread: Optional[float]
    nrmse: Optional[float]
    hit_rate: Optional[float]
    reference_price_range: Optional[float]
    passes: bool
    reference_publisher_id: int = OVERNIGHT_REFERENCE_PUBLISHER_ID
    error: Optional[str] = None


@dataclass
class PublisherFeedMetrics:
    """Per-publisher metrics within a feed evaluation."""

    publisher_id: int
    n_observations: int
    passes: bool
    nrmse: Optional[float] = None
    hit_rate: Optional[float] = None
    rmse: Optional[float] = None
    mean_spread: Optional[float] = None
    rmse_over_spread: Optional[float] = None
    benchmark_price_range: Optional[float] = None
    mean_diff: Optional[float] = None
    std_diff: Optional[float] = None
    mean_pct_diff: Optional[float] = None
    std_pct_diff: Optional[float] = None
    mae: Optional[float] = None
    t_statistic: Optional[float] = None
    t_pvalue: Optional[float] = None
    wilcoxon_statistic: Optional[float] = None
    wilcoxon_pvalue: Optional[float] = None
    normality_pvalue: Optional[float] = None
    mean_abs_z_score: Optional[float] = None
    premarket_metrics: Optional[ExtendedHoursMetrics] = None
    afterhours_metrics: Optional[ExtendedHoursMetrics] = None
    overnight_metrics: Optional[OvernightMetrics] = None
    error: Optional[str] = None


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
    median_nrmse: Optional[float] = None
    median_hit_rate: Optional[float] = None
    publisher_details: Optional[list[PublisherFeedMetrics]] = None
    premarket_passing_count: Optional[int] = None
    premarket_failing_count: Optional[int] = None
    afterhours_passing_count: Optional[int] = None
    afterhours_failing_count: Optional[int] = None
    overnight_passing_count: Optional[int] = None
    overnight_failing_count: Optional[int] = None
    overnight_reference_publisher_id: Optional[int] = None
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


def is_futures_symbol(symbol: str) -> bool:
    """Detect if a symbol represents a futures contract."""

    if not symbol:
        return False

    base = symbol.split("/")[0] if "/" in symbol else symbol
    parts = base.split(".")
    if len(parts) < 2:
        return False

    ticker = parts[-1]
    if len(ticker) < 2:
        return False

    month_code = ticker[-2].upper()
    year_digit = ticker[-1]

    return month_code in FUTURES_MONTH_CODES and year_digit.isdigit()


@lru_cache(maxsize=32)
def get_market_hours_filter_sql(mode: str, date: str, column_name: str = "publish_time") -> str:
    """Generate SQL WHERE clause for regular market hours filtering."""

    if mode not in ("us-equities", "equity-us"):
        return ""

    dt = datetime.strptime(date, "%Y-%m-%d")
    est = ZoneInfo("America/New_York")
    utc = ZoneInfo("UTC")

    market_open_est = dt.replace(
        hour=US_EQUITY_MARKET_OPEN_HOUR,
        minute=US_EQUITY_MARKET_OPEN_MINUTE,
        tzinfo=est,
    )
    market_close_est = dt.replace(
        hour=US_EQUITY_MARKET_CLOSE_HOUR,
        minute=US_EQUITY_MARKET_CLOSE_MINUTE,
        tzinfo=est,
    )

    market_open_utc = market_open_est.astimezone(utc)
    market_close_utc = market_close_est.astimezone(utc)

    return f"""
        AND {column_name} >= '{market_open_utc.strftime('%Y-%m-%d %H:%M:%S')}'
        AND {column_name} < '{market_close_utc.strftime('%Y-%m-%d %H:%M:%S')}'
    """


@lru_cache(maxsize=32)
def get_extended_hours_filter_sql(
    session: TradingSession,
    date: str,
    column_name: str = "publish_time",
) -> str:
    """Generate SQL WHERE clause for pre-market or after-hours filtering."""

    dt = datetime.strptime(date, "%Y-%m-%d")
    est = ZoneInfo("America/New_York")
    utc = ZoneInfo("UTC")

    if session == TradingSession.PREMARKET:
        start_est = dt.replace(
            hour=US_EQUITY_PREMARKET_OPEN_HOUR,
            minute=US_EQUITY_PREMARKET_OPEN_MINUTE,
            tzinfo=est,
        )
        end_est = dt.replace(
            hour=US_EQUITY_MARKET_OPEN_HOUR,
            minute=US_EQUITY_MARKET_OPEN_MINUTE,
            tzinfo=est,
        )
    elif session == TradingSession.AFTERHOURS:
        start_est = dt.replace(
            hour=US_EQUITY_MARKET_CLOSE_HOUR,
            minute=US_EQUITY_MARKET_CLOSE_MINUTE,
            tzinfo=est,
        )
        end_est = dt.replace(
            hour=US_EQUITY_AFTERHOURS_CLOSE_HOUR,
            minute=US_EQUITY_AFTERHOURS_CLOSE_MINUTE,
            tzinfo=est,
        )
    else:
        return ""

    start_utc = start_est.astimezone(utc)
    end_utc = end_est.astimezone(utc)

    return f"""
        AND {column_name} >= '{start_utc.strftime('%Y-%m-%d %H:%M:%S')}'
        AND {column_name} < '{end_utc.strftime('%Y-%m-%d %H:%M:%S')}'
    """


@lru_cache(maxsize=32)
def get_overnight_hours_filter_sql(date: str, column_name: str = "publish_time") -> str:
    """Generate SQL WHERE clause for overnight session filtering (8 PM - 4 AM ET)."""

    dt = datetime.strptime(date, "%Y-%m-%d")
    est = ZoneInfo("America/New_York")
    utc = ZoneInfo("UTC")

    overnight_start_est = dt.replace(
        hour=US_EQUITY_OVERNIGHT_START_HOUR,
        minute=US_EQUITY_OVERNIGHT_START_MINUTE,
        tzinfo=est,
    )
    overnight_end_est = (dt + timedelta(days=1)).replace(
        hour=US_EQUITY_OVERNIGHT_END_HOUR,
        minute=US_EQUITY_OVERNIGHT_END_MINUTE,
        tzinfo=est,
    )

    overnight_start_utc = overnight_start_est.astimezone(utc)
    overnight_end_utc = overnight_end_est.astimezone(utc)

    return f"""
        AND {column_name} >= '{overnight_start_utc.strftime('%Y-%m-%d %H:%M:%S')}'
        AND {column_name} < '{overnight_end_utc.strftime('%Y-%m-%d %H:%M:%S')}'
    """


def get_benchmark_table(mode: str, symbol: Optional[str]) -> str:
    """Determine which benchmark table to use based on mode and symbol."""

    if symbol and is_futures_symbol(symbol):
        return "datascope_futures_benchmark_data"

    if mode in ("fx", "metals"):
        return "datascope_fx_benchmark_data"
    if mode == "us-treasuries":
        return "datascope_us_treasury_benchmark_data"
    return "datascope_global_equities_benchmark_data"


def get_benchmark_columns(mode: str) -> tuple[str, str, str]:
    """Get benchmark columns by mode (treasuries use yield columns)."""

    if mode == "us-treasuries":
        return ("yield", "bid_yield", "ask_yield")
    return ("price", "bid_price", "ask_price")


def compute_statistical_metrics(
    diffs: list[float],
    signed_pct_diffs: list[float],
    min_observations: int = 20,
) -> dict:
    """Compute advanced statistical metrics for price differences."""

    result = {
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

    n = len(diffs)
    if n < 2:
        return result

    result["mean_diff"] = statistics.mean(diffs)
    result["std_diff"] = statistics.stdev(diffs)
    result["mean_pct_diff"] = statistics.mean(signed_pct_diffs)
    result["std_pct_diff"] = statistics.stdev(signed_pct_diffs) if n >= 2 else None
    result["mae"] = statistics.mean([abs(d) for d in diffs])

    if result["std_diff"] and result["std_diff"] > 0:
        z_scores = [(d - result["mean_diff"]) / result["std_diff"] for d in diffs]
        result["mean_abs_z_score"] = statistics.mean([abs(z) for z in z_scores])

    if n < min_observations:
        return result

    try:
        from scipy import stats
    except Exception:
        return result

    try:
        t_stat, t_pval = stats.ttest_1samp(diffs, 0)
        result["t_statistic"] = float(t_stat)
        result["t_pvalue"] = float(t_pval)
    except Exception:
        pass

    try:
        non_zero_diffs = [d for d in diffs if d != 0]
        if len(non_zero_diffs) >= min_observations:
            w_stat, w_pval = stats.wilcoxon(non_zero_diffs)
            result["wilcoxon_statistic"] = float(w_stat)
            result["wilcoxon_pvalue"] = float(w_pval)
    except Exception:
        pass

    try:
        _, norm_pval = stats.normaltest(diffs)
        result["normality_pvalue"] = float(norm_pval)
    except Exception:
        pass

    return result


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
            if ts not in benchmark_by_ts:
                continue

            bench_price, spread = benchmark_by_ts[ts]
            diff = pub_price - bench_price
            pct_diff = abs(diff / bench_price) * 100 if bench_price else 0

            metrics = publisher_metrics[pub_id]
            metrics["squared_errors"].append(diff**2)
            if spread is not None:
                metrics["spreads"].append(spread)
            metrics["pct_diffs"].append(pct_diff)
            metrics["benchmark_prices"].append(bench_price)

        results: dict[int, ExtendedHoursMetrics] = {}
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
            mean_spread = (
                sum(metrics["spreads"]) / n_spreads if n_spreads > 0 else None
            )

            benchmark_range = max(metrics["benchmark_prices"]) - min(
                metrics["benchmark_prices"]
            )
            nrmse = rmse / benchmark_range if benchmark_range > 0 else None

            hits_within_10bps = sum(1 for pct in metrics["pct_diffs"] if pct <= 0.1)
            hit_rate = (hits_within_10bps / n_observations) * 100

            rmse_over_spread = (
                rmse / mean_spread if mean_spread and mean_spread > 0 else None
            )

            if nrmse is not None:
                passes = nrmse < 0.01 or (nrmse < 0.05 and hit_rate >= 98)
            else:
                passes = False

            results[pub_id] = ExtendedHoursMetrics(
                session=session,
                n_observations=n_observations,
                rmse=rmse,
                mean_spread=mean_spread,
                rmse_over_spread=rmse_over_spread,
                nrmse=nrmse,
                hit_rate=hit_rate,
                benchmark_price_range=benchmark_range,
                passes=passes,
                error=None,
            )

        return results

    except Exception as e:
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
                error=str(e),
            )
            for pub_id in all_publishers
        } if "all_publishers" in locals() else {}


def evaluate_overnight_for_all_publishers(
    client_lazer,
    feed_id: int,
    date: str,
    divisor: float,
    min_observations: int = SESSION_MIN_OBSERVATIONS,
    reference_publisher_id: int = OVERNIGHT_REFERENCE_PUBLISHER_ID,
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
                spread = ref_spread if ref_spread is not None and ref_spread > 0 else None
                reference_by_ts[ts] = (ref_price, spread)

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
            if ts not in reference_by_ts:
                continue

            ref_price, spread = reference_by_ts[ts]
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

            rmse_over_spread = rmse / mean_spread if mean_spread and mean_spread > 0 else None

            if nrmse is not None:
                passes = nrmse < 0.01 or (nrmse < 0.05 and hit_rate >= 98)
            else:
                passes = False

            results[pub_id] = OvernightMetrics(
                n_observations=n_observations,
                n_reference_observations=n_reference_observations,
                rmse=rmse,
                mean_spread=mean_spread,
                rmse_over_spread=rmse_over_spread,
                nrmse=nrmse,
                hit_rate=hit_rate,
                reference_price_range=reference_range,
                passes=passes,
                reference_publisher_id=reference_publisher_id,
                error=None,
            )

        return results

    except Exception as e:
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
                error=str(e),
            )
            for pub_id in all_publishers
        } if "all_publishers" in locals() else {}


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
    Deprecated: retained for compatibility.

    quick_benchmark.py now uses the two-query implementation for all evaluations.
    """

    return evaluate_feed_two_queries(
        client_lazer,
        client_analytics,
        feed_id,
        date,
        mode,
        target_pub_count=target_pub_count,
        tolerance_seconds=tolerance_seconds,
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
) -> BenchmarkResult:
    """Evaluate a feed across all publishers using aggregated one-second buckets."""

    start_time = time.time()
    mode = normalize_asset_class(mode)

    # Kept for signature compatibility; current implementation aligns by 1-second buckets.
    _ = tolerance_seconds

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
            if ts not in benchmark_by_ts:
                continue

            bench_price, spread = benchmark_by_ts[ts]
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
            mean_spread = (
                sum(metrics["spreads"]) / n_spreads if n_spreads > 0 else None
            )

            benchmark_range = max(metrics["benchmark_prices"]) - min(
                metrics["benchmark_prices"]
            )
            nrmse = rmse / benchmark_range if benchmark_range > 0 else None

            hits_within_10bps = sum(1 for pct in metrics["pct_diffs"] if pct <= 0.1)
            hit_rate = (hits_within_10bps / n_observations) * 100

            rmse_over_spread = (
                rmse / mean_spread if mean_spread and mean_spread > 0 else None
            )

            if nrmse is not None:
                passes = nrmse < 0.01 or (nrmse < 0.05 and hit_rate >= 98)
            else:
                passes = False

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

            if passes:
                passing_publishers.append(pub_id)
            else:
                failing_publishers.append(pub_id)

            publisher_details_internal.append(
                PublisherFeedMetrics(
                    publisher_id=pub_id,
                    n_observations=n_observations,
                    passes=passes,
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

        details_by_pub = {detail.publisher_id: detail for detail in publisher_details_internal}

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
            d.nrmse for d in publisher_details_internal if d.nrmse is not None and not d.error
        ]
        hit_rate_values = [
            d.hit_rate
            for d in publisher_details_internal
            if d.hit_rate is not None and not d.error
        ]

        median_nrmse = statistics.median(nrmse_values) if nrmse_values else None
        median_hit_rate = statistics.median(hit_rate_values) if hit_rate_values else None

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
            publisher_details=publisher_details_internal if include_detailed else None,
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
) -> list[BenchmarkResult]:
    """Process feeds from CSV file with parallel execution."""

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
                f"{result.median_nrmse:.4f}" if result.median_nrmse is not None else "N/A"
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

    write_results_csv(
        results,
        output_path,
        include_extended_hours=include_extended_hours,
        include_overnight=include_overnight,
        include_detailed=include_detailed,
    )

    return results


def write_results_csv(
    results: list[BenchmarkResult],
    output_path: Path,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    include_detailed: bool = False,
):
    """Write benchmark results to CSV file."""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    header = [
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
        "median_nrmse",
        "median_hit_rate",
    ]

    if include_extended_hours:
        header.extend(
            [
                "premarket_passing_count",
                "premarket_failing_count",
                "afterhours_passing_count",
                "afterhours_failing_count",
            ]
        )

    if include_overnight:
        header.extend(
            [
                "overnight_passing_count",
                "overnight_failing_count",
                "overnight_reference_publisher_id",
            ]
        )

    header.extend(["error", "execution_time_ms"])

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for r in sorted(results, key=lambda x: (x.date, x.feed_id)):
            row = [
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
                f"{r.median_nrmse:.6f}" if r.median_nrmse is not None else "",
                f"{r.median_hit_rate:.2f}" if r.median_hit_rate is not None else "",
            ]

            if include_extended_hours:
                row.extend(
                    [
                        r.premarket_passing_count if r.premarket_passing_count is not None else "",
                        r.premarket_failing_count if r.premarket_failing_count is not None else "",
                        r.afterhours_passing_count if r.afterhours_passing_count is not None else "",
                        r.afterhours_failing_count if r.afterhours_failing_count is not None else "",
                    ]
                )

            if include_overnight:
                row.extend(
                    [
                        r.overnight_passing_count if r.overnight_passing_count is not None else "",
                        r.overnight_failing_count if r.overnight_failing_count is not None else "",
                        r.overnight_reference_publisher_id
                        if r.overnight_reference_publisher_id is not None
                        else "",
                    ]
                )

            row.extend([r.error or "", r.execution_time_ms])
            writer.writerow(row)

        if include_detailed:
            writer.writerow([])
            writer.writerow(["PUBLISHER DETAIL"])

            detail_header = [
                "feed_id",
                "publisher_id",
                "date",
                "mode",
                "symbol",
                "passes",
                "n_observations",
                "nrmse",
                "hit_rate",
                "rmse",
                "mean_spread",
                "rmse_over_spread",
                "benchmark_price_range",
                "mean_diff",
                "std_diff",
                "mean_pct_diff",
                "std_pct_diff",
                "mae",
                "t_statistic",
                "t_pvalue",
                "wilcoxon_statistic",
                "wilcoxon_pvalue",
                "normality_pvalue",
                "mean_abs_z_score",
            ]

            if include_extended_hours:
                detail_header.extend(
                    [
                        "premarket_n_observations",
                        "premarket_nrmse",
                        "premarket_hit_rate",
                        "premarket_passes",
                        "premarket_error",
                        "afterhours_n_observations",
                        "afterhours_nrmse",
                        "afterhours_hit_rate",
                        "afterhours_passes",
                        "afterhours_error",
                    ]
                )

            if include_overnight:
                detail_header.extend(
                    [
                        "overnight_n_observations",
                        "overnight_n_reference_observations",
                        "overnight_nrmse",
                        "overnight_hit_rate",
                        "overnight_passes",
                        "overnight_reference_publisher_id",
                        "overnight_error",
                    ]
                )

            detail_header.append("error")
            writer.writerow(detail_header)

            for feed_result in sorted(results, key=lambda x: (x.date, x.feed_id)):
                details = feed_result.publisher_details or []
                for d in sorted(details, key=lambda x: x.publisher_id):
                    row = [
                        feed_result.feed_id,
                        d.publisher_id,
                        feed_result.date,
                        feed_result.mode,
                        feed_result.symbol or "",
                        d.passes,
                        d.n_observations,
                        f"{d.nrmse:.6f}" if d.nrmse is not None else "",
                        f"{d.hit_rate:.2f}" if d.hit_rate is not None else "",
                        f"{d.rmse:.6f}" if d.rmse is not None else "",
                        f"{d.mean_spread:.6f}" if d.mean_spread is not None else "",
                        f"{d.rmse_over_spread:.6f}" if d.rmse_over_spread is not None else "",
                        f"{d.benchmark_price_range:.6f}"
                        if d.benchmark_price_range is not None
                        else "",
                        f"{d.mean_diff:.8f}" if d.mean_diff is not None else "",
                        f"{d.std_diff:.8f}" if d.std_diff is not None else "",
                        f"{d.mean_pct_diff:.6f}" if d.mean_pct_diff is not None else "",
                        f"{d.std_pct_diff:.6f}" if d.std_pct_diff is not None else "",
                        f"{d.mae:.8f}" if d.mae is not None else "",
                        f"{d.t_statistic:.4f}" if d.t_statistic is not None else "",
                        f"{d.t_pvalue:.6f}" if d.t_pvalue is not None else "",
                        f"{d.wilcoxon_statistic:.4f}" if d.wilcoxon_statistic is not None else "",
                        f"{d.wilcoxon_pvalue:.6f}" if d.wilcoxon_pvalue is not None else "",
                        f"{d.normality_pvalue:.6f}" if d.normality_pvalue is not None else "",
                        f"{d.mean_abs_z_score:.4f}" if d.mean_abs_z_score is not None else "",
                    ]

                    if include_extended_hours:
                        pm = d.premarket_metrics
                        ah = d.afterhours_metrics
                        row.extend(
                            [
                                pm.n_observations if pm else "",
                                f"{pm.nrmse:.6f}" if pm and pm.nrmse is not None else "",
                                f"{pm.hit_rate:.2f}" if pm and pm.hit_rate is not None else "",
                                pm.passes if pm else "",
                                pm.error if pm else "",
                                ah.n_observations if ah else "",
                                f"{ah.nrmse:.6f}" if ah and ah.nrmse is not None else "",
                                f"{ah.hit_rate:.2f}" if ah and ah.hit_rate is not None else "",
                                ah.passes if ah else "",
                                ah.error if ah else "",
                            ]
                        )

                    if include_overnight:
                        on = d.overnight_metrics
                        row.extend(
                            [
                                on.n_observations if on else "",
                                on.n_reference_observations if on else "",
                                f"{on.nrmse:.6f}" if on and on.nrmse is not None else "",
                                f"{on.hit_rate:.2f}" if on and on.hit_rate is not None else "",
                                on.passes if on else "",
                                on.reference_publisher_id if on else "",
                                on.error if on else "",
                            ]
                        )

                    row.append(d.error or "")
                    writer.writerow(row)

    print(f"\nResults written to: {output_path}")


def _distribution_stats(values: list[float]) -> dict:
    """Compute summary distribution stats including p90/p95."""

    if not values:
        return {
            "median": None,
            "mean": None,
            "min": None,
            "max": None,
            "p90": None,
            "p95": None,
        }

    sorted_values = sorted(values)
    n = len(sorted_values)

    if n >= 2:
        try:
            q = statistics.quantiles(sorted_values, n=100)
            p90 = q[89]
            p95 = q[94]
        except statistics.StatisticsError:
            p90 = sorted_values[min(int(n * 0.90), n - 1)]
            p95 = sorted_values[min(int(n * 0.95), n - 1)]
    else:
        p90 = p95 = sorted_values[0]

    return {
        "median": statistics.median(sorted_values),
        "mean": statistics.mean(sorted_values),
        "min": min(sorted_values),
        "max": max(sorted_values),
        "p90": p90,
        "p95": p95,
    }


def compute_summary_stats(
    results: list[BenchmarkResult],
    total_time: float,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
) -> dict:
    """Compute comprehensive summary statistics for feed-level results."""

    total_feeds = len(results)
    error_count = sum(1 for r in results if r.error)
    ready_count = sum(1 for r in results if r.ready and not r.error)
    not_ready_count = sum(1 for r in results if not r.ready and not r.error)

    nrmse_values = [r.median_nrmse for r in results if r.median_nrmse is not None and not r.error]
    hit_rate_values = [
        r.median_hit_rate for r in results if r.median_hit_rate is not None and not r.error
    ]

    nrmse_stats = _distribution_stats(nrmse_values)
    hit_rate_stats = _distribution_stats(hit_rate_values)

    mode_stats: dict[str, dict[str, int]] = {}
    for r in results:
        mode = normalize_asset_class(r.mode)
        if mode not in mode_stats:
            mode_stats[mode] = {"ready": 0, "not_ready": 0, "error": 0}

        if r.error:
            mode_stats[mode]["error"] += 1
        elif r.ready:
            mode_stats[mode]["ready"] += 1
        else:
            mode_stats[mode]["not_ready"] += 1

    extended_hours_stats = {}
    if include_extended_hours:
        pm_pass = sum(r.premarket_passing_count or 0 for r in results)
        pm_fail = sum(r.premarket_failing_count or 0 for r in results)
        ah_pass = sum(r.afterhours_passing_count or 0 for r in results)
        ah_fail = sum(r.afterhours_failing_count or 0 for r in results)

        pm_total = pm_pass + pm_fail
        ah_total = ah_pass + ah_fail

        extended_hours_stats = {
            "premarket_pass": pm_pass,
            "premarket_fail": pm_fail,
            "premarket_total": pm_total,
            "premarket_pass_rate": (pm_pass / pm_total * 100) if pm_total > 0 else None,
            "afterhours_pass": ah_pass,
            "afterhours_fail": ah_fail,
            "afterhours_total": ah_total,
            "afterhours_pass_rate": (ah_pass / ah_total * 100) if ah_total > 0 else None,
        }

    overnight_stats = {}
    if include_overnight:
        on_pass = sum(r.overnight_passing_count or 0 for r in results)
        on_fail = sum(r.overnight_failing_count or 0 for r in results)
        on_total = on_pass + on_fail

        reference_id = next(
            (
                r.overnight_reference_publisher_id
                for r in results
                if r.overnight_reference_publisher_id is not None
            ),
            OVERNIGHT_REFERENCE_PUBLISHER_ID,
        )

        overnight_stats = {
            "pass": on_pass,
            "fail": on_fail,
            "total": on_total,
            "pass_rate": (on_pass / on_total * 100) if on_total > 0 else None,
            "reference_publisher_id": reference_id,
        }

    return {
        "total_feeds": total_feeds,
        "ready_count": ready_count,
        "not_ready_count": not_ready_count,
        "error_count": error_count,
        "nrmse": nrmse_stats,
        "hit_rate": hit_rate_stats,
        "mode_stats": mode_stats,
        "extended_hours": extended_hours_stats,
        "overnight": overnight_stats,
        "total_time_sec": total_time,
        "avg_time_ms": (total_time / total_feeds * 1000) if total_feeds > 0 else 0,
    }


def print_interpretation_guide(summary_stats: dict) -> None:
    """Print a concise interpretation guide for feed-level results."""

    print(f"\n{'='*70}")
    print("INTERPRETATION GUIDE")
    print(f"{'='*70}")

    print("PASS criteria per publisher: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 98%)")
    print("Feed is READY when passing publishers >= target publisher count.")

    median_nrmse = summary_stats.get("nrmse", {}).get("median")
    median_hit_rate = summary_stats.get("hit_rate", {}).get("median")

    if median_nrmse is not None:
        print(f"Median feed nrmse: {median_nrmse:.6f} (lower is better)")
        if median_nrmse < 0.01:
            print("Interpretation: strong benchmark alignment on median feed quality.")
        elif median_nrmse < 0.05:
            print("Interpretation: moderate alignment; hit rate becomes decisive.")
        else:
            print("Interpretation: broad quality gaps; investigate sources with high deviation.")

    if median_hit_rate is not None:
        print(f"Median feed hit_rate: {median_hit_rate:.2f}% (higher is better)")
        if median_hit_rate >= 98:
            print("Interpretation: benchmark tracking is generally tight.")
        elif median_hit_rate >= 95:
            print("Interpretation: acceptable but close to pass threshold risk.")
        else:
            print("Interpretation: frequent misses vs benchmark; review latency and pricing logic.")

    print("Suggested focus: investigate feeds with low median_hit_rate and high median_nrmse first.")


def main():
    parser = argparse.ArgumentParser(
        description="Feed-level benchmark evaluation for Lazer feeds",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process feeds from CSV file
  python quick_benchmark.py --csv price_id_list.csv

  # Process a single feed
  python quick_benchmark.py --feed-id 327 --date 2025-10-06 --mode fx

  # Include US-equity extended hours
  python quick_benchmark.py --feed-id 1163 --date 2025-10-02 --mode us-equities --extended-hours

  # Include overnight session against publisher 32
  python quick_benchmark.py --feed-id 1163 --date 2025-10-02 --mode us-equities --overnight

  # Skip scipy tests for faster runs
  python quick_benchmark.py --csv price_id_list.csv --skip-scipy-tests

  # Output detailed per-publisher rows
  python quick_benchmark.py --csv price_id_list.csv --detailed

  # Filter CSV run to specific feed IDs
  python quick_benchmark.py --csv price_id_list.csv --filter-feed-id 327 1163
""",
    )

    parser.add_argument("--csv", type=Path, help="CSV file containing feed_id,date,mode columns")
    parser.add_argument("--feed-id", type=int, help="Single feed ID to evaluate")
    parser.add_argument("--date", help="Date for single feed evaluation (YYYY-MM-DD)")
    parser.add_argument(
        "--mode",
        choices=[
            "fx",
            "metals",
            "us-equities",
            "commodity",
            "us-treasuries",
            "treasuries",
            "rates",
        ],
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
    parser.add_argument(
        "--include-asset-class",
        type=str,
        nargs="+",
        metavar="CLASS",
        help="Only process feeds with these asset classes",
    )
    parser.add_argument(
        "--exclude-asset-class",
        type=str,
        nargs="+",
        metavar="CLASS",
        help="Exclude feeds with these asset classes",
    )
    parser.add_argument(
        "--extended-hours",
        action="store_true",
        help="Include pre-market and after-hours evaluation for US equities",
    )
    parser.add_argument(
        "--overnight",
        action="store_true",
        help="Include overnight evaluation for US equities using publisher 32 as reference",
    )
    parser.add_argument(
        "--skip-scipy-tests",
        action="store_true",
        help="Skip t-test/Wilcoxon/normality tests for faster execution",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Append detailed per-publisher rows to CSV output",
    )
    parser.add_argument(
        "--filter-feed-id",
        type=int,
        nargs="+",
        metavar="ID",
        help="Only process these feed IDs when using --csv",
    )
    parser.add_argument(
        "--list-asset-classes",
        action="store_true",
        help="List unique asset classes in the CSV file and exit",
    )

    args = parser.parse_args()

    if args.list_asset_classes:
        if not args.csv:
            parser.error("--list-asset-classes requires --csv")
    elif args.csv and (args.feed_id or args.date or args.mode):
        parser.error("Use either --csv OR (--feed-id, --date, --mode), not both")
    elif not args.csv and not (args.feed_id and args.date and args.mode):
        parser.error("Either --csv or all of (--feed-id, --date, --mode) required")

    if not args.csv and (args.include_asset_class or args.exclude_asset_class):
        parser.error("--include-asset-class and --exclude-asset-class only apply to --csv mode")

    if not args.csv and args.filter_feed_id:
        parser.error("--filter-feed-id only applies to --csv mode")

    if args.include_asset_class and args.exclude_asset_class:
        include_set = {normalize_asset_class(ac) for ac in args.include_asset_class}
        exclude_set = {normalize_asset_class(ac) for ac in args.exclude_asset_class}
        overlap = include_set & exclude_set
        if overlap:
            parser.error(f"Asset classes cannot be both included and excluded: {overlap}")

    if args.csv and not args.csv.exists():
        print(f"Error: CSV file '{args.csv}' not found")
        sys.exit(1)

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

    if args.extended_hours or args.overnight:
        if args.csv:
            print(
                "Note: --extended-hours and --overnight only apply to us-equities feeds; "
                "other asset classes are evaluated normally."
            )
        else:
            if normalize_asset_class(args.mode) != "us-equities":
                print(
                    "Warning: --extended-hours/--overnight only apply to us-equities; "
                    "session metrics will be skipped for this run."
                )

    total_start = time.time()

    if args.csv:
        feed_id_filter = set(args.filter_feed_id) if args.filter_feed_id else None
        results = process_csv(
            args.csv,
            args.output,
            args.target_pub_count,
            args.workers,
            include_asset_classes=args.include_asset_class,
            exclude_asset_classes=args.exclude_asset_class,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            skip_scipy_tests=args.skip_scipy_tests,
            include_detailed=args.detailed,
            feed_id_filter=feed_id_filter,
        )
    else:
        config = load_config()
        client_lazer, client_analytics = get_clients(config)

        result = evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            args.feed_id,
            args.date,
            args.mode,
            target_pub_count=args.target_pub_count,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            skip_scipy_tests=args.skip_scipy_tests,
            include_detailed=args.detailed,
        )

        results = [result]
        write_results_csv(
            results,
            args.output,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            include_detailed=args.detailed,
        )

    total_time = time.time() - total_start
    summary = compute_summary_stats(
        results,
        total_time,
        include_extended_hours=args.extended_hours,
        include_overnight=args.overnight,
    )

    print(f"\n{'='*70}")
    print("PASS/FAIL CRITERIA")
    print(f"{'='*70}")
    print("Publisher passes if: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 98%)")
    print("Feed is READY if passing publishers >= target publisher count")

    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"Total feeds evaluated: {summary['total_feeds']}")
    print(f"Ready (PASS): {summary['ready_count']}")
    print(f"Not Ready (FAIL): {summary['not_ready_count']}")
    print(f"Errors: {summary['error_count']}")

    nrmse_stats = summary["nrmse"]
    if nrmse_stats["median"] is not None:
        print(
            "NRMSE distribution (feed medians): "
            f"median={nrmse_stats['median']:.6f}, mean={nrmse_stats['mean']:.6f}, "
            f"p90={nrmse_stats['p90']:.6f}, p95={nrmse_stats['p95']:.6f}"
        )
    else:
        print("NRMSE distribution (feed medians): no data")

    hit_rate_stats = summary["hit_rate"]
    if hit_rate_stats["median"] is not None:
        print(
            "Hit rate distribution (feed medians): "
            f"median={hit_rate_stats['median']:.2f}%, mean={hit_rate_stats['mean']:.2f}%, "
            f"min={hit_rate_stats['min']:.2f}%, max={hit_rate_stats['max']:.2f}%"
        )
    else:
        print("Hit rate distribution (feed medians): no data")

    print("\nPer-asset-class breakdown:")
    mode_stats = summary["mode_stats"]
    if mode_stats:
        for mode in sorted(mode_stats):
            stats = mode_stats[mode]
            print(
                f"  {mode:<15} ready={stats['ready']:<4} "
                f"not_ready={stats['not_ready']:<4} error={stats['error']:<4}"
            )
    else:
        print("  No feeds processed")

    if args.extended_hours:
        ext = summary["extended_hours"]
        print("\nExtended hours summary:")
        if ext.get("premarket_total", 0) > 0:
            print(
                f"  Pre-market: pass={ext['premarket_pass']} fail={ext['premarket_fail']} "
                f"pass_rate={ext['premarket_pass_rate']:.2f}%"
            )
        else:
            print("  Pre-market: no evaluable session data")

        if ext.get("afterhours_total", 0) > 0:
            print(
                f"  After-hours: pass={ext['afterhours_pass']} fail={ext['afterhours_fail']} "
                f"pass_rate={ext['afterhours_pass_rate']:.2f}%"
            )
        else:
            print("  After-hours: no evaluable session data")

    if args.overnight:
        overnight = summary["overnight"]
        print("\nOvernight summary:")
        if overnight.get("total", 0) > 0:
            print(
                f"  Reference publisher: {overnight['reference_publisher_id']}\n"
                f"  pass={overnight['pass']} fail={overnight['fail']} "
                f"pass_rate={overnight['pass_rate']:.2f}%"
            )
        else:
            print(
                f"  Reference publisher: {overnight.get('reference_publisher_id', OVERNIGHT_REFERENCE_PUBLISHER_ID)}\n"
                "  no evaluable overnight data"
            )

    print(f"\nTiming: total={summary['total_time_sec']:.2f}s, avg_per_feed={summary['avg_time_ms']:.0f}ms")

    print_interpretation_guide(summary)


if __name__ == "__main__":
    main()
