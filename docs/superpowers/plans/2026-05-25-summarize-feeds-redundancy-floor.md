# summarize_feeds Redundancy Floor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "0 passed → fallback to top-3" branch in `summarize_feeds.py` with a redundancy floor of N (default 5): take all quality passers, then top up with the next-best near-misses bounded by an `n_observations` floor and a `2×` `rmse_over_spread` ceiling.

**Architecture:** Single-file change in `lazer_dq/summarize_feeds.py`. The selection function `apply_filter` changes from returning `(passers, is_fallback)` to `(selected, n_passed, n_topup)`. Those two counts flow through `_build_per_feed_data` into the `allowed` sheet's Notes column. The CLI flag `--fallback-top` is retired in favor of `--redundancy-floor` and `--topup-ceiling-mult`. The `rankings` sheet, exclusion logic, and asset-class registry are unchanged.

**Tech Stack:** Python 3, `openpyxl`, `pytest`. Run tests with `python3 -m pytest`. The system has no `python`; always use `python3`.

**Spec:** `docs/superpowers/specs/2026-05-25-summarize-feeds-redundancy-floor-design.md`

---

## File Structure

- **Modify:** `lazer_dq/summarize_feeds.py`
  - Constants block (~L73–75): add `DEFAULT_REDUNDANCY_FLOOR`, `DEFAULT_TOPUP_CEILING_MULT`; remove `DEFAULT_FALLBACK_TOP`.
  - New helpers near `_format_allowed_pub_ids` (~L360): `_format_mult`, `_topup_note`.
  - `apply_filter` (~L200–232): new signature + redundancy-floor logic.
  - `_build_per_feed_data` (~L491–551): new params, new per-mode dict keys, new return tuple.
  - `write_allowed_sheet` (~L369–488): new `ceiling_mult` param, Notes/fill driven by `n_passed`/`n_topup`.
  - `main` (~L647–755): swap CLI flags, update call sites and summary prints.
- **Modify:** `lazer_dq/tests/test_summarize_feeds.py`
  - Rewrite the `apply_filter` unit-test section (~L214–290).
  - Update `_build_per_feed_data` test (~L693–711) and three `mode_data` fixtures carrying `"is_fallback"` (~L739, L777, L818).
  - Add `_format_mult` / `_topup_note` tests and `write_allowed_sheet` Notes tests.
- **Modify:** `docs/summarize_feeds.md` (L39, L62, L108–111): replace `--fallback-top` docs with the floor/ceiling model.
- **Do NOT touch:** historical records under `docs/plans/`, `docs/specs/`, and other `docs/superpowers/plans/` files — they document past work and must not be edited.

---

### Task 1: Additive helpers and constants (safe, suite stays green)

This task only **adds** code. It removes nothing, so the full suite stays green and we get an early commit. The `apply_filter` signature change and `DEFAULT_FALLBACK_TOP` removal come in Task 2.

**Files:**

- Modify: `lazer_dq/summarize_feeds.py`
- Test: `lazer_dq/tests/test_summarize_feeds.py`

- [ ] **Step 1: Write failing tests for the new helpers**

Add this block to `lazer_dq/tests/test_summarize_feeds.py` immediately after the existing `apply_filter` import line (`from lazer_dq.summarize_feeds import apply_filter`, ~L208):

```python
from lazer_dq.summarize_feeds import _format_mult, _topup_note


# ---------- _format_mult / _topup_note ----------


def test_format_mult_drops_trailing_zero():
    assert _format_mult(2.0) == "2"
    assert _format_mult(1.5) == "1.5"
    assert _format_mult(3.0) == "3"


def test_topup_note_renders_counts_and_multiplier():
    assert _topup_note(2, 3, 2.0) == "2 passed + 3 top-up (≤2×)"
    assert _topup_note(0, 5, 2.0) == "0 passed + 5 top-up (≤2×)"
    assert _topup_note(1, 4, 1.5) == "1 passed + 4 top-up (≤1.5×)"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py -k "format_mult or topup_note" -v`
