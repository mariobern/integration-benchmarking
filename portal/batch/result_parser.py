"""
Result parser for publisher_benchmark.py CSV output.

Parses the CSV output from publisher_benchmark.py into structured data
that can be stored in the Postgres database.
"""

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator, Optional


@dataclass
class ParsedBenchmarkResult:
    """Parsed benchmark result from CSV."""

    publisher_id: int
    feed_id: int
    benchmark_date: date
    asset_class: str
    symbol: Optional[str]
    passes: bool
    n_observations: int

    # Primary metrics
    nrmse: Optional[Decimal]
    hit_rate: Optional[Decimal]
    benchmark_price_range: Optional[Decimal]

    # Secondary metrics
    rmse: Optional[Decimal]
    mean_spread: Optional[Decimal]
    rmse_over_spread: Optional[Decimal]

    # Statistical metrics
    mean_diff: Optional[Decimal]
    std_diff: Optional[Decimal]
    mean_pct_diff: Optional[Decimal]
    std_pct_diff: Optional[Decimal]
    mae: Optional[Decimal]
    t_statistic: Optional[Decimal]
    t_pvalue: Optional[Decimal]
    wilcoxon_statistic: Optional[Decimal]
    wilcoxon_pvalue: Optional[Decimal]
    normality_pvalue: Optional[Decimal]
    mean_abs_z_score: Optional[Decimal]

    # Extended hours (US equities only)
    premarket_n_observations: Optional[int]
    premarket_nrmse: Optional[Decimal]
    premarket_hit_rate: Optional[Decimal]
    premarket_passes: Optional[bool]
    premarket_error: Optional[str]

    afterhours_n_observations: Optional[int]
    afterhours_nrmse: Optional[Decimal]
    afterhours_hit_rate: Optional[Decimal]
    afterhours_passes: Optional[bool]
    afterhours_error: Optional[str]

    # Overnight session (US equities only, uses publisher 32 as reference)
    overnight_n_observations: Optional[int]
    overnight_n_reference_observations: Optional[int]
    overnight_nrmse: Optional[Decimal]
    overnight_hit_rate: Optional[Decimal]
    overnight_passes: Optional[bool]
    overnight_reference_publisher_id: Optional[int]
    overnight_error: Optional[str]

    # Error and timing
    error: Optional[str]
    execution_time_ms: Optional[int]


def _parse_decimal(value: str) -> Optional[Decimal]:
    """Parse a string to Decimal, returning None for empty/invalid values."""
    if not value or value.strip() == "":
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        return None


def _parse_int(value: str) -> Optional[int]:
    """Parse a string to int, returning None for empty/invalid values."""
    if not value or value.strip() == "":
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _parse_bool(value: str) -> Optional[bool]:
    """Parse a string to bool, returning None for empty/invalid values."""
    if not value or value.strip() == "":
        return None
    v = value.strip().lower()
    if v in ("true", "1", "yes"):
        return True
    elif v in ("false", "0", "no"):
        return False
    return None


def _parse_date(value: str) -> date:
    """Parse a date string in YYYY-MM-DD format."""
    return date.fromisoformat(value.strip())


