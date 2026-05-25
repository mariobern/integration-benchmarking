"""Unit tests for lib.json_surgery raw-text block finders."""
from lib.json_surgery import find_feed_block, find_session_block


def test_find_feed_block_locates_feed():
    raw = '{"feeds": [ {"feedId": 100, "state": "COMING_SOON"} ]}'
    bounds = find_feed_block(raw, 100)
    assert bounds is not None
    start, end = bounds
    assert raw[start] == "{"
    assert raw[end - 1] == "}"
    assert '"feedId": 100' in raw[start:end]


def test_find_feed_block_returns_none_for_missing():
    raw = '{"feeds": [ {"feedId": 100} ]}'
    assert find_feed_block(raw, 999) is None


def test_find_feed_block_with_nested_braces():
    raw = (
        '[ {"feedId": 60, "metadata": {"a": {"b": 1}}, '
        '"marketSchedules": [ {"session": "REGULAR"} ]} ]'
    )
    bounds = find_feed_block(raw, 60)
    assert bounds is not None
    start, end = bounds
    block = raw[start:end]
    assert block.count("{") == block.count("}")
    assert '"feedId": 60' in block


def test_find_session_block_locates_session():
    block = (
        '{"marketSchedules": [ '
        '{"allowedPublisherIds": [1,2], "session": "REGULAR"}, '
        '{"allowedPublisherIds": [3], "session": "PRE_MARKET"} ]}'
    )
    bounds = find_session_block(block, "PRE_MARKET")
    assert bounds is not None
    s, e = bounds
    assert '"session": "PRE_MARKET"' in block[s:e]
    assert '"session": "REGULAR"' not in block[s:e]


def test_find_session_block_returns_none_for_missing():
    block = '{"marketSchedules": [ {"session": "REGULAR"} ]}'
    assert find_session_block(block, "OVER_NIGHT") is None
