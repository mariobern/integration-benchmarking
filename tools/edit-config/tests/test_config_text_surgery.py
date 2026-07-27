from pathlib import Path

import pytest
import json
from edit_config_lib.config_text_surgery import find_feed_block, find_matching_close
from edit_config_lib.config_text_surgery import (
    find_session_block,
    find_publisher_array_span,
    find_int_field_span,
    find_string_field_span,
    find_object_field_span,
    find_number_field_span,
    insert_field_before_close_brace,
    delete_object_field,
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


from edit_config_lib.config_text_surgery import find_ric_identifier_spans


def test_find_ric_identifier_spans_single_empty():
    block = """{
  "feedId": 884,
  "marketSchedules": [
    {
      "benchmarkMapping": {
        "datascope_ric": {
          "identifiers": [
            {
              "identifier": "",
              "validFrom": "1970-01-01T00:00:00.000000000Z"
            }
          ]
        }
      }
    }
  ]
}"""
    spans = find_ric_identifier_spans(block)
    assert len(spans) == 1
    start, end, value = spans[0]
    assert block[start:end] == '""'
    assert value == ""


def test_find_ric_identifier_spans_populated_is_returned_too():
    block = """{
  "marketSchedules": [
    {
      "benchmarkMapping": {
        "datascope_ric": {
          "identifiers": [
            {"identifier": "0700.HK", "validFrom": "1970-01-01T00:00:00.000000000Z"}
          ]
        }
      }
    }
  ]
}"""
    spans = find_ric_identifier_spans(block)
    assert len(spans) == 1
    start, end, value = spans[0]
    assert block[start:end] == '"0700.HK"'
    assert value == "0700.HK"


def test_find_ric_identifier_spans_multiple_schedules():
    block = """{
  "marketSchedules": [
    {"benchmarkMapping": {"datascope_ric": {"identifiers": [{"identifier": ""}]}}},
    {"benchmarkMapping": {"datascope_ric": {"identifiers": [{"identifier": "X"}]}}}
  ]
}"""
    spans = find_ric_identifier_spans(block)
    assert [v for _, _, v in spans] == ["", "X"]
    assert spans[0][0] < spans[1][0]


def test_find_ric_identifier_spans_no_datascope_ric():
    block = '{"marketSchedules": [{"benchmarkMapping": {}}]}'
    assert find_ric_identifier_spans(block) == []


def test_find_ric_identifier_spans_no_marketSchedules():
    block = '{"feedId": 1}'
    assert find_ric_identifier_spans(block) == []


import json

from edit_config_lib.config_text_surgery import (
    insert_field_after_open_brace,
    insert_field_before_session,
    find_marketschedules_end,
)


class TestInsertHelpers:
    SESSION_BLOCK = (
        "{\n"
        '          "marketSchedule": "X",\n'
        '          "session": "REGULAR"\n'
        "        }"
    )

    def test_insert_after_open_brace_leads_the_entry(self):
        out = insert_field_after_open_brace(
            self.SESSION_BLOCK, '"allowedPublisherIds": [ 80 ],'
        )
        data = json.loads(out)
        assert data["allowedPublisherIds"] == [80]
        assert list(data.keys())[0] == "allowedPublisherIds"

    def test_insert_after_open_brace_matches_indent(self):
        out = insert_field_after_open_brace(
            self.SESSION_BLOCK, '"allowedPublisherIds": [ 80 ],'
        )
        assert '\n          "allowedPublisherIds": [ 80 ],\n' in out

    def test_insert_before_session_canonical_position(self):
        out = insert_field_before_session(self.SESSION_BLOCK, '"minPublishers": 3,')
        data = json.loads(out)
        assert list(data.keys()) == ["marketSchedule", "minPublishers", "session"]

    def test_insert_before_session_falls_back_without_session_key(self):
        block = '{\n  "foo": 1\n}'
        out = insert_field_before_session(block, '"minPublishers": 3,')
        assert json.loads(out)["minPublishers"] == 3


class TestFindMarketschedulesEnd:
    def test_end_points_past_closing_bracket(self):
        block = (
            '{ "marketSchedules": [ { "minPublishers": 2, "session": "REGULAR" } ],'
            ' "minPublishers": 3 }'
        )
        end = find_marketschedules_end(block)
        assert block[end - 1] == "]"
        assert '"minPublishers": 3' in block[end:]

    def test_absent_array_returns_zero(self):
        assert find_marketschedules_end('{ "foo": 1 }') == 0


from edit_config_lib.config_text_surgery import delete_scalar_field


class TestDeleteScalarField:
    def test_deletes_int_field_and_trailing_comma(self):
        block = '{\n  "exchangeId": 1,\n  "feedId": 922\n}'
        out = delete_scalar_field(block, "exchangeId")
        assert out == '{\n  "feedId": 922\n}'

    def test_deletes_string_field(self):
        block = (
            '{\n  "marketSchedule": "America/New_York;0930-1600",\n'
            '  "session": "REGULAR"\n}'
        )
        out = delete_scalar_field(block, "marketSchedule")
        assert out == '{\n  "session": "REGULAR"\n}'

    def test_string_value_with_escaped_quote(self):
        block = '{\n  "k": "a\\"b",\n  "session": "REGULAR"\n}'
        out = delete_scalar_field(block, "k")
        assert out == '{\n  "session": "REGULAR"\n}'

    def test_absent_key_returns_unchanged(self):
        block = '{\n  "session": "REGULAR"\n}'
        assert delete_scalar_field(block, "exchangeId") == block

    def test_only_named_key_removed(self):
        block = '{\n  "exchangeId": 1,\n  "expiryTime": "5s",\n  "feedId": 5\n}'
        out = delete_scalar_field(block, "exchangeId")
        assert '"expiryTime"' in out and '"feedId"' in out
        assert '"exchangeId"' not in out


SESSION_WITH_FILTER = """        {
          "allowedPublisherIds": [
            59,
            84
          ],
          "minPublishers": 2,
          "session": "REGULAR",
          "stalePriceFilter": {
            "movedPriceThresholdBps": 0.5,
            "stalenessThresholdSecs": 10800,
            "windowSecs": 60
          }
        }"""

SESSION_WITHOUT_FILTER = """        {
          "allowedPublisherIds": [
            59,
            84
          ],
          "minPublishers": 2,
          "session": "REGULAR"
        }"""


class TestFindObjectFieldSpan:
    def test_locates_stale_price_filter(self):
        span = find_object_field_span(SESSION_WITH_FILTER, "stalePriceFilter")
        assert span is not None
        assert SESSION_WITH_FILTER[span[0]] == "{"
        assert SESSION_WITH_FILTER[span[1] - 1] == "}"
        assert json.loads(SESSION_WITH_FILTER[span[0] : span[1]]) == {
            "movedPriceThresholdBps": 0.5,
            "stalenessThresholdSecs": 10800,
            "windowSecs": 60,
        }

    def test_absent_field_returns_none(self):
        assert find_object_field_span(SESSION_WITHOUT_FILTER, "stalePriceFilter") is None


class TestFindNumberFieldSpan:
    def test_decimal_value_captured_whole(self):
        span = find_number_field_span(SESSION_WITH_FILTER, "movedPriceThresholdBps")
        assert span is not None
        assert SESSION_WITH_FILTER[span[0] : span[1]] == "0.5"

    def test_integer_value(self):
        span = find_number_field_span(SESSION_WITH_FILTER, "windowSecs")
        assert SESSION_WITH_FILTER[span[0] : span[1]] == "60"

    def test_replacing_decimal_keeps_json_valid(self):
        span = find_number_field_span(SESSION_WITH_FILTER, "movedPriceThresholdBps")
        out = SESSION_WITH_FILTER[: span[0]] + "2.5" + SESSION_WITH_FILTER[span[1] :]
        assert json.loads(out)["stalePriceFilter"]["movedPriceThresholdBps"] == 2.5

    def test_absent_field_returns_none(self):
        assert find_number_field_span(SESSION_WITH_FILTER, "nope") is None


class TestInsertFieldBeforeCloseBrace:
    def test_appends_as_last_field_with_comma_on_previous_line(self):
        field = '"stalePriceFilter": {\n            "windowSecs": 60\n          }'
        out = insert_field_before_close_brace(SESSION_WITHOUT_FILTER, field)
        parsed = json.loads(out)
        assert parsed["stalePriceFilter"] == {"windowSecs": 60}
        assert parsed["session"] == "REGULAR"
        assert '"session": "REGULAR",' in out

    def test_empty_object(self):
        out = insert_field_before_close_brace("{\n        }", '"a": 1')
        assert json.loads(out) == {"a": 1}


class TestDeleteObjectField:
    def test_removes_field_and_preceding_comma(self):
        out = delete_object_field(SESSION_WITH_FILTER, "stalePriceFilter")
        parsed = json.loads(out)
        assert "stalePriceFilter" not in parsed
        assert parsed["session"] == "REGULAR"
        assert parsed["minPublishers"] == 2

    def test_absent_field_is_noop(self):
        assert (
            delete_object_field(SESSION_WITHOUT_FILTER, "stalePriceFilter")
            == SESSION_WITHOUT_FILTER
        )

    def test_only_field_leaves_empty_object(self):
        block = '{\n  "stalePriceFilter": {\n    "windowSecs": 60\n  }\n}'
        assert json.loads(delete_object_field(block, "stalePriceFilter")) == {}
