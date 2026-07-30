# summarize_feeds.py Raw-RMSE Passer Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional raw-`rmse` ceiling to `lazer_dq/summarize_feeds.py` that, when set via new `--max-rmse-*` CLI flags, a publisher must additionally clear to count as an `allowed`-sheet passer.

**Architecture:** `apply_filter()` gains an optional `max_rmse: float | None = None` parameter that gates passers only (mirroring existing `hit_rate` behavior) using the `rmse` column already present in every `stats.csv` row. Four new `us-equities`-only CLI flags (`--max-rmse-regular/-pre/-post/-overnight`, all default `None`) are threaded through `main()` → `_build_per_feed_data()` → `apply_filter()` via a new `max_rmse_map` dict, mirroring the existing `max_ros_map`/`min_hit_map` plumbing.

**Tech Stack:** Python 3, `argparse`, `pytest`, `openpyxl` (existing stack, no new dependencies).

## Global Constraints

- Default behavior when the new flags are unset must be byte-for-byte identical to today (spec: "Non-goals" — no default rmse threshold).
- Top-ups (redundancy-floor backfill) are never gated by `max_rmse` — only passers are (spec: "Filtering semantics").
- No changes to `rank_top_n()`, the `rankings` sheet, `write_allowed_sheet()`, or Notes-column messaging (spec: "Non-goals" / "Threading through").
- New flags apply to `us-equities` only; other asset classes get `max_rmse_map = {mode: None for mode in modes}` (spec: "CLI surface").
- Match existing code style (black-formatted); run `pre-commit run --files <changed files>` before considering a task done.

---

### Task 1: `apply_filter()` raw-rmse passer gate

**Files:**
- Modify: `lazer_dq/summarize_feeds.py:222-273` (the `apply_filter` function)
- Test: `lazer_dq/tests/test_summarize_feeds.py:164-171` (the `_stat` helper) and `:227-341` (the `apply_filter` test block)

**Interfaces:**
- Consumes: nothing new — reads the existing `r["rmse"]` key already present in every real `stats.csv` row (see `STATS_HEADER` at `lazer_dq/tests/test_summarize_feeds.py:110-114`: `...,rmse,nrmse,rmse_over_spread,...`).
- Produces: `apply_filter(stats, max_ros, min_hit, min_obs, floor, ceiling_mult, max_rmse=None)` — same 3-tuple return `(selected, n_passed, n_topup)` as before. `max_rmse` is keyword-only in practice (always passed by name from Task 2 onward); existing positional callers are unaffected since it has a default.

- [ ] **Step 1: Extend the `_stat` test helper to optionally carry a raw `rmse` field**

In `lazer_dq/tests/test_summarize_feeds.py`, find the current helper:

```python
def _stat(publisher_id, ros, hit=80.0, n_obs=10000):
    """Helper: minimal stats.csv-style dict."""
    return {
        "publisher_id": str(publisher_id),
        "rmse_over_spread": str(ros),
        "hit_rate_0.1pct": str(hit),
        "n_observations": str(n_obs),
    }
```

Replace it with:

```python
def _stat(publisher_id, ros, hit=80.0, n_obs=10000, rmse=None):
    """Helper: minimal stats.csv-style dict. `rmse` key is omitted unless given,
    so existing tests (which don't pass it) are unaffected."""
    d = {
        "publisher_id": str(publisher_id),
        "rmse_over_spread": str(ros),
        "hit_rate_0.1pct": str(hit),
        "n_observations": str(n_obs),
    }
    if rmse is not None:
        d["rmse"] = str(rmse)
    return d
```

This is a pure addition (new optional parameter, existing call sites unaffected) — no test run needed for this step alone, it's covered by Step 2's run.

- [ ] **Step 2: Write the failing tests for the new `max_rmse` gate**

Add these four tests immediately after `test_apply_filter_returns_empty_for_empty_input` (currently ending at `lazer_dq/tests/test_summarize_feeds.py:340`), before the blank lines preceding `from lazer_dq.summarize_feeds import compute_aggregate`:

```python
def test_apply_filter_max_rmse_default_none_ignores_rmse_field():
    # max_rmse defaults to None -> the (huge) rmse field must have no effect.
    stats = [_stat(11, 0.5, rmse=999.0)]
    selected, n_passed, n_topup = apply_filter(
        stats, max_ros=1.0, min_hit=80, min_obs=1000, floor=0, ceiling_mult=2.0
    )
    assert n_passed == 1
    assert n_topup == 0
    assert {r["publisher_id"] for r in selected} == {"11"}


def test_apply_filter_max_rmse_gates_passers_only():
    # 11 clears ros/hit/n_obs but its raw rmse (5.0) exceeds max_rmse=1.0 -> not a passer.
    # 20 clears everything including rmse -> passer.
    stats = [
        _stat(11, 0.5, rmse=5.0),
        _stat(20, 0.6, rmse=0.5),
    ]
    selected, n_passed, n_topup = apply_filter(
        stats,
        max_ros=1.0,
        min_hit=80,
        min_obs=1000,
        floor=0,
        ceiling_mult=2.0,
        max_rmse=1.0,
    )
    assert n_passed == 1
    assert n_topup == 0
    assert {r["publisher_id"] for r in selected} == {"20"}


def test_apply_filter_max_rmse_does_not_gate_topups():
    # 11 fails only the max_rmse gate (5.0 > 1.0); it's otherwise eligible
    # (ros and n_obs clear the top-up bar), so with floor=1 it must be topped
    # up despite failing the rmse gate -> top-ups are rmse-agnostic.
    stats = [_stat(11, 0.5, rmse=5.0)]
    selected, n_passed, n_topup = apply_filter(
        stats,
        max_ros=1.0,
        min_hit=80,
        min_obs=1000,
        floor=1,
        ceiling_mult=2.0,
        max_rmse=1.0,
    )
    assert n_passed == 0
    assert n_topup == 1
    assert {r["publisher_id"] for r in selected} == {"11"}


def test_apply_filter_max_rmse_missing_field_treated_as_non_passer():
    # No 'rmse' key at all (simulates a malformed/missing raw-rmse column).
    # With max_rmse set, this must fail the gate (non-passer) but remain
    # eligible as a top-up, not be silently skipped.
    stats = [_stat(11, 0.5)]  # rmse omitted
    selected, n_passed, n_topup = apply_filter(
        stats,
        max_ros=1.0,
        min_hit=80,
        min_obs=1000,
        floor=1,
        ceiling_mult=2.0,
        max_rmse=1.0,
    )
    assert n_passed == 0
    assert n_topup == 1
    assert {r["publisher_id"] for r in selected} == {"11"}
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `pytest lazer_dq/tests/test_summarize_feeds.py -k max_rmse -v`
Expected: `test_apply_filter_max_rmse_default_none_ignores_rmse_field` passes already (no code change needed for the no-op case, since `apply_filter` doesn't accept `max_rmse` yet — actually expect a `TypeError: apply_filter() got an unexpected keyword argument 'max_rmse'` for the three tests that pass `max_rmse=1.0`). All 4 should either error or fail — none should silently pass by accident. Confirm the failures are `TypeError` (unexpected keyword `max_rmse`), not assertion mismatches, which would indicate a pre-existing bug unrelated to this change.

- [ ] **Step 4: Implement the `max_rmse` gate in `apply_filter()`**

In `lazer_dq/summarize_feeds.py`, replace the current `apply_filter` function (lines 222-273):

```python
def apply_filter(
    stats, max_ros: float, min_hit: float, min_obs: int, floor: int, ceiling_mult: float
):
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
```

with:

```python
def apply_filter(
    stats,
    max_ros: float,
    min_hit: float,
    min_obs: int,
    floor: int,
    ceiling_mult: float,
    max_rmse: float | None = None,
):
    """Apply per-mode thresholds with a redundancy floor. Return (selected, n_passed, n_topup).

    selected : passers (sorted ascending by rmse_over_spread) plus, when there
               are fewer than `floor` passers, the next-best below-threshold
               publishers ("top-ups") sorted by rmse_over_spread. Each top-up
               must clear the n_observations floor AND have
               rmse_over_spread <= ceiling_mult * max_ros. The floor is a
               minimum, never a cap: if more than `floor` publishers pass, all
               of them are returned.
    n_passed : count meeting all thresholds (r/s, hit_rate, n_obs, and rmse if set).
    n_topup  : count of below-threshold fillers added to reach the floor.
    max_rmse : optional raw-rmse ceiling (default: disabled). When set, a row
               must additionally have rmse <= max_rmse to count as a passer —
               gates passers only, same as hit_rate; top-ups are unaffected.
               A missing/non-numeric rmse field when max_rmse is set fails the
               gate (row becomes a non-passer, still eligible for top-up).

    Empty input -> ([], 0, 0). Rows with non-numeric metric fields are skipped.
    Note: hit_rate and max_rmse gate passers only, not top-ups; the ceiling is
    the top-up quality proxy.
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
        rmse_ok = True
        if max_rmse is not None:
            try:
                rmse_ok = float(r["rmse"]) <= max_rmse
            except (ValueError, KeyError):
                rmse_ok = False
        if ros <= max_ros and hit >= min_hit and n_obs >= min_obs and rmse_ok:
            passers.append((ros, r))
        else:
            non_passers.append((ros, r, n_obs))
```

The rest of the function body (`passers.sort(...)` through the `return selected, n_passed, len(topups)` line) is unchanged — leave it exactly as-is.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest lazer_dq/tests/test_summarize_feeds.py -k "apply_filter or max_rmse" -v`
Expected: all `apply_filter` tests PASS, including the 4 new ones and all pre-existing ones (regression check).

- [ ] **Step 6: Run the full test file to confirm no regressions**

Run: `pytest lazer_dq/tests/test_summarize_feeds.py -v`
Expected: all tests PASS (this file's suite; per project CLAUDE.md, run this file directly rather than repo-root `pytest -q`, which has a pre-existing unrelated conftest clash).

- [ ] **Step 7: Format and commit**

Run: `pre-commit run --files lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py`

If it reformats anything, review the diff, then:

```bash
git add lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git commit -m "feat: add optional max_rmse passer gate to apply_filter"
```

---

### Task 2: Thread `--max-rmse-*` CLI flags through `main()` and `_build_per_feed_data()`

**Files:**
- Modify: `lazer_dq/summarize_feeds.py:559-653` (`_build_per_feed_data`)
- Modify: `lazer_dq/summarize_feeds.py:656-904` (`main`)
- Test: `lazer_dq/tests/test_summarize_feeds.py` (extend the `_build_per_feed_data` and `main` test blocks)

**Interfaces:**
- Consumes: `apply_filter(..., max_rmse=None)` from Task 1 (exact signature above).
- Produces: `_build_per_feed_data(..., max_rmse_map=None)` — new keyword-only parameter, a `dict[str, float | None]` keyed by mode name (same keying as `max_ros_map`/`min_hit_map`). `main()` builds this dict and passes it through. CLI flags: `--max-rmse-regular`, `--max-rmse-pre`, `--max-rmse-post`, `--max-rmse-overnight` (all `type=float`, `default=None`).

- [ ] **Step 1: Write the failing test for `_build_per_feed_data` honoring `max_rmse_map`**

Find `test_build_per_feed_data_honors_modes_parameter` (starts at `lazer_dq/tests/test_summarize_feeds.py:739`) and read it plus the `_write_stats_csv`/`STATS_HEADER` helpers above it for the exact row format before writing this. Add a new test after it in the same "`_build_per_feed_data` with custom modes" section:

```python
def test_build_per_feed_data_max_rmse_map_excludes_high_rmse_from_allowed(tmp_path):
    pubs_md = tmp_path / "publishers.md"
    pubs_md.write_text("| ID | Name | Active |\n| --- | --- | --- |\n")

    reports = tmp_path / "dq_reports"
    # publisher 11: rmse=5.0 (col 8), rmse_over_spread=0.05 (col 10, passes),
    #   hit_rate=100.0 (col 17, passes), n_observations=22218 (passes).
    # publisher 12: rmse=0.05 (passes), otherwise identical -> should remain a passer.
    _write_stats_csv(
        reports,
        "lazer-prod",
        "us-equities",
        1021,
        "2026-05-06",
        [
            "1021,11,22218,-0.05,0.08,-0.01,0.02,5.0,0.51,0.05,0.07,-84,0,75,0,0,100.0,0.96,fail\n",
            "1021,12,22218,-0.05,0.08,-0.01,0.02,0.05,0.51,0.05,0.07,-84,0,75,0,0,100.0,0.96,fail\n",
        ],
    )

    excluded = load_excluded_publishers(pubs_md)
    (per_feed, _skipped, _topup, _zero, _modes_with_data, _cells) = _build_per_feed_data(
        [1021],
        reports,
        "lazer-prod",
        "2026-05-06",
        excluded,
        top_n=10,
        max_ros_map={"us-equities": 1.0},
        min_hit_map={"us-equities": 80.0},
        min_obs=1000,
        floor=0,
        ceiling_mult=2.0,
        modes=["us-equities"],
        max_rmse_map={"us-equities": 1.0},
    )
    filtered = per_feed[1021]["us-equities"]["filtered"]
    ids = {r["publisher_id"] for r in filtered}
    assert ids == {"12"}
    assert "11" not in ids
    assert per_feed[1021]["us-equities"]["n_passed"] == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest lazer_dq/tests/test_summarize_feeds.py -k max_rmse_map -v`
Expected: FAIL with `TypeError: _build_per_feed_data() got an unexpected keyword argument 'max_rmse_map'`.

- [ ] **Step 3: Add `max_rmse_map` to `_build_per_feed_data`**

In `lazer_dq/summarize_feeds.py`, update the function signature (currently at line 559):

```python
def _build_per_feed_data(
    feed_ids,
    reports_dir,
    cluster,
    date,
    excluded,
    top_n,
    max_ros_map,
    min_hit_map,
    min_obs,
    floor,
    ceiling_mult,
    modes,
    manual_exclude=None,
):
```

to:

```python
def _build_per_feed_data(
    feed_ids,
    reports_dir,
    cluster,
    date,
    excluded,
    top_n,
    max_ros_map,
    min_hit_map,
    min_obs,
    floor,
    ceiling_mult,
    modes,
    manual_exclude=None,
    max_rmse_map=None,
):
```

Update its docstring (the `manual_exclude` paragraph) by adding directly below it:

```python
    `max_rmse_map` is an optional dict[mode] -> float|None raw-rmse ceiling
    (default: all None, i.e. disabled). Threaded straight into apply_filter's
    max_rmse parameter per mode; see apply_filter's docstring for gating
    semantics.
    """
