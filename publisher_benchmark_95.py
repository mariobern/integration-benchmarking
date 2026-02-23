#!/usr/bin/env python3
"""
Single-publisher benchmark evaluation script for Lazer feeds.

This script evaluates a SINGLE publisher's data quality against benchmark data (Datascope).
It is significantly faster than quick_benchmark.py because it only queries and evaluates
one publisher instead of all publishers.

The publisher ID can be extracted from CSV filename pattern: publisher_{id}_feeds.csv.
In single-feed mode (without CSV), publisher ID must be provided explicitly.

Pass/Fail Criteria:
- A publisher PASSES if: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 95%)
- nrmse = RMSE / (max_benchmark_price - min_benchmark_price)
- hit_rate = % of observations within 10 basis points (0.1%) of benchmark
- rmse_over_spread is reported as an additional metric but NOT used for pass/fail

Market Hours Filtering:
- US equities: Only regular trading hours (9:30 AM - 4:00 PM EST) are evaluated
- Other asset classes: Full day data is evaluated

Usage:
    python publisher_benchmark.py --csv publisher_55_feeds.csv
    python publisher_benchmark.py --csv feeds.csv --publisher-id 55
    python publisher_benchmark.py --publisher-id 55 --feed-id 327 --date 2025-10-06 --mode fx
"""

import argparse
import csv
import re
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import clickhouse_connect
import yaml
from scipy import stats

from date_utils import expand_date_args, validate_date_args


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
# F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun, N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec
FUTURES_MONTH_CODES = "FGHJKMNQUVXZ"

# US Equities market hours (EST/EDT) - Regular trading session only
US_EQUITY_MARKET_OPEN_HOUR = 9
US_EQUITY_MARKET_OPEN_MINUTE = 30
US_EQUITY_MARKET_CLOSE_HOUR = 16
US_EQUITY_MARKET_CLOSE_MINUTE = 0

# US Equities extended hours (EST/EDT)
# Pre-market: 4:00 AM - 9:30 AM EST
US_EQUITY_PREMARKET_OPEN_HOUR = 4
US_EQUITY_PREMARKET_OPEN_MINUTE = 0
# After-hours: 4:00 PM - 8:00 PM EST
US_EQUITY_AFTERHOURS_CLOSE_HOUR = 20
US_EQUITY_AFTERHOURS_CLOSE_MINUTE = 0
# Overnight: 8:00 PM - 4:00 AM EST (next day)
US_EQUITY_OVERNIGHT_START_HOUR = 20
US_EQUITY_OVERNIGHT_START_MINUTE = 0
US_EQUITY_OVERNIGHT_END_HOUR = 4
US_EQUITY_OVERNIGHT_END_MINUTE = 0

# Reference publisher for overnight benchmark (Blue Ocean ATS)
OVERNIGHT_REFERENCE_PUBLISHER_ID = 32


def is_futures_symbol(symbol: str) -> bool:
    """
    Detect if a symbol represents a futures contract.

    Futures symbols follow the pattern:
    - Commodities.XXX[MONTH][YEAR]/USD (e.g., Commodities.CCH6/USD - Copper March 2026)
    - Equity.US.XXX[MONTH][YEAR]/USD (e.g., Equity.US.EMH6/USD - E-Mini S&P March 2026)

    Where:
    - MONTH is one of F,G,H,J,K,M,N,Q,U,V,X,Z (monthly codes)
    - YEAR is a single digit (5=2025, 6=2026, 7=2027, etc.)

    Special equity index futures:
    - EM = E-Mini S&P 500
    - NM = Nasdaq Mini
    - DM = Dow Jones Mini

    Commodity futures:
    - CC = Copper
    - WTI = WTI Crude Oil
    - BRENT = Brent Crude Oil
    """
    if not symbol:
        return False

    # Extract base symbol (before /USD)
    if "/" in symbol:
        base = symbol.split("/")[0]
    else:
        base = symbol

    # Get the ticker part (after last .)
    parts = base.split(".")
    if len(parts) < 2:
        return False

    ticker = parts[-1]
    if len(ticker) < 2:
        return False

    # Check if ends with month code + year digit
    month_code = ticker[-2].upper()
    year_digit = ticker[-1]

    return month_code in FUTURES_MONTH_CODES and year_digit.isdigit()


@lru_cache(maxsize=128)
def get_market_hours_filter_sql(
    mode: str, date: str, column_name: str = "publish_time"
) -> str:
    """
    Generate SQL WHERE clause for market hours filtering.

    For US equities: 9:30 AM - 4:00 PM EST (converted to UTC)
    Returns empty string for non-equity modes.

    Results are cached to avoid regenerating the same filter SQL
    hundreds of times per publisher during batch processing.

    Args:
        mode: Asset class (e.g., 'us-equities', 'fx')
        date: Date string in YYYY-MM-DD format
        column_name: The timestamp column name to filter on

    Returns:
        SQL WHERE clause fragment or empty string
    """
    if mode not in ("us-equities", "equity-us"):
        return ""

    # Parse date and create timezone-aware datetimes
    dt = datetime.strptime(date, "%Y-%m-%d")
    est = ZoneInfo("America/New_York")
    utc = ZoneInfo("UTC")

    # Market open: 9:30 AM EST
    market_open_est = dt.replace(
        hour=US_EQUITY_MARKET_OPEN_HOUR, minute=US_EQUITY_MARKET_OPEN_MINUTE, tzinfo=est
    )
    market_open_utc = market_open_est.astimezone(utc)

    # Market close: 4:00 PM EST
    market_close_est = dt.replace(
        hour=US_EQUITY_MARKET_CLOSE_HOUR,
        minute=US_EQUITY_MARKET_CLOSE_MINUTE,
        tzinfo=est,
    )
    market_close_utc = market_close_est.astimezone(utc)

    return f"""
        AND {column_name} >= '{market_open_utc.strftime('%Y-%m-%d %H:%M:%S')}'
        AND {column_name} < '{market_close_utc.strftime('%Y-%m-%d %H:%M:%S')}'
    """


@lru_cache(maxsize=128)
def get_extended_hours_filter_sql(
    session: TradingSession, date: str, column_name: str = "publish_time"
) -> str:
    """
    Generate SQL WHERE clause for extended hours filtering.

    For US equities extended hours:
    - Pre-market: 4:00 AM - 9:30 AM EST
    - After-hours: 4:00 PM - 8:00 PM EST

    Results are cached to avoid regenerating the same filter SQL
    hundreds of times per publisher during batch processing.

    Args:
        session: Which extended hours session (PREMARKET or AFTERHOURS)
        date: Date string in YYYY-MM-DD format
        column_name: The timestamp column name to filter on

    Returns:
        SQL WHERE clause fragment
    """
    dt = datetime.strptime(date, "%Y-%m-%d")
    est = ZoneInfo("America/New_York")
    utc = ZoneInfo("UTC")

    if session == TradingSession.PREMARKET:
        # Pre-market: 4:00 AM - 9:30 AM EST
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
        # After-hours: 4:00 PM - 8:00 PM EST
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