def parse_benchmark_csv(csv_path: Path) -> Iterator[ParsedBenchmarkResult]:
    """
    Parse publisher_benchmark.py CSV output.

    Yields ParsedBenchmarkResult objects for each data row.
    Stops when it encounters the SUMMARY section.

    Args:
        csv_path: Path to the CSV file

    Yields:
        ParsedBenchmarkResult for each valid data row
    """
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            # Stop at SUMMARY section
            if row.get("publisher_id", "").strip() == "SUMMARY":
                break

            # Skip empty rows
            if not row.get("publisher_id") or not row.get("feed_id"):
                continue

            # Check if this CSV has extended hours columns
            has_extended_hours = "premarket_n_observations" in row
            has_overnight = "overnight_n_observations" in row

            yield ParsedBenchmarkResult(
                publisher_id=int(row["publisher_id"]),
                feed_id=int(row["feed_id"]),
                benchmark_date=_parse_date(row["date"]),
                asset_class=row["mode"].strip(),
                symbol=row["symbol"].strip() if row.get("symbol") else None,
                passes=_parse_bool(row["passes"]) or False,
                n_observations=_parse_int(row["n_observations"]) or 0,
                # Primary metrics
                nrmse=_parse_decimal(row.get("nrmse", "")),
                hit_rate=_parse_decimal(row.get("hit_rate", "")),
                benchmark_price_range=_parse_decimal(row.get("benchmark_price_range", "")),
                # Secondary metrics
                rmse=_parse_decimal(row.get("rmse", "")),
                mean_spread=_parse_decimal(row.get("mean_spread", "")),
                rmse_over_spread=_parse_decimal(row.get("rmse_over_spread", "")),
                # Statistical metrics
                mean_diff=_parse_decimal(row.get("mean_diff", "")),
                std_diff=_parse_decimal(row.get("std_diff", "")),
                mean_pct_diff=_parse_decimal(row.get("mean_pct_diff", "")),
                std_pct_diff=_parse_decimal(row.get("std_pct_diff", "")),
                mae=_parse_decimal(row.get("mae", "")),
                t_statistic=_parse_decimal(row.get("t_statistic", "")),
                t_pvalue=_parse_decimal(row.get("t_pvalue", "")),
                wilcoxon_statistic=_parse_decimal(row.get("wilcoxon_statistic", "")),
                wilcoxon_pvalue=_parse_decimal(row.get("wilcoxon_pvalue", "")),
                normality_pvalue=_parse_decimal(row.get("normality_pvalue", "")),
                mean_abs_z_score=_parse_decimal(row.get("mean_abs_z_score", "")),
                # Extended hours (if present)
                premarket_n_observations=_parse_int(row.get("premarket_n_observations", "")) if has_extended_hours else None,
                premarket_nrmse=_parse_decimal(row.get("premarket_nrmse", "")) if has_extended_hours else None,
                premarket_hit_rate=_parse_decimal(row.get("premarket_hit_rate", "")) if has_extended_hours else None,
                premarket_passes=_parse_bool(row.get("premarket_passes", "")) if has_extended_hours else None,
                premarket_error=row.get("premarket_error", "").strip() or None if has_extended_hours else None,
                afterhours_n_observations=_parse_int(row.get("afterhours_n_observations", "")) if has_extended_hours else None,
                afterhours_nrmse=_parse_decimal(row.get("afterhours_nrmse", "")) if has_extended_hours else None,
                afterhours_hit_rate=_parse_decimal(row.get("afterhours_hit_rate", "")) if has_extended_hours else None,
                afterhours_passes=_parse_bool(row.get("afterhours_passes", "")) if has_extended_hours else None,
                afterhours_error=row.get("afterhours_error", "").strip() or None if has_extended_hours else None,
                # Overnight session (if present)
                overnight_n_observations=_parse_int(row.get("overnight_n_observations", "")) if has_overnight else None,
                overnight_n_reference_observations=_parse_int(row.get("overnight_n_reference_observations", "")) if has_overnight else None,
                overnight_nrmse=_parse_decimal(row.get("overnight_nrmse", "")) if has_overnight else None,
                overnight_hit_rate=_parse_decimal(row.get("overnight_hit_rate", "")) if has_overnight else None,
                overnight_passes=_parse_bool(row.get("overnight_passes", "")) if has_overnight else None,
                overnight_reference_publisher_id=_parse_int(row.get("overnight_reference_publisher_id", "")) if has_overnight else None,
                overnight_error=row.get("overnight_error", "").strip() or None if has_overnight else None,
                # Error and timing
                error=row.get("error", "").strip() or None,
                execution_time_ms=_parse_int(row.get("execution_time_ms", "")),
            )