```

(Keep the existing docstring content above it — this is an addition, not a replacement of the whole docstring.)

Right after the existing `manual_exclude = manual_exclude or set()` line, add:

```python
    max_rmse_map = max_rmse_map or {}
```

Then update the `apply_filter` call (currently):

```python
            selected, n_passed, n_topup = apply_filter(
                filter_input,
                max_ros_map[mode],
                min_hit_map[mode],
                min_obs,
                floor,
                ceiling_mult,
            )
```

to:

```python
            selected, n_passed, n_topup = apply_filter(
                filter_input,
                max_ros_map[mode],
                min_hit_map[mode],
                min_obs,
                floor,
                ceiling_mult,
                max_rmse=max_rmse_map.get(mode),
            )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest lazer_dq/tests/test_summarize_feeds.py -k max_rmse_map -v`
Expected: PASS.

- [ ] **Step 5: Run the full test file to confirm no regressions**

Run: `pytest lazer_dq/tests/test_summarize_feeds.py -v`
Expected: all PASS (existing `_build_per_feed_data` calls don't pass `max_rmse_map`, so it defaults to `None` → `{}` → `.get(mode)` returns `None` for every mode, identical to today's behavior).

- [ ] **Step 6: Write the failing CLI test**

Read `test_main_writes_workbook_for_one_feed_one_mode` (`lazer_dq/tests/test_summarize_feeds.py:378-461`) in full first — this new test follows the same shape. Add a new test after it:

```python
def test_main_max_rmse_regular_excludes_high_rmse_publisher(
    tmp_path, monkeypatch, capsys
):
    """--max-rmse-regular gates the REGULAR-session allowed list by raw rmse."""
    pubs_md = tmp_path / "publishers.md"
    pubs_md.write_text(
        "| ID | Name | Active |\n| --- | --- | --- |\n| 11 | Amber.Production | Yes |\n"
        "| 12 | Other.Production | Yes |\n"
    )

    csv = tmp_path / "input.csv"
    csv.write_text("1021, 2026-05-06, us-equities\n")

    reports = tmp_path / "dq_reports"
    _write_stats_csv(
        reports,
        "lazer-prod",
        "us-equities",
        1021,
        "2026-05-06",
        [
            # 11: rmse=5.0 -> excluded once --max-rmse-regular=1.0 is set.
            "1021,11,22218,-0.05,0.08,-0.01,0.02,5.0,0.51,0.05,0.07,-84,0,75,0,0,100.0,0.96,fail\n",
            # 12: rmse=0.05 -> stays a passer.
            "1021,12,22218,-0.05,0.08,-0.01,0.02,0.05,0.51,0.05,0.07,-84,0,75,0,0,100.0,0.96,fail\n",
        ],
    )

    out_path = tmp_path / "out.xlsx"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summarize_feeds",
            "--csv",
            str(csv),
            "--cluster",
            "lazer-prod",
            "--date",
            "2026-05-06",
            "--reports-dir",
            str(reports),
            "--publishers-md",
            str(pubs_md),
            "--output",
            str(out_path),
            "--redundancy-floor",
            "0",
            "--max-rmse-regular",
            "1.0",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0

    wb = load_workbook(out_path, data_only=True)
    allow = wb["allowed"]
    # Row 3 = aggregate, row 4 = REGULAR (MODE_ORDER[0]).
    assert allow.cell(4, 2).value == "REGULAR"
    assert allow.cell(4, 3).value == '"allowedPublisherIds": [ 12 ],'
