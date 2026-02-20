"""Tests for feed_readiness.py -- publisher consistency & classifications."""
import csv
import io
import tempfile
from pathlib import Path
from typing import Optional

import pytest

from feed_readiness import (
    FeedReadinessResult,
    PublisherReadinessDetail,
    compute_publisher_consistency,
    write_publisher_consistency_csv,
    write_results_csv,
    print_publisher_consistency,
    _regular_status,
    _premarket_status,
    _afterhours_status,
    _overnight_status,
)


def make_detail(
    publisher_id: int,
    fully_passes: bool = False,
    benchmark_passes: bool = False,
    uptime_passes: bool = False,
    benchmark_error: Optional[str] = None,
    uptime_error: Optional[str] = None,
    premarket_benchmark_passes: Optional[bool] = None,
    premarket_uptime_passes: Optional[bool] = None,
    premarket_uptime_pct: Optional[float] = None,
    afterhours_benchmark_passes: Optional[bool] = None,
    afterhours_uptime_passes: Optional[bool] = None,
    afterhours_uptime_pct: Optional[float] = None,
    overnight_benchmark_passes: Optional[bool] = None,
    overnight_uptime_passes: Optional[bool] = None,
    overnight_uptime_pct: Optional[float] = None,
) -> PublisherReadinessDetail:
    return PublisherReadinessDetail(
        publisher_id=publisher_id,
        benchmark_passes=benchmark_passes,
        benchmark_nrmse=0.01 if benchmark_passes else None,
        benchmark_hit_rate=98.0 if benchmark_passes else None,
        benchmark_n_observations=100,
        benchmark_error=benchmark_error,
        uptime_passes=uptime_passes,
        uptime_pct=99.0 if uptime_passes else 50.0,
        uptime_error=uptime_error,
        fully_passes=fully_passes,
        premarket_benchmark_passes=premarket_benchmark_passes,
        premarket_uptime_passes=premarket_uptime_passes,
        premarket_uptime_pct=premarket_uptime_pct,
        afterhours_benchmark_passes=afterhours_benchmark_passes,
        afterhours_uptime_passes=afterhours_uptime_passes,
        afterhours_uptime_pct=afterhours_uptime_pct,
        overnight_benchmark_passes=overnight_benchmark_passes,
        overnight_uptime_passes=overnight_uptime_passes,
        overnight_uptime_pct=overnight_uptime_pct,
    )


def make_result(
    feed_id: int,
    date: str,
    details: list[PublisherReadinessDetail],
) -> FeedReadinessResult:
    passing = [d for d in details if d.fully_passes]
    return FeedReadinessResult(
        feed_id=feed_id,
        date=date,
        mode="us-equities",
        symbol="Equity.US.TEST/USD",
        ready=len(passing) >= 4,
        benchmark_ready=len(passing) >= 4,
        uptime_ready=len(passing) >= 4,
        target_pub_count=4,
        fully_passing_count=len(passing),
        benchmark_only_passing_count=0,
        uptime_only_passing_count=0,
        both_failing_count=len(details) - len(passing),
        total_publisher_count=len(details),
        benchmark_passing_count=len(passing),
        benchmark_failing_count=len(details) - len(passing),
        median_nrmse=0.01,
        median_hit_rate=98.0,
        uptime_passing_count=len(passing),
        uptime_failing_count=len(details) - len(passing),
        median_uptime_pct=99.0,
        fully_passing_publishers=[d.publisher_id for d in passing],
        benchmark_only_publishers=[],
        uptime_only_publishers=[],
        both_failing_publishers=[d.publisher_id for d in details if not d.fully_passes],
        publisher_details=details,
    )


# ---------------------------------------------------------------------------
# Session status extractor tests
# ---------------------------------------------------------------------------


class TestRegularStatus:
    def test_pass(self):
        detail = make_detail(publisher_id=1, fully_passes=True, benchmark_passes=True, uptime_passes=True)
        assert _regular_status(detail) == "PASS"

    def test_fail(self):
        detail = make_detail(publisher_id=1, fully_passes=False)
        assert _regular_status(detail) == "FAIL"

    def test_error_benchmark(self):
        detail = make_detail(publisher_id=1, benchmark_error="No data")
        assert _regular_status(detail) == "ERROR"

    def test_error_uptime(self):
        detail = make_detail(publisher_id=1, uptime_error="Timeout")
        assert _regular_status(detail) == "ERROR"