Expected: FAIL — `ImportError: cannot import name '_format_mult'`.

- [ ] **Step 3: Add the constants**

In `lazer_dq/summarize_feeds.py`, replace the constants block:

```python
DEFAULT_MIN_N_OBS = 1000
DEFAULT_TOP_N = 10
DEFAULT_FALLBACK_TOP = 3
```

with (keep `DEFAULT_FALLBACK_TOP` for now — Task 2 removes it once its last reference is gone):

```python
DEFAULT_MIN_N_OBS = 1000
DEFAULT_TOP_N = 10
DEFAULT_FALLBACK_TOP = 3
DEFAULT_REDUNDANCY_FLOOR = 5
DEFAULT_TOPUP_CEILING_MULT = 2.0
```

- [ ] **Step 4: Add the helper functions**

In `lazer_dq/summarize_feeds.py`, immediately **above** the existing `_format_allowed_pub_ids` definition (~L360), add:

```python
def _format_mult(ceiling_mult: float) -> str:
    """Render the ceiling multiplier without a trailing .0 (2.0 -> '2', 1.5 -> '1.5')."""
    return f"{ceiling_mult:g}"


def _topup_note(n_passed: int, n_topup: int, ceiling_mult: float) -> str:
    """Notes-column text for a row that needed below-threshold top-ups."""
    return f"{n_passed} passed + {n_topup} top-up (≤{_format_mult(ceiling_mult)}×)"
```

(`≤` is `≤`, `×` is `×` — written as escapes here only to be unambiguous; type the literal characters.)

- [ ] **Step 5: Run the helper tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py -k "format_mult or topup_note" -v`
Expected: PASS (5 assertions across 2 tests).

- [ ] **Step 6: Run the full suite to confirm nothing broke**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py -v`
Expected: PASS (all existing tests + the 2 new ones).

- [ ] **Step 7: Commit**

```bash
git add lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git commit -m "feat(lazer_dq): add redundancy-floor constants and Notes helpers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Redundancy-floor selection (coupled refactor)

`apply_filter`, `_build_per_feed_data`, `write_allowed_sheet`, and `main` share the per-mode data shape, so they change together. The suite is **red mid-task** and only returns green after Step 9. Commit once, at the end.

**Files:**

- Modify: `lazer_dq/summarize_feeds.py`
- Test: `lazer_dq/tests/test_summarize_feeds.py`

- [ ] **Step 1: Replace the `apply_filter` unit-test section (red)**

In `lazer_dq/tests/test_summarize_feeds.py`, delete the entire existing `apply_filter` test section — from the comment `# ---------- apply_filter ----------` (~L211) down to the end of `test_apply_filter_uses_per_mode_thresholds` (~L290) — and replace it with:

