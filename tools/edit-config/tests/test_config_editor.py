import json
from pathlib import Path

import pytest

from lib.config_editor import FilterSet, resolve_targets


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "after_sample.json"


@pytest.fixture
def feeds():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["feeds"]


class TestFilterSet:
    def test_at_least_one_filter_required(self):
        with pytest.raises(ValueError, match="at least one"):
            FilterSet().validate()

    def test_feed_ids_alone_valid(self):
        FilterSet(feed_ids={1, 2}).validate()  # no raise

    def test_state_alone_valid(self):
        FilterSet(states={"STABLE"}).validate()


class TestResolveTargets:
    def test_by_feed_id(self, feeds):
        f = FilterSet(feed_ids={1})
        result = resolve_targets(f, feeds)
        assert [x["feedId"] for x in result] == [1]

    def test_by_feed_id_set(self, feeds):
        f = FilterSet(feed_ids={1, 100, 922})
        result = resolve_targets(f, feeds)
        assert sorted(x["feedId"] for x in result) == [1, 100, 922]

    def test_by_state_single(self, feeds):
        f = FilterSet(states={"INACTIVE"})
        result = resolve_targets(f, feeds)
        assert [x["feedId"] for x in result] == [6000]

    def test_by_state_list(self, feeds):
        f = FilterSet(states={"STABLE", "COMING_SOON"})
        result = resolve_targets(f, feeds)
        ids = sorted(x["feedId"] for x in result)
        assert ids == [1, 100, 922, 1023, 5000]

    def test_by_asset_class(self, feeds):
        f = FilterSet(asset_class="fx")
        result = resolve_targets(f, feeds)
        assert sorted(x["feedId"] for x in result) == [100, 6000]

    def test_by_symbol_pattern(self, feeds):
        f = FilterSet(symbol_pattern="Equity.US.*")
        result = resolve_targets(f, feeds)
        assert sorted(x["feedId"] for x in result) == [922, 1023]

    def test_and_combination(self, feeds):
        f = FilterSet(asset_class="equity", states={"STABLE"})
        result = resolve_targets(f, feeds)
        assert sorted(x["feedId"] for x in result) == [922, 1023]

    def test_empty_match_returns_empty(self, feeds):
        f = FilterSet(feed_ids={99999})
        assert resolve_targets(f, feeds) == []

    def test_feed_id_intersected_with_state(self, feeds):
        # feed 922 is STABLE; 5000 is COMING_SOON. Filter for both IDs but
        # only STABLE state -> should only get 922.
        f = FilterSet(feed_ids={922, 5000}, states={"STABLE"})
        result = resolve_targets(f, feeds)
        assert [x["feedId"] for x in result] == [922]


import argparse

from lib.config_editor import PlannedOp, build_op_from_args
from lib.config_ops import (
    AddPublisher,
    RemovePublisher,
    SetMinPublishers,
    BumpMinPublishers,
    SetState,
)


