"""Output formatting for feed-level benchmark results (quick_benchmark).

Extracted from quick_benchmark.py. Contains publisher summary computation,
CSV writing, summary stats, and interpretation guide for BenchmarkResult data.

Functions:
    compute_publisher_summary    - Cross-date publisher pass/fail matrix
    write_publisher_summary_csv  - Write PUBLISHER SUMMARY CSV section
    write_results_csv            - Full CSV output with optional detail rows
    compute_summary_stats        - Feed-level summary statistics
    print_interpretation_guide   - Console interpretation guide
    print_publisher_summary      - Console publisher consistency summary
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

from lib.config import normalize_asset_class
from lib.models import (
    BenchmarkResult,
    ExtendedHoursMetrics,
    OvernightMetrics,
    OVERNIGHT_REFERENCE_PUBLISHER_ID,
    PublisherFeedMetrics,
    TradingSession,
)
from lib.statistics import distribution_stats


def compute_publisher_summary(
    results: list[BenchmarkResult],
    include_extended_hours: bool = False,
    include_overnight: bool = False,
) -> dict:
    """Build cross-date publisher pass/fail matrix from detailed results."""

    def _status_from_regular(detail: PublisherFeedMetrics) -> str:
        if detail.error:
            return "ERROR"
        return "PASS" if detail.passes else "FAIL"

    def _status_from_session(
        metrics: Optional[ExtendedHoursMetrics | OvernightMetrics],
    ) -> Optional[str]:
        if metrics is None:
            return None
        if metrics.error:
            return "ERROR"
        return "PASS" if metrics.passes else "FAIL"

    def _session_stats(session_results: dict[str, str]) -> dict:
        pass_count = sum(1 for status in session_results.values() if status == "PASS")
        fail_count = sum(1 for status in session_results.values() if status == "FAIL")
        error_count = sum(1 for status in session_results.values() if status == "ERROR")
        dates_seen = len(session_results)
        pass_rate = (pass_count / dates_seen * 100) if dates_seen > 0 else None
        return {
            "dates_seen": dates_seen,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "error_count": error_count,
            "pass_rate": pass_rate,
        }

    dates = sorted({r.date for r in results})

    publisher_sessions: dict[int, dict[str, dict[str, str]]] = {}
    for result in sorted(results, key=lambda r: (r.date, r.feed_id)):
        for detail in result.publisher_details or []:
            pub_sessions = publisher_sessions.setdefault(
                detail.publisher_id,
                {
                    TradingSession.REGULAR.value: {},
                    TradingSession.PREMARKET.value: {},
                    TradingSession.AFTERHOURS.value: {},
                    TradingSession.OVERNIGHT.value: {},
                },
            )

            pub_sessions[TradingSession.REGULAR.value][
                result.date
            ] = _status_from_regular(detail)

            if include_extended_hours:
                pm_status = _status_from_session(detail.premarket_metrics)
                if pm_status is not None:
                    pub_sessions[TradingSession.PREMARKET.value][
                        result.date
                    ] = pm_status

                ah_status = _status_from_session(detail.afterhours_metrics)
                if ah_status is not None:
                    pub_sessions[TradingSession.AFTERHOURS.value][
                        result.date
                    ] = ah_status

            if include_overnight:
                on_status = _status_from_session(detail.overnight_metrics)
                if on_status is not None:
                    pub_sessions[TradingSession.OVERNIGHT.value][
                        result.date
                    ] = on_status

    rows = []
    for publisher_id, session_results in publisher_sessions.items():
        regular_results = session_results[TradingSession.REGULAR.value]
        regular_stats = _session_stats(regular_results)
        rows.append(
            {
                "publisher_id": publisher_id,
                "dates_seen": regular_stats["dates_seen"],
                "sessions": {
                    TradingSession.REGULAR.value: {
                        "results": dict(sorted(regular_results.items())),
                        **regular_stats,
                    },
                    TradingSession.PREMARKET.value: {
                        "results": dict(
                            sorted(
                                session_results[TradingSession.PREMARKET.value].items()
                            )
                        ),
                        **_session_stats(
                            session_results[TradingSession.PREMARKET.value]
                        ),
                    },
                    TradingSession.AFTERHOURS.value: {
                        "results": dict(
                            sorted(
                                session_results[TradingSession.AFTERHOURS.value].items()
                            )
                        ),
                        **_session_stats(
                            session_results[TradingSession.AFTERHOURS.value]
                        ),
                    },
                    TradingSession.OVERNIGHT.value: {
                        "results": dict(
                            sorted(
                                session_results[TradingSession.OVERNIGHT.value].items()
                            )
                        ),
                        **_session_stats(
                            session_results[TradingSession.OVERNIGHT.value]
                        ),
                    },
                },
            }
        )

    rows.sort(
        key=lambda row: (
            -(row["sessions"][TradingSession.REGULAR.value]["pass_rate"] or 0),
            row["publisher_id"],
        )
    )

    def _compute_classifications(session_name: str) -> dict[str, list[int]]:
        always_passing = []
        always_failing = []
        intermittent = []
        for row in rows:
            statuses = list(row["sessions"][session_name]["results"].values())
            if not statuses:
                continue
            if all(status == "PASS" for status in statuses):
                always_passing.append(row["publisher_id"])
            elif all(status == "FAIL" for status in statuses):
                always_failing.append(row["publisher_id"])
            else:
                intermittent.append(row["publisher_id"])
        return {
            "always_passing": always_passing,
            "always_failing": always_failing,
            "intermittent": intermittent,
        }

    return {
        "dates": dates,
        "rows": rows,
        "classifications": {
            TradingSession.REGULAR.value: _compute_classifications(
                TradingSession.REGULAR.value
            ),
            TradingSession.PREMARKET.value: _compute_classifications(
                TradingSession.PREMARKET.value
            ),
            TradingSession.AFTERHOURS.value: _compute_classifications(
                TradingSession.AFTERHOURS.value
            ),
            TradingSession.OVERNIGHT.value: _compute_classifications(
                TradingSession.OVERNIGHT.value
            ),
        },
    }


def write_publisher_summary_csv(
    writer: csv.writer,
    publisher_summary: dict,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
) -> None:
    """Write PUBLISHER SUMMARY section with cross-date consistency metrics."""

    def _format_rate(rate: Optional[float]) -> str:
        return f"{rate:.2f}%" if rate is not None else ""

    def _format_results(session_data: dict) -> str:
        return ";".join(
            f"{date_value}:{status}"
            for date_value, status in session_data["results"].items()
        )

    writer.writerow([])
    writer.writerow(["PUBLISHER SUMMARY"])

    summary_header = [
        "publisher_id",
        "dates_seen",
        "regular_pass_dates",
        "regular_fail_dates",
        "regular_pass_rate",
        "regular_results",
    ]

    if include_extended_hours:
        summary_header.extend(
            [
                "premarket_pass_dates",
                "premarket_fail_dates",
                "premarket_pass_rate",
                "premarket_results",
                "afterhours_pass_dates",
                "afterhours_fail_dates",
                "afterhours_pass_rate",
                "afterhours_results",
            ]
        )

    if include_overnight:
        summary_header.extend(
            [
                "overnight_pass_dates",
                "overnight_fail_dates",
                "overnight_pass_rate",
                "overnight_results",
            ]
        )

    writer.writerow(summary_header)

    for row in publisher_summary["rows"]:
        regular = row["sessions"][TradingSession.REGULAR.value]
        csv_row = [
            row["publisher_id"],
            row["dates_seen"],
            regular["pass_count"],
            regular["fail_count"],
            _format_rate(regular["pass_rate"]),
            _format_results(regular),
        ]

        if include_extended_hours:
            premarket = row["sessions"][TradingSession.PREMARKET.value]
            afterhours = row["sessions"][TradingSession.AFTERHOURS.value]
            csv_row.extend(
                [
                    premarket["pass_count"],
                    premarket["fail_count"],
                    _format_rate(premarket["pass_rate"]),
                    _format_results(premarket),
                    afterhours["pass_count"],
                    afterhours["fail_count"],
                    _format_rate(afterhours["pass_rate"]),
                    _format_results(afterhours),
                ]
            )

        if include_overnight:
            overnight = row["sessions"][TradingSession.OVERNIGHT.value]
            csv_row.extend(
                [
                    overnight["pass_count"],
                    overnight["fail_count"],
                    _format_rate(overnight["pass_rate"]),
                    _format_results(overnight),
                ]
            )

        writer.writerow(csv_row)

    writer.writerow([])
    writer.writerow(["PUBLISHER CLASSIFICATIONS"])

    sessions_to_classify = [TradingSession.REGULAR.value]
    if include_extended_hours:
        sessions_to_classify.extend(
            [TradingSession.PREMARKET.value, TradingSession.AFTERHOURS.value]
        )
    if include_overnight:
        sessions_to_classify.append(TradingSession.OVERNIGHT.value)

    for session_name in sessions_to_classify:
        classifications = publisher_summary["classifications"][session_name]
        _fmt = lambda ids: ";".join(str(x) for x in ids) if ids else ""
        writer.writerow(
            [f"{session_name}_always_passing", _fmt(classifications["always_passing"])]
        )
        writer.writerow(
            [f"{session_name}_always_failing", _fmt(classifications["always_failing"])]
        )
        writer.writerow(
            [f"{session_name}_intermittent", _fmt(classifications["intermittent"])]
        )


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
                        r.premarket_passing_count
                        if r.premarket_passing_count is not None
                        else "",
                        r.premarket_failing_count
                        if r.premarket_failing_count is not None
                        else "",
                        r.afterhours_passing_count
                        if r.afterhours_passing_count is not None
                        else "",
                        r.afterhours_failing_count
                        if r.afterhours_failing_count is not None
                        else "",
                    ]
                )

            if include_overnight:
                row.extend(
                    [
                        r.overnight_passing_count
                        if r.overnight_passing_count is not None
                        else "",
                        r.overnight_failing_count
                        if r.overnight_failing_count is not None
                        else "",
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
                        f"{d.rmse_over_spread:.6f}"
                        if d.rmse_over_spread is not None
                        else "",
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
                        f"{d.wilcoxon_statistic:.4f}"
                        if d.wilcoxon_statistic is not None
                        else "",
                        f"{d.wilcoxon_pvalue:.6f}"
                        if d.wilcoxon_pvalue is not None
                        else "",
                        f"{d.normality_pvalue:.6f}"
                        if d.normality_pvalue is not None
                        else "",
                        f"{d.mean_abs_z_score:.4f}"
                        if d.mean_abs_z_score is not None
                        else "",
                    ]

                    if include_extended_hours:
                        pm = d.premarket_metrics
                        ah = d.afterhours_metrics
                        row.extend(
                            [
                                pm.n_observations if pm else "",
                                f"{pm.nrmse:.6f}"
                                if pm and pm.nrmse is not None
                                else "",
                                f"{pm.hit_rate:.2f}"
                                if pm and pm.hit_rate is not None
                                else "",
                                pm.passes if pm else "",
                                pm.error if pm else "",
                                ah.n_observations if ah else "",
                                f"{ah.nrmse:.6f}"
                                if ah and ah.nrmse is not None
                                else "",
                                f"{ah.hit_rate:.2f}"
                                if ah and ah.hit_rate is not None
                                else "",
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
                                f"{on.nrmse:.6f}"
                                if on and on.nrmse is not None
                                else "",
                                f"{on.hit_rate:.2f}"
                                if on and on.hit_rate is not None
                                else "",
                                on.passes if on else "",
                                on.reference_publisher_id if on else "",
                                on.error if on else "",
                            ]
                        )

                    row.append(d.error or "")
                    writer.writerow(row)

        unique_dates = {r.date for r in results}
        if len(unique_dates) > 1:
            publisher_summary = compute_publisher_summary(
                results,
                include_extended_hours=include_extended_hours,
                include_overnight=include_overnight,
            )
            write_publisher_summary_csv(
                writer,
                publisher_summary,
                include_extended_hours=include_extended_hours,
                include_overnight=include_overnight,
            )

    print(f"\nResults written to: {output_path}")


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

    nrmse_values = [
        r.median_nrmse for r in results if r.median_nrmse is not None and not r.error
    ]
    hit_rate_values = [
        r.median_hit_rate
        for r in results
        if r.median_hit_rate is not None and not r.error
    ]

    nrmse_stats = distribution_stats(nrmse_values)
    hit_rate_stats = distribution_stats(hit_rate_values)

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

    per_date_stats: dict[str, dict[str, int]] = {}
    for r in results:
        if r.date not in per_date_stats:
            per_date_stats[r.date] = {"ready": 0, "not_ready": 0, "error": 0}
        if r.error:
            per_date_stats[r.date]["error"] += 1
        elif r.ready:
            per_date_stats[r.date]["ready"] += 1
        else:
            per_date_stats[r.date]["not_ready"] += 1

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
            "afterhours_pass_rate": (ah_pass / ah_total * 100)
            if ah_total > 0
            else None,
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
        "per_date_stats": per_date_stats,
        "extended_hours": extended_hours_stats,
        "overnight": overnight_stats,
        "total_time_sec": total_time,
        "avg_time_ms": (total_time / total_feeds * 1000) if total_feeds > 0 else 0,
    }


def print_interpretation_guide(
    summary_stats: dict, hit_rate_threshold: float = 95
) -> None:
    """Print a concise interpretation guide for feed-level results."""

    print(f"\n{'='*70}")
    print("INTERPRETATION GUIDE")
    print(f"{'='*70}")

    print(
        f"PASS criteria per publisher: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= {hit_rate_threshold}%)"
    )
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
            print(
                "Interpretation: broad quality gaps; investigate sources with high deviation."
            )

    if median_hit_rate is not None:
        print(f"Median feed hit_rate: {median_hit_rate:.2f}% (higher is better)")
        if median_hit_rate >= hit_rate_threshold + 3:
            print("Interpretation: benchmark tracking is generally tight.")
        elif median_hit_rate >= hit_rate_threshold:
            print("Interpretation: acceptable but close to pass threshold risk.")
        else:
            print(
                "Interpretation: frequent misses vs benchmark; review latency and pricing logic."
            )

    print(
        "Suggested focus: investigate feeds with low median_hit_rate and high median_nrmse first."
    )


def print_publisher_summary(
    publisher_summary: dict,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
) -> None:
    """Print cross-date publisher consistency summary."""

    def _format_console_rate(rate: Optional[float]) -> str:
        return f"{rate:.1f}%" if rate is not None else "N/A"

    def _format_console_results(session_data: dict) -> str:
        entries = []
        for date_value, status in session_data["results"].items():
            mm_dd = datetime.strptime(date_value, "%Y-%m-%d").strftime("%m-%d")
            entries.append(f"{mm_dd}:{status}")
        return " ".join(entries)

    def _print_session_block(title: str, session_name: str) -> None:
        print(f"\n{title}:")
        print("  Publisher  Pass  Fail  Rate    Results")

        printed_any = False
        for row in publisher_summary["rows"]:
            session_data = row["sessions"][session_name]
            if session_data["dates_seen"] == 0:
                continue

            print(
                f"  {row['publisher_id']:<9} "
                f"{session_data['pass_count']:<5} "
                f"{session_data['fail_count']:<5} "
                f"{_format_console_rate(session_data['pass_rate']):<7} "
                f"{_format_console_results(session_data)}"
            )
            printed_any = True

        if not printed_any:
            print("  No evaluable publisher results")
            return

        classifications = publisher_summary["classifications"][session_name]

        def _format_group(group: list[int]) -> str:
            return ", ".join(str(x) for x in group) if group else "-"

        print(
            f"\n  Always passing: {_format_group(classifications['always_passing'])} "
            f"({len(classifications['always_passing'])} publishers)"
        )
        print(
            f"  Always failing: {_format_group(classifications['always_failing'])} "
            f"({len(classifications['always_failing'])} publishers)"
        )
        print(
            f"  Intermittent: {_format_group(classifications['intermittent'])} "
            f"({len(classifications['intermittent'])} publishers)"
        )

    print(f"\n{'='*70}")
    print(f"PUBLISHER CONSISTENCY (across {len(publisher_summary['dates'])} dates)")
    print(f"{'='*70}")

    _print_session_block("REGULAR SESSION", TradingSession.REGULAR.value)

    if include_extended_hours:
        _print_session_block("PREMARKET", TradingSession.PREMARKET.value)
        _print_session_block("AFTERHOURS", TradingSession.AFTERHOURS.value)

    if include_overnight:
        _print_session_block("OVERNIGHT", TradingSession.OVERNIGHT.value)


def print_console_summary(
    results: list[BenchmarkResult],
    total_time: float,
    *,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    hit_rate_threshold: float = 95.0,
) -> None:
    """Print full console summary including criteria, stats, and publisher consistency."""
    summary = compute_summary_stats(
        results,
        total_time,
        include_extended_hours=include_extended_hours,
        include_overnight=include_overnight,
    )

    print(f"\n{'='*70}")
    print("PASS/FAIL CRITERIA")
    print(f"{'='*70}")
    print(
        f"Publisher passes if: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= {hit_rate_threshold}%)"
    )
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

    per_date_stats = summary.get("per_date_stats", {})
    if len(per_date_stats) > 1:
        print("\nPer-date breakdown:")
        for date_value in sorted(per_date_stats):
            stats = per_date_stats[date_value]
            print(
                f"  {date_value:<12} ready={stats['ready']:<4} "
                f"not_ready={stats['not_ready']:<4} error={stats['error']:<4}"
            )

    if include_extended_hours:
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

    if include_overnight:
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

    print(
        f"\nTiming: total={summary['total_time_sec']:.2f}s, avg_per_feed={summary['avg_time_ms']:.0f}ms"
    )

    print_interpretation_guide(summary, hit_rate_threshold=hit_rate_threshold)

    if len({r.date for r in results}) > 1:
        publisher_summary = compute_publisher_summary(
            results,
            include_extended_hours=include_extended_hours,
            include_overnight=include_overnight,
        )
        print_publisher_summary(
            publisher_summary,
            include_extended_hours=include_extended_hours,
            include_overnight=include_overnight,
        )
