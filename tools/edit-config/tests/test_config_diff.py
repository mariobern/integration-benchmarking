import pytest

from lib.config_ops import Change
from lib.config_diff import render_diff


class TestRenderDiff:
    def test_publisher_change_renders(self):
        change = Change(
            feed_id=1000,
            symbol="X",
            location="top_level",
            field="allowedPublisherIds",
            before=[1, 3, 14],
            after=[1, 3, 14, 80],
        )
        out = render_diff([change])
        assert "@@ feedId 1000 (X) @@" in out
        assert "-" in out and "+" in out
        assert "[ 1, 3, 14 ]" in out
        assert "[ 1, 3, 14, 80 ]" in out

    def test_session_hunk_header_includes_session(self):
        change = Change(
            feed_id=922,
            symbol="Equity.US.AAPL/USD",
            location="PRE_MARKET",
            field="allowedPublisherIds",
            before=[1, 2, 3],
            after=[1, 2],
        )
        out = render_diff([change])
        assert "session PRE_MARKET" in out

    def test_int_field_renders_as_value(self):
        change = Change(
            feed_id=1,
            symbol="Crypto.BTC/USD",
            location="top_level",
            field="minPublishers",
            before=3,
            after=4,
        )
        out = render_diff([change])
        assert "minPublishers" in out
        assert '"minPublishers": 3' in out
        assert '"minPublishers": 4' in out

    def test_state_field_renders_quoted(self):
        change = Change(
            feed_id=1,
            symbol="X",
            location="top_level",
            field="state",
            before="STABLE",
            after="COMING_SOON",
        )
        out = render_diff([change])
        assert '"state": "STABLE"' in out
        assert '"state": "COMING_SOON"' in out

    def test_truncation(self):
        changes = [
            Change(
                feed_id=i,
                symbol=f"f{i}",
                location="top_level",
                field="minPublishers",
                before=2,
                after=3,
            )
            for i in range(50)
        ]
        out = render_diff(changes, max_hunks=10)
        # Only 10 hunks rendered + footer
        assert out.count("@@ feedId") == 10
        assert "40 more" in out

    def test_no_truncation_when_under_limit(self):
        changes = [
            Change(
                feed_id=i,
                symbol=f"f{i}",
                location="top_level",
                field="minPublishers",
                before=2,
                after=3,
            )
            for i in range(5)
        ]
        out = render_diff(changes, max_hunks=10)
        assert out.count("@@ feedId") == 5
        assert "more" not in out

    def test_show_full_diff_disables_truncation(self):
        changes = [
            Change(
                feed_id=i,
                symbol=f"f{i}",
                location="top_level",
                field="minPublishers",
                before=2,
                after=3,
            )
            for i in range(50)
        ]
        out = render_diff(changes, max_hunks=10, show_full=True)
        assert out.count("@@ feedId") == 50

    def test_empty_changes(self):
        out = render_diff([])
        assert out.strip() == "(no changes)"
