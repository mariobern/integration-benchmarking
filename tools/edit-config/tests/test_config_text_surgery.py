from pathlib import Path

import pytest
from edit_config_lib.config_text_surgery import find_feed_block, find_matching_close
from edit_config_lib.config_text_surgery import (
    find_session_block,
    find_publisher_array_span,
    find_int_field_span,
    find_string_field_span,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "after_sample.json"


class TestFindMatchingClose:
    def test_simple_object(self):
        s = "{}"
        assert find_matching_close(s, 0) == 1

    def test_simple_array(self):
        s = "[]"
        assert find_matching_close(s, 0) == 1

    def test_nested_object(self):
        s = '{"a": {"b": 1}}'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_nested_array(self):
        s = "[[1, 2], [3, 4]]"
        assert find_matching_close(s, 0) == len(s) - 1

    def test_string_with_close_brace(self):
        s = '{"a": "}"}'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_string_with_close_bracket(self):
        s = '["]", "x"]'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_string_with_escaped_quote(self):
        s = '{"a": "he said \\"hi\\""}'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_string_with_escaped_backslash_then_quote(self):
        # "abc\\" — backslash is escaped, the quote then closes the string
        s = '{"a": "abc\\\\"}'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_starts_at_inner_open(self):
        s = '{"a": {"b": 1}}'
        # Inner { starts at index 6 (after '"a": ')
        assert find_matching_close(s, 6) == 13

    def test_unbalanced_returns_none(self):
        assert find_matching_close("{[}", 0) is None
        assert find_matching_close("{", 0) is None

    def test_offset_not_on_open_returns_none(self):
        assert find_matching_close('{"a": 1}', 1) is None


class TestFindFeedBlock:
    def setup_method(self):
        self.raw = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_finds_first_feed(self):
        bounds = find_feed_block(self.raw, 1)
        assert bounds is not None
        start, end = bounds
        block = self.raw[start:end]
        assert block.startswith("{")
        assert block.endswith("}")
        assert '"feedId": 1' in block

    def test_finds_feed_922(self):
        bounds = find_feed_block(self.raw, 922)
        assert bounds is not None
        start, end = bounds
        block = self.raw[start:end]
        assert '"feedId": 922' in block
        assert '"symbol": "Equity.US.AAPL/USD"' in block

    def test_missing_feed_returns_none(self):
        assert find_feed_block(self.raw, 99999) is None

    def test_does_not_match_substring_of_id(self):
        # feedId 100 should not be matched by a search for 10
        assert find_feed_block(self.raw, 10) is None


class TestFindSessionBlock:
    def setup_method(self):
        self.raw = FIXTURE_PATH.read_text(encoding="utf-8")
        start, end = find_feed_block(self.raw, 922)
        self.feed_block = self.raw[start:end]

    def test_finds_regular(self):
        bounds = find_session_block(self.feed_block, "REGULAR")
        assert bounds is not None
        s, e = bounds
        sub = self.feed_block[s:e]
        assert '"session": "REGULAR"' in sub

    def test_finds_pre_market(self):
        bounds = find_session_block(self.feed_block, "PRE_MARKET")
        assert bounds is not None
        s, e = bounds
        assert '"session": "PRE_MARKET"' in self.feed_block[s:e]

    def test_missing_session_returns_none(self):
        # PRE_MARKET on a single-session feed
        start, end = find_feed_block(self.raw, 1)
        crypto_block = self.raw[start:end]
        assert find_session_block(crypto_block, "PRE_MARKET") is None


class TestFindPublisherArraySpan:
    def setup_method(self):
        self.raw = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_top_level_array(self):
        start, end = find_feed_block(self.raw, 1)
        block = self.raw[start:end]
        bounds = find_publisher_array_span(block)
        assert bounds is not None
        s, e = bounds
        # The slice should be exactly the [ … ] value
        assert block[s] == "["
        assert block[e - 1] == "]"
        # Contents should match: [ 1, 3, 7, 11 ]
        assert "1" in block[s:e] and "11" in block[s:e]

    def test_session_array(self):
        start, end = find_feed_block(self.raw, 922)
        feed = self.raw[start:end]
        s_start, s_end = find_session_block(feed, "OVER_NIGHT")
        sess = feed[s_start:s_end]
        bounds = find_publisher_array_span(sess)
        assert bounds is not None
        s, e = bounds
        assert sess[s] == "["
        assert sess[e - 1] == "]"


class TestFindIntFieldSpan:
    def setup_method(self):
        self.raw = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_top_level_min_publishers(self):
        # We want the top-level minPublishers, not a session's. Pass
        # the top-level "tail" portion of the feed (after marketSchedules).
        from edit_config_lib.config_text_surgery import find_matching_close

        start, end = find_feed_block(self.raw, 922)
        feed = self.raw[start:end]
        # locate marketSchedules end and search after that
        ms_idx = feed.index('"marketSchedules":')
        ms_open = feed.index("[", ms_idx)
        ms_close = find_matching_close(feed, ms_open)
        tail = feed[ms_close + 1 :]
        bounds = find_int_field_span(tail, "minPublishers")
        assert bounds is not None
        s, e = bounds
        # The value of feed 922 top-level minPublishers is 1.
        assert tail[s:e] == "1"

    def test_session_min_publishers(self):
        start, end = find_feed_block(self.raw, 922)
        feed = self.raw[start:end]
        s_start, s_end = find_session_block(feed, "REGULAR")
        sess = feed[s_start:s_end]
        bounds = find_int_field_span(sess, "minPublishers")
        assert bounds is not None
        s, e = bounds
        assert sess[s:e] == "3"


class TestFindStringFieldSpan:
    def setup_method(self):
        self.raw = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_state_field(self):
        start, end = find_feed_block(self.raw, 1)
        feed = self.raw[start:end]
        bounds = find_string_field_span(feed, "state")
        assert bounds is not None
        s, e = bounds
        # Span should include the surrounding quotes
        assert feed[s] == '"'
        assert feed[e - 1] == '"'
        assert feed[s:e] == '"STABLE"'