```

- [ ] **Step 7: Run it to verify it fails**

Run: `pytest lazer_dq/tests/test_summarize_feeds.py -k max_rmse_regular_excludes -v`
Expected: FAIL — either an `argparse` error (`unrecognized arguments: --max-rmse-regular`) causing `SystemExit` with a non-zero code, or an assertion mismatch on `allow.cell(4, 3).value` (publisher 11 still included). Either failure mode confirms the flag doesn't exist yet.

- [ ] **Step 8: Add the 4 CLI flags and wire `max_rmse_map` in `main()`**

In `lazer_dq/summarize_feeds.py`, find this block (currently ending around line 748):

```python
    parser.add_argument(
        "--max-rmse-over-spread-overnight",
        type=float,
        default=ASSET_CLASS_CONFIG["us-equities"]["default_max_ros"][
            "us-equities-overnight"
        ],
    )
    parser.add_argument(
        "--min-hit-rate-overnight",
        type=float,
        default=ASSET_CLASS_CONFIG["us-equities"]["default_min_hit"][
            "us-equities-overnight"
        ],
    )
    parser.add_argument("--min-n-observations", type=int, default=DEFAULT_MIN_N_OBS)
```

Insert 4 new flags between the `--min-hit-rate-overnight` block and `--min-n-observations`:

```python
    parser.add_argument(
        "--max-rmse-over-spread-overnight",
        type=float,
        default=ASSET_CLASS_CONFIG["us-equities"]["default_max_ros"][
            "us-equities-overnight"
        ],
    )
    parser.add_argument(
        "--min-hit-rate-overnight",
        type=float,
        default=ASSET_CLASS_CONFIG["us-equities"]["default_min_hit"][
            "us-equities-overnight"
        ],
    )
    parser.add_argument(
        "--max-rmse-regular",
        type=float,
        default=None,
        help="Optional raw-rmse ceiling for us-equities REGULAR passers "
        "(default: disabled). Gates passers only; top-ups are unaffected.",
    )
    parser.add_argument(
        "--max-rmse-pre",
        type=float,
        default=None,
        help="Optional raw-rmse ceiling for us-equities PRE_MARKET passers "
        "(default: disabled).",
    )
    parser.add_argument(
        "--max-rmse-post",
        type=float,
        default=None,
        help="Optional raw-rmse ceiling for us-equities POST_MARKET passers "
        "(default: disabled).",
    )
    parser.add_argument(
        "--max-rmse-overnight",
        type=float,
        default=None,
        help="Optional raw-rmse ceiling for us-equities OVER_NIGHT passers "
        "(default: disabled).",
    )
    parser.add_argument("--min-n-observations", type=int, default=DEFAULT_MIN_N_OBS)