```python
# ---------- apply_filter ----------


def test_apply_filter_returns_all_passers_when_at_or_above_floor():
    # 6 publishers all pass; floor is a minimum, never a cap -> return all 6.
    stats = [
        _stat(11, 0.5),
        _stat(20, 0.3),
        _stat(35, 0.4),
        _stat(42, 0.2),
        _stat(50, 0.6),
        _stat(60, 0.1),
    ]
    selected, n_passed, n_topup = apply_filter(
        stats, max_ros=1.0, min_hit=80, min_obs=1000, floor=5, ceiling_mult=2.0
    )
    assert n_passed == 6
    assert n_topup == 0
    # All returned, sorted ascending by rmse_over_spread.
    assert [r["publisher_id"] for r in selected] == ["60", "42", "20", "35", "11", "50"]


def test_apply_filter_tops_up_to_floor_with_near_misses():
    stats = [
        _stat(11, 0.5),  # passer
        _stat(20, 0.3),  # passer
        _stat(35, 1.4),  # near-miss (r/s > 1.0 but <= 2.0 ceiling)
        _stat(42, 1.8),  # near-miss
        _stat(50, 1.2),  # near-miss
        _stat(60, 1.9),  # near-miss (6th best, not needed once floor reached)
    ]
    selected, n_passed, n_topup = apply_filter(
        stats, max_ros=1.0, min_hit=80, min_obs=1000, floor=5, ceiling_mult=2.0
    )
    assert n_passed == 2
    assert n_topup == 3
    ids = {r["publisher_id"] for r in selected}
    # passers 11, 20 + 3 best near-misses by r/s: 50 (1.2), 35 (1.4), 42 (1.8).
    assert ids == {"11", "20", "50", "35", "42"}
    assert "60" not in ids


def test_apply_filter_ceiling_excludes_bad_topups_even_below_floor():
    stats = [
        _stat(11, 0.5),  # passer
        _stat(20, 1.5),  # near-miss within 2.0 ceiling
        _stat(35, 2.5),  # over ceiling -> never promoted
        _stat(42, 3.0),  # over ceiling -> never promoted
    ]
    selected, n_passed, n_topup = apply_filter(
        stats, max_ros=1.0, min_hit=80, min_obs=1000, floor=5, ceiling_mult=2.0
    )
    assert n_passed == 1
    assert n_topup == 1
    # Stays below the floor of 5; 35 and 42 are never promoted.
    assert {r["publisher_id"] for r in selected} == {"11", "20"}


def test_apply_filter_topups_must_meet_n_obs_floor():
    stats = [
        _stat(11, 0.5, n_obs=10000),  # passer
        _stat(20, 1.5, n_obs=500),  # within ceiling but too few observations
        _stat(35, 1.6, n_obs=10000),  # eligible near-miss
    ]
    selected, n_passed, n_topup = apply_filter(
        stats, max_ros=1.0, min_hit=80, min_obs=1000, floor=5, ceiling_mult=2.0
    )
    assert n_passed == 1
    assert n_topup == 1
    assert {r["publisher_id"] for r in selected} == {"11", "35"}


def test_apply_filter_hit_rate_does_not_gate_topups():
    # All fail hit-rate (10 < 80) -> 0 passers. 11 passes r/s but fails hit,
    # so it is a non-passer that is still eligible as a top-up.
    stats = [
        _stat(11, 0.5, hit=10),
        _stat(20, 1.1, hit=10),
        _stat(35, 1.5, hit=10),
        _stat(42, 1.9, hit=10),
        _stat(50, 1.3, hit=10),
        _stat(60, 1.4, hit=10),
    ]
    selected, n_passed, n_topup = apply_filter(
        stats, max_ros=1.0, min_hit=80, min_obs=1000, floor=5, ceiling_mult=2.0
    )
    assert n_passed == 0
    assert n_topup == 5
    # Best 5 by r/s: 11 (0.5), 20 (1.1), 50 (1.3), 60 (1.4), 35 (1.5); 42 (1.9) excluded.
    assert {r["publisher_id"] for r in selected} == {"11", "20", "50", "60", "35"}
    assert "42" not in {r["publisher_id"] for r in selected}


def test_apply_filter_empty_when_all_over_ceiling():
    stats = [
        _stat(11, 2.5, hit=10),
        _stat(20, 3.0, hit=10),
        _stat(35, 5.0, hit=10),
    ]
    selected, n_passed, n_topup = apply_filter(
        stats, max_ros=1.0, min_hit=80, min_obs=1000, floor=5, ceiling_mult=2.0
    )
    assert selected == []
    assert n_passed == 0
    assert n_topup == 0


def test_apply_filter_returns_empty_for_empty_input():
    selected, n_passed, n_topup = apply_filter(
        [], max_ros=1.0, min_hit=80, min_obs=1000, floor=5, ceiling_mult=2.0
    )
    assert selected == []
    assert n_passed == 0
    assert n_topup == 0
```