@lru_cache(maxsize=128)
def get_overnight_hours_filter_sql(date: str, column_name: str = "publish_time") -> str:
    """
    Generate SQL WHERE clause for overnight hours filtering.

    Overnight session for US equities: 8:00 PM - 4:00 AM EST (next day).
    This spans two calendar days: 8 PM on the given date to 4 AM the next day.

    In UTC (EST = UTC-5 or EDT = UTC-4):
    - 8:00 PM EST = 01:00 UTC (next day)
    - 4:00 AM EST = 09:00 UTC (same day as UTC conversion)

    Results are cached to avoid regenerating the same filter SQL
    hundreds of times per publisher during batch processing.

    Args:
        date: Date string in YYYY-MM-DD format (the trading date, not the calendar date)
        column_name: The timestamp column name to filter on

    Returns:
        SQL WHERE clause fragment
    """
    from datetime import timedelta

    dt = datetime.strptime(date, "%Y-%m-%d")
    est = ZoneInfo("America/New_York")
    utc = ZoneInfo("UTC")

    # Overnight start: 8:00 PM EST on the given date
    overnight_start_est = dt.replace(
        hour=US_EQUITY_OVERNIGHT_START_HOUR,
        minute=US_EQUITY_OVERNIGHT_START_MINUTE,
        tzinfo=est,
    )

    # Overnight end: 4:00 AM EST the next day
    next_day = dt + timedelta(days=1)
    overnight_end_est = next_day.replace(
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
    """
    Determine which benchmark table to use based on mode and symbol.

    Returns:
        - 'datascope_futures_benchmark_data' for futures contracts
        - 'datascope_fx_benchmark_data' for fx/metals
        - 'datascope_us_treasury_benchmark_data' for us-treasuries
        - 'datascope_global_equities_benchmark_data' for us-equities (non-futures)
    """
    # Check if symbol is a futures contract
    if symbol and is_futures_symbol(symbol):
        return "datascope_futures_benchmark_data"

    # Fallback to existing logic
    if mode in ("fx", "metals"):
        return "datascope_fx_benchmark_data"
    elif mode == "us-treasuries":
        return "datascope_us_treasury_benchmark_data"
    else:
        return "datascope_global_equities_benchmark_data"


def get_benchmark_columns(mode: str) -> tuple[str, str, str]:
    """
    Get the correct column names for benchmark data based on mode.

    Treasuries use yield columns instead of price columns.

    Args:
        mode: The normalized asset class (e.g., 'fx', 'us-treasuries')

    Returns:
        Tuple of (price_column, bid_column, ask_column)
    """
    if mode == "us-treasuries":
        return ("yield", "bid_yield", "ask_yield")
    else:
        return ("price", "bid_price", "ask_price")


def compute_statistical_metrics(
    diffs: list[float],
    signed_pct_diffs: list[float],
    min_observations: int = 20,
) -> dict:
    """
    Compute advanced statistical metrics for price differences.

    Args:
        diffs: List of price differences (publisher - benchmark)
        signed_pct_diffs: List of signed percentage differences
        min_observations: Minimum observations for statistical tests

    Returns:
        Dictionary containing all computed metrics (None for metrics
        that couldn't be computed due to insufficient data)
    """
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

    # Basic statistics (always computed if n >= 2)
    result["mean_diff"] = statistics.mean(diffs)
    result["std_diff"] = statistics.stdev(diffs)
    result["mean_pct_diff"] = statistics.mean(signed_pct_diffs)
    result["std_pct_diff"] = statistics.stdev(signed_pct_diffs) if n >= 2 else None
    result["mae"] = statistics.mean([abs(d) for d in diffs])

    # Z-score calculation
    if result["std_diff"] and result["std_diff"] > 0:
        z_scores = [(d - result["mean_diff"]) / result["std_diff"] for d in diffs]
        result["mean_abs_z_score"] = statistics.mean([abs(z) for z in z_scores])

    # Statistical tests require minimum observations
    if n < min_observations:
        return result

    # One-sample t-test: Is mean difference significantly different from 0?
    try:
        t_stat, t_pval = stats.ttest_1samp(diffs, 0)
        result["t_statistic"] = float(t_stat)
        result["t_pvalue"] = float(t_pval)
    except Exception:
        pass  # Keep as None if test fails

    # Wilcoxon signed-rank test: Non-parametric alternative
    try:
        non_zero_diffs = [d for d in diffs if d != 0]
        if len(non_zero_diffs) >= min_observations:
            w_stat, w_pval = stats.wilcoxon(non_zero_diffs)
            result["wilcoxon_statistic"] = float(w_stat)
            result["wilcoxon_pvalue"] = float(w_pval)
    except Exception:
        pass  # Keep as None if test fails

    # D'Agostino-Pearson normality test
    try:
        _, norm_pval = stats.normaltest(diffs)
        result["normality_pvalue"] = float(norm_pval)
    except Exception:
        pass  # Keep as None if test fails

    return result


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
    """
    Metrics for overnight session (8 PM - 4 AM ET) using publisher 32 as benchmark.

    Unlike ExtendedHoursMetrics which uses Datascope as benchmark, overnight metrics
    use publisher 32 (Blue Ocean ATS) as the reference. This is a publisher-vs-publisher
    comparison, not an official benchmark comparison.
    """

    n_observations: int
    n_reference_observations: int  # How many observations from publisher 32
    rmse: Optional[float]
    mean_spread: Optional[float]  # Spread from reference publisher
    rmse_over_spread: Optional[float]
    nrmse: Optional[float]
    hit_rate: Optional[float]
    reference_price_range: Optional[float]
    passes: bool
    reference_publisher_id: int = OVERNIGHT_REFERENCE_PUBLISHER_ID
    error: Optional[str] = None


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
    # Metrics for enhanced pass/fail criteria
    nrmse: Optional[float] = None
    hit_rate: Optional[float] = None
    benchmark_price_range: Optional[float] = None
    # New statistical metrics
    mean_diff: Optional[float] = None  # Mean of price differences
    std_diff: Optional[float] = None  # Std dev of price differences
    mean_pct_diff: Optional[float] = None  # Mean of percentage differences
    std_pct_diff: Optional[float] = None  # Std dev of percentage differences
    mae: Optional[float] = None  # Mean Absolute Error
    # Statistical tests
    t_statistic: Optional[float] = None  # t-test statistic
    t_pvalue: Optional[float] = None  # t-test p-value
    wilcoxon_statistic: Optional[float] = None  # Wilcoxon signed-rank statistic
    wilcoxon_pvalue: Optional[float] = None  # Wilcoxon p-value
    normality_pvalue: Optional[
        float
    ] = None  # D'Agostino-Pearson normality test p-value
    mean_abs_z_score: Optional[float] = None  # Mean absolute z-score
    # Extended hours results (only populated when --extended-hours is used)
    premarket_metrics: Optional[ExtendedHoursMetrics] = None
    afterhours_metrics: Optional[ExtendedHoursMetrics] = None
    # Overnight results (only populated when --overnight is used)
    # Uses publisher 32 as benchmark instead of Datascope
    overnight_metrics: Optional[OvernightMetrics] = None
    error: Optional[str] = None
    execution_time_ms: int = 0


def compute_summary_stats(
    results: list[PublisherBenchmarkResult],
    publisher_id: int,
    total_time: float,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
) -> dict:
    """Compute comprehensive summary statistics from benchmark results."""
    # Basic counts - mutually exclusive: error > pass/fail
    total_feeds = len(results)
    error_count = sum(1 for r in results if r.error)
    pass_count = sum(1 for r in results if r.passes and not r.error)
    fail_count = sum(1 for r in results if not r.passes and not r.error)

    # Count passes by criterion type (for detailed breakdown)
    pass_by_nrmse_alone = sum(
        1
        for r in results
        if r.passes and not r.error and r.nrmse is not None and r.nrmse < 0.01
    )
    pass_by_nrmse_and_hit_rate = sum(
        1
        for r in results
        if r.passes
        and not r.error
        and r.nrmse is not None
        and r.nrmse >= 0.01
        and r.nrmse < 0.05
        and r.hit_rate is not None
        and r.hit_rate >= 95
    )

    # Filter results with valid rmse_over_spread for statistical calculations
    valid_results = [
        r for r in results if r.rmse_over_spread is not None and r.error is None
    ]
    valid_rmse_ratios = [r.rmse_over_spread for r in valid_results]

    # Calculate percentiles if we have data
    if valid_rmse_ratios:
        sorted_ratios = sorted(valid_rmse_ratios)
        median_rmse = statistics.median(sorted_ratios)
        mean_rmse = statistics.mean(sorted_ratios)
        min_rmse = min(sorted_ratios)
        max_rmse = max(sorted_ratios)

        # Calculate percentiles (90th and 95th) using proper statistical method
        n = len(sorted_ratios)
        if n >= 2:
            # Use quantiles for accurate percentile calculation
            # quantiles(data, n=100) returns 99 cut points for 100 quantiles
            try:
                quantile_values = statistics.quantiles(sorted_ratios, n=100)
                p90_rmse = quantile_values[89]  # 90th percentile (0-indexed)
                p95_rmse = quantile_values[94]  # 95th percentile (0-indexed)
            except statistics.StatisticsError:
                # Fall back to simple calculation for very small datasets
                p90_rmse = sorted_ratios[min(int(n * 0.90), n - 1)]
                p95_rmse = sorted_ratios[min(int(n * 0.95), n - 1)]
        else:
            # Single data point - all percentiles are the same value
            p90_rmse = p95_rmse = sorted_ratios[0]
    else:
        median_rmse = mean_rmse = min_rmse = max_rmse = p90_rmse = p95_rmse = None

    # NRMSE statistics
    valid_nrmse_results = [
        r for r in results if r.nrmse is not None and r.error is None
    ]
    valid_nrmse_values = [r.nrmse for r in valid_nrmse_results]

    if valid_nrmse_values:
        sorted_nrmse = sorted(valid_nrmse_values)
        median_nrmse = statistics.median(sorted_nrmse)
        mean_nrmse = statistics.mean(sorted_nrmse)
        min_nrmse = min(sorted_nrmse)
        max_nrmse = max(sorted_nrmse)

        n = len(sorted_nrmse)
        if n >= 2:
            try:
                quantile_values = statistics.quantiles(sorted_nrmse, n=100)
                p90_nrmse = quantile_values[89]
                p95_nrmse = quantile_values[94]
            except statistics.StatisticsError:
                p90_nrmse = sorted_nrmse[min(int(n * 0.90), n - 1)]
                p95_nrmse = sorted_nrmse[min(int(n * 0.95), n - 1)]
        else:
            p90_nrmse = p95_nrmse = sorted_nrmse[0]
    else:
        median_nrmse = mean_nrmse = min_nrmse = max_nrmse = p90_nrmse = p95_nrmse = None

    # Hit rate statistics
    valid_hit_rate_results = [
        r for r in results if r.hit_rate is not None and r.error is None
    ]
    valid_hit_rates = [r.hit_rate for r in valid_hit_rate_results]

    if valid_hit_rates:
        median_hit_rate = statistics.median(valid_hit_rates)
        mean_hit_rate = statistics.mean(valid_hit_rates)
        min_hit_rate = min(valid_hit_rates)
        max_hit_rate = max(valid_hit_rates)
    else:
        median_hit_rate = mean_hit_rate = min_hit_rate = max_hit_rate = None

    # Observation statistics - only from non-error results with actual data
    observations = [
        r.n_observations for r in results if r.error is None and r.n_observations > 0
    ]
    total_observations = sum(observations) if observations else 0
    mean_observations = statistics.mean(observations) if observations else 0
    median_observations = statistics.median(observations) if observations else 0

    # Breakdown by asset class (mode)
    mode_stats: dict[str, dict[str, int]] = {}
    for r in results:
        normalized_mode = normalize_asset_class(r.mode)
        if normalized_mode not in mode_stats:
            mode_stats[normalized_mode] = {"pass": 0, "fail": 0, "error": 0}
        if r.error:
            mode_stats[normalized_mode]["error"] += 1
        elif r.passes:
            mode_stats[normalized_mode]["pass"] += 1
        else:
            mode_stats[normalized_mode]["fail"] += 1

    # MAE statistics
    valid_mae_results = [r for r in results if r.mae is not None and r.error is None]
    valid_mae_values = [r.mae for r in valid_mae_results]

    if valid_mae_values:
        sorted_mae = sorted(valid_mae_values)
        median_mae = statistics.median(sorted_mae)
        mean_mae = statistics.mean(sorted_mae)
        n = len(sorted_mae)
        if n >= 2:
            try:
                quantile_values = statistics.quantiles(sorted_mae, n=100)
                p90_mae = quantile_values[89]
                p95_mae = quantile_values[94]
            except statistics.StatisticsError:
                p90_mae = sorted_mae[min(int(n * 0.90), n - 1)]
                p95_mae = sorted_mae[min(int(n * 0.95), n - 1)]
        else:
            p90_mae = p95_mae = sorted_mae[0]
    else:
        median_mae = mean_mae = p90_mae = p95_mae = None

    # Mean difference statistics
    valid_mean_diff = [
        r.mean_diff for r in results if r.mean_diff is not None and r.error is None
    ]
    if valid_mean_diff:
        median_mean_diff = statistics.median(valid_mean_diff)
        mean_mean_diff = statistics.mean(valid_mean_diff)
    else:
        median_mean_diff = mean_mean_diff = None

    # T-test summary (count of significant results)
    significant_t_tests = sum(
        1
        for r in results
        if r.t_pvalue is not None and r.t_pvalue < 0.05 and r.error is None
    )
    total_t_tests = sum(
        1 for r in results if r.t_pvalue is not None and r.error is None
    )

    # Normality test summary
    normal_distributions = sum(
        1
        for r in results
        if r.normality_pvalue is not None
        and r.normality_pvalue >= 0.05
        and r.error is None
    )
    total_normality_tests = sum(
        1 for r in results if r.normality_pvalue is not None and r.error is None
    )

    # Mean absolute z-score statistics
    valid_z_scores = [
        r.mean_abs_z_score
        for r in results
        if r.mean_abs_z_score is not None and r.error is None
    ]
    if valid_z_scores:
        median_z_score = statistics.median(valid_z_scores)
        mean_z_score = statistics.mean(valid_z_scores)
    else:
        median_z_score = mean_z_score = None

    # Extended hours statistics (only for US equities when enabled)
    extended_hours_stats = {}
    if include_extended_hours:
        # Filter US equity results with extended hours data
        us_equity_results = [
            r
            for r in results
            if normalize_asset_class(r.mode) == "us-equities" and r.error is None
        ]

        # Pre-market statistics
        premarket_results = [
            r.premarket_metrics for r in us_equity_results if r.premarket_metrics
        ]
        pm_pass = sum(1 for pm in premarket_results if pm.passes and not pm.error)
        pm_fail = sum(1 for pm in premarket_results if not pm.passes and not pm.error)
        pm_error = sum(1 for pm in premarket_results if pm.error)
        pm_total = len(premarket_results)

        pm_nrmse_values = [
            pm.nrmse
            for pm in premarket_results
            if pm.nrmse is not None and not pm.error
        ]
        pm_hit_rate_values = [
            pm.hit_rate
            for pm in premarket_results
            if pm.hit_rate is not None and not pm.error
        ]

        extended_hours_stats["premarket_total_feeds"] = pm_total
        extended_hours_stats["premarket_pass_count"] = pm_pass
        extended_hours_stats["premarket_fail_count"] = pm_fail
        extended_hours_stats["premarket_error_count"] = pm_error
        extended_hours_stats["premarket_pass_rate_pct"] = (
            round((pm_pass / pm_total * 100), 2) if pm_total > 0 else 0
        )
        extended_hours_stats["premarket_median_nrmse"] = (
            statistics.median(pm_nrmse_values) if pm_nrmse_values else None
        )
        extended_hours_stats["premarket_median_hit_rate"] = (
            statistics.median(pm_hit_rate_values) if pm_hit_rate_values else None
        )

        # After-hours statistics
        afterhours_results = [
            r.afterhours_metrics for r in us_equity_results if r.afterhours_metrics
        ]
        ah_pass = sum(1 for ah in afterhours_results if ah.passes and not ah.error)
        ah_fail = sum(1 for ah in afterhours_results if not ah.passes and not ah.error)
        ah_error = sum(1 for ah in afterhours_results if ah.error)
        ah_total = len(afterhours_results)

        ah_nrmse_values = [
            ah.nrmse
            for ah in afterhours_results
            if ah.nrmse is not None and not ah.error
        ]
        ah_hit_rate_values = [
            ah.hit_rate
            for ah in afterhours_results
            if ah.hit_rate is not None and not ah.error
        ]

        extended_hours_stats["afterhours_total_feeds"] = ah_total
        extended_hours_stats["afterhours_pass_count"] = ah_pass
        extended_hours_stats["afterhours_fail_count"] = ah_fail
        extended_hours_stats["afterhours_error_count"] = ah_error
        extended_hours_stats["afterhours_pass_rate_pct"] = (
            round((ah_pass / ah_total * 100), 2) if ah_total > 0 else 0
        )
        extended_hours_stats["afterhours_median_nrmse"] = (
            statistics.median(ah_nrmse_values) if ah_nrmse_values else None
        )
        extended_hours_stats["afterhours_median_hit_rate"] = (
            statistics.median(ah_hit_rate_values) if ah_hit_rate_values else None
        )

    # Overnight statistics (only for US equities when enabled, uses publisher 32 as benchmark)
    overnight_stats = {}
    if include_overnight:
        # Filter US equity results with overnight data
        us_equity_results = [
            r
            for r in results
            if normalize_asset_class(r.mode) == "us-equities" and r.error is None
        ]

        overnight_results = [
            r.overnight_metrics for r in us_equity_results if r.overnight_metrics
        ]
        on_pass = sum(1 for on in overnight_results if on.passes and not on.error)
        on_fail = sum(1 for on in overnight_results if not on.passes and not on.error)
        on_error = sum(1 for on in overnight_results if on.error)
        on_total = len(overnight_results)

        on_nrmse_values = [
            on.nrmse
            for on in overnight_results
            if on.nrmse is not None and not on.error
        ]
        on_hit_rate_values = [
            on.hit_rate
            for on in overnight_results
            if on.hit_rate is not None and not on.error
        ]

        overnight_stats["overnight_total_feeds"] = on_total
        overnight_stats["overnight_pass_count"] = on_pass
        overnight_stats["overnight_fail_count"] = on_fail
        overnight_stats["overnight_error_count"] = on_error
        overnight_stats["overnight_pass_rate_pct"] = (
            round((on_pass / on_total * 100), 2) if on_total > 0 else 0
        )
        overnight_stats["overnight_median_nrmse"] = (
            statistics.median(on_nrmse_values) if on_nrmse_values else None
        )
        overnight_stats["overnight_median_hit_rate"] = (
            statistics.median(on_hit_rate_values) if on_hit_rate_values else None
        )
        overnight_stats[
            "overnight_reference_publisher_id"
        ] = OVERNIGHT_REFERENCE_PUBLISHER_ID

    per_date_breakdown: dict[str, dict[str, int | float | None]] = {}
    results_by_date: dict[str, list[PublisherBenchmarkResult]] = {}
    for result in results:
        results_by_date.setdefault(result.date, []).append(result)

    for date_value in sorted(results_by_date):
        date_results = results_by_date[date_value]
        date_total = len(date_results)
        date_pass = sum(1 for r in date_results if r.passes and not r.error)
        date_fail = sum(1 for r in date_results if not r.passes and not r.error)
        date_error = sum(1 for r in date_results if r.error)
        date_nrmse = [
            r.nrmse for r in date_results if r.nrmse is not None and not r.error
        ]
        date_hit_rate = [
            r.hit_rate for r in date_results if r.hit_rate is not None and not r.error
        ]

        per_date_breakdown[date_value] = {
            "total": date_total,
            "pass": date_pass,
            "fail": date_fail,
            "error": date_error,
            "pass_rate_pct": round((date_pass / date_total * 100), 2)
            if date_total > 0
            else 0,
            "median_nrmse": statistics.median(date_nrmse) if date_nrmse else None,
            "median_hit_rate": statistics.median(date_hit_rate)
            if date_hit_rate
            else None,
        }

    return {
        "publisher_id": publisher_id,
        "total_feeds": total_feeds,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "pass_rate_pct": round((pass_count / total_feeds * 100), 2)
        if total_feeds > 0
        else 0,
        # Pass criteria breakdown
        "pass_by_nrmse_alone": pass_by_nrmse_alone,
        "pass_by_nrmse_and_hit_rate": pass_by_nrmse_and_hit_rate,
        # NRMSE statistics
        "median_nrmse": median_nrmse,
        "mean_nrmse": mean_nrmse,
        "p90_nrmse": p90_nrmse,
        "p95_nrmse": p95_nrmse,
        "min_nrmse": min_nrmse,
        "max_nrmse": max_nrmse,
        # Hit rate statistics
        "median_hit_rate": median_hit_rate,
        "mean_hit_rate": mean_hit_rate,
        "min_hit_rate": min_hit_rate,
        "max_hit_rate": max_hit_rate,
        # rmse_over_spread statistics (legacy, for reference)
        "median_rmse_over_spread": median_rmse,
        "mean_rmse_over_spread": mean_rmse,
        "p90_rmse_over_spread": p90_rmse,
        "p95_rmse_over_spread": p95_rmse,
        "min_rmse_over_spread": min_rmse,
        "max_rmse_over_spread": max_rmse,
        # Coverage metrics
        "total_observations": total_observations,
        "mean_observations_per_feed": round(mean_observations, 1)
        if mean_observations
        else 0,
        "median_observations_per_feed": int(median_observations)
        if median_observations
        else 0,
        "total_time_sec": round(total_time, 2),
        "avg_time_per_feed_ms": int((total_time / total_feeds * 1000))
        if total_feeds > 0
        else 0,
        "mode_stats": mode_stats,
        # New statistical metrics
        "median_mae": median_mae,
        "mean_mae": mean_mae,
        "p90_mae": p90_mae,
        "p95_mae": p95_mae,
        "median_mean_diff": median_mean_diff,
        "mean_mean_diff": mean_mean_diff,
        "significant_t_tests": significant_t_tests,
        "total_t_tests": total_t_tests,
        "t_test_significance_rate": round(
            (significant_t_tests / total_t_tests * 100), 2
        )
        if total_t_tests > 0
        else None,
        "normal_distributions": normal_distributions,
        "total_normality_tests": total_normality_tests,
        "normality_rate": round((normal_distributions / total_normality_tests * 100), 2)
        if total_normality_tests > 0
        else None,
        "median_z_score": median_z_score,
        "mean_z_score": mean_z_score,
        "per_date_breakdown": per_date_breakdown,
        # Extended hours statistics (empty dict if not enabled)
        "extended_hours": extended_hours_stats,
        # Overnight statistics (empty dict if not enabled)
        "overnight": overnight_stats,
    }


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


def get_symbols_for_feeds(
    client_lazer, feed_ids: list[int]
) -> dict[int, Optional[str]]:
    """
    Batch query symbols for multiple feed IDs.

    Args:
        client_lazer: ClickHouse client for Lazer cluster
        feed_ids: List of feed IDs to look up

    Returns:
        Dictionary mapping feed_id -> symbol (or None if not found)
    """
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
    """
    Evaluate metrics for a single trading session.

    Returns:
        Tuple of (n_observations, rmse, mean_spread, rmse_over_spread,
                  nrmse, hit_rate, benchmark_price_range, error)
    """
    # Get correct column names for this mode (treasuries use yield columns)
    price_col, bid_col, ask_col = get_benchmark_columns(mode)

    # Query publisher prices
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

    # Query benchmark prices (uses yield columns for treasuries, price columns otherwise)
    # Allow rows with only price (no bid/ask) for extended hours trade-only data
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
                f"No publisher data for session",
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

        # Build benchmark lookup dict (allow rows with price but no spread)
        benchmark_by_ts = {
            row[0]: (row[1], row[2])
            for row in bench_result.result_rows
            if row[1] is not None
        }

        # Compute metrics
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
) -> OvernightMetrics:
    """
    Evaluate a publisher's overnight session data against publisher 32 (Blue Ocean ATS).

    Unlike Datascope benchmarking, this queries both the target publisher and the
    reference publisher from the same publisher_updates table on the Lazer cluster.

    Args:
        client_lazer: ClickHouse client for Lazer cluster
        publisher_id: The publisher to evaluate
        feed_id: The feed ID to evaluate
        date: Date string in YYYY-MM-DD format
        divisor: Price divisor (10^|exponent|)
        min_observations: Minimum observations required for valid metrics
        reference_publisher_id: Publisher ID to use as benchmark (default: 32)

    Returns:
        OvernightMetrics with evaluation results
    """
    # Get overnight time filter
    overnight_filter = get_overnight_hours_filter_sql(date, "publish_time")

    # Query publisher prices for overnight session
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

    # Query reference publisher (32) prices for overnight session
    # Include spread data from bid/ask if available
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

        # Build reference lookup dict
        # reference_by_ts: ts -> (price, spread)
        reference_by_ts = {}
        for row in ref_result.result_rows:
            ts, ref_price, ref_spread, _ = row
            if ref_price is not None:
                # Use a default spread if bid/ask not available
                spread = (
                    ref_spread if ref_spread is not None and ref_spread > 0 else None
                )
                reference_by_ts[ts] = (ref_price, spread)

        n_reference_observations = len(reference_by_ts)

        # Compute metrics
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

        # Apply same pass/fail criteria as regular sessions
        if nrmse is not None:
            passes = nrmse < 0.01 or (nrmse < 0.05 and hit_rate >= 95)
        else:
            passes = False

        return OvernightMetrics(
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
) -> PublisherBenchmarkResult:
    """
    Evaluate a single publisher's data quality for one feed.

    This is significantly faster than quick_benchmark.py because it only
    queries data for ONE publisher instead of all publishers.

    Args:
        client_lazer: ClickHouse client for Lazer cluster
        client_analytics: ClickHouse client for Analytics cluster (Datascope)
        publisher_id: The publisher to evaluate
        feed_id: The feed ID to evaluate
        date: Date string in YYYY-MM-DD format
        mode: Asset class (fx, metals, us-equities, etc.)
        include_extended_hours: If True, evaluate pre-market and after-hours sessions
        include_overnight: If True, evaluate overnight session using publisher 32 as benchmark
        skip_scipy_tests: If True, skip scipy statistical tests for faster execution
    """
    start_time = time.time()

    # Normalize mode early for consistent handling throughout the function
    mode = normalize_asset_class(mode)

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

    # Determine benchmark table based on mode and symbol (handles futures detection)
    benchmark_table = get_benchmark_table(mode, symbol)

    # Get correct column names for this mode (treasuries use yield columns)
    price_col, bid_col, ask_col = get_benchmark_columns(mode)

    # Get market hours filter for US equities (regular trading session only)
    publisher_market_filter = get_market_hours_filter_sql(mode, date, "publish_time")
    benchmark_market_filter = get_market_hours_filter_sql(mode, date, "date_time")

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
          {publisher_market_filter}
        GROUP BY ts_second
        ORDER BY ts_second
    """

    # Query 2: Get benchmark prices aggregated by second (uses yield columns for treasuries)
    # Allow rows with only price (no bid/ask) for extended hours trade-only data
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

        # Build benchmark lookup dict (allow rows with price but no spread)
        benchmark_by_ts = {
            row[0]: (row[1], row[2])
            for row in bench_result.result_rows
            if row[1] is not None
        }

        # Compute metrics for this publisher
        squared_errors = []
        spreads = []
        pct_diffs = []  # For hit_rate calculation (absolute)
        benchmark_prices = []  # For nrmse calculation
        diffs = []  # Raw price differences for statistical tests
        signed_pct_diffs = []  # Signed percentage differences

        for row in pub_result.result_rows:
            ts, pub_price, _ = row

            if ts not in benchmark_by_ts:
                continue

            bench_price, spread = benchmark_by_ts[ts]
            diff = pub_price - bench_price
            pct_diff = abs(diff / bench_price) * 100  # Percentage difference (absolute)
            signed_pct_diff = (diff / bench_price) * 100  # Signed percentage difference

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

        # Calculate nrmse (RMSE normalized by benchmark price range)
        benchmark_range = max(benchmark_prices) - min(benchmark_prices)
        if benchmark_range > 0:
            nrmse = rmse / benchmark_range
        else:
            nrmse = None

        # Calculate hit_rate (% within 10 basis points = 0.1%)
        hits_within_10bps = sum(1 for pct in pct_diffs if pct <= 0.1)
        hit_rate = (hits_within_10bps / n_observations) * 100

        # Calculate rmse_over_spread (additional metric, not required for pass)
        if mean_spread and mean_spread > 0:
            rmse_over_spread = rmse / mean_spread
        else:
            rmse_over_spread = None

        # New pass/fail logic:
        # passes if: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 95)
        if nrmse is not None:
            passes = nrmse < 0.01 or (nrmse < 0.05 and hit_rate >= 95)
        else:
            passes = False

        # Compute advanced statistical metrics (skip if requested for faster execution)
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

        # Evaluate extended hours if requested and applicable (US equities only)
        premarket_metrics = None
        afterhours_metrics = None

        if include_extended_hours and mode in ("us-equities", "equity-us"):
            # Pre-market evaluation (4:00 AM - 9:30 AM EST)
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
                min_observations=50,  # Lower threshold for extended hours
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

            # Determine pass/fail for pre-market
            if pm_nrmse is not None and pm_hr is not None:
                pm_passes = pm_nrmse < 0.01 or (pm_nrmse < 0.05 and pm_hr >= 95)
            else:
                pm_passes = False

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

            # After-hours evaluation (4:00 PM - 8:00 PM EST)
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
                min_observations=50,  # Lower threshold for extended hours
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

            # Determine pass/fail for after-hours
            if ah_nrmse is not None and ah_hr is not None:
                ah_passes = ah_nrmse < 0.01 or (ah_nrmse < 0.05 and ah_hr >= 95)
            else:
                ah_passes = False

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

        # Evaluate overnight session if requested and applicable (US equities only)
        # Uses publisher 32 (Blue Ocean ATS) as benchmark instead of Datascope
        overnight_metrics = None

        if include_overnight and mode in ("us-equities", "equity-us"):
            # Skip overnight evaluation if the publisher being evaluated IS the reference
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
                    min_observations=50,  # Lower threshold for overnight
                )

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

            # Apply asset class filters
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

    # Apply feed ID filter if provided
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


def write_results_csv(
    results: list[PublisherBenchmarkResult],
    output_path: Path,
    summary_stats: Optional[dict] = None,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
):
    """Write benchmark results to CSV file with optional summary section."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Define header columns (used for both output and padding summary rows)
    header = [
        "publisher_id",
        "feed_id",
        "date",
        "mode",
        "symbol",
        "passes",
        "n_observations",
        "nrmse",
        "hit_rate",
        "benchmark_price_range",
        "rmse",
        "mean_spread",
        "rmse_over_spread",
        # New statistical metrics
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

    # Add extended hours columns if enabled
    if include_extended_hours:
        header.extend(
            [
                # Pre-market columns
                "premarket_n_observations",
                "premarket_nrmse",
                "premarket_hit_rate",
                "premarket_passes",
                "premarket_error",
                # After-hours columns
                "afterhours_n_observations",
                "afterhours_nrmse",
                "afterhours_hit_rate",
                "afterhours_passes",
                "afterhours_error",
            ]
        )

    # Add overnight columns if enabled (uses publisher 32 as benchmark)
    if include_overnight:
        header.extend(
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

    header.extend(["error", "execution_time_ms"])
    num_cols = len(header)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for r in sorted(results, key=lambda x: (x.date, x.feed_id)):
            row = [
                r.publisher_id,
                r.feed_id,
                r.date,
                r.mode,
                r.symbol or "",
                r.passes,
                r.n_observations,
                f"{r.nrmse:.6f}" if r.nrmse is not None else "",
                f"{r.hit_rate:.2f}" if r.hit_rate is not None else "",
                f"{r.benchmark_price_range:.6f}"
                if r.benchmark_price_range is not None
                else "",
                f"{r.rmse:.6f}" if r.rmse is not None else "",
                f"{r.mean_spread:.6f}" if r.mean_spread is not None else "",
                f"{r.rmse_over_spread:.6f}" if r.rmse_over_spread is not None else "",
                # New statistical metrics
                f"{r.mean_diff:.8f}" if r.mean_diff is not None else "",
                f"{r.std_diff:.8f}" if r.std_diff is not None else "",
                f"{r.mean_pct_diff:.6f}" if r.mean_pct_diff is not None else "",
                f"{r.std_pct_diff:.6f}" if r.std_pct_diff is not None else "",
                f"{r.mae:.8f}" if r.mae is not None else "",
                f"{r.t_statistic:.4f}" if r.t_statistic is not None else "",
                f"{r.t_pvalue:.6f}" if r.t_pvalue is not None else "",
                f"{r.wilcoxon_statistic:.4f}"
                if r.wilcoxon_statistic is not None
                else "",
                f"{r.wilcoxon_pvalue:.6f}" if r.wilcoxon_pvalue is not None else "",
                f"{r.normality_pvalue:.6f}" if r.normality_pvalue is not None else "",
                f"{r.mean_abs_z_score:.4f}" if r.mean_abs_z_score is not None else "",
            ]

            # Add extended hours data if enabled
            if include_extended_hours:
                pm = r.premarket_metrics
                ah = r.afterhours_metrics
                row.extend(
                    [
                        # Pre-market
                        pm.n_observations if pm else "",
                        f"{pm.nrmse:.6f}" if pm and pm.nrmse is not None else "",
                        f"{pm.hit_rate:.2f}" if pm and pm.hit_rate is not None else "",
                        pm.passes if pm else "",
                        pm.error or "" if pm else "",
                        # After-hours
                        ah.n_observations if ah else "",
                        f"{ah.nrmse:.6f}" if ah and ah.nrmse is not None else "",
                        f"{ah.hit_rate:.2f}" if ah and ah.hit_rate is not None else "",
                        ah.passes if ah else "",
                        ah.error or "" if ah else "",
                    ]
                )

            # Add overnight data if enabled
            if include_overnight:
                on = r.overnight_metrics
                row.extend(
                    [
                        on.n_observations if on else "",
                        on.n_reference_observations if on else "",
                        f"{on.nrmse:.6f}" if on and on.nrmse is not None else "",
                        f"{on.hit_rate:.2f}" if on and on.hit_rate is not None else "",
                        on.passes if on else "",
                        on.reference_publisher_id if on else "",
                        on.error or "" if on else "",
                    ]
                )

            row.extend([r.error or "", r.execution_time_ms])
            writer.writerow(row)

        # Write summary section if provided
        if summary_stats:
            # Empty row separator
            writer.writerow([""] * num_cols)

            # Summary header
            writer.writerow(["SUMMARY"] + [""] * (num_cols - 1))

            # Helper to write a summary row
            def write_summary_row(key: str, value):
                if value is None:
                    formatted_value = ""
                elif isinstance(value, float):
                    formatted_value = f"{value:.6f}"
                else:
                    formatted_value = str(value)
                writer.writerow([key, formatted_value] + [""] * (num_cols - 2))

            # Core metrics
            write_summary_row("publisher_id", summary_stats["publisher_id"])
            write_summary_row("total_feeds", summary_stats["total_feeds"])
            write_summary_row("pass_count", summary_stats["pass_count"])
            write_summary_row("fail_count", summary_stats["fail_count"])
            write_summary_row("error_count", summary_stats["error_count"])
            write_summary_row("pass_rate_pct", summary_stats["pass_rate_pct"])

            # Pass criteria breakdown
            write_summary_row(
                "pass_by_nrmse_alone", summary_stats["pass_by_nrmse_alone"]
            )
            write_summary_row(
                "pass_by_nrmse_and_hit_rate",
                summary_stats["pass_by_nrmse_and_hit_rate"],
            )

            # NRMSE quality metrics (primary)
            write_summary_row("median_nrmse", summary_stats["median_nrmse"])
            write_summary_row("mean_nrmse", summary_stats["mean_nrmse"])
            write_summary_row("p90_nrmse", summary_stats["p90_nrmse"])
            write_summary_row("p95_nrmse", summary_stats["p95_nrmse"])
            write_summary_row("min_nrmse", summary_stats["min_nrmse"])
            write_summary_row("max_nrmse", summary_stats["max_nrmse"])

            # Hit rate metrics
            write_summary_row("median_hit_rate", summary_stats["median_hit_rate"])
            write_summary_row("mean_hit_rate", summary_stats["mean_hit_rate"])
            write_summary_row("min_hit_rate", summary_stats["min_hit_rate"])
            write_summary_row("max_hit_rate", summary_stats["max_hit_rate"])

            # RMSE over spread metrics (reference, not used for pass/fail)
            write_summary_row(
                "median_rmse_over_spread", summary_stats["median_rmse_over_spread"]
            )
            write_summary_row(
                "mean_rmse_over_spread", summary_stats["mean_rmse_over_spread"]
            )
            write_summary_row(
                "p90_rmse_over_spread", summary_stats["p90_rmse_over_spread"]
            )
            write_summary_row(
                "p95_rmse_over_spread", summary_stats["p95_rmse_over_spread"]
            )
            write_summary_row(
                "min_rmse_over_spread", summary_stats["min_rmse_over_spread"]
            )
            write_summary_row(
                "max_rmse_over_spread", summary_stats["max_rmse_over_spread"]
            )

            # Coverage metrics
            write_summary_row("total_observations", summary_stats["total_observations"])
            write_summary_row(
                "mean_observations_per_feed",
                summary_stats["mean_observations_per_feed"],
            )
            write_summary_row(
                "median_observations_per_feed",
                summary_stats["median_observations_per_feed"],
            )

            # Timing metrics
            write_summary_row("total_time_sec", summary_stats["total_time_sec"])
            write_summary_row(
                "avg_time_per_feed_ms", summary_stats["avg_time_per_feed_ms"]
            )

            # New statistical summary metrics
            write_summary_row("median_mae", summary_stats.get("median_mae"))
            write_summary_row("mean_mae", summary_stats.get("mean_mae"))
            write_summary_row("p90_mae", summary_stats.get("p90_mae"))
            write_summary_row("p95_mae", summary_stats.get("p95_mae"))
            write_summary_row("median_mean_diff", summary_stats.get("median_mean_diff"))
            write_summary_row("mean_mean_diff", summary_stats.get("mean_mean_diff"))
            write_summary_row(
                "significant_t_tests", summary_stats.get("significant_t_tests")
            )
            write_summary_row("total_t_tests", summary_stats.get("total_t_tests"))
            write_summary_row(
                "t_test_significance_rate",
                summary_stats.get("t_test_significance_rate"),
            )
            write_summary_row(
                "normal_distributions", summary_stats.get("normal_distributions")
            )
            write_summary_row(
                "total_normality_tests", summary_stats.get("total_normality_tests")
            )
            write_summary_row("normality_rate", summary_stats.get("normality_rate"))
            write_summary_row("median_z_score", summary_stats.get("median_z_score"))
            write_summary_row("mean_z_score", summary_stats.get("mean_z_score"))

            # Breakdown by asset class
            mode_stats = summary_stats.get("mode_stats", {})
            for mode in sorted(mode_stats.keys()):
                stats = mode_stats[mode]
                write_summary_row(f"pass_count_{mode}", stats["pass"])
                write_summary_row(f"fail_count_{mode}", stats["fail"])
                write_summary_row(f"error_count_{mode}", stats["error"])

            # Extended hours summary (if enabled)
            ext_stats = summary_stats.get("extended_hours", {})
            if ext_stats:
                write_summary_row("", "")  # Separator
                write_summary_row("EXTENDED_HOURS", "")
                write_summary_row(
                    "premarket_total_feeds", ext_stats.get("premarket_total_feeds")
                )
                write_summary_row(
                    "premarket_pass_count", ext_stats.get("premarket_pass_count")
                )
                write_summary_row(
                    "premarket_fail_count", ext_stats.get("premarket_fail_count")
                )
                write_summary_row(
                    "premarket_error_count", ext_stats.get("premarket_error_count")
                )
                write_summary_row(
                    "premarket_pass_rate_pct", ext_stats.get("premarket_pass_rate_pct")
                )
                write_summary_row(
                    "premarket_median_nrmse", ext_stats.get("premarket_median_nrmse")
                )
                write_summary_row(
                    "premarket_median_hit_rate",
                    ext_stats.get("premarket_median_hit_rate"),
                )
                write_summary_row(
                    "afterhours_total_feeds", ext_stats.get("afterhours_total_feeds")
                )
                write_summary_row(
                    "afterhours_pass_count", ext_stats.get("afterhours_pass_count")
                )
                write_summary_row(
                    "afterhours_fail_count", ext_stats.get("afterhours_fail_count")
                )
                write_summary_row(
                    "afterhours_error_count", ext_stats.get("afterhours_error_count")
                )
                write_summary_row(
                    "afterhours_pass_rate_pct",
                    ext_stats.get("afterhours_pass_rate_pct"),
                )
                write_summary_row(
                    "afterhours_median_nrmse", ext_stats.get("afterhours_median_nrmse")
                )
                write_summary_row(
                    "afterhours_median_hit_rate",
                    ext_stats.get("afterhours_median_hit_rate"),
                )

            # Overnight summary (if enabled)
            overnight_stats = summary_stats.get("overnight", {})
            if overnight_stats:
                write_summary_row("", "")  # Separator
                write_summary_row("OVERNIGHT_SESSION", "")
                write_summary_row(
                    "overnight_reference_publisher_id",
                    overnight_stats.get("overnight_reference_publisher_id"),
                )
                write_summary_row(
                    "overnight_total_feeds",
                    overnight_stats.get("overnight_total_feeds"),
                )
                write_summary_row(
                    "overnight_pass_count", overnight_stats.get("overnight_pass_count")
                )
                write_summary_row(
                    "overnight_fail_count", overnight_stats.get("overnight_fail_count")
                )
                write_summary_row(
                    "overnight_error_count",
                    overnight_stats.get("overnight_error_count"),
                )
                write_summary_row(
                    "overnight_pass_rate_pct",
                    overnight_stats.get("overnight_pass_rate_pct"),
                )
                write_summary_row(
                    "overnight_median_nrmse",
                    overnight_stats.get("overnight_median_nrmse"),
                )
                write_summary_row(
                    "overnight_median_hit_rate",
                    overnight_stats.get("overnight_median_hit_rate"),
                )

            per_date_breakdown = summary_stats.get("per_date_breakdown", {})
            if len(per_date_breakdown) > 1:
                writer.writerow([""] * num_cols)
                writer.writerow(["PER_DATE_BREAKDOWN"] + [""] * (num_cols - 1))
                writer.writerow(
                    [
                        "date",
                        "total",
                        "pass",
                        "fail",
                        "error",
                        "pass_rate_pct",
                        "median_nrmse",
                        "median_hit_rate",
                    ]
                    + [""] * (num_cols - 8)
                )
                for date_value in sorted(per_date_breakdown):
                    date_stats = per_date_breakdown[date_value]
                    writer.writerow(
                        [
                            date_value,
                            date_stats.get("total", ""),
                            date_stats.get("pass", ""),
                            date_stats.get("fail", ""),
                            date_stats.get("error", ""),
                            f"{date_stats.get('pass_rate_pct', 0):.2f}",
                            (
                                f"{date_stats['median_nrmse']:.6f}"
                                if date_stats.get("median_nrmse") is not None
                                else ""
                            ),
                            (
                                f"{date_stats['median_hit_rate']:.2f}"
                                if date_stats.get("median_hit_rate") is not None
                                else ""
                            ),
                        ]
                        + [""] * (num_cols - 8)
                    )

    print(f"\nResults written to: {output_path}")


def print_interpretation_guide(summary_stats: dict) -> None:
    """Print an interpretive guide explaining what the metrics mean."""
    print(f"\n{'='*70}")
    print("INTERPRETATION GUIDE - What These Numbers Mean")
    print(f"{'='*70}")

    print("\n--- PASS/FAIL CRITERIA ---")
    print("Your feed PASSES if: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 95%)")
    print("  - nrmse: RMSE normalized by benchmark price range (lower is better)")
    print(
        "  - hit_rate: % of prices within 10 basis points of benchmark (higher is better)"
    )

    print("\n--- ACCURACY METRICS ---")
    print("MAE (Mean Absolute Error):")
    print("  - Average absolute deviation from benchmark price")
    print(
        "  - Interpretation: Lower is better; should be small relative to asset price"
    )
    if summary_stats.get("median_mae") is not None:
        print(f"  - Your median MAE: {summary_stats['median_mae']:.8f}")

    mean_diff = summary_stats.get("mean_mean_diff")
    if mean_diff is not None:
        print(f"\nMean Difference (Systematic Bias): {mean_diff:.8f}")
        if abs(mean_diff) < 1e-8:
            print("  - Your prices show NO systematic bias (excellent)")
        elif mean_diff > 0:
            print("  - Your prices tend to be HIGHER than benchmark")
            print("  - ACTION: Review price source calibration")
        else:
            print("  - Your prices tend to be LOWER than benchmark")
            print("  - ACTION: Review price source calibration")

    print("\n--- STATISTICAL TESTS ---")

    t_rate = summary_stats.get("t_test_significance_rate")
    total_t = summary_stats.get("total_t_tests", 0)
    sig_t = summary_stats.get("significant_t_tests", 0)
    if t_rate is not None:
        print(f"\nT-Test Significance: {sig_t}/{total_t} feeds ({t_rate:.1f}%)")
        print("  - Tests if mean price difference is statistically different from zero")
        if t_rate > 50:
            print(
                "  - HIGH rate (>50%) suggests systematic pricing bias across many feeds"
            )
            print("  - ACTION: Investigate price source accuracy and calibration")
        elif t_rate > 20:
            print("  - MODERATE rate suggests some feeds have systematic bias")
            print("  - ACTION: Review failing feeds individually")
        else:
            print("  - LOW rate (<20%) is good - differences appear mostly random")

    norm_rate = summary_stats.get("normality_rate")
    total_norm = summary_stats.get("total_normality_tests", 0)
    normal_count = summary_stats.get("normal_distributions", 0)
    if norm_rate is not None:
        print(
            f"\nNormality Test: {normal_count}/{total_norm} feeds ({norm_rate:.1f}%) have normally distributed errors"
        )
        if norm_rate >= 70:
            print("  - HIGH rate indicates consistent, predictable error patterns")
            print("  - Errors are likely due to latency/timing rather than data issues")
        elif norm_rate >= 40:
            print("  - MODERATE rate - mixed error patterns")
        else:
            print("  - LOW rate suggests outliers or irregular error patterns")
            print(
                "  - ACTION: Investigate data quality issues, latency spikes, or stale prices"
            )

    median_z = summary_stats.get("median_z_score")
    if median_z is not None:
        print(f"\nMedian Z-Score: {median_z:.4f}")
        print("  - Average deviation from mean in standard deviation units")
        print("  - Expected value for normal distribution: ~0.8")
        if median_z > 1.5:
            print("  - HIGH z-scores indicate frequent large deviations (outliers)")
            print("  - ACTION: Add spike detection or validate price updates")
        elif median_z < 0.5:
            print(
                "  - LOW z-scores indicate very stable, consistent pricing (excellent)"
            )
        else:
            print("  - NORMAL range - typical error volatility")

    print(f"\n{'='*70}")
    print("HOW TO IMPROVE YOUR DATA QUALITY")
    print(f"{'='*70}")
    print("1. REDUCE SYSTEMATIC BIAS:")
    print("   - Calibrate your price source against benchmark")
    print("   - Check for rounding or truncation issues")
    print("   - Verify timezone handling is correct")
    print("\n2. REDUCE RANDOM ERROR:")
    print("   - Improve data freshness (reduce latency)")
    print("   - Increase update frequency during volatile periods")
    print("   - Use faster data sources")
    print("\n3. REDUCE OUTLIERS:")
    print("   - Add spike detection before publishing")
    print("   - Validate price updates against recent history")
    print("   - Implement circuit breakers for extreme moves")
    print("\n4. INCREASE HIT RATE:")
    print("   - Target: >95% of prices within 10 basis points")
    print("   - Monitor real-time deviation from benchmark")
    print("   - Alert on sustained deviations")
    print(f"{'='*70}\n")


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

  # Test specific feed IDs only
  python publisher_benchmark.py --csv publisher_55_feeds.csv --feed-id 327 1163

  # Combine feed ID filter with asset class filter
  python publisher_benchmark.py --csv publisher_55_feeds.csv --include-asset-class us-equities --feed-id 500 501

  # Test specific feed ID with overnight session
  python publisher_benchmark.py --csv publisher_55_feeds.csv --feed-id 500 --overnight

  # Single-feed mode (no CSV needed)
  python publisher_benchmark.py --publisher-id 55 --feed-id 327 --date 2025-10-06 --mode fx

  # Multiple feed IDs × multiple dates
  python publisher_benchmark.py --publisher-id 55 --feed-id 327 328 --date 2025-10-06 2025-10-07 --mode us-equities

  # Date range
  python publisher_benchmark.py --publisher-id 55 --feed-id 327 --start-date 2025-10-01 --end-date 2025-10-06 --mode fx
""",
    )

    parser.add_argument(
        "--csv",
        type=Path,
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
        "--date",
        nargs="+",
        metavar="YYYY-MM-DD",
        help="Date(s) to evaluate in single-feed mode, or override CSV dates",
    )
    parser.add_argument(
        "--start-date",
        help="Range start date in single-feed mode, or CSV override start (inclusive, YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        help="Range end date in single-feed mode, or CSV override end (inclusive, YYYY-MM-DD)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        help="Asset class: fx, metals, us-equities, commodity, us-treasuries",
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
        "--feed-id",
        type=int,
        nargs="+",
        metavar="ID",
        dest="feed_ids",
        help="Feed ID(s) to evaluate in single-feed mode, or specific IDs to filter from CSV mode.",
    )
    parser.add_argument(
        "--list-asset-classes",
        action="store_true",
        help="List unique asset classes in the CSV file and exit",
    )
    parser.add_argument(
        "--extended-hours",
        action="store_true",
        help="Include extended hours evaluation for US equities. "
        "Pre-market: 4:00 AM - 9:30 AM EST, After-hours: 4:00 PM - 8:00 PM EST. "
        "Adds separate columns for pre-market and after-hours metrics. "
        "Only affects us-equities; other asset classes are unchanged.",
    )
    parser.add_argument(
        "--overnight",
        action="store_true",
        help="Include overnight session evaluation for US equities (8 PM - 4 AM EST). "
        "Uses publisher 32 (Blue Ocean ATS) as the benchmark reference instead of Datascope. "
        "This is a publisher-vs-publisher comparison, not an official benchmark. "
        "Independent of --extended-hours; both flags can be used together. "
        "Only affects us-equities; other asset classes are unchanged.",
    )
    parser.add_argument(
        "--skip-scipy-tests",
        action="store_true",
        help="Skip statistical tests (t-test, Wilcoxon, normality) for faster execution. "
        "Pass/fail is determined by nrmse and hit_rate only, so scipy tests are "
        "informational. Statistical metric columns will be empty in output. "
        "Reduces processing time by ~40%%.",
    )

    args = parser.parse_args()

    if args.list_asset_classes and not args.csv:
        parser.error("--list-asset-classes requires --csv")

    if not args.csv and (args.include_asset_class or args.exclude_asset_class):
        parser.error(
            "--include-asset-class and --exclude-asset-class only apply to --csv mode"
        )

    if args.csv and args.mode:
        parser.error(
            "--mode is for single-feed mode. Use either --csv OR (--feed-id, --date, --mode)"
        )
    elif not args.csv and not (args.feed_ids and args.mode):
        parser.error("Either --csv or all of (--feed-id, --date, --mode) are required")

    date_override: list[str] | None = None
    resolved_dates: list[str] = []
    if args.csv and not args.list_asset_classes:
        try:
            validate_date_args(args)
            resolved_dates = expand_date_args(args.date, args.start_date, args.end_date)
            date_override = resolved_dates if resolved_dates else None
        except ValueError as e:
            parser.error(str(e))
    elif not args.csv:
        try:
            validate_date_args(args)
            resolved_dates = expand_date_args(args.date, args.start_date, args.end_date)
        except ValueError as e:
            parser.error(str(e))
        if not resolved_dates:
            parser.error("Single-feed mode requires --date or --start-date/--end-date")
        if args.publisher_id is None:
            parser.error("--publisher-id is required in single-feed mode")

    # Validate CSV file exists
    if args.csv and not args.csv.exists():
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
        print(
            f"\nBenchmarkable asset classes: {', '.join(sorted(BENCHMARKABLE_ASSET_CLASSES))}"
        )
        sys.exit(0)

    # Determine publisher ID
    publisher_id = args.publisher_id
    if args.csv and publisher_id is None:
        publisher_id = extract_publisher_id_from_filename(args.csv.name)
        if publisher_id is None:
            print(
                f"Error: Could not extract publisher ID from filename '{args.csv.name}'"
            )
            print(
                "Expected format: publisher_{{id}}_feeds.csv (e.g., publisher_55_feeds.csv)"
            )
            print("Or use --publisher-id to specify explicitly")
            sys.exit(1)
        print(f"Extracted publisher ID {publisher_id} from filename")

    # Validate include/exclude don't overlap
    if args.include_asset_class and args.exclude_asset_class:
        include_set = {normalize_asset_class(ac) for ac in args.include_asset_class}
        exclude_set = {normalize_asset_class(ac) for ac in args.exclude_asset_class}
        overlap = include_set & exclude_set
        if overlap:
            parser.error(
                f"Asset classes cannot be both included and excluded: {overlap}"
            )

    # Determine output path
    output_path = args.output
    if output_path is None:
        output_path = Path(f"publisher_{publisher_id}_benchmark_results.csv")

    total_start = time.time()

    # Convert feed ID list to set for efficient lookup
    feed_id_filter = set(args.feed_ids) if args.feed_ids else None

    if args.csv:
        results = process_csv(
            args.csv,
            publisher_id,
            args.workers,
            date_override=date_override,
            include_asset_classes=args.include_asset_class,
            exclude_asset_classes=args.exclude_asset_class,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            feed_id_filter=feed_id_filter,
            skip_scipy_tests=args.skip_scipy_tests,
        )
    else:
        config = load_config()
        results = []
        feed_date_pairs = [
            (feed_id, date_value, args.mode)
            for feed_id in args.feed_ids
            for date_value in resolved_dates
        ]

        print(
            f"Processing {len(feed_date_pairs)} feed-date evaluations "
            f"for publisher {publisher_id} with {args.workers} workers..."
        )

        def evaluate_single(args_tuple):
            feed_id, date_value, mode = args_tuple
            client_lazer, client_analytics = get_clients(config)
            return evaluate_publisher_feed(
                client_lazer,
                client_analytics,
                publisher_id,
                feed_id,
                date_value,
                mode,
                include_extended_hours=args.extended_hours,
                include_overnight=args.overnight,
                skip_scipy_tests=args.skip_scipy_tests,
            )

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(evaluate_single, task): task for task in feed_date_pairs
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
                    f"  [{result.execution_time_ms:>4}ms] Feed {result.feed_id} "
                    f"({result.symbol or 'unknown'}): {status} - nrmse={nrmse_str}, "
                    f"hit_rate={hit_rate_str}, n={result.n_observations}"
                )

    # Compute summary statistics
    total_time = time.time() - total_start
    summary_stats = compute_summary_stats(
        results,
        publisher_id,
        total_time,
        include_extended_hours=args.extended_hours,
        include_overnight=args.overnight,
    )

    # Write results and summary to CSV
    write_results_csv(
        results,
        output_path,
        summary_stats,
        include_extended_hours=args.extended_hours,
        include_overnight=args.overnight,
    )

    # Print summary to console
    print(f"\n{'='*70}")
    print(f"SUMMARY - Publisher {publisher_id}")
    print(f"{'='*70}")
    print("Pass criteria: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 95%)")
    print(f"{'='*70}")
    print(f"Total feeds evaluated: {summary_stats['total_feeds']}")
    print(f"PASS: {summary_stats['pass_count']}")
    print(f"  - by nrmse < 0.01 alone: {summary_stats['pass_by_nrmse_alone']}")
    print(
        f"  - by nrmse < 0.05 + hit_rate >= 95%: {summary_stats['pass_by_nrmse_and_hit_rate']}"
    )
    print(f"FAIL: {summary_stats['fail_count']}")
    print(f"Errors: {summary_stats['error_count']}")
    print(f"Pass rate: {summary_stats['pass_rate_pct']:.1f}%")
    print(f"{'='*70}")
    print("NRMSE Statistics (lower is better):")
    if summary_stats["median_nrmse"] is not None:
        print(f"  Median: {summary_stats['median_nrmse']:.6f}")
        print(f"  Mean: {summary_stats['mean_nrmse']:.6f}")
        print(f"  P90: {summary_stats['p90_nrmse']:.6f}")
        print(f"  P95: {summary_stats['p95_nrmse']:.6f}")
        print(f"  Min: {summary_stats['min_nrmse']:.6f}")
        print(f"  Max: {summary_stats['max_nrmse']:.6f}")
    else:
        print("  No valid NRMSE data")
    print(f"{'='*70}")
    print("Hit Rate Statistics (higher is better, % within 10 bps):")
    if summary_stats["median_hit_rate"] is not None:
        print(f"  Median: {summary_stats['median_hit_rate']:.2f}%")
        print(f"  Mean: {summary_stats['mean_hit_rate']:.2f}%")
        print(f"  Min: {summary_stats['min_hit_rate']:.2f}%")
        print(f"  Max: {summary_stats['max_hit_rate']:.2f}%")
    else:
        print("  No valid hit rate data")
    print(f"{'='*70}")
    print("RMSE/Spread Statistics (reference metric, not used for pass/fail):")
    if summary_stats["median_rmse_over_spread"] is not None:
        print(f"  Median: {summary_stats['median_rmse_over_spread']:.4f}")
        print(f"  Mean: {summary_stats['mean_rmse_over_spread']:.4f}")
        print(f"  P90: {summary_stats['p90_rmse_over_spread']:.4f}")
        print(f"  P95: {summary_stats['p95_rmse_over_spread']:.4f}")
    else:
        print("  No valid rmse/spread data")
    print(f"{'='*70}")
    print(f"Total observations: {summary_stats['total_observations']:,}")
    print(
        f"Mean observations per feed: {summary_stats['mean_observations_per_feed']:,.1f}"
    )
    print(
        f"Median observations per feed: {summary_stats['median_observations_per_feed']:,}"
    )
    print(f"{'='*70}")
    print(f"Total time: {summary_stats['total_time_sec']:.2f}s")
    if summary_stats["total_feeds"] > 0:
        print(f"Average time per feed: {summary_stats['avg_time_per_feed_ms']}ms")
    else:
        print("No feeds were processed (all filtered out or empty CSV)")

    # Print breakdown by asset class
    mode_stats = summary_stats.get("mode_stats", {})
    if mode_stats:
        print(f"{'='*60}")
        print("BREAKDOWN BY ASSET CLASS:")
        for mode in sorted(mode_stats.keys()):
            stats = mode_stats[mode]
            total = stats["pass"] + stats["fail"] + stats["error"]
            pass_rate = (stats["pass"] / total * 100) if total > 0 else 0
            print(
                f"  {mode:<15}: {stats['pass']:>3} pass, {stats['fail']:>3} fail, "
                f"{stats['error']:>3} error ({pass_rate:.1f}% pass rate)"
            )

    per_date_breakdown = summary_stats.get("per_date_breakdown", {})
    if len(per_date_breakdown) > 1:
        print(f"\n{'='*70}")
        print("PER-DATE BREAKDOWN")
        print("Date          Total  Pass  Fail  Error  Pass%  Med NRMSE  Med Hit%")
        for date_value in sorted(per_date_breakdown):
            date_stats = per_date_breakdown[date_value]
            median_nrmse = (
                f"{date_stats['median_nrmse']:.6f}"
                if date_stats.get("median_nrmse") is not None
                else "N/A"
            )
            median_hit_rate = (
                f"{date_stats['median_hit_rate']:.2f}%"
                if date_stats.get("median_hit_rate") is not None
                else "N/A"
            )
            print(
                f"{date_value:<12}  "
                f"{int(date_stats.get('total', 0)):>5}  "
                f"{int(date_stats.get('pass', 0)):>4}  "
                f"{int(date_stats.get('fail', 0)):>4}  "
                f"{int(date_stats.get('error', 0)):>5}  "
                f"{float(date_stats.get('pass_rate_pct', 0)):>5.1f}%  "
                f"{median_nrmse:>9}  "
                f"{median_hit_rate:>8}"
            )

    # Print extended hours summary if enabled
    if args.extended_hours:
        ext_stats = summary_stats.get("extended_hours", {})
        if ext_stats:
            print(f"\n{'='*70}")
            print("EXTENDED HOURS - US EQUITIES ONLY")
            print(f"{'='*70}")

            # Pre-market
            print("\nPRE-MARKET (4:00 AM - 9:30 AM EST):")
            pm_total = ext_stats.get("premarket_total_feeds", 0)
            if pm_total > 0:
                print(f"  Total feeds: {pm_total}")
                print(f"  PASS: {ext_stats.get('premarket_pass_count', 0)}")
                print(f"  FAIL: {ext_stats.get('premarket_fail_count', 0)}")
                print(f"  Errors: {ext_stats.get('premarket_error_count', 0)}")
                print(
                    f"  Pass rate: {ext_stats.get('premarket_pass_rate_pct', 0):.1f}%"
                )
                pm_nrmse = ext_stats.get("premarket_median_nrmse")
                pm_hr = ext_stats.get("premarket_median_hit_rate")
                if pm_nrmse is not None:
                    print(f"  Median NRMSE: {pm_nrmse:.6f}")
                if pm_hr is not None:
                    print(f"  Median Hit Rate: {pm_hr:.2f}%")
            else:
                print("  No pre-market data available")

            # After-hours
            print("\nAFTER-HOURS (4:00 PM - 8:00 PM EST):")
            ah_total = ext_stats.get("afterhours_total_feeds", 0)
            if ah_total > 0:
                print(f"  Total feeds: {ah_total}")
                print(f"  PASS: {ext_stats.get('afterhours_pass_count', 0)}")
                print(f"  FAIL: {ext_stats.get('afterhours_fail_count', 0)}")
                print(f"  Errors: {ext_stats.get('afterhours_error_count', 0)}")
                print(
                    f"  Pass rate: {ext_stats.get('afterhours_pass_rate_pct', 0):.1f}%"
                )
                ah_nrmse = ext_stats.get("afterhours_median_nrmse")
                ah_hr = ext_stats.get("afterhours_median_hit_rate")
                if ah_nrmse is not None:
                    print(f"  Median NRMSE: {ah_nrmse:.6f}")
                if ah_hr is not None:
                    print(f"  Median Hit Rate: {ah_hr:.2f}%")
            else:
                print("  No after-hours data available")

    # Print overnight summary if enabled
    if args.overnight:
        overnight_stats = summary_stats.get("overnight", {})
        if overnight_stats:
            print(f"\n{'='*70}")
            print("OVERNIGHT SESSION - US EQUITIES ONLY")
            print(f"{'='*70}")
            print(
                f"Benchmark reference: Publisher {overnight_stats.get('overnight_reference_publisher_id', 32)} (Blue Ocean ATS)"
            )
            print(
                "NOTE: This is a publisher-vs-publisher comparison, not an official benchmark."
            )
            print(f"{'='*70}")

            on_total = overnight_stats.get("overnight_total_feeds", 0)
            if on_total > 0:
                print(f"\nOVERNIGHT (8:00 PM - 4:00 AM EST):")
                print(f"  Total feeds: {on_total}")
                print(f"  PASS: {overnight_stats.get('overnight_pass_count', 0)}")
                print(f"  FAIL: {overnight_stats.get('overnight_fail_count', 0)}")
                print(f"  Errors: {overnight_stats.get('overnight_error_count', 0)}")
                print(
                    f"  Pass rate: {overnight_stats.get('overnight_pass_rate_pct', 0):.1f}%"
                )
                on_nrmse = overnight_stats.get("overnight_median_nrmse")
                on_hr = overnight_stats.get("overnight_median_hit_rate")
                if on_nrmse is not None:
                    print(f"  Median NRMSE: {on_nrmse:.6f}")
                if on_hr is not None:
                    print(f"  Median Hit Rate: {on_hr:.2f}%")
            else:
                print("  No overnight data available")

    # Print interpretation guide
    print_interpretation_guide(summary_stats)


if __name__ == "__main__":
    main()
