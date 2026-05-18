"""Editor orchestrator: plan + simulate."""

from session_editor_lib.editor import PlanItem, simulate
from session_editor_lib.ops import AddSession, RemoveSession


def _session_set(feed):
    return tuple(s["session"] for s in feed["marketSchedules"])


def test_simulate_does_not_mutate_input(sample_feeds):
    before_aapl = next(f for f in sample_feeds if f["feedId"] == 922)
    before_sessions = _session_set(before_aapl)

    plan = [PlanItem(op=RemoveSession(session="OVER_NIGHT"), feed_ids={922})]
    simulate(plan, sample_feeds)

    after_aapl = next(f for f in sample_feeds if f["feedId"] == 922)
    assert _session_set(after_aapl) == before_sessions


def test_simulate_returns_modified_copy(sample_feeds):
    plan = [PlanItem(op=RemoveSession(session="OVER_NIGHT"), feed_ids={922})]
    result = simulate(plan, sample_feeds)
    aapl = next(f for f in result.after_feeds if f["feedId"] == 922)
    assert "OVER_NIGHT" not in _session_set(aapl)
    assert result.changed_count == 1


def test_pre_filter_excludes_non_us_equity(sample_feeds):
    # No feed-id targeting: should still skip BTC, INACTIVE included.
    plan = [PlanItem(op=AddSession(session="OVER_NIGHT"))]
    result = simulate(plan, sample_feeds)

    op_outcomes = result.outcomes[0]
    touched = {o.feed_id for o in op_outcomes}
    assert 1 not in touched  # BTC excluded

    btc = next(f for f in result.after_feeds if f["feedId"] == 1)
    assert _session_set(btc) == ("REGULAR",)


def test_force_flag_includes_non_us_equity(sample_feeds):
    plan = [
        PlanItem(
            op=AddSession(session="OVER_NIGHT", force=True),
            feed_ids={1},
            force_non_us=True,
        )
    ]
    result = simulate(plan, sample_feeds)
    btc = next(f for f in result.after_feeds if f["feedId"] == 1)
    assert "OVER_NIGHT" in _session_set(btc)


def test_symbol_pattern_filter(sample_feeds):
    plan = [
        PlanItem(
            op=RemoveSession(session="POST_MARKET"),
            symbol_pattern="Equity.US.AAPL/USD",
        )
    ]
    result = simulate(plan, sample_feeds)
    # Only AAPL should be hit.
    op_outcomes = result.outcomes[0]
    actions = [(o.feed_id, o.action) for o in op_outcomes]
    assert actions == [(922, "removed")]


def test_state_filter(sample_feeds):
    # INACTIVE feed (956) shouldn't be matched when filtering STABLE.
    plan = [
        PlanItem(
            op=AddSession(session="PRE_MARKET"),
            state="INACTIVE",
        )
    ]
    result = simulate(plan, sample_feeds)
    op_outcomes = result.outcomes[0]
    touched = {o.feed_id for o in op_outcomes}
    assert touched == {956}


def test_multi_op_plan_chains(sample_feeds):
    plan = [
        PlanItem(op=RemoveSession(session="POST_MARKET"), feed_ids={922}),
        PlanItem(op=AddSession(session="OVER_NIGHT"), feed_ids={924}),
    ]
    result = simulate(plan, sample_feeds)
    aapl = next(f for f in result.after_feeds if f["feedId"] == 922)
    abnb = next(f for f in result.after_feeds if f["feedId"] == 924)
    assert "POST_MARKET" not in _session_set(aapl)
    assert "OVER_NIGHT" in _session_set(abnb)
    assert result.changed_count == 2