- [ ] **Step 2: Run the new `apply_filter` tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py -k apply_filter -v`
Expected: FAIL — the current `apply_filter` returns a 2-tuple and takes `fallback_n`, so unpacking into three names / passing `floor=` raises `TypeError`.

- [ ] **Step 3: Rewrite `apply_filter`**

In `lazer_dq/summarize_feeds.py`, replace the entire current `apply_filter` function (from `def apply_filter(stats, max_ros: float, min_hit: float, min_obs: int, fallback_n: int):` through its `return [r for _, r in parseable[:fallback_n]], True`) with:

```python
def apply_filter(stats, max_ros: float, min_hit: float, min_obs: int, floor: int, ceiling_mult: float):
    """Apply per-mode thresholds with a redundancy floor. Return (selected, n_passed, n_topup).

    selected : passers (sorted ascending by rmse_over_spread) plus, when there
               are fewer than `floor` passers, the next-best below-threshold
               publishers ("top-ups") sorted by rmse_over_spread. Each top-up
               must clear the n_observations floor AND have
               rmse_over_spread <= ceiling_mult * max_ros. The floor is a
               minimum, never a cap: if more than `floor` publishers pass, all
               of them are returned.
    n_passed : count meeting all three thresholds (r/s, hit_rate, n_obs).
    n_topup  : count of below-threshold fillers added to reach the floor.

    Empty input -> ([], 0, 0). Rows with non-numeric metric fields are skipped.
    Note: hit_rate gates passers only, not top-ups; the ceiling is the top-up
    quality proxy.
    """
    if not stats:
        return [], 0, 0

    passers: list[tuple[float, dict]] = []
    non_passers: list[tuple[float, dict, int]] = []
    for r in stats:
        try:
            ros = float(r["rmse_over_spread"])
            hit = float(r["hit_rate_0.1pct"])
            n_obs = int(r["n_observations"])
        except (ValueError, KeyError):
            continue
        if ros <= max_ros and hit >= min_hit and n_obs >= min_obs:
            passers.append((ros, r))
        else:
            non_passers.append((ros, r, n_obs))

    passers.sort(key=lambda x: x[0])
    n_passed = len(passers)
    if n_passed >= floor:
        return [r for _, r in passers], n_passed, 0

    # Top up with below-threshold publishers within the quality ceiling.
    ceiling = ceiling_mult * max_ros
    eligible = [
        (ros, r) for (ros, r, n_obs) in non_passers if n_obs >= min_obs and ros <= ceiling
    ]
    eligible.sort(key=lambda x: x[0])
    topups = eligible[: floor - n_passed]
    selected = [r for _, r in passers] + [r for _, r in topups]
    return selected, n_passed, len(topups)
```

- [ ] **Step 4: Run the `apply_filter` tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py -k apply_filter -v`
Expected: PASS (7 tests). The rest of the suite is still red — that is expected until Step 9.

- [ ] **Step 5: Update `_build_per_feed_data`**

In `lazer_dq/summarize_feeds.py`, replace the function signature line:

```python
    fallback_top,
    modes,
):
```

with:

```python
    floor,
    ceiling_mult,
    modes,
):
```

Replace the four counter initializers / docstring tail. Change the docstring's return line and the init block:

```python
    per_feed_data: dict = {}
    skipped: list[int] = []
    fallback_count = 0
    modes_with_data = 0
```

becomes:

```python
    per_feed_data: dict = {}
    skipped: list[int] = []
    topup_rows = 0
    zero_passer_rows = 0
    modes_with_data = 0
```

Replace the per-mode block that calls `apply_filter` and records results:

```python
            ranked = rank_top_n(kept, n=top_n, excluded=set())  # already excluded
            filtered, is_fallback = apply_filter(
                kept, max_ros_map[mode], min_hit_map[mode], min_obs, fallback_top
            )
            mode_data[mode] = {
                "ranked": ranked,
                "filtered": filtered,
                "is_fallback": is_fallback,
            }
            any_data = True
            modes_with_data += 1
            if is_fallback:
                fallback_count += 1
```

with:

```python
            ranked = rank_top_n(kept, n=top_n, excluded=set())  # already excluded
            selected, n_passed, n_topup = apply_filter(
                kept, max_ros_map[mode], min_hit_map[mode], min_obs, floor, ceiling_mult
            )
            mode_data[mode] = {
                "ranked": ranked,
                "filtered": selected,
                "n_passed": n_passed,
                "n_topup": n_topup,
            }
            any_data = True
            modes_with_data += 1
            if n_topup > 0:
                topup_rows += 1
            if n_passed == 0:
                zero_passer_rows += 1
```

Replace the return statement:

```python
    return per_feed_data, skipped, fallback_count, modes_with_data
```

with:

```python
    return per_feed_data, skipped, topup_rows, zero_passer_rows, modes_with_data
```

Also update the docstring's first line (currently `"""Returns (per_feed_data, skipped_feeds, fallback_count, modes_with_data_count)."""`) to:

```python
    """Returns (per_feed_data, skipped_feeds, topup_rows, zero_passer_rows, modes_with_data_count).
```

- [ ] **Step 6: Update `write_allowed_sheet`**

In `lazer_dq/summarize_feeds.py`, change the signature:

```python
def write_allowed_sheet(
    ws,
    per_feed_data: dict,
    skipped_feeds: list,
    date: str,
    cluster: str,
    modes: list,
    sessions: dict,
):
```

to add `ceiling_mult` (default keeps non-test callers working):

```python
def write_allowed_sheet(
    ws,
    per_feed_data: dict,
    skipped_feeds: list,
    date: str,
    cluster: str,
    modes: list,
    sessions: dict,
    ceiling_mult: float = DEFAULT_TOPUP_CEILING_MULT,
):
```

In the docstring, change the line:

```python
           row: <feed_id> | REGULAR      | JSON or "(no data)"              | optional FALLBACK note
```

to:

```python
           row: <feed_id> | REGULAR      | JSON or "(no data)"              | optional "N passed + M top-up" note
```

Replace the per-session render block:

```python
            if md is None:
                ws.cell(row=row, column=3, value="(no data)")
                ws.cell(
                    row=row, column=4, value=f"mode missing for {date}"
                ).fill = light_gray
            elif ids is None:
                # Filter returned empty *after* parsing rows — rare, treat as no data.
                ws.cell(row=row, column=3, value="(no data)")
                ws.cell(
                    row=row, column=4, value="filter empty after parse"
                ).fill = light_gray
            else:
                ws.cell(row=row, column=3, value=_format_allowed_pub_ids(ids))
                if md["is_fallback"]:
                    ws.cell(
                        row=row, column=4, value="FALLBACK: 0 passed filter"
                    ).fill = yellow
            row += 1
```

with:

```python
            if md is None:
                ws.cell(row=row, column=3, value="(no data)")
                ws.cell(
                    row=row, column=4, value=f"mode missing for {date}"
                ).fill = light_gray
            elif ids is None:
                # Had data, but nothing passed and no publisher sat within the ceiling.
                ws.cell(row=row, column=3, value="(no data)")
                ws.cell(
                    row=row,
                    column=4,
                    value=f"0 passed, all > {_format_mult(ceiling_mult)}× ceiling",
                ).fill = light_gray
            else:
                ws.cell(row=row, column=3, value=_format_allowed_pub_ids(ids))
                if md["n_topup"] > 0:
                    ws.cell(
                        row=row,
                        column=4,
                        value=_topup_note(md["n_passed"], md["n_topup"], ceiling_mult),
                    ).fill = yellow
            row += 1
```

(`×` is `×` — type the literal character.)

- [ ] **Step 7: Update `main` (CLI flags, call sites, summary prints)**

In `lazer_dq/summarize_feeds.py`, replace the argparse line:

```python
    parser.add_argument("--fallback-top", type=int, default=DEFAULT_FALLBACK_TOP)
```

with:

```python
    parser.add_argument(
        "--redundancy-floor",
        type=int,
        default=DEFAULT_REDUNDANCY_FLOOR,
        help="Minimum publishers per feed/session; top up below-threshold "
        "near-misses to reach it (default: 5).",
    )
    parser.add_argument(
        "--topup-ceiling-mult",
        type=float,
        default=DEFAULT_TOPUP_CEILING_MULT,
        help="A top-up's rmse_over_spread must be <= this multiple of the "
        "per-mode pass threshold (default: 2.0).",
    )
```

