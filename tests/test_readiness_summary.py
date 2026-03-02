"""Tests for write_summary_csv() in lib/readiness_output.py."""
import csv
from pathlib import Path
from typing import Optional

from lib.readiness_core import FeedReadinessResult
from lib.readiness_output import write_summary_csv


def _make_result(
    feed_id: int = 100,
    date: str = "2026-01-15",
    mode: str = "us-equities",
    symbol: str = "Equity.US.TEST/USD",
    ready: bool = True,
    fully_passing_count: int = 5,
    target_pub_count: int = 4,
    median_nrmse: Optional[float] = 0.003456,
    median_hit_rate: Optional[float] = 97.65,
    median_uptime_pct: Optional[float] = 99.8765,
    fully_passing_publishers: Optional[list[int]] = None,
    premarket_ready: Optional[bool] = None,
    premarket_fully_passing_count: Optional[int] = None,
    premarket_median_uptime_pct: Optional[float] = None,
    premarket_fully_passing_publishers: Optional[list[int]] = None,
    afterhours_ready: Optional[bool] = None,
    afterhours_fully_passing_count: Optional[int] = None,
    afterhours_median_uptime_pct: Optional[float] = None,
    afterhours_fully_passing_publishers: Optional[list[int]] = None,
    overnight_ready: Optional[bool] = None,
    overnight_fully_passing_count: Optional[int] = None,
    overnight_median_uptime_pct: Optional[float] = None,
    overnight_fully_passing_publishers: Optional[list[int]] = None,
) -> FeedReadinessResult:
    if fully_passing_publishers is None:
        fully_passing_publishers = list(range(1, fully_passing_count + 1))
    return FeedReadinessResult(
        feed_id=feed_id,
        date=date,
        mode=mode,
        symbol=symbol,
        ready=ready,
        benchmark_ready=ready,
        uptime_ready=ready,
        target_pub_count=target_pub_count,
        fully_passing_count=fully_passing_count,
        benchmark_only_passing_count=0,
        uptime_only_passing_count=0,
        both_failing_count=0,
        total_publisher_count=fully_passing_count,
        benchmark_passing_count=fully_passing_count,
        benchmark_failing_count=0,
        median_nrmse=median_nrmse,
        median_hit_rate=median_hit_rate,
        uptime_passing_count=fully_passing_count,
        uptime_failing_count=0,
        median_uptime_pct=median_uptime_pct,
        fully_passing_publishers=fully_passing_publishers,
        benchmark_only_publishers=[],
        uptime_only_publishers=[],
        both_failing_publishers=[],
        premarket_ready=premarket_ready,
        premarket_fully_passing_count=premarket_fully_passing_count,
        premarket_median_uptime_pct=premarket_median_uptime_pct,
        premarket_fully_passing_publishers=premarket_fully_passing_publishers,
        afterhours_ready=afterhours_ready,
        afterhours_fully_passing_count=afterhours_fully_passing_count,
        afterhours_median_uptime_pct=afterhours_median_uptime_pct,
        afterhours_fully_passing_publishers=afterhours_fully_passing_publishers,
        overnight_ready=overnight_ready,
        overnight_fully_passing_count=overnight_fully_passing_count,
        overnight_median_uptime_pct=overnight_median_uptime_pct,
        overnight_fully_passing_publishers=overnight_fully_passing_publishers,
    )


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    """Read CSV and return (header, data_rows)."""
    with open(path) as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