class TestPremarketStatus:
    def test_pass(self):
        detail = make_detail(
            publisher_id=1,
            premarket_benchmark_passes=True,
            premarket_uptime_passes=True,
            premarket_uptime_pct=99.0,
        )
        assert _premarket_status(detail) == "PASS"

    def test_fail_benchmark(self):
        detail = make_detail(
            publisher_id=1,
            premarket_benchmark_passes=False,
            premarket_uptime_passes=True,
            premarket_uptime_pct=99.0,
        )
        assert _premarket_status(detail) == "FAIL"

    def test_fail_uptime(self):
        detail = make_detail(
            publisher_id=1,
            premarket_benchmark_passes=True,
            premarket_uptime_passes=False,
            premarket_uptime_pct=80.0,
        )
        assert _premarket_status(detail) == "FAIL"

    def test_no_data_none_uptime(self):
        detail = make_detail(publisher_id=1, premarket_uptime_pct=None)
        assert _premarket_status(detail) is None

    def test_no_data_zero_uptime(self):
        detail = make_detail(publisher_id=1, premarket_uptime_pct=0.0)
        assert _premarket_status(detail) is None

    def test_error_benchmark_none(self):
        detail = make_detail(
            publisher_id=1,
            premarket_benchmark_passes=None,
            premarket_uptime_passes=True,
            premarket_uptime_pct=99.0,
        )
        assert _premarket_status(detail) == "ERROR"


class TestAfterhoursStatus:
    def test_pass(self):
        detail = make_detail(
            publisher_id=1,
            afterhours_benchmark_passes=True,
            afterhours_uptime_passes=True,
            afterhours_uptime_pct=99.0,
        )
        assert _afterhours_status(detail) == "PASS"

    def test_no_data(self):
        detail = make_detail(publisher_id=1, afterhours_uptime_pct=None)
        assert _afterhours_status(detail) is None

    def test_fail(self):
        detail = make_detail(
            publisher_id=1,
            afterhours_benchmark_passes=False,
            afterhours_uptime_passes=True,
            afterhours_uptime_pct=99.0,
        )
        assert _afterhours_status(detail) == "FAIL"


class TestOvernightStatus:
    def test_pass(self):
        detail = make_detail(
            publisher_id=1,
            overnight_benchmark_passes=True,
            overnight_uptime_passes=True,
            overnight_uptime_pct=99.0,
        )
        assert _overnight_status(detail) == "PASS"

    def test_no_data(self):
        detail = make_detail(publisher_id=1, overnight_uptime_pct=None)
        assert _overnight_status(detail) is None

    def test_error(self):
        detail = make_detail(
            publisher_id=1,
            overnight_benchmark_passes=None,
            overnight_uptime_passes=True,
            overnight_uptime_pct=99.0,
        )
        assert _overnight_status(detail) == "ERROR"


# ---------------------------------------------------------------------------
# compute_publisher_consistency tests
# ---------------------------------------------------------------------------


class TestComputePublisherConsistency:
    """Tests for compute_publisher_consistency with status_extractor."""

    def _make_two_date_results(self):
        """Two dates, publisher 19 passes regular+premarket, publisher 20 fails both."""
        details_d1 = [
            make_detail(
                publisher_id=19, fully_passes=True, benchmark_passes=True, uptime_passes=True,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=99.0,
            ),
            make_detail(
                publisher_id=20, fully_passes=False,
                premarket_benchmark_passes=False, premarket_uptime_passes=True, premarket_uptime_pct=80.0,
            ),
        ]
        details_d2 = [
            make_detail(
                publisher_id=19, fully_passes=True, benchmark_passes=True, uptime_passes=True,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=99.0,
            ),
            make_detail(
                publisher_id=20, fully_passes=False,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=95.0,
            ),
        ]
        return [
            make_result(feed_id=100, date="2026-02-17", details=details_d1),
            make_result(feed_id=100, date="2026-02-18", details=details_d2),
        ]

    def test_regular_default_extractor(self):
        results = self._make_two_date_results()
        consistency = compute_publisher_consistency(results)
        row_19 = next(r for r in consistency["rows"] if r["publisher_id"] == 19)
        assert row_19["pass_count"] == 2
        assert 19 in consistency["classifications"]["always_passing"]
        row_20 = next(r for r in consistency["rows"] if r["publisher_id"] == 20)
        assert row_20["fail_count"] == 2
        assert 20 in consistency["classifications"]["always_failing"]

    def test_premarket_extractor(self):
        results = self._make_two_date_results()
        consistency = compute_publisher_consistency(results, status_extractor=_premarket_status)
        row_19 = next(r for r in consistency["rows"] if r["publisher_id"] == 19)
        assert row_19["pass_count"] == 2
        row_20 = next(r for r in consistency["rows"] if r["publisher_id"] == 20)
        assert row_20["pass_count"] == 1
        assert row_20["fail_count"] == 1
        assert 20 in consistency["classifications"]["intermittent"]

    def test_extractor_none_excludes_publisher(self):
        details = [
            make_detail(
                publisher_id=19, fully_passes=True,
                premarket_uptime_pct=99.0, premarket_benchmark_passes=True, premarket_uptime_passes=True,
            ),
            make_detail(
                publisher_id=20, fully_passes=False,
                premarket_uptime_pct=None,
            ),
        ]
        results = [
            make_result(feed_id=100, date="2026-02-17", details=details),
            make_result(feed_id=100, date="2026-02-18", details=details),
        ]
        consistency = compute_publisher_consistency(results, status_extractor=_premarket_status)
        publisher_ids = {r["publisher_id"] for r in consistency["rows"]}
        assert 19 in publisher_ids
        assert 20 not in publisher_ids

    def test_backward_compatible_no_extractor(self):
        details = [make_detail(publisher_id=19, fully_passes=True, benchmark_passes=True, uptime_passes=True)]
        results = [
            make_result(feed_id=100, date="2026-02-17", details=details),
            make_result(feed_id=100, date="2026-02-18", details=details),
        ]
        consistency = compute_publisher_consistency(results)
        assert consistency["classifications"]["always_passing"] == [19]