Now remove the `DEFAULT_FALLBACK_TOP = 3` constant line added context from Task 1 (it has no remaining references). The constants block becomes:

```python
DEFAULT_MIN_N_OBS = 1000
DEFAULT_TOP_N = 10
DEFAULT_REDUNDANCY_FLOOR = 5
DEFAULT_TOPUP_CEILING_MULT = 2.0
```

Replace the `_build_per_feed_data` call:

```python
    per_feed_data, skipped, fb_count, modes_with_data = _build_per_feed_data(
        feed_ids,
        reports_dir,
        args.cluster,
        args.date,
        excluded,
        args.top_n,
        max_ros_map,
        min_hit_map,
        args.min_n_observations,
        args.fallback_top,
        modes=modes,
    )
```

with:

```python
    per_feed_data, skipped, topup_rows, zero_passer_rows, modes_with_data = (
        _build_per_feed_data(
            feed_ids,
            reports_dir,
            args.cluster,
            args.date,
            excluded,
            args.top_n,
            max_ros_map,
            min_hit_map,
            args.min_n_observations,
            args.redundancy_floor,
            args.topup_ceiling_mult,
            modes=modes,
        )
    )
```

Replace the `write_allowed_sheet` call:

```python
    write_allowed_sheet(
        ws_allow,
        per_feed_data,
        skipped,
        args.date,
        args.cluster,
        modes=modes,
        sessions=sessions,
    )
```

with:

```python
    write_allowed_sheet(
        ws_allow,
        per_feed_data,
        skipped,
        args.date,
        args.cluster,
        modes=modes,
        sessions=sessions,
        ceiling_mult=args.topup_ceiling_mult,
    )
```

Replace the final summary print line:

```python
    print(f"Fallbacks triggered: {fb_count} cells")
```

with:

```python
    print(f"Rows using top-ups: {topup_rows} cells")
    print(f"Rows with 0 passers: {zero_passer_rows} cells")
```

- [ ] **Step 8: Update the dependent tests and fixtures**

In `lazer_dq/tests/test_summarize_feeds.py`:

(a) Replace the `_build_per_feed_data` test body. Find `test_build_per_feed_data_honors_modes_parameter` (~L680) and replace its `_build_per_feed_data(...)` call and the assertions that follow with:

```python
    per_feed, skipped, topup_rows, zero_passer_rows, modes_with_data = (
        _build_per_feed_data(
            feed_ids=[884],
            reports_dir=reports,
            cluster="lazer-prod",
            date="2026-05-19",
            excluded={0},
            top_n=10,
            max_ros_map={"hk-equities": 1.0},
            min_hit_map={"hk-equities": 80.0},
            min_obs=1000,
            floor=5,
            ceiling_mult=2.0,
            modes=["hk-equities"],
        )
    )
    assert skipped == []
    assert modes_with_data == 1
    assert per_feed[884]["hk-equities"] is not None
    assert per_feed[884]["hk-equities"]["ranked"][0]["publisher_id"] == "5"
    # Publisher 5 (r/s 0.5, hit 90, 5000 obs) passes outright.
    assert per_feed[884]["hk-equities"]["n_passed"] == 1
    assert per_feed[884]["hk-equities"]["n_topup"] == 0
    assert topup_rows == 0
    assert zero_passer_rows == 0
    # Crucially: no us-equities key at all.
    assert "us-equities" not in per_feed[884]
```

(b) Replace the three `mode_data` fixtures that still carry `"is_fallback": False`. In each of `test_write_rankings_sheet_one_mode_uses_6_columns` (~L739), `test_write_rankings_sheet_four_modes_uses_24_columns` (~L777), and `test_write_allowed_sheet_one_mode_emits_two_rows_per_feed` (~L818), change the line:

```python
                "is_fallback": False,
```

to:

```python
                "n_passed": 2,
                "n_topup": 0,
```

(c) Update the `write_allowed_sheet` call inside `test_write_allowed_sheet_one_mode_emits_two_rows_per_feed` to pass the new param. Change:

```python
    write_allowed_sheet(
        ws,
        per_feed,
        skipped_feeds=[],
        date="2026-05-19",
        cluster="lazer-prod",
        modes=["hk-equities"],
        sessions={"hk-equities": "REGULAR"},
    )
```

to:

```python
    write_allowed_sheet(
        ws,
        per_feed,
        skipped_feeds=[],
        date="2026-05-19",
        cluster="lazer-prod",
        modes=["hk-equities"],
        sessions={"hk-equities": "REGULAR"},
        ceiling_mult=2.0,
    )
```

(d) Add new `write_allowed_sheet` Notes tests. Append after `test_write_allowed_sheet_one_mode_emits_two_rows_per_feed` (~L837):

```python
def test_write_allowed_sheet_topup_note_when_below_floor(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    per_feed = {
        884: {
            "hk-equities": {
                "ranked": [_ranked_row(5)],
                "filtered": [_ranked_row(5), _ranked_row(7), _ranked_row(9)],
                "n_passed": 1,
                "n_topup": 2,
            }
        }
    }
    write_allowed_sheet(
        ws,
        per_feed,
        skipped_feeds=[],
        date="2026-05-19",
        cluster="lazer-prod",
        modes=["hk-equities"],
        sessions={"hk-equities": "REGULAR"},
        ceiling_mult=2.0,
    )
    # Session row is row 4; Notes is column 4.
    assert ws.cell(row=4, column=4).value == "1 passed + 2 top-up (≤2×)"
    assert "5, 7, 9" in ws.cell(row=4, column=3).value


def test_write_allowed_sheet_all_passers_has_blank_note(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    per_feed = {
        884: {
            "hk-equities": {
                "ranked": [_ranked_row(5)],
                "filtered": [_ranked_row(5), _ranked_row(7)],
                "n_passed": 2,
                "n_topup": 0,
            }
        }
    }
    write_allowed_sheet(
        ws,
        per_feed,
        skipped_feeds=[],
        date="2026-05-19",
        cluster="lazer-prod",
        modes=["hk-equities"],
        sessions={"hk-equities": "REGULAR"},
        ceiling_mult=2.0,
    )
    assert ws.cell(row=4, column=4).value is None


def test_write_allowed_sheet_empty_by_ceiling_note(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    per_feed = {
        884: {
            "hk-equities": {
                "ranked": [_ranked_row(5, ros=3.0)],
                "filtered": [],
                "n_passed": 0,
                "n_topup": 0,
            }
        }
    }
    write_allowed_sheet(
        ws,
        per_feed,
        skipped_feeds=[],
        date="2026-05-19",
        cluster="lazer-prod",
        modes=["hk-equities"],
        sessions={"hk-equities": "REGULAR"},
        ceiling_mult=2.0,
    )
    assert ws.cell(row=4, column=3).value == "(no data)"
    assert ws.cell(row=4, column=4).value == "0 passed, all > 2× ceiling"
```

(`≤` is `≤`, `×` is `×` — type the literal characters.)

- [ ] **Step 9: Run the full suite to verify green**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py -v`
Expected: PASS (all tests, including the rewritten `apply_filter` set, the updated `_build_per_feed_data` test, and the 3 new `write_allowed_sheet` Notes tests). Zero failures.

- [ ] **Step 10: Smoke-test the CLI end to end on real reports (if `dq_reports/` is present)**

Run:

```bash
python3 -m lazer_dq.summarize_feeds \
    --csv equity_hk_feed_ids.csv --asset-class hk-equities \
    --cluster lazer-prod --date 2026-05-22 --output /tmp/floor_check.xlsx
