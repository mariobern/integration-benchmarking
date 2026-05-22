# summarize_feeds Asset-Class Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `lazer_dq/summarize_feeds.py` to support multiple asset classes via a registry, unblock `hk-equities` summarization today, and make adding the next asset class a 1-entry dict edit.

**Architecture:** Replace the four module-level US-equities constants (`MODE_ORDER`, `MODE_TO_SESSION`, `DEFAULT_MAX_ROS`, `DEFAULT_MIN_HIT`) with a single `ASSET_CLASS_CONFIG` dict keyed by asset-class slug. Add `--asset-class` CLI flag (default `us-equities` for backward compatibility). Pipe the selected entry's `modes` + `sessions` through `_build_per_feed_data`, `write_rankings_sheet`, and `write_allowed_sheet` as parameters. Make the rankings-sheet column layout parametric on `len(modes)` (6N columns: 1 rank + N × 5-col blocks + (N-1) spacers).

**Tech Stack:** Python 3, `openpyxl`, `pytest`. No new dependencies. Spec: `docs/superpowers/specs/2026-05-22-summarize-feeds-asset-class-registry-design.md`.

---

## Task 1: Add the registry and prove us-equities still resolves through it

**Files:**

- Modify: `lazer_dq/summarize_feeds.py` (top of file, lines 17-48)
- Test: `lazer_dq/tests/test_summarize_feeds.py` (append new section)

- [ ] **Step 1: Write the failing test**

Append to `lazer_dq/tests/test_summarize_feeds.py`:

```python
# ---------- ASSET_CLASS_CONFIG registry ----------

from lazer_dq.summarize_feeds import ASSET_CLASS_CONFIG


def test_registry_has_us_equities_entry_with_all_required_keys():
    assert "us-equities" in ASSET_CLASS_CONFIG
    cfg = ASSET_CLASS_CONFIG["us-equities"]
    assert cfg["modes"] == [
        "us-equities",
        "us-equities-pre",
        "us-equities-post",
        "us-equities-overnight",
    ]
    assert cfg["sessions"] == {
        "us-equities": "REGULAR",
        "us-equities-pre": "PRE_MARKET",
        "us-equities-post": "POST_MARKET",
        "us-equities-overnight": "OVER_NIGHT",
    }
    assert cfg["default_max_ros"] == {
        "us-equities": 1.0,
        "us-equities-pre": 2.0,
        "us-equities-post": 2.0,
        "us-equities-overnight": 3.0,
    }
    assert cfg["default_min_hit"] == {
        "us-equities": 80.0,
        "us-equities-pre": 50.0,
        "us-equities-post": 50.0,
        "us-equities-overnight": 25.0,
    }


def test_registry_has_hk_equities_entry():
    assert "hk-equities" in ASSET_CLASS_CONFIG
    cfg = ASSET_CLASS_CONFIG["hk-equities"]
    assert cfg["modes"] == ["hk-equities"]
    assert cfg["sessions"] == {"hk-equities": "REGULAR"}
    assert cfg["default_max_ros"] == {"hk-equities": 1.0}
    assert cfg["default_min_hit"] == {"hk-equities": 80.0}


def test_legacy_constants_still_match_us_equities_registry_entry():
    """Back-compat: MODE_ORDER / MODE_TO_SESSION still exist for any external importer."""
    from lazer_dq.summarize_feeds import MODE_ORDER, MODE_TO_SESSION

    assert MODE_ORDER == ASSET_CLASS_CONFIG["us-equities"]["modes"]
    assert MODE_TO_SESSION == ASSET_CLASS_CONFIG["us-equities"]["sessions"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
source venv/bin/activate
pytest lazer_dq/tests/test_summarize_feeds.py::test_registry_has_us_equities_entry_with_all_required_keys -v
```

Expected: FAIL with `ImportError: cannot import name 'ASSET_CLASS_CONFIG'`.

- [ ] **Step 3: Add the registry**

In `lazer_dq/summarize_feeds.py`, replace lines 17-48 (the `MODE_TO_SESSION`, `MODE_ORDER`, `DEFAULT_MAX_ROS`, `DEFAULT_MIN_HIT` block) with:

```python
# Asset-class registry. Adding a new asset class = adding one entry here.
# Each entry declares:
#   modes:           ordered list of dq_reports/<cluster>/<mode>/ directory names to read.
#   sessions:        mode -> after.json session-label, for the 'allowed' sheet.
#   default_max_ros: per-mode max rmse_over_spread threshold.
#   default_min_hit: per-mode min hit_rate_0.1pct (%) threshold.
ASSET_CLASS_CONFIG: dict = {
    "us-equities": {
        "modes": [
            "us-equities",
            "us-equities-pre",
            "us-equities-post",
            "us-equities-overnight",
        ],
        "sessions": {
            "us-equities": "REGULAR",
            "us-equities-pre": "PRE_MARKET",
            "us-equities-post": "POST_MARKET",
            "us-equities-overnight": "OVER_NIGHT",
        },
        "default_max_ros": {
            "us-equities": 1.0,
            "us-equities-pre": 2.0,
            "us-equities-post": 2.0,
            "us-equities-overnight": 3.0,
        },
        "default_min_hit": {
            "us-equities": 80.0,
            "us-equities-pre": 50.0,
            "us-equities-post": 50.0,
            "us-equities-overnight": 25.0,
        },
    },
    "hk-equities": {
        "modes": ["hk-equities"],
        "sessions": {"hk-equities": "REGULAR"},
        "default_max_ros": {"hk-equities": 1.0},
        "default_min_hit": {"hk-equities": 80.0},
    },
}

# Back-compat aliases — kept so any external code importing these names keeps working.
# Internal code should prefer ASSET_CLASS_CONFIG[<slug>][...] going forward.
MODE_TO_SESSION = ASSET_CLASS_CONFIG["us-equities"]["sessions"]
MODE_ORDER = ASSET_CLASS_CONFIG["us-equities"]["modes"]

DEFAULT_MIN_N_OBS = 1000
DEFAULT_TOP_N = 10
DEFAULT_FALLBACK_TOP = 3
```

- [ ] **Step 4: Run the new tests + the full suite**

```bash
pytest lazer_dq/tests/test_summarize_feeds.py -v
```

Expected: all new registry tests PASS, all existing tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git commit -m "refactor(lazer_dq): introduce ASSET_CLASS_CONFIG registry"
```

---

## Task 2: Thread `modes` + `sessions` through `_build_per_feed_data`

The function currently closes over module-level `MODE_ORDER`. Make it accept the mode list as a parameter so it can be driven by the registry.

**Files:**

- Modify: `lazer_dq/summarize_feeds.py` (`_build_per_feed_data`, lines 429-484)
- Test: `lazer_dq/tests/test_summarize_feeds.py`

- [ ] **Step 1: Write the failing test**

Append to `lazer_dq/tests/test_summarize_feeds.py`:

```python
# ---------- _build_per_feed_data with custom modes ----------

from lazer_dq.summarize_feeds import _build_per_feed_data


def test_build_per_feed_data_honors_modes_parameter(tmp_path):
    """Only the modes passed in are looked up under reports_dir; others are not touched."""
    reports = tmp_path / "dq_reports"
    # Write a stats.csv ONLY for hk-equities.
    _write_stats_csv(
        reports,
        "lazer-prod",
        "hk-equities",
        884,
        "2026-05-19",
        [
            "publisher_id,n_observations,rmse,rmse_over_spread,hit_rate_0.1pct\n",
            "5,5000,0.001,0.5,90.0\n",
        ],
    )
    per_feed, skipped, fb_count, modes_with_data = _build_per_feed_data(
        feed_ids=[884],
        reports_dir=reports,
        cluster="lazer-prod",
        date="2026-05-19",
        excluded={0},
        top_n=10,
        max_ros_map={"hk-equities": 1.0},
        min_hit_map={"hk-equities": 80.0},
        min_obs=1000,
        fallback_top=3,
        modes=["hk-equities"],
    )
    assert skipped == []
    assert modes_with_data == 1
    assert per_feed[884]["hk-equities"] is not None
    assert per_feed[884]["hk-equities"]["ranked"][0]["publisher_id"] == "5"
    # Crucially: no us-equities key at all.
    assert "us-equities" not in per_feed[884]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest lazer_dq/tests/test_summarize_feeds.py::test_build_per_feed_data_honors_modes_parameter -v
```

Expected: FAIL — `_build_per_feed_data()` got unexpected keyword argument `modes`.

- [ ] **Step 3: Add `modes` parameter to `_build_per_feed_data`**

In `lazer_dq/summarize_feeds.py`, change the function signature and body. Replace the existing `_build_per_feed_data` (lines 429-484) with:

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
    fallback_top,
    modes,
):
    """Returns (per_feed_data, skipped_feeds, fallback_count, modes_with_data_count).

    `modes` is the ordered list of dq_reports subdirectory names to read for each feed
    (drawn from ASSET_CLASS_CONFIG[<asset_class>]["modes"]).
    """
    per_feed_data: dict = {}
    skipped: list[int] = []
    fallback_count = 0
    modes_with_data = 0

    for feed_id in feed_ids:
        mode_data: dict = {}
        any_data = False
        for mode in modes:
            raw = load_stats(reports_dir, cluster, mode, feed_id, date)
            if raw is None:
                mode_data[mode] = None
                continue
            # Apply exclusion at the row level.
            kept = []
            for r in raw:
                try:
                    pid = int(r["publisher_id"])
                except (ValueError, KeyError):
                    continue
                if pid in excluded:
                    continue
                kept.append(r)
            if not kept:
                mode_data[mode] = None  # all rows excluded
                continue
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
        if not any_data:
            skipped.append(feed_id)
        per_feed_data[feed_id] = mode_data
    return per_feed_data, skipped, fallback_count, modes_with_data
```