# ---------------------------------------------------------------------------
# write_publisher_consistency_csv tests
# ---------------------------------------------------------------------------


class TestWritePublisherConsistencyCsv:
    def _write_and_read(self, consistency, session_prefix=""):
        buf = io.StringIO()
        writer = csv.writer(buf)
        write_publisher_consistency_csv(writer, consistency, session_prefix=session_prefix)
        buf.seek(0)
        return buf.getvalue()

    def _make_consistency(self):
        return {
            "dates": ["2026-02-17", "2026-02-18"],
            "rows": [
                {
                    "publisher_id": 19,
                    "dates_seen": 2,
                    "pass_count": 2,
                    "fail_count": 0,
                    "error_count": 0,
                    "pass_rate": 100.0,
                    "results": {"2026-02-17": "PASS", "2026-02-18": "PASS"},
                },
            ],
            "classifications": {
                "always_passing": [19],
                "always_failing": [],
                "intermittent": [],
            },
        }

    def test_regular_default_prefix(self):
        output = self._write_and_read(self._make_consistency())
        assert "PUBLISHER CONSISTENCY" in output
        assert "PUBLISHER CLASSIFICATIONS" in output
        assert "regular_always_passing" in output

    def test_premarket_prefix(self):
        output = self._write_and_read(self._make_consistency(), session_prefix="PREMARKET ")
        assert "PREMARKET PUBLISHER CONSISTENCY" in output
        assert "PREMARKET PUBLISHER CLASSIFICATIONS" in output
        assert "premarket_always_passing" in output
        assert "regular_always_passing" not in output

    def test_overnight_prefix(self):
        output = self._write_and_read(self._make_consistency(), session_prefix="OVERNIGHT ")
        assert "OVERNIGHT PUBLISHER CONSISTENCY" in output
        assert "overnight_always_passing" in output


# ---------------------------------------------------------------------------
# print_publisher_consistency tests
# ---------------------------------------------------------------------------


class TestPrintPublisherConsistency:
    def _make_consistency(self):
        return {
            "dates": ["2026-02-17", "2026-02-18"],
            "rows": [
                {
                    "publisher_id": 19,
                    "dates_seen": 2,
                    "pass_count": 2,
                    "fail_count": 0,
                    "error_count": 0,
                    "pass_rate": 100.0,
                    "results": {"2026-02-17": "PASS", "2026-02-18": "PASS"},
                },
            ],
            "classifications": {
                "always_passing": [19],
                "always_failing": [],
                "intermittent": [],
            },
        }

    def test_regular_default(self, capsys):
        print_publisher_consistency(self._make_consistency())
        out = capsys.readouterr().out
        assert "REGULAR SESSION:" in out
        assert "Always passing:" in out

    def test_premarket_session(self, capsys):
        print_publisher_consistency(self._make_consistency(), session_prefix="PREMARKET ")
        out = capsys.readouterr().out
        assert "PREMARKET SESSION:" in out

    def test_overnight_session(self, capsys):
        print_publisher_consistency(self._make_consistency(), session_prefix="OVERNIGHT ")
        out = capsys.readouterr().out
        assert "OVERNIGHT SESSION:" in out