```

Expected: exits 0; stdout ends with `Rows using top-ups: N cells` and `Rows with 0 passers: M cells` (no `Fallbacks triggered` line). If `dq_reports/` or that CSV is absent, skip this step — the pytest suite already covers behavior.

Also confirm the retired flag is gone:

```bash
python3 -m lazer_dq.summarize_feeds --help | grep -E "redundancy-floor|topup-ceiling-mult|fallback-top"
```

Expected: lists `--redundancy-floor` and `--topup-ceiling-mult`; no `--fallback-top`.

- [ ] **Step 11: Commit**

```bash
git add lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git commit -m "feat(lazer_dq): redundancy floor with ceiling-bounded top-ups in summarize_feeds

Replace the 0-passed fallback (top-3) with a floor of N (default 5): take all
quality passers, then top up with next-best near-misses that clear the n_obs
floor and sit within 2x the pass threshold on rmse_over_spread. Retire
--fallback-top for --redundancy-floor and --topup-ceiling-mult.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Update user-facing docs

**Files:**

- Modify: `docs/summarize_feeds.md`

- [ ] **Step 1: Update the "ranking knobs" example**

In `docs/summarize_feeds.md`, replace:

```
    --top-n 15 --fallback-top 5 --min-n-observations 500
```

with:

```
    --top-n 15 --redundancy-floor 5 --topup-ceiling-mult 2.0 --min-n-observations 500
```

- [ ] **Step 2: Update the Arguments table**

Replace the table row:

```
| `--fallback-top`                   | Fallback size when zero publishers pass thresholds | `3`                                |
```

with:

```
| `--redundancy-floor`               | Minimum publishers per feed/session (top up below-threshold near-misses to reach it) | `5`                                |
| `--topup-ceiling-mult`             | A top-up's `rmse_over_spread` must be ≤ this × the per-mode pass threshold            | `2.0`                              |
```

- [ ] **Step 3: Update the "Ranking & Filtering" step 4**

Replace:

```
4. **Filter** by per-mode thresholds (`max-rmse-over-spread-*`, `min-hit-rate-*`):
   - If ≥ 1 publisher passes → return all passers.
   - If 0 pass → return the top `--fallback-top` from the ranked list.
   - If fewer than `--fallback-top` exist → return what's available.
```

with:

```
4. **Filter** by per-mode thresholds (`max-rmse-over-spread-*`, `min-hit-rate-*`) and apply the redundancy floor:
   - **Passers** = publishers meeting all three thresholds (`rmse_over_spread`, `hit_rate`, `n_observations`), sorted ascending by `rmse_over_spread`.
   - If passers ≥ `--redundancy-floor` → return all passers (the floor is a minimum, never a cap).
   - If passers < `--redundancy-floor` → **top up** with the next-best below-threshold publishers, ranked by `rmse_over_spread`, each of which must clear `--min-n-observations` and have `rmse_over_spread ≤ --topup-ceiling-mult × max-rmse-over-spread-<mode>`. Take only as many as needed to reach the floor.
   - A publisher above the ceiling is never promoted, even if the feed stays below the floor.
   - The `Notes` column shows the mix, e.g. `2 passed + 3 top-up (≤2×)` (highlighted yellow), or `0 passed, all > 2× ceiling` when nothing sits within the ceiling.
```

- [ ] **Step 4: Run prettier on the doc**

Run: `pre-commit run --files docs/summarize_feeds.md`
Expected: PASS (prettier may reformat the table column widths — that is fine).

- [ ] **Step 5: Commit**

```bash
git add docs/summarize_feeds.md
git commit -m "docs(lazer_dq): document redundancy floor and retire --fallback-top

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Final Verification

- [ ] Run the full test suite once more: `python3 -m pytest lazer_dq/tests/ -v` → all pass.
- [ ] Run `pre-commit run --files lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py docs/summarize_feeds.md` → black, prettier, trailing-whitespace, end-of-file hooks pass.
- [ ] `git grep -n "fallback_top\|DEFAULT_FALLBACK_TOP\|is_fallback\|fb_count\|Fallbacks triggered" lazer_dq/` returns nothing (all live references removed; historical `docs/` records intentionally retain them).
