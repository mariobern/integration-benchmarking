"""YAML batch-spec parser."""

import pytest

from session_editor_lib.ops import AddSession, RemoveSession
from session_editor_lib.spec import parse_spec


def test_parses_add_and_remove(tmp_path):
    spec = tmp_path / "s.yaml"
    spec.write_text(
        """
version: 1
operations:
  - op: add_session
    session: OVER_NIGHT
    feed_id: 924
    min_publishers: 100
  - op: remove_session
    session: [PRE_MARKET, POST_MARKET]
    feed_id: "1000-1003,2000"
        """,
        encoding="utf-8",
    )
    plan = parse_spec(spec)
    # add → 1 item, remove with 2 sessions → 2 items: total 3
    assert len(plan) == 3
    assert isinstance(plan[0].op, AddSession)
    assert plan[0].op.session == "OVER_NIGHT"
    assert plan[0].op.min_publishers == 100
    assert plan[0].feed_ids == {924}

    assert isinstance(plan[1].op, RemoveSession)
    assert plan[1].op.session == "PRE_MARKET"
    assert plan[1].feed_ids == {1000, 1001, 1002, 1003, 2000}
    assert isinstance(plan[2].op, RemoveSession)
    assert plan[2].op.session == "POST_MARKET"


def test_rejects_unknown_op(tmp_path):
    spec = tmp_path / "s.yaml"
    spec.write_text(
        "version: 1\noperations:\n  - op: zap_session\n    session: REGULAR\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown op"):
        parse_spec(spec)


def test_rejects_unknown_keys(tmp_path):
    spec = tmp_path / "s.yaml"
    spec.write_text(
        """
version: 1
operations:
  - op: add_session
    session: OVER_NIGHT
    bogus_key: hi
        """,
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown keys"):
        parse_spec(spec)


def test_rejects_bad_version(tmp_path):
    spec = tmp_path / "s.yaml"
    spec.write_text("version: 99\noperations: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported spec version"):
        parse_spec(spec)


def test_feed_id_int_list(tmp_path):
    spec = tmp_path / "s.yaml"
    spec.write_text(
        """
version: 1
operations:
  - op: remove_session
    session: OVER_NIGHT
    feed_id: [922, "1000-1002", 2000]
        """,
        encoding="utf-8",
    )
    plan = parse_spec(spec)
    assert plan[0].feed_ids == {922, 1000, 1001, 1002, 2000}


def test_missing_session_raises(tmp_path):
    spec = tmp_path / "s.yaml"
    spec.write_text(
        "version: 1\noperations:\n  - op: add_session\n    feed_id: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="`session` is required"):
        parse_spec(spec)