def parse_summary_from_csv(csv_path: Path) -> dict[str, Any]:
    """
    Parse the SUMMARY section from publisher_benchmark.py CSV output.

    Args:
        csv_path: Path to the CSV file

    Returns:
        Dictionary of summary statistics
    """
    summary = {}
    in_summary = False

    with open(csv_path, newline="") as f:
        reader = csv.reader(f)

        for row in reader:
            if not row:
                continue

            # Look for SUMMARY marker
            if row[0] == "SUMMARY":
                in_summary = True
                continue

            if in_summary and len(row) >= 2:
                key = row[0].strip()
                value = row[1].strip()

                if not key:
                    continue

                # Parse value based on content
                if value == "":
                    summary[key] = None
                elif value.replace(".", "").replace("-", "").isdigit():
                    # Numeric value
                    if "." in value:
                        summary[key] = float(value)
                    else:
                        summary[key] = int(value)
                else:
                    summary[key] = value

    return summary


def result_to_dict(result: ParsedBenchmarkResult) -> dict[str, Any]:
    """
    Convert ParsedBenchmarkResult to a dictionary for database insertion.

    Converts Decimal values to appropriate Python types.
    """
    def decimal_to_float(v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    return {
        "publisher_id": result.publisher_id,
        "feed_id": result.feed_id,
        "benchmark_date": result.benchmark_date,
        "asset_class": result.asset_class,
        "symbol": result.symbol,
        "passes": result.passes,
        "n_observations": result.n_observations,
        # Primary metrics
        "nrmse": decimal_to_float(result.nrmse),
        "hit_rate": decimal_to_float(result.hit_rate),
        "benchmark_price_range": decimal_to_float(result.benchmark_price_range),
        # Secondary metrics
        "rmse": decimal_to_float(result.rmse),
        "mean_spread": decimal_to_float(result.mean_spread),
        "rmse_over_spread": decimal_to_float(result.rmse_over_spread),
        # Statistical metrics
        "mean_diff": decimal_to_float(result.mean_diff),
        "std_diff": decimal_to_float(result.std_diff),
        "mean_pct_diff": decimal_to_float(result.mean_pct_diff),
        "std_pct_diff": decimal_to_float(result.std_pct_diff),
        "mae": decimal_to_float(result.mae),
        "t_statistic": decimal_to_float(result.t_statistic),
        "t_pvalue": decimal_to_float(result.t_pvalue),
        "wilcoxon_statistic": decimal_to_float(result.wilcoxon_statistic),
        "wilcoxon_pvalue": decimal_to_float(result.wilcoxon_pvalue),
        "normality_pvalue": decimal_to_float(result.normality_pvalue),
        "mean_abs_z_score": decimal_to_float(result.mean_abs_z_score),
        # Extended hours
        "premarket_n_observations": result.premarket_n_observations,
        "premarket_nrmse": decimal_to_float(result.premarket_nrmse),
        "premarket_hit_rate": decimal_to_float(result.premarket_hit_rate),
        "premarket_passes": result.premarket_passes,
        "premarket_error": result.premarket_error,
        "afterhours_n_observations": result.afterhours_n_observations,
        "afterhours_nrmse": decimal_to_float(result.afterhours_nrmse),
        "afterhours_hit_rate": decimal_to_float(result.afterhours_hit_rate),
        "afterhours_passes": result.afterhours_passes,
        "afterhours_error": result.afterhours_error,
        # Overnight session
        "overnight_n_observations": result.overnight_n_observations,
        "overnight_n_reference_observations": result.overnight_n_reference_observations,
        "overnight_nrmse": decimal_to_float(result.overnight_nrmse),
        "overnight_hit_rate": decimal_to_float(result.overnight_hit_rate),
        "overnight_passes": result.overnight_passes,
        "overnight_reference_publisher_id": result.overnight_reference_publisher_id,
        "overnight_error": result.overnight_error,
        # Error and timing
        "error": result.error,
        "execution_time_ms": result.execution_time_ms,
    }
