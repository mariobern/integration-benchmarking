"""Text-surgery layer: preserves byte-level formatting of after.json."""

from __future__ import annotations

import json
import re

from session_editor_lib.text_apply import (
    apply_edits,
    plan_add_session,
    plan_remove_session,
)


# --- Use compact text fixtures that mirror after.json's actual style. ---


COMPACT_FIXTURE = """\
{
  "feeds": [
    {
      "feedId": 924,
      "symbol": "Equity.US.ABNB/USD",
      "state": "STABLE",
      "metadata": { "asset_type": "equity" },
      "marketSchedules": [
        {
          "allowedPublisherIds": [ 1, 2, 3 ],
          "benchmarkMapping": {
            "datascope_ric": {
              "identifiers": [ { "identifier": "ABNB.O", "validFrom": "1970-01-01T00:00:00.000000000Z" } ]
            }
          },
          "marketSchedule": "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;",
          "minPublishers": 3,
          "session": "REGULAR"
        },
        {
          "allowedPublisherIds": [ 4, 5 ],
          "benchmarkMapping": {
            "datascope_ric": {
              "identifiers": [ { "identifier": "ABNB.O", "validFrom": "1970-01-01T00:00:00.000000000Z" } ]
            }
          },
          "marketSchedule": "America/New_York;0400-0930,0400-0930,0400-0930,0400-0930,0400-0930,C,C;",
          "minPublishers": 2,
          "session": "PRE_MARKET"
        }
      ]
    }
  ]
}
"""


def test_remove_middle_session_preserves_layout_except_block():
    edit = plan_remove_session(COMPACT_FIXTURE, feed_id=924, session="PRE_MARKET")
    assert edit is not None
    new_text = apply_edits(COMPACT_FIXTURE, [edit])

    # Result is still valid JSON.
    parsed = json.loads(new_text)
    sessions = [s["session"] for s in parsed["feeds"][0]["marketSchedules"]]
    assert sessions == ["REGULAR"]

    # PRE_MARKET block is gone but the surrounding lines are intact.
    assert "PRE_MARKET" not in new_text
    assert '"session": "REGULAR"' in new_text
    # Compact identifiers array preserved (no expansion).
    assert '"identifiers": [ { "identifier": "ABNB.O"' in new_text


def test_remove_missing_session_returns_none():
    edit = plan_remove_session(COMPACT_FIXTURE, feed_id=924, session="OVER_NIGHT")
    assert edit is None


def test_add_session_uses_regular_as_template_preserves_compact_style():
    edit = plan_add_session(
        COMPACT_FIXTURE, feed_id=924, session="OVER_NIGHT", min_publishers=100
    )
    assert edit is not None
    new_text = apply_edits(COMPACT_FIXTURE, [edit])

    parsed = json.loads(new_text)
    sessions = [s["session"] for s in parsed["feeds"][0]["marketSchedules"]]
    assert sessions == ["REGULAR", "PRE_MARKET", "OVER_NIGHT"]

    # Compact identifiers array (single line) is preserved in the new block.
    # The .O RIC is rewritten to .BLUE.
    assert '"identifiers": [ { "identifier": "ABNB.BLUE"' in new_text
    # minPublishers sentinel.
    assert '"minPublishers": 100' in new_text
    # Empty allowedPublisherIds.
    assert re.search(r'"allowedPublisherIds":\s*\[\s*\]', new_text)


def test_add_session_idempotent():
    """Adding a session that already exists returns None."""
    edit = plan_add_session(
        COMPACT_FIXTURE, feed_id=924, session="REGULAR", min_publishers=100
    )
    # REGULAR is already there → idempotent
    assert edit is None


def test_add_overnight_inserts_canonically_after_post_market():
    """If POST_MARKET exists, OVER_NIGHT slots after it (canonical order)."""
    fixture = COMPACT_FIXTURE.replace(
        '"session": "PRE_MARKET"', '"session": "POST_MARKET"'
    ).replace(
        '"marketSchedule": "America/New_York;0400-0930',
        '"marketSchedule": "America/New_York;1600-2000',
    )
    edit = plan_add_session(
        fixture, feed_id=924, session="OVER_NIGHT", min_publishers=100
    )
    assert edit is not None
    new_text = apply_edits(fixture, [edit])
    parsed = json.loads(new_text)
    sessions = [s["session"] for s in parsed["feeds"][0]["marketSchedules"]]
    assert sessions == ["REGULAR", "POST_MARKET", "OVER_NIGHT"]


def test_remove_last_session_in_array():
    """Removing PRE_MARKET (last) handles the comma correctly."""
    edit = plan_remove_session(COMPACT_FIXTURE, feed_id=924, session="PRE_MARKET")
    new_text = apply_edits(COMPACT_FIXTURE, [edit])
    # Trailing comma after REGULAR removed; array still valid.
    assert "PRE_MARKET" not in new_text
    json.loads(new_text)  # must parse


def test_apply_edits_is_right_to_left_safe():
    """Multiple edits don't trip over each other's offsets."""
    e1 = plan_remove_session(COMPACT_FIXTURE, feed_id=924, session="PRE_MARKET")
    # Independent edit on the same feed: change REGULAR's allowedPublisherIds
    # via a hand-rolled TextEdit to confirm right-to-left application.
    from session_editor_lib.text_apply import TextEdit

    idx = COMPACT_FIXTURE.index('"allowedPublisherIds": [ 1, 2, 3 ]')
    e2 = TextEdit(
        start=idx,
        end=idx + len('"allowedPublisherIds": [ 1, 2, 3 ]'),
        replacement='"allowedPublisherIds": [ 99 ]',
    )
    new_text = apply_edits(COMPACT_FIXTURE, [e1, e2])
    parsed = json.loads(new_text)
    feed = parsed["feeds"][0]
    assert feed["marketSchedules"][0]["allowedPublisherIds"] == [99]
    assert len(feed["marketSchedules"]) == 1


def test_add_overnight_rewrites_n_suffix_to_blue():
    """`.N` suffix (NYSE) also rewrites to .BLUE for OVER_NIGHT."""
    fixture = COMPACT_FIXTURE.replace("ABNB.O", "IBM.N")
    edit = plan_add_session(
        fixture, feed_id=924, session="OVER_NIGHT", min_publishers=100
    )
    new_text = apply_edits(fixture, [edit])
    # The new OVER_NIGHT block has IBM.BLUE; the original REGULAR keeps IBM.N.
    assert "IBM.BLUE" in new_text
    assert "IBM.N" in new_text