(The only change is the new `modes` keyword parameter; `for mode in MODE_ORDER` becomes `for mode in modes`.)

- [ ] **Step 4: Update the existing `main()` call site**

Find the call in `main()` (currently line 593-604). Add `modes=MODE_ORDER` as a keyword argument so existing tests keep passing while we propagate the change. Change:

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
    )
```

to:

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
        modes=MODE_ORDER,
    )
```

- [ ] **Step 5: Run tests**

```bash
pytest lazer_dq/tests/test_summarize_feeds.py -v
```

Expected: new test PASSES, all existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git commit -m "refactor(lazer_dq): pass modes through _build_per_feed_data"
```

---

## Task 3: Parametrize `write_rankings_sheet` on the mode list

The current implementation hard-codes the 24-column layout with `mode_starts = {"us-equities": 2, "us-equities-pre": 8, ...}` and `for col_idx in range(1, 25)`. Make both parametric on `len(modes)` → 6N columns.

**Files:**

- Modify: `lazer_dq/summarize_feeds.py` (`write_rankings_sheet`, lines 190-302)
- Test: `lazer_dq/tests/test_summarize_feeds.py`

- [ ] **Step 1: Write the failing test**

Append to `lazer_dq/tests/test_summarize_feeds.py`:

```python
# ---------- write_rankings_sheet parametric layout ----------

from lazer_dq.summarize_feeds import write_rankings_sheet


def _ranked_row(pub_id, n_obs=5000, rmse=0.001, ros=0.5, hit=90.0):
    return {
        "publisher_id": str(pub_id),
        "n_observations": str(n_obs),
        "rmse": str(rmse),
        "rmse_over_spread": str(ros),
        "hit_rate_0.1pct": str(hit),
    }