# ---------------------------------------------------------------------------
# write_results_csv session consistency integration tests
# ---------------------------------------------------------------------------


class TestWriteResultsCsvSessionConsistency:
    def _make_multi_date_results(self):
        """Two dates with session data for premarket and overnight."""
        details_d1 = [
            make_detail(
                publisher_id=19, fully_passes=True, benchmark_passes=True, uptime_passes=True,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=99.0,
                afterhours_benchmark_passes=True, afterhours_uptime_passes=True, afterhours_uptime_pct=98.0,
                overnight_benchmark_passes=True, overnight_uptime_passes=True, overnight_uptime_pct=98.0,
            ),
            make_detail(
                publisher_id=20, fully_passes=False,
                premarket_benchmark_passes=False, premarket_uptime_passes=True, premarket_uptime_pct=80.0,
                afterhours_benchmark_passes=False, afterhours_uptime_passes=True, afterhours_uptime_pct=70.0,
                overnight_uptime_pct=None,
            ),
        ]
        details_d2 = [
            make_detail(
                publisher_id=19, fully_passes=True, benchmark_passes=True, uptime_passes=True,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=99.0,
                afterhours_benchmark_passes=True, afterhours_uptime_passes=True, afterhours_uptime_pct=97.0,
                overnight_benchmark_passes=False, overnight_uptime_passes=True, overnight_uptime_pct=95.0,
            ),
            make_detail(
                publisher_id=20, fully_passes=False,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=95.0,
                afterhours_benchmark_passes=True, afterhours_uptime_passes=True, afterhours_uptime_pct=90.0,
                overnight_uptime_pct=None,
            ),
        ]
        return [
            make_result(feed_id=100, date="2026-02-17", details=details_d1),
            make_result(feed_id=100, date="2026-02-18", details=details_d2),
        ]

    def test_no_session_sections_without_flags(self):
        results = self._make_multi_date_results()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = Path(f.name)
        write_results_csv(results, path, include_extended_hours=False, include_overnight=False, include_detailed=True)
        content = path.read_text()
        assert "PUBLISHER CONSISTENCY" in content
        assert "PREMARKET PUBLISHER CONSISTENCY" not in content
        assert "OVERNIGHT PUBLISHER CONSISTENCY" not in content
        path.unlink()

    def test_extended_hours_adds_premarket_afterhours(self):
        results = self._make_multi_date_results()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = Path(f.name)
        write_results_csv(results, path, include_extended_hours=True, include_overnight=False, include_detailed=True)
        content = path.read_text()
        assert "PUBLISHER CONSISTENCY" in content
        assert "PREMARKET PUBLISHER CONSISTENCY" in content
        assert "PREMARKET PUBLISHER CLASSIFICATIONS" in content
        assert "premarket_always_passing" in content
        assert "AFTERHOURS PUBLISHER CONSISTENCY" in content
        assert "afterhours_always_passing" in content
        assert "OVERNIGHT PUBLISHER CONSISTENCY" not in content
        path.unlink()

    def test_overnight_adds_overnight_section(self):
        results = self._make_multi_date_results()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = Path(f.name)
        write_results_csv(results, path, include_extended_hours=False, include_overnight=True, include_detailed=True)
        content = path.read_text()
        assert "OVERNIGHT PUBLISHER CONSISTENCY" in content
        assert "overnight_always_passing" in content
        assert "PREMARKET PUBLISHER CONSISTENCY" not in content
        path.unlink()

    def test_both_flags_all_sections(self):
        results = self._make_multi_date_results()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = Path(f.name)
        write_results_csv(results, path, include_extended_hours=True, include_overnight=True, include_detailed=True)
        content = path.read_text()
        assert "PUBLISHER CONSISTENCY" in content
        assert "PREMARKET PUBLISHER CONSISTENCY" in content
        assert "AFTERHOURS PUBLISHER CONSISTENCY" in content
        assert "OVERNIGHT PUBLISHER CONSISTENCY" in content
        path.unlink()

    def test_single_date_no_session_sections(self):
        details = [
            make_detail(
                publisher_id=19, fully_passes=True, benchmark_passes=True, uptime_passes=True,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=99.0,
            ),
        ]
        results = [make_result(feed_id=100, date="2026-02-17", details=details)]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = Path(f.name)
        write_results_csv(results, path, include_extended_hours=True, include_overnight=True, include_detailed=True)
        content = path.read_text()
        assert "PREMARKET PUBLISHER CONSISTENCY" not in content
        path.unlink()