def make_args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        add_publisher=None,
        remove_publisher=None,
        set_min_publishers=None,
        bump_min_publishers=None,
        set_state=None,
        from_spec=None,
        feed_id=None,
        feed_ids_from=None,
        symbol_pattern=None,
        asset_class=None,
        state=None,
        session=None,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestBuildOpFromArgs:
    def test_add_publisher(self):
        args = make_args(add_publisher=80, feed_id="100-105", session="REGULAR")
        ops = build_op_from_args(args)
        assert len(ops) == 1
        op, filters = ops[0].op, ops[0].filters
        assert isinstance(op, AddPublisher)
        assert op.publisher_id == 80
        assert op.session == "REGULAR"
        assert filters.feed_ids == {100, 101, 102, 103, 104, 105}

    def test_remove_publisher_default_session(self):
        args = make_args(remove_publisher=22, feed_id="922")
        ops = build_op_from_args(args)
        assert isinstance(ops[0].op, RemovePublisher)
        assert ops[0].op.session is None

    def test_set_min_publishers(self):
        args = make_args(set_min_publishers=3, feed_id="922", session="REGULAR")
        ops = build_op_from_args(args)
        assert isinstance(ops[0].op, SetMinPublishers)
        assert ops[0].op.value == 3

    def test_bump_min_publishers_signed(self):
        args = make_args(bump_min_publishers="+1", feed_id="922")
        ops = build_op_from_args(args)
        assert isinstance(ops[0].op, BumpMinPublishers)
        assert ops[0].op.delta == 1

        args2 = make_args(bump_min_publishers="-2", feed_id="922")
        ops2 = build_op_from_args(args2)
        assert ops2[0].op.delta == -2

    def test_set_state(self):
        args = make_args(set_state="COMING_SOON", feed_id="500,501")
        ops = build_op_from_args(args)
        assert isinstance(ops[0].op, SetState)
        assert ops[0].op.value == "COMING_SOON"

    def test_no_op_flag_raises(self):
        args = make_args(feed_id="1")
        with pytest.raises(ValueError, match="no operation"):
            build_op_from_args(args)

    def test_multiple_op_flags_raises(self):
        args = make_args(add_publisher=1, remove_publisher=2, feed_id="1")
        with pytest.raises(ValueError, match="exactly one"):
            build_op_from_args(args)

    def test_no_targeting_raises(self):
        args = make_args(add_publisher=80)
        with pytest.raises(ValueError, match="at least one"):
            build_op_from_args(args)

    def test_state_filter_value(self):
        args = make_args(add_publisher=80, asset_class="equity", state="STABLE")
        ops = build_op_from_args(args)
        assert ops[0].filters.states == {"STABLE"}

    def test_feed_id_with_ranges(self):
        args = make_args(add_publisher=80, feed_id="100-200,205,208,3530-3540")
        ops = build_op_from_args(args)
        ids = ops[0].filters.feed_ids
        assert 100 in ids and 200 in ids and 205 in ids and 3540 in ids
        assert 201 not in ids and 209 not in ids

    def test_feed_ids_from_file(self, tmp_path):
        f = tmp_path / "ids.txt"
        f.write_text("1,2,3\n100-102", encoding="utf-8")
        args = make_args(add_publisher=80, feed_ids_from=str(f))
        ops = build_op_from_args(args)
        assert ops[0].filters.feed_ids == {1, 2, 3, 100, 101, 102}

    def test_feed_id_and_feed_ids_from_unioned(self, tmp_path):
        f = tmp_path / "ids.txt"
        f.write_text("100", encoding="utf-8")
        args = make_args(add_publisher=80, feed_id="1,2", feed_ids_from=str(f))
        ops = build_op_from_args(args)
        assert ops[0].filters.feed_ids == {1, 2, 100}


from lib.config_editor import parse_yaml_spec


YAML_BASIC = Path(__file__).parent / "fixtures" / "edits_basic.yaml"
YAML_INVALID = Path(__file__).parent / "fixtures" / "edits_invalid.yaml"


class TestParseYamlSpec:
    def test_parses_all_op_types(self):
        ops = parse_yaml_spec(str(YAML_BASIC))
        assert len(ops) == 6
        kinds = [type(p.op).__name__ for p in ops]
        assert kinds == [
            "AddPublisher",
            "RemovePublisher",
            "SetMinPublishers",
            "BumpMinPublishers",
            "SetState",
            "AddPublisher",
        ]

    def test_feed_id_range_string(self):
        ops = parse_yaml_spec(str(YAML_BASIC))
        # First op uses "100-105"
        assert ops[0].filters.feed_ids == {100, 101, 102, 103, 104, 105}

    def test_feed_id_mixed_list(self):
        ops = parse_yaml_spec(str(YAML_BASIC))
        # Last op uses [1, "100-101", 5000]
        assert ops[-1].filters.feed_ids == {1, 100, 101, 5000}

    def test_state_list_in_yaml(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "operations:\n"
            "  - op: add_publisher\n"
            "    publisher_id: 1\n"
            "    feed_id: 1\n"
            "    state: [STABLE, COMING_SOON]\n",
            encoding="utf-8",
        )
        ops = parse_yaml_spec(str(spec))
        assert ops[0].filters.states == {"STABLE", "COMING_SOON"}

    def test_unknown_key_rejected(self):
        with pytest.raises(ValueError, match="unknown key"):
            parse_yaml_spec(str(YAML_INVALID))

    def test_missing_op_field_rejected(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "operations:\n  - publisher_id: 1\n    feed_id: 1\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="missing.*op"):
            parse_yaml_spec(str(spec))

    def test_unknown_op_rejected(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "operations:\n  - op: drop_feed\n    feed_id: 1\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="unknown op"):
            parse_yaml_spec(str(spec))

    def test_version_above_1_fails(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "version: 2\noperations:\n"
            "  - op: add_publisher\n    publisher_id: 1\n    feed_id: 1\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="version"):
            parse_yaml_spec(str(spec))

    def test_no_operations_key_fails(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text("foo: bar\n", encoding="utf-8")
        with pytest.raises(ValueError, match="operations"):
            parse_yaml_spec(str(spec))