```

Next, find the `max_ros_map`/`min_hit_map` construction (currently around lines 806-823):

```python
    if args.asset_class == "us-equities":
        # us-equities keeps its existing flat per-mode CLI flags.
        max_ros_map = {
            "us-equities": args.max_rmse_over_spread_regular,
            "us-equities-pre": args.max_rmse_over_spread_pre,
            "us-equities-post": args.max_rmse_over_spread_post,
            "us-equities-overnight": args.max_rmse_over_spread_overnight,
        }
        min_hit_map = {
            "us-equities": args.min_hit_rate_regular,
            "us-equities-pre": args.min_hit_rate_pre,
            "us-equities-post": args.min_hit_rate_post,
            "us-equities-overnight": args.min_hit_rate_overnight,
        }
    else:
        # Other asset classes use the registry defaults (no per-mode CLI overrides yet).
        max_ros_map = dict(asset_cfg["default_max_ros"])
        min_hit_map = dict(asset_cfg["default_min_hit"])
```

Replace with:

```python
    if args.asset_class == "us-equities":
        # us-equities keeps its existing flat per-mode CLI flags.
        max_ros_map = {
            "us-equities": args.max_rmse_over_spread_regular,
            "us-equities-pre": args.max_rmse_over_spread_pre,
            "us-equities-post": args.max_rmse_over_spread_post,
            "us-equities-overnight": args.max_rmse_over_spread_overnight,
        }
        min_hit_map = {
            "us-equities": args.min_hit_rate_regular,
            "us-equities-pre": args.min_hit_rate_pre,
            "us-equities-post": args.min_hit_rate_post,
            "us-equities-overnight": args.min_hit_rate_overnight,
        }
        max_rmse_map = {
            "us-equities": args.max_rmse_regular,
            "us-equities-pre": args.max_rmse_pre,
            "us-equities-post": args.max_rmse_post,
            "us-equities-overnight": args.max_rmse_overnight,
        }
    else:
        # Other asset classes use the registry defaults (no per-mode CLI overrides yet).
        max_ros_map = dict(asset_cfg["default_max_ros"])
        min_hit_map = dict(asset_cfg["default_min_hit"])
        max_rmse_map = {mode: None for mode in modes}
