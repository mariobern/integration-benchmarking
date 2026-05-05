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
