import json
from pathlib import Path

import pytest

from edit_config_lib.config_editor import FilterSet, resolve_targets


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

from edit_config_lib.config_editor import PlannedOp, build_op_from_args
from edit_config_lib.config_ops import (
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


from edit_config_lib.config_editor import parse_yaml_spec


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


from copy import deepcopy

from edit_config_lib.config_editor import (
    SimulationResult,
    simulate_plan,
)
from edit_config_lib.config_ops import AddPublisher, SetState


class TestSimulatePlan:
    def test_single_op_succeeds(self, feeds):
        plan = [
            PlannedOp(
                op=AddPublisher(publisher_id=80),
                filters=FilterSet(feed_ids={1}),
            )
        ]
        result = simulate_plan(plan, feeds)
        assert isinstance(result, SimulationResult)
        assert result.errors == []
        assert len(result.changes) == 1
        assert result.changes[0].after == [1, 3, 7, 11, 80]

    def test_zero_match_is_error(self, feeds):
        plan = [
            PlannedOp(
                op=AddPublisher(publisher_id=80),
                filters=FilterSet(feed_ids={99999}),
            )
        ]
        result = simulate_plan(plan, feeds)
        assert result.changes == []
        assert any(
            "zero" in e.lower() or "no feeds" in e.lower() for e in result.errors
        )

    def test_op_error_recorded(self, feeds):
        # Add to PRE_MARKET on a crypto feed -> OpError
        plan = [
            PlannedOp(
                op=AddPublisher(publisher_id=80, session="PRE_MARKET"),
                filters=FilterSet(feed_ids={1}),
            )
        ]
        result = simulate_plan(plan, feeds)
        assert any("PRE_MARKET" in e for e in result.errors)

    def test_inter_op_visibility(self, feeds):
        # Op 1: add publisher 80 to feed 1.
        # Op 2: add publisher 80 again -> should NOOP because op 1 already added it.
        plan = [
            PlannedOp(
                op=AddPublisher(publisher_id=80), filters=FilterSet(feed_ids={1})
            ),
            PlannedOp(
                op=AddPublisher(publisher_id=80), filters=FilterSet(feed_ids={1})
            ),
        ]
        result = simulate_plan(plan, feeds)
        assert len(result.changes) == 1  # only op 1 produced a change

    def test_does_not_mutate_input_feeds(self, feeds):
        original = deepcopy(feeds)
        plan = [
            PlannedOp(
                op=AddPublisher(publisher_id=80),
                filters=FilterSet(feed_ids={1}),
            )
        ]
        simulate_plan(plan, feeds)
        assert feeds == original  # no mutation of caller's data

    def test_warnings_collected(self, feeds):
        plan = [
            PlannedOp(
                op=SetState(value="INACTIVE"),
                filters=FilterSet(feed_ids={1}),
            )
        ]
        result = simulate_plan(plan, feeds)
        assert any("deactivat" in w.message.lower() for w in result.warnings)


from edit_config_lib.config_editor import apply_changes
from edit_config_lib.config_ops import Change


class TestApplyChanges:
    def setup_method(self):
        self.raw = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_publisher_top_level_change(self):
        change = Change(
            feed_id=1,
            symbol="Crypto.BTC/USD",
            location="top_level",
            field="allowedPublisherIds",
            before=[1, 3, 7, 11],
            after=[1, 3, 7, 11, 80],
        )
        new_raw = apply_changes(self.raw, [change])
        # Locate the feed 1 block in the result
        new_data = json.loads(new_raw)
        f = next(x for x in new_data["feeds"] if x["feedId"] == 1)
        assert f["allowedPublisherIds"] == [1, 3, 7, 11, 80]

    def test_publisher_session_change(self):
        change = Change(
            feed_id=922,
            symbol="Equity.US.AAPL/USD",
            location="PRE_MARKET",
            field="allowedPublisherIds",
            before=[19, 20, 22, 41, 42, 45, 55, 59, 65],
            after=[19, 20, 41, 42, 45, 55, 59, 65],
        )
        new_raw = apply_changes(self.raw, [change])
        new_data = json.loads(new_raw)
        f = next(x for x in new_data["feeds"] if x["feedId"] == 922)
        pre = next(s for s in f["marketSchedules"] if s["session"] == "PRE_MARKET")
        assert pre["allowedPublisherIds"] == [19, 20, 41, 42, 45, 55, 59, 65]

    def test_min_publishers_top_level(self):
        change = Change(
            feed_id=1,
            symbol="Crypto.BTC/USD",
            location="top_level",
            field="minPublishers",
            before=3,
            after=4,
        )
        new_raw = apply_changes(self.raw, [change])
        new_data = json.loads(new_raw)
        f = next(x for x in new_data["feeds"] if x["feedId"] == 1)
        assert f["minPublishers"] == 4

    def test_min_publishers_session(self):
        change = Change(
            feed_id=922,
            symbol="Equity.US.AAPL/USD",
            location="OVER_NIGHT",
            field="minPublishers",
            before=2,
            after=3,
        )
        new_raw = apply_changes(self.raw, [change])
        new_data = json.loads(new_raw)
        f = next(x for x in new_data["feeds"] if x["feedId"] == 922)
        on = next(s for s in f["marketSchedules"] if s["session"] == "OVER_NIGHT")
        assert on["minPublishers"] == 3

    def test_state_change(self):
        change = Change(
            feed_id=5000,
            symbol="Crypto.NEW/USD",
            location="top_level",
            field="state",
            before="COMING_SOON",
            after="STABLE",
        )
        new_raw = apply_changes(self.raw, [change])
        new_data = json.loads(new_raw)
        f = next(x for x in new_data["feeds"] if x["feedId"] == 5000)
        assert f["state"] == "STABLE"

    def test_multiple_changes_same_feed(self):
        changes = [
            Change(
                feed_id=922,
                symbol="X",
                location="top_level",
                field="allowedPublisherIds",
                before=[
                    11,
                    12,
                    13,
                    14,
                    19,
                    20,
                    21,
                    22,
                    26,
                    29,
                    32,
                    35,
                    41,
                    42,
                    45,
                    48,
                    54,
                    55,
                    57,
                    59,
                    64,
                    65,
                    69,
                    71,
                    72,
                    73,
                ],
                after=[
                    11,
                    12,
                    13,
                    14,
                    19,
                    20,
                    21,
                    22,
                    26,
                    29,
                    32,
                    35,
                    41,
                    42,
                    45,
                    48,
                    54,
                    55,
                    57,
                    59,
                    64,
                    65,
                    69,
                    71,
                    72,
                    73,
                    80,
                ],
            ),
            Change(
                feed_id=922,
                symbol="X",
                location="REGULAR",
                field="minPublishers",
                before=3,
                after=4,
            ),
        ]
        new_raw = apply_changes(self.raw, changes)
        new_data = json.loads(new_raw)
        f = next(x for x in new_data["feeds"] if x["feedId"] == 922)
        assert 80 in f["allowedPublisherIds"]
        regular = next(s for s in f["marketSchedules"] if s["session"] == "REGULAR")
        assert regular["minPublishers"] == 4

    def test_multiple_changes_different_feeds(self):
        changes = [
            Change(
                feed_id=1,
                symbol="X",
                location="top_level",
                field="minPublishers",
                before=3,
                after=2,
            ),
            Change(
                feed_id=100,
                symbol="Y",
                location="top_level",
                field="minPublishers",
                before=3,
                after=4,
            ),
        ]
        new_raw = apply_changes(self.raw, changes)
        new_data = json.loads(new_raw)
        f1 = next(x for x in new_data["feeds"] if x["feedId"] == 1)
        f100 = next(x for x in new_data["feeds"] if x["feedId"] == 100)
        assert f1["minPublishers"] == 2
        assert f100["minPublishers"] == 4

    def test_empty_changes_is_identity(self):
        assert apply_changes(self.raw, []) == self.raw


import shutil

from edit_config_lib.config_editor import write_with_backup, run_linter


class TestWriteWithBackup:
    def test_writes_backup_and_new_content(self, tmp_path):
        target = tmp_path / "after.json"
        target.write_text("ORIGINAL", encoding="utf-8")
        write_with_backup(str(target), "MODIFIED")
        assert target.read_text() == "MODIFIED"
        assert (tmp_path / "after.json.bak").read_text() == "ORIGINAL"

    def test_skip_backup_flag(self, tmp_path):
        target = tmp_path / "after.json"
        target.write_text("ORIGINAL", encoding="utf-8")
        write_with_backup(str(target), "MODIFIED", no_backup=True)
        assert target.read_text() == "MODIFIED"
        assert not (tmp_path / "after.json.bak").exists()

    def test_overwrites_prior_backup(self, tmp_path):
        target = tmp_path / "after.json"
        target.write_text("ORIGINAL", encoding="utf-8")
        (tmp_path / "after.json.bak").write_text("STALE_BACKUP", encoding="utf-8")
        write_with_backup(str(target), "MODIFIED")
        assert (tmp_path / "after.json.bak").read_text() == "ORIGINAL"


class TestRunLinter:
    def test_runs_existing_linter_on_fixture(self, tmp_path):
        # Copy the fixture so we don't run on the real after.json
        src = FIXTURE_PATH
        dst = tmp_path / "after.json"
        shutil.copy(src, dst)
        rc, output = run_linter(str(dst))
        assert isinstance(rc, int)
        assert isinstance(output, str)

    def test_handles_missing_linter_gracefully(self, monkeypatch, tmp_path):
        # Point at a non-existent linter path; expect a non-zero rc and
        # a clear "not found" message rather than a crash.
        from edit_config_lib import config_editor

        monkeypatch.setattr(config_editor, "_LINTER_PATH", "/does/not/exist.py")
        target = tmp_path / "after.json"
        shutil.copy(FIXTURE_PATH, target)
        rc, output = run_linter(str(target))
        assert rc != 0
        assert "linter" in output.lower() or "not found" in output.lower()