```

Finally, find the `_build_per_feed_data(...)` call (currently around lines 834-848):

```python
    ) = _build_per_feed_data(
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
        manual_exclude=manual_exclude,
    )
```

Add `max_rmse_map` as a new keyword argument:

```python
    ) = _build_per_feed_data(
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
        manual_exclude=manual_exclude,
        max_rmse_map=max_rmse_map,
    )
```

- [ ] **Step 9: Run the CLI test to verify it passes**

Run: `pytest lazer_dq/tests/test_summarize_feeds.py -k max_rmse_regular_excludes -v`
Expected: PASS.

- [ ] **Step 10: Run the full test file to confirm no regressions**

Run: `pytest lazer_dq/tests/test_summarize_feeds.py -v`
Expected: all PASS.

- [ ] **Step 11: Format and commit**

Run: `pre-commit run --files lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py`

```bash
git add lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git commit -m "feat: add --max-rmse-* CLI flags to summarize_feeds.py"
```

---

### Task 3: Document the new flags

**Files:**
- Modify: `docs/summarize_feeds.md`

**Interfaces:**
- Consumes: the finished `--max-rmse-regular/-pre/-post/-overnight` flags and gating semantics from Task 2 (final behavior, not new code).
- Produces: nothing consumed by later tasks — this is the last task.

- [ ] **Step 1: Add the new flags to the Arguments table**

In `docs/summarize_feeds.md`, find this row (in the Arguments table):

```markdown
| `--max-rmse-over-spread-overnight` | RMSE/spread ceiling for `us-equities-overnight`                                                                         | `3.0`                              |
| `--min-hit-rate-overnight`         | Hit-rate floor (%) for `us-equities-overnight`                                                                          | `25.0`                             |
| `--min-n-observations`             | Minimum sample size to consider a publisher                                                                             | `1000`                             |
```

Replace it with (adding 4 rows before `--min-n-observations`):

```markdown
| `--max-rmse-over-spread-overnight` | RMSE/spread ceiling for `us-equities-overnight`                                                                         | `3.0`                              |
| `--min-hit-rate-overnight`         | Hit-rate floor (%) for `us-equities-overnight`                                                                          | `25.0`                             |
| `--max-rmse-regular`               | Optional raw-rmse ceiling for `us-equities` passers (disabled unless set)                                              | none (off)                         |
| `--max-rmse-pre`                   | Optional raw-rmse ceiling for `us-equities-pre` passers (disabled unless set)                                          | none (off)                         |
| `--max-rmse-post`                  | Optional raw-rmse ceiling for `us-equities-post` passers (disabled unless set)                                         | none (off)                         |
| `--max-rmse-overnight`             | Optional raw-rmse ceiling for `us-equities-overnight` passers (disabled unless set)                                    | none (off)                         |
| `--min-n-observations`             | Minimum sample size to consider a publisher                                                                             | `1000`                             |
```

- [ ] **Step 2: Extend the "Ranking & Filtering" passer bullet**

Find this bullet in the "Ranking & Filtering" section:

```markdown
   - **Passers** = publishers meeting all three thresholds — `rmse_over_spread`, `hit_rate`, and `n_observations ≥ --min-n-observations` — sorted ascending by `rmse_over_spread`.