def test_write_rankings_sheet_one_mode_uses_6_columns(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    per_feed = {
        884: {
            "hk-equities": {
                "ranked": [_ranked_row(5), _ranked_row(7)],
                "filtered": [_ranked_row(5)],
                "is_fallback": False,
            }
        }
    }
    write_rankings_sheet(
        ws,
        per_feed,
        date="2026-05-19",
        cluster="lazer-prod",
        modes=["hk-equities"],
    )
    out = tmp_path / "out.xlsx"
    wb.save(out)

    from openpyxl import load_workbook

    wb2 = load_workbook(out)
    ws2 = wb2["Sheet"]
    # Mode-block header in row 3, column B (mode block starts at column 2 always).
    assert ws2.cell(row=3, column=2).value == "hk-equities"
    # Sub-headers row 4: rank | pub | n_obs | rmse | r/s | hit%  → 6 cols, nothing in col 7.
    assert ws2.cell(row=4, column=1).value == "rank"
    assert ws2.cell(row=4, column=2).value == "pub"
    assert ws2.cell(row=4, column=6).value == "hit%"
    assert ws2.cell(row=4, column=7).value is None
    # First data row: publisher_id=5 in column B (under "pub").
    # Row 6 = banner, row 7 = first data row (rank 1).
    assert ws2.cell(row=7, column=1).value == 1
    assert ws2.cell(row=7, column=2).value == 5


def test_write_rankings_sheet_four_modes_uses_24_columns(tmp_path):
    """Regression: us-equities layout is unchanged (24 cols, 5-col blocks + spacers at G/M/S)."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    per_feed = {
        922: {
            "us-equities": {
                "ranked": [_ranked_row(5)],
                "filtered": [_ranked_row(5)],
                "is_fallback": False,
            },
            "us-equities-pre": None,
            "us-equities-post": None,
            "us-equities-overnight": None,
        }
    }
    write_rankings_sheet(
        ws,
        per_feed,
        date="2026-05-19",
        cluster="lazer-prod",
        modes=[
            "us-equities",
            "us-equities-pre",
            "us-equities-post",
            "us-equities-overnight",
        ],
    )
    # Mode block headers at columns 2 (B), 8 (H), 14 (N), 20 (T) — unchanged from current layout.
    assert ws.cell(row=3, column=2).value == "us-equities"
    assert ws.cell(row=3, column=8).value == "us-equities-pre"
    assert ws.cell(row=3, column=14).value == "us-equities-post"
    assert ws.cell(row=3, column=20).value == "us-equities-overnight"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest lazer_dq/tests/test_summarize_feeds.py::test_write_rankings_sheet_one_mode_uses_6_columns -v
```

Expected: FAIL — `write_rankings_sheet()` got unexpected keyword argument `modes`.

- [ ] **Step 3: Parametrize `write_rankings_sheet`**

In `lazer_dq/summarize_feeds.py`, replace `write_rankings_sheet` (lines 190-302) with:

```python
def write_rankings_sheet(
    ws, per_feed_data: dict, date: str, cluster: str, modes: list[str]
) -> None:
    """Populate the 'rankings' worksheet.

    Layout is parametric on len(modes):
      - 1 rank column (A) +
      - N × 5-col mode blocks (pub | n_obs | rmse | r/s | hit%) +
      - (N-1) × 1-col spacers between blocks
      = 6N total columns.

    Examples:
      - 4 modes (us-equities) → 24 cols, blocks at B/H/N/T (unchanged from prior layout).
      - 1 mode  (hk-equities) → 6 cols, single block at B.
    """
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    bold = Font(bold=True)
    bold_lg = Font(bold=True, size=12)
    bold_xl = Font(bold=True, size=14)
    gray = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")
    center = Alignment(horizontal="center")

    n_modes = len(modes)
    total_cols = 6 * n_modes  # 1 rank + 5N blocks + (N-1) spacers = 6N
    # mode_starts[i] is the 1-indexed start column of the i-th mode block.
    # Block 0 starts at column 2 (B). Each subsequent block starts 6 columns later
    # (5 data cols + 1 spacer).
    mode_starts = {mode: 2 + 6 * i for i, mode in enumerate(modes)}
    sub_headers = ["pub", "n_obs", "rmse", "r/s", "hit%"]

    # Row 1: title.
    ws.cell(row=1, column=1, value=f"DQ Summary — {cluster} — {date}").font = bold_xl
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)
    ws.cell(row=1, column=1).alignment = center

    # Row 3: mode-block headers.
    for mode in modes:
        col = mode_starts[mode]
        c = ws.cell(row=3, column=col, value=mode)
        c.font = bold
        c.fill = gray
        c.alignment = center
        ws.merge_cells(start_row=3, start_column=col, end_row=3, end_column=col + 4)

    # Row 4: sub-headers.
    a4 = ws.cell(row=4, column=1, value="rank")
    a4.font = bold
    a4.fill = gray
    for mode in modes:
        start = mode_starts[mode]
        for i, label in enumerate(sub_headers):
            c = ws.cell(row=4, column=start + i, value=label)
            c.font = bold
            c.fill = gray

    # Freeze header rows.
    ws.freeze_panes = "A5"

    # Per-feed sections.
    row = 6
    for feed_id, mode_data in per_feed_data.items():
        # Banner. Force inline-string type so leading '=' is not parsed as a formula.
        banner = ws.cell(row=row, column=1, value=f"=== Feed {feed_id} ===")
        banner.data_type = "s"
        banner.font = bold_lg
        ws.merge_cells(
            start_row=row, start_column=1, end_row=row, end_column=total_cols
        )
        row += 1

        ranked_per_mode = {
            m: (mode_data[m]["ranked"] if mode_data.get(m) else None) for m in modes
        }
        n_rows = max((len(r) for r in ranked_per_mode.values() if r), default=0)
        if n_rows == 0:
            ws.cell(row=row, column=2, value="(no data)")
            row += 2
            continue

        for i in range(n_rows):
            ws.cell(row=row + i, column=1, value=i + 1)
        for mode in modes:
            start = mode_starts[mode]
            ranked = ranked_per_mode[mode]
            if ranked is None:
                ws.cell(row=row, column=start, value="(no data)")
                continue
            for i, r in enumerate(ranked):
                ws.cell(row=row + i, column=start + 0, value=int(r["publisher_id"]))
                ws.cell(row=row + i, column=start + 1, value=int(r["n_observations"]))
                ws.cell(row=row + i, column=start + 2, value=round(float(r["rmse"]), 4))
                ws.cell(
                    row=row + i,
                    column=start + 3,
                    value=round(float(r["rmse_over_spread"]), 4),
                )
                ws.cell(
                    row=row + i,
                    column=start + 4,
                    value=round(float(r["hit_rate_0.1pct"]), 2),
                )
        row += n_rows + 1

    # Column widths.
    for col_idx in range(1, total_cols + 1):
        letter = get_column_letter(col_idx)
        ws.column_dimensions[letter].width = 9
    ws.column_dimensions["A"].width = 6  # rank
```

- [ ] **Step 4: Update `main()` call site to pass `modes`**

Find the `write_rankings_sheet(ws_rank, per_feed_data, args.date, args.cluster)` call (currently line 618). Change to:

```python
    write_rankings_sheet(ws_rank, per_feed_data, args.date, args.cluster, modes=MODE_ORDER)
```

- [ ] **Step 5: Run tests**

```bash
pytest lazer_dq/tests/test_summarize_feeds.py -v
```

Expected: new rankings tests PASS, all existing tests still PASS (the existing integration test exercises the 4-mode layout and verifies column positions).

- [ ] **Step 6: Commit**

```bash
git add lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git commit -m "refactor(lazer_dq): parametrize write_rankings_sheet on mode list"
```

---

## Task 4: Parametrize `write_allowed_sheet` on the mode list + sessions map

**Files:**

- Modify: `lazer_dq/summarize_feeds.py` (`write_allowed_sheet`, lines 313-427)
- Test: `lazer_dq/tests/test_summarize_feeds.py`

- [ ] **Step 1: Write the failing test**

Append to `lazer_dq/tests/test_summarize_feeds.py`:

```python
# ---------- write_allowed_sheet parametric layout ----------

from lazer_dq.summarize_feeds import write_allowed_sheet


def test_write_allowed_sheet_one_mode_emits_two_rows_per_feed(tmp_path):
    """For hk-equities (1 mode): each feed gets 1 aggregate + 1 session row."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    per_feed = {
        884: {
            "hk-equities": {
                "ranked": [_ranked_row(5), _ranked_row(7)],
                "filtered": [_ranked_row(5), _ranked_row(7)],
                "is_fallback": False,
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
    )
    # Row 3: aggregate row for feed 884.
    assert ws.cell(row=3, column=1).value == 884
    assert ws.cell(row=3, column=2).value == "(aggregate)"
    assert "5, 7" in ws.cell(row=3, column=3).value
    # Row 4: REGULAR session row for hk-equities.
    assert ws.cell(row=4, column=1).value == 884
    assert ws.cell(row=4, column=2).value == "REGULAR"
    assert "5, 7" in ws.cell(row=4, column=3).value
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest lazer_dq/tests/test_summarize_feeds.py::test_write_allowed_sheet_one_mode_emits_two_rows_per_feed -v
```

Expected: FAIL — `write_allowed_sheet()` got unexpected keyword argument `modes`.

- [ ] **Step 3: Parametrize `write_allowed_sheet`**

In `lazer_dq/summarize_feeds.py`, replace `write_allowed_sheet` (lines 313-426) with:

```python
def write_allowed_sheet(
    ws,
    per_feed_data: dict,
    skipped_feeds: list[int],
    date: str,
    cluster: str,
    modes: list[str],
    sessions: dict,
) -> None:
    """Populate the 'allowed' worksheet.

    Layout (4 cols, NO merges) is unchanged. What varies is the number of
    session rows per feed: one aggregate row + one row per mode in `modes`,
    plus a blank divider.

    `sessions` maps mode -> after.json session label (e.g. "REGULAR").
    """
    from openpyxl.styles import Font, PatternFill

    bold = Font(bold=True)
    bold_xl = Font(bold=True, size=14)
    gray = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")
    yellow = PatternFill(start_color="FFF4B5", end_color="FFF4B5", fill_type="solid")
    light_gray = PatternFill(
        start_color="EEEEEE", end_color="EEEEEE", fill_type="solid"
    )

    # Row 1: title (single cell, no merge).
    ws.cell(
        row=1, column=1, value=f"Allowed Publishers — {cluster} — {date}"
    ).font = bold_xl

    # Row 2: column headers.
    headers = ["Feed ID", "Session", "allowedPublisherIds", "Notes"]
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=2, column=i, value=h)
        c.font = bold
        c.fill = gray

    ws.freeze_panes = "A3"
    ws.auto_filter.ref = "A2:D2"

    row = 3
    for feed_id, mode_data in per_feed_data.items():
        per_session_arrays: list[list[int] | None] = []
        for mode in modes:
            md = mode_data.get(mode) if mode_data else None
            if md is None:
                per_session_arrays.append(None)
            else:
                ids = sorted({int(r["publisher_id"]) for r in md["filtered"]})
                per_session_arrays.append(ids if ids else None)

        # Aggregate row.
        agg = compute_aggregate(per_session_arrays)
        ws.cell(row=row, column=1, value=feed_id)
        ws.cell(row=row, column=2, value="(aggregate)")
        ws.cell(
            row=row,
            column=3,
            value=_format_allowed_pub_ids(agg) if agg else "(no data)",
        )
        if not agg:
            ws.cell(row=row, column=4, value="all sessions empty").fill = light_gray
        row += 1

        # Per-session rows.
        for mode, ids in zip(modes, per_session_arrays):
            session_label = sessions[mode]
            md = mode_data.get(mode) if mode_data else None
            ws.cell(row=row, column=1, value=feed_id)
            ws.cell(row=row, column=2, value=session_label)
            if md is None:
                ws.cell(row=row, column=3, value="(no data)")
                ws.cell(
                    row=row, column=4, value=f"mode missing for {date}"
                ).fill = light_gray
            elif ids is None:
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

        row += 1  # blank divider between feeds

    # Skipped-feeds footer.
    if skipped_feeds:
        row += 1
        ws.cell(
            row=row, column=1, value="Feeds skipped (no data for any mode):"
        ).font = bold
        for fid in skipped_feeds:
            row += 1
            ws.cell(row=row, column=1, value=fid)

    last_data_row = max(row, 2)
    ws.auto_filter.ref = f"A2:D{last_data_row}"

    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 80
    ws.column_dimensions["D"].width = 32
```

(Changes from the original: function signature gains `modes` and `sessions` params; the two `for mode in MODE_ORDER` loops become `for mode in modes`; `MODE_TO_SESSION[mode]` becomes `sessions[mode]`.)

- [ ] **Step 4: Update `main()` call site**

Find the `write_allowed_sheet(ws_allow, per_feed_data, skipped, args.date, args.cluster)` call (currently line 619). Change to:

```python
    write_allowed_sheet(
        ws_allow,
        per_feed_data,
        skipped,
        args.date,
        args.cluster,
        modes=MODE_ORDER,
        sessions=MODE_TO_SESSION,
    )
```

- [ ] **Step 5: Run tests**

```bash
pytest lazer_dq/tests/test_summarize_feeds.py -v
```

Expected: new test PASSES, all existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git commit -m "refactor(lazer_dq): parametrize write_allowed_sheet on modes+sessions"
```

---

## Task 5: Add `--asset-class` flag and CSV mode validation

This is where the user-facing change lands. After this task, `python -m lazer_dq.summarize_feeds --csv equity_hk_feed_ids.csv --asset-class hk-equities --cluster lazer-prod --date 2026-05-19` works.

**Files:**

- Modify: `lazer_dq/summarize_feeds.py` (top: add helper; `main()`: add flag + validation; pick maps from registry)
- Test: `lazer_dq/tests/test_summarize_feeds.py`

- [ ] **Step 1: Write the failing tests**

Append to `lazer_dq/tests/test_summarize_feeds.py`:

```python
# ---------- validate_csv_modes ----------

from lazer_dq.summarize_feeds import validate_csv_modes


def test_validate_csv_modes_accepts_matching_modes(tmp_path):
    csv = tmp_path / "ok.csv"
    csv.write_text(
        "884,2026-05-19,hk-equities\n"
        "885,2026-05-19,hk-equities\n"
    )
    # Should not raise / not exit. Returns None.
    assert validate_csv_modes(csv, allowed_modes=["hk-equities"]) is None


def test_validate_csv_modes_accepts_empty_third_column(tmp_path):
    """Back-compat: feed-id-only CSVs (no mode column) are still accepted."""
    csv = tmp_path / "legacy.csv"
    csv.write_text("884\n885\n")
    assert validate_csv_modes(csv, allowed_modes=["hk-equities"]) is None


def test_validate_csv_modes_rejects_mismatched_modes(tmp_path, capsys):
    csv = tmp_path / "bad.csv"
    csv.write_text(
        "884,2026-05-19,us-equities\n"
        "885,2026-05-19,us-equities\n"
    )
    with pytest.raises(SystemExit) as exc:
        validate_csv_modes(csv, allowed_modes=["hk-equities"])
    assert exc.value.code != 0
    out = capsys.readouterr().out
    assert "us-equities" in out
    assert "hk-equities" in out


# ---------- main() with --asset-class hk-equities ----------


def test_main_hk_equities_end_to_end(tmp_path, monkeypatch):
    """Full run for a 1-feed hk-equities CSV produces a workbook with the HK layout."""
    reports = tmp_path / "dq_reports"
    _write_stats_csv(
        reports,
        "lazer-prod",
        "hk-equities",
        884,
        "2026-05-19",
        [
            "publisher_id,n_observations,rmse,rmse_over_spread,hit_rate_0.1pct\n",
            "5,5000,0.001,0.5,90.0\n",
            "7,5000,0.001,0.6,92.0\n",
        ],
    )
    csv = tmp_path / "hk.csv"
    csv.write_text("884,2026-05-19,hk-equities\n")
    md = tmp_path / "publishers.md"
    md.write_text("| ID | Name | Active |\n| 0 | Zero.Test | Yes |\n")
    out = tmp_path / "out.xlsx"

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
            "2026-05-19",
            "--reports-dir",
            str(reports),
            "--publishers-md",
            str(md),
            "--asset-class",
            "hk-equities",
            "--output",
            str(out),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert out.exists()

    wb = load_workbook(out)
    rank = wb["rankings"]
    # 6-column layout: mode header at B, no spacer after, nothing at column 7.
    assert rank.cell(row=3, column=2).value == "hk-equities"
    assert rank.cell(row=4, column=7).value is None

    allowed = wb["allowed"]
    # Row 3 = aggregate, Row 4 = REGULAR session, Row 5 = blank.
    assert allowed.cell(row=3, column=2).value == "(aggregate)"
    assert allowed.cell(row=4, column=2).value == "REGULAR"


def test_main_rejects_mode_mismatch(tmp_path, monkeypatch, capsys):
    """--asset-class hk-equities + CSV containing us-equities rows → exit non-zero."""
    csv = tmp_path / "mixed.csv"
    csv.write_text("884,2026-05-19,us-equities\n")
    md = tmp_path / "publishers.md"
    md.write_text("# empty\n")
    reports = tmp_path / "dq_reports"
    (reports / "lazer-prod").mkdir(parents=True)

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
            "2026-05-19",
            "--reports-dir",
            str(reports),
            "--publishers-md",
            str(md),
            "--asset-class",
            "hk-equities",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code != 0
    out = capsys.readouterr().out
    assert "us-equities" in out
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest lazer_dq/tests/test_summarize_feeds.py::test_validate_csv_modes_accepts_matching_modes lazer_dq/tests/test_summarize_feeds.py::test_main_hk_equities_end_to_end -v
```

Expected: FAIL — `validate_csv_modes` not defined; `main()` doesn't recognize `--asset-class`.

- [ ] **Step 3: Add `validate_csv_modes` helper**

In `lazer_dq/summarize_feeds.py`, add this function immediately after `discover_feeds` (so it's defined before `load_stats`):

```python
def validate_csv_modes(csv_path, allowed_modes: list[str]) -> None:
    """Verify every CSV row's column-3 mode is in allowed_modes.

    Rows with empty column 3 (legacy feed-id-only CSVs) are accepted.
    On mismatch, print an explanatory error and sys.exit(1).
    """
    bad: list[tuple[int | str, str]] = []
    allowed_set = set(allowed_modes)
    with open(csv_path, "r") as f:
        reader = csv_mod.reader(f)
        for row in reader:
            if not row or not row[0].strip():
                continue
            if len(row) < 3:
                continue  # legacy feed-id-only row
            mode = row[2].strip()
            if not mode:
                continue
            if mode not in allowed_set:
                bad.append((row[0].strip(), mode))
    if bad:
        sample = ", ".join(f"{fid} ({m})" for fid, m in bad[:5])
        more = f" (and {len(bad) - 5} more)" if len(bad) > 5 else ""
        print(
            f"Error: CSV contains modes not in --asset-class={allowed_modes!r}.\n"
            f"       Allowed modes: {sorted(allowed_set)}\n"
            f"       Mismatched rows: {sample}{more}"
        )
        sys.exit(1)
```

- [ ] **Step 4: Add `--asset-class` flag and wire the registry in `main()`**

In `lazer_dq/summarize_feeds.py`, inside `main()`:

(a) Add the new argparse argument. Insert this immediately after the existing `--output` argument (before the `--max-rmse-over-spread-regular` line, ~line 519):

```python
    parser.add_argument(
        "--asset-class",
        choices=sorted(ASSET_CLASS_CONFIG.keys()),
        default="us-equities",
        help="Asset class to summarize (default: us-equities). Determines which "
        "dq_reports/<cluster>/<mode>/ directories are read and the workbook layout.",
    )
```

(b) After `excluded = load_excluded_publishers(md_path)` and before `feed_ids = discover_feeds(csv_path)` (~line 574), add:

```python
    asset_cfg = ASSET_CLASS_CONFIG[args.asset_class]
    modes = asset_cfg["modes"]
    sessions = asset_cfg["sessions"]

    validate_csv_modes(csv_path, allowed_modes=modes)
```

(c) Replace the `max_ros_map` and `min_hit_map` construction (lines 580-591) with:

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

(d) Update the `_build_per_feed_data` call to pass `modes=modes` (not `modes=MODE_ORDER`):

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

(e) Update the workbook calls:

```python
    write_rankings_sheet(ws_rank, per_feed_data, args.date, args.cluster, modes=modes)
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

(f) Update the final stats print line. Replace:

```python
    print(f"Modes with data: {modes_with_data}/{len(feed_ids) * 4} cells")
```

with:

```python
    print(
        f"Modes with data: {modes_with_data}/{len(feed_ids) * len(modes)} cells"
    )
```

- [ ] **Step 5: Run the full test suite**

```bash
pytest lazer_dq/tests/test_summarize_feeds.py -v
```

Expected: all tests PASS (new + existing).

- [ ] **Step 6: Manual smoke test against real data**

```bash
source venv/bin/activate
python -m lazer_dq.summarize_feeds \
    --csv equity_hk_feed_ids.csv \
    --reports-dir dq_reports \
    --cluster lazer-prod \
    --date 2026-05-19 \
    --asset-class hk-equities \
    --output /tmp/hk_summary.xlsx
```

Expected: exits 0, prints "Summary written to /tmp/hk_summary.xlsx", a non-zero "Feeds with at least one mode" count, and the file exists. Open it (`ls -la /tmp/hk_summary.xlsx`) to confirm size > 5KB.

- [ ] **Step 7: Verify the existing us-equities flow still works**

If you have an existing us-equities CSV handy (e.g. one used previously), run it without `--asset-class` and confirm the output workbook still has the 4-mode, 24-column layout. If not, this is covered by the existing integration tests `test_main_writes_workbook_for_one_feed_one_mode` and `test_main_excluded_publishers_never_appear_in_either_sheet`.

- [ ] **Step 8: Commit**

```bash
git add lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git commit -m "feat(lazer_dq): add --asset-class flag with hk-equities support"
```

---

## Task 6: Documentation

**Files:**

- Modify: `CLAUDE.md` (Scripts table + new gotcha)
- Modify: `lazer_dq/summarize_feeds.py` (module docstring + argparse epilog)

- [ ] **Step 1: Update `summarize_feeds.py` module docstring**

Replace the module docstring at the top of `lazer_dq/summarize_feeds.py` (lines 2-11) with:

```python
"""DQ summary workbook generator — reads dq_reports/, emits one .xlsx.

Two sheets per run:
  rankings — top-N publishers per (feed, mode) by rmse_over_spread, modes side-by-side
  allowed  — paste-ready allowedPublisherIds JSON arrays per feed/session

Per-asset-class layout. Pick the asset class with --asset-class:
  us-equities (default) — 4 modes: regular, pre, post, overnight (24-col layout)
  hk-equities           — 1 mode:  regular (6-col layout)

Adding a new asset class = adding one entry to ASSET_CLASS_CONFIG.

Run:
    python3 -m lazer_dq.summarize_feeds \\
        --csv MV_Mario_3_pre.csv --cluster lazer-prod --date 2026-05-06

    python3 -m lazer_dq.summarize_feeds \\
        --csv equity_hk_feed_ids.csv --asset-class hk-equities \\
        --cluster lazer-prod --date 2026-05-19
"""
```

- [ ] **Step 2: Update the argparse epilog example**

In `main()`, find the `epilog=` block on the `argparse.ArgumentParser` call (around line 491-495). Replace with:

```python
        epilog="""\
Examples:
  # Default (us-equities, 4 modes):
  python3 -m lazer_dq.summarize_feeds \\
      --csv MV_Mario_3_pre.csv --cluster lazer-prod --date 2026-05-06

  # HK equities:
  python3 -m lazer_dq.summarize_feeds \\
      --csv equity_hk_feed_ids.csv --asset-class hk-equities \\
      --cluster lazer-prod --date 2026-05-19
""",
```

- [ ] **Step 3: Add a gotcha to CLAUDE.md**

In `/home/mariobern/integration-benchmarking/CLAUDE.md`, find the "Key Gotchas" section. Append this bullet at the end of the list (immediately before the closing of the section):

```markdown
- **`summarize_feeds` asset class** — `lazer_dq/summarize_feeds.py` defaults to `--asset-class us-equities` (4 modes). For HK equities use `--asset-class hk-equities` (1 mode). Mode set + session labels + default thresholds live in `ASSET_CLASS_CONFIG` at the top of the file; adding a new asset class is a one-entry edit. The CSV's column-3 mode must match the selected asset class or the script exits with a clear error.
```

- [ ] **Step 4: Run pre-commit on the changed files**

```bash
source venv/bin/activate
pre-commit run --files lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py CLAUDE.md
```

Expected: black, prettier, trailing-whitespace, end-of-file-fixer all PASS (or auto-fix and you re-stage).

- [ ] **Step 5: Final test run**

```bash
pytest lazer_dq/tests/test_summarize_feeds.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add lazer_dq/summarize_feeds.py CLAUDE.md
git commit -m "docs(lazer_dq): document --asset-class flag and registry"
```

---

## Self-Review Summary

- **Spec coverage:** registry (Task 1), CLI flag (Task 5), CSV validation (Task 5), parametric rankings layout (Task 3), parametric allowed layout (Task 4), us-equities back-compat (verified in Tasks 1, 3, 5, 6), tests for HK + mismatch (Task 5), docs (Task 6). All spec sections covered.
- **Placeholders:** none — every step has either exact code or an exact command with expected output.
- **Type consistency:** `modes` is `list[str]` everywhere; `sessions` is `dict[str, str]`; `ASSET_CLASS_CONFIG` shape is identical in spec, Task 1 test, and Task 1 implementation.
- **Frequent commits:** 6 commits, one per task.
- **TDD:** every task is Write-test → Run-fail → Implement → Run-pass → Commit.