class TestWriteSummaryCsv:
    """Tests for write_summary_csv()."""

    def test_only_ready_feeds_included(self, tmp_path):
        """3 results (2 ready, 1 not), verify only 2 rows written."""
        results = [
            _make_result(feed_id=1, ready=True),
            _make_result(feed_id=2, ready=False),
            _make_result(feed_id=3, ready=True),
        ]
        out = tmp_path / "summary.csv"
        count = write_summary_csv(results, out)

        assert count == 2
        header, rows = _read_csv(out)
        assert len(rows) == 2
        feed_ids = {row[0] for row in rows}
        assert feed_ids == {"1", "3"}

    def test_base_columns_present(self, tmp_path):
        """Verify exactly 10 base columns."""
        results = [_make_result()]
        out = tmp_path / "summary.csv"
        write_summary_csv(results, out)

        header, _ = _read_csv(out)
        expected = [
            "feed_id",
            "symbol",
            "date",
            "mode",
            "fully_passing_count",
            "target_pub_count",
            "median_nrmse",
            "median_hit_rate",
            "median_uptime_pct",
            "fully_passing_publishers",
        ]
        assert header == expected

    def test_column_values_formatted(self, tmp_path):
        """Verify nrmse 6 decimals, hit_rate 2 decimals, uptime 4 decimals,
        publishers semicolon-separated."""
        results = [
            _make_result(
                feed_id=42,
                symbol="Equity.US.AAPL/USD",
                date="2026-02-01",
                mode="us-equities",
                median_nrmse=0.003456,
                median_hit_rate=97.65,
                median_uptime_pct=99.8765,
                fully_passing_publishers=[10, 20, 30],
                fully_passing_count=3,
                target_pub_count=3,
            )
        ]
        out = tmp_path / "summary.csv"
        write_summary_csv(results, out)

        _, rows = _read_csv(out)
        assert len(rows) == 1
        row = rows[0]
        # Column indices: 0=feed_id, 1=symbol, 2=date, 3=mode,
        # 4=fully_passing_count, 5=target_pub_count,
        # 6=median_nrmse, 7=median_hit_rate, 8=median_uptime_pct,
        # 9=fully_passing_publishers
        assert row[6] == "0.003456"  # nrmse 6 decimals
        assert row[7] == "97.65"  # hit_rate 2 decimals
        assert row[8] == "99.8765"  # uptime 4 decimals
        assert row[9] == "10;20;30"  # semicolon-separated

    def test_no_ready_feeds_writes_header_only(self, tmp_path):
        """0 ready feeds -> header-only CSV."""
        results = [
            _make_result(feed_id=1, ready=False),
            _make_result(feed_id=2, ready=False),
        ]
        out = tmp_path / "summary.csv"
        count = write_summary_csv(results, out)

        assert count == 0
        header, rows = _read_csv(out)
        assert len(header) > 0
        assert len(rows) == 0

    def test_sorted_by_date_feed_id_mode(self, tmp_path):
        """Verify sort order: date, feed_id, mode."""
        results = [
            _make_result(feed_id=200, date="2026-01-20", mode="us-equities"),
            _make_result(feed_id=100, date="2026-01-20", mode="fx"),
            _make_result(feed_id=100, date="2026-01-15", mode="fx"),
            _make_result(feed_id=100, date="2026-01-20", mode="metals"),
        ]
        out = tmp_path / "summary.csv"
        write_summary_csv(results, out)

        _, rows = _read_csv(out)
        assert len(rows) == 4
        # Expected order: (2026-01-15, 100, fx), (2026-01-20, 100, fx),
        # (2026-01-20, 100, metals), (2026-01-20, 200, us-equities)
        assert rows[0][0] == "100"  # feed_id
        assert rows[0][2] == "2026-01-15"  # date
        assert rows[1][0] == "100"
        assert rows[1][2] == "2026-01-20"
        assert rows[1][3] == "fx"
        assert rows[2][0] == "100"
        assert rows[2][3] == "metals"
        assert rows[3][0] == "200"
        assert rows[3][3] == "us-equities"

    def test_extended_hours_columns(self, tmp_path):
        """With include_extended_hours=True, verify 4 extra columns."""
        results = [
            _make_result(
                premarket_ready=True,
                premarket_fully_passing_count=4,
                premarket_median_uptime_pct=98.5432,
                premarket_fully_passing_publishers=[1, 2, 3, 4],
                afterhours_ready=False,
                afterhours_fully_passing_count=2,
                afterhours_median_uptime_pct=95.1234,
                afterhours_fully_passing_publishers=[1, 2],
            )
        ]
        out = tmp_path / "summary.csv"
        write_summary_csv(results, out, include_extended_hours=True)

        header, rows = _read_csv(out)
        # 10 base + 4 extended = 14
        assert len(header) == 14
        assert "premarket_ready" in header
        assert "premarket_fully_passing_count" in header
        assert "afterhours_ready" in header
        assert "afterhours_fully_passing_count" in header

        row = rows[0]
        pm_rd_idx = header.index("premarket_ready")
        pm_fp_idx = header.index("premarket_fully_passing_count")
        ah_rd_idx = header.index("afterhours_ready")
        ah_fp_idx = header.index("afterhours_fully_passing_count")
        assert row[pm_rd_idx] == "True"
        assert row[pm_fp_idx] == "4"
        assert row[ah_rd_idx] == "False"
        assert row[ah_fp_idx] == "2"

    def test_overnight_columns(self, tmp_path):
        """With include_overnight=True, verify 2 extra columns."""
        results = [
            _make_result(
                overnight_ready=True,
                overnight_fully_passing_count=5,
                overnight_median_uptime_pct=97.6543,
                overnight_fully_passing_publishers=[1, 2, 3, 4, 5],
            )
        ]
        out = tmp_path / "summary.csv"
        write_summary_csv(results, out, include_overnight=True)

        header, rows = _read_csv(out)
        # 10 base + 2 overnight = 12
        assert len(header) == 12
        assert "overnight_ready" in header
        assert "overnight_fully_passing_count" in header

        row = rows[0]
        on_rd_idx = header.index("overnight_ready")
        on_fp_idx = header.index("overnight_fully_passing_count")
        assert row[on_rd_idx] == "True"
        assert row[on_fp_idx] == "5"

    def test_no_extended_columns_by_default(self, tmp_path):
        """Verify extended columns absent without flags."""
        results = [_make_result()]
        out = tmp_path / "summary.csv"
        write_summary_csv(results, out)

        header, _ = _read_csv(out)
        assert len(header) == 10
        for col in [
            "premarket_ready",
            "premarket_fully_passing_count",
            "afterhours_ready",
            "afterhours_fully_passing_count",
            "overnight_ready",
            "overnight_fully_passing_count",
        ]:
            assert col not in header

    def test_none_metrics_render_empty(self, tmp_path):
        """None values -> empty strings."""
        results = [
            _make_result(
                median_nrmse=None,
                median_hit_rate=None,
                median_uptime_pct=None,
                fully_passing_publishers=[],
                fully_passing_count=0,
                target_pub_count=0,
            )
        ]
        out = tmp_path / "summary.csv"
        write_summary_csv(results, out)

        _, rows = _read_csv(out)
        assert len(rows) == 1
        row = rows[0]
        # nrmse, hit_rate, uptime should be empty strings
        assert row[6] == ""  # median_nrmse
        assert row[7] == ""  # median_hit_rate
        assert row[8] == ""  # median_uptime_pct
        assert row[9] == ""  # fully_passing_publishers (empty list)

    def test_empty_session_publisher_lists_render_empty(self, tmp_path):
        """Session publisher list columns should be empty when values are []/None."""
        results = [
            _make_result(
                premarket_ready=False,
                premarket_fully_passing_count=0,
                premarket_fully_passing_publishers=[],
                afterhours_ready=False,
                afterhours_fully_passing_count=0,
                afterhours_fully_passing_publishers=None,
                overnight_ready=False,
                overnight_fully_passing_count=0,
                overnight_fully_passing_publishers=None,
            )
        ]
        out = tmp_path / "summary.csv"
        write_summary_csv(
            results,
            out,
            include_extended_hours=True,
            include_overnight=True,
        )

        header, rows = _read_csv(out)
        row = rows[0]
        assert row[header.index("premarket_fully_passing_publishers")] == ""
        assert row[header.index("afterhours_fully_passing_publishers")] == ""
        assert row[header.index("overnight_fully_passing_publishers")] == ""