```

Replace with:

```markdown
   - **Passers** = publishers meeting all thresholds — `rmse_over_spread`, `hit_rate`, `n_observations ≥ --min-n-observations`, and (when `--max-rmse-*` is set for the mode) raw `rmse ≤ --max-rmse-<mode>` — sorted ascending by `rmse_over_spread`.
   - `--max-rmse-*` is `us-equities`-only and off by default. Like `hit_rate`, it gates passers only — top-ups are never rmse-gated, only capped by the existing `rmse_over_spread` ceiling (`--topup-ceiling-mult`).
```

- [ ] **Step 3: Add a usage example**

Find the "Override per-mode thresholds" example block:

```markdown
# Override per-mode thresholds
python -m lazer_dq.summarize_feeds \
    --csv feeds.csv --cluster lazer-prod --date 2026-05-06 \
    --max-rmse-over-spread-regular 0.8 --min-hit-rate-regular 85.0 \
    --max-rmse-over-spread-pre 1.5 --min-hit-rate-pre 60.0
```

Add a new example directly after it (before the "Override ranking knobs" block):

````markdown
# Also gate REGULAR-session passers by raw rmse (off by default)
python -m lazer_dq.summarize_feeds \
    --csv feeds.csv --cluster lazer-prod --date 2026-05-06 \
    --max-rmse-regular 0.05
````

- [ ] **Step 4: Proofread the diff**

Run: `git diff docs/summarize_feeds.md`
Expected: only the additions above; table column alignment doesn't need to be pixel-perfect (prettier will reflow markdown tables on commit).

- [ ] **Step 5: Run prettier and commit**

Run: `pre-commit run --files docs/summarize_feeds.md`

```bash
git add docs/summarize_feeds.md
git commit -m "docs: document --max-rmse-* flags for summarize_feeds.py"
```

---

## Definition of Done

- [ ] `apply_filter()` accepts optional `max_rmse`, gates passers only, top-ups unaffected (Task 1).
- [ ] 4 new `--max-rmse-*` CLI flags exist for `us-equities`, default `None`/disabled, threaded through `_build_per_feed_data()` (Task 2).
- [ ] `docs/summarize_feeds.md` documents the new flags and passer semantics (Task 3).
- [ ] `pytest lazer_dq/tests/test_summarize_feeds.py -v` passes in full.
- [ ] `pre-commit run --files lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py docs/summarize_feeds.md` is clean.
- [ ] Existing invocations without any `--max-rmse-*` flag produce identical output to before this change (verified by the full regression suite passing unchanged).
