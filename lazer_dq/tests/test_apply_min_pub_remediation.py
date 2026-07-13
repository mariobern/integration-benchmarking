import json

import pandas as pd

from lazer_dq.apply_min_pub_remediation import (
    _parse_linter_error_count,
    build_spec,
    verify_static,
)


def _selected_df():
    return pd.DataFrame(
        [
            {
                "feed_id": 10,
                "symbol": "Equity.US.A/USD",
                "session": "REGULAR",
                "candidate_publisher_id": 7,
                "selected": True,
                "selection_rank": 1,
                "quality_path": "engine",
            },
            {
                "feed_id": 11,
                "symbol": "Crypto.B/USD",
                "session": "REGULAR",
                "candidate_publisher_id": 7,
                "selected": True,
                "selection_rank": 1,
                "quality_path": "peer",
            },
            {
                "feed_id": 10,
                "symbol": "Equity.US.A/USD",
                "session": "PRE_MARKET",
                "candidate_publisher_id": 8,
                "selected": True,
                "selection_rank": 1,
                "quality_path": "engine",
            },
            {
                "feed_id": 12,
                "symbol": "Crypto.C/USD",
                "session": "REGULAR",
                "candidate_publisher_id": 9,
                "selected": False,
                "selection_rank": "",
                "quality_path": "peer",
            },
        ]
    )


def test_build_spec_groups_by_publisher_and_session():
    spec = build_spec(_selected_df())
    assert spec["version"] == 1
    ops = spec["operations"]
    # publisher 7 REGULAR on feeds 10,11 -> one op; publisher 8 PRE_MARKET -> one op
    assert {"op": "add_publisher", "publisher_id": 7, "feed_id": "10,11"} in ops
    assert {
        "op": "add_publisher",
        "publisher_id": 8,
        "feed_id": "10",
        "session": "PRE_MARKET",
    } in ops
    assert len(ops) == 2  # non-selected publisher 9 excluded


def _mini_config(regular_allowed):
    return {
        "exchanges": [],
        "feeds": [
            {
                "feedId": 10,
                "symbol": "Equity.US.A/USD",
                "state": "STABLE",
                "minPublishers": 2,
                "metadata": {"asset_type": "equity"},
                "marketSchedules": [
                    {
                        "session": "REGULAR",
                        "allowedPublisherIds": regular_allowed,
                        "marketSchedule": "UTC;O,O,O,O,O,O,O;",
                    }
                ],
            }
        ],
    }


def test_verify_static_pass_and_fail():
    selected = pd.DataFrame(
        [
            {
                "feed_id": 10,
                "symbol": "Equity.US.A/USD",
                "session": "REGULAR",
                "candidate_publisher_id": 7,
                "selected": True,
                "selection_rank": 1,
                "quality_path": "peer",
            }
        ]
    )
    summary = pd.DataFrame(
        [{"feed_id": 10, "session": "REGULAR", "target": 4, "met_target": True}]
    )
    # applied config: pubs 1,2,3 + added 7 -> allowed_count 4 >= target 4, 7 present
    ok = verify_static(_mini_config([1, 2, 3, 7]), selected, summary)
    assert all(r["status"] == "PASS" for r in ok)
    # broken config: 7 missing
    bad = verify_static(_mini_config([1, 2, 3]), selected, summary)
    assert any(r["check"] == "selected_applied" and r["status"] == "FAIL" for r in bad)
    # duplicate publisher entry -> static FAIL
    dup = verify_static(_mini_config([1, 2, 3, 7, 7]), selected, summary)
    assert any(r["check"] == "static_margin" and r["status"] == "FAIL" for r in dup)


def test_parse_linter_error_count_json_format():
    """JSON with 5070 errors + 2773 warnings, rc=1."""
    json_output = """{
  "findings": [
    {
      "rule_id": "E005",
      "severity": "ERROR",
      "message": "STABLE feed with no publishers"
    },
    {
      "rule_id": "W001",
      "severity": "WARNING",
      "message": "some warning"
    }
  ]
}"""
    # Create 5070 error entries + 2773 warning entries.
    errors = [{"severity": "ERROR", "rule_id": f"E{i}"} for i in range(5070)]
    warnings = [{"severity": "WARNING", "rule_id": f"W{i}"} for i in range(2773)]
    findings = errors + warnings
    full_json = json.dumps({"findings": findings})

    result = _parse_linter_error_count(full_json, 1)
    assert result == 5070, f"Expected 5070, got {result}"


def test_parse_linter_error_count_summary_line():
    """Text output with 'Summary: 5070 errors, 2773 warnings' + rc=1."""
    text = """NOTE: baseline unavailable
ERRORS (5070 found):
  E005: STABLE feed with no publishers
  E008: publisherIds not in list
...
Summary: 5070 errors, 2773 warnings
"""
    result = _parse_linter_error_count(text, 1)
    assert result == 5070, f"Expected 5070, got {result}"


def test_parse_linter_error_count_zero_errors():
    """Text output 'Summary: 0 errors, 3 warnings', rc=0."""
    text = """WARNINGS (3 found):
Summary: 0 errors, 3 warnings
"""
    result = _parse_linter_error_count(text, 0)
    assert result == 0, f"Expected 0, got {result}"


def test_parse_linter_error_count_no_summary_nonzero_rc():
    """No Summary line, rc=2 -> None (linter failed)."""
    text = "Some error output without summary"
    result = _parse_linter_error_count(text, 2)
    assert result is None, f"Expected None, got {result}"


def test_parse_linter_error_count_no_summary_zero_rc():
    """No Summary line, rc=0 -> 0 (linter succeeded, no errors found)."""
    text = "Linter ran successfully with no output"
    result = _parse_linter_error_count(text, 0)
    assert result == 0, f"Expected 0, got {result}"
