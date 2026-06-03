# Per-run `--exclude-publisher` for `summarize_feeds.py` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--exclude-publisher` CLI flag to `summarize_feeds.py` that holds one or more publisher IDs out of the `allowed` sheet (config-facing) while keeping them visible in the `rankings` sheet, with auto next-best backfill via the existing redundancy floor.

**Architecture:** A second, narrower exclusion layer (`manual_exclude: set[int]`) applied **only** on the path to `apply_filter` (the `allowed` sheet), leaving `rank_top_n` (the `rankings` sheet) untouched. Backfill is free: removing a publisher can drop a feed below `--redundancy-floor`, and the existing top-up branch inside `apply_filter` pulls in the next-best. Transparency via a stdout summary line and a note written into the otherwise-empty `allowed`-sheet title row (no row shift).

**Tech Stack:** Python 3, `argparse`, `openpyxl`, `pytest`. All code lives in `lazer_dq/summarize_feeds.py`; tests in `lazer_dq/tests/test_summarize_feeds.py`.

---

## File Structure

- **Modify:** `lazer_dq/summarize_feeds.py`
  - `_build_per_feed_data(...)` — new `manual_exclude` keyword param; strip those IDs before `apply_filter`; count affected cells; return one extra value.
  - `write_allowed_sheet(...)` — new optional `manual_exclude` param; write a title-row note when non-empty.
  - `main()` — new `--exclude-publisher` argument; build the set; thread it into both functions; print a summary line.
- **Modify (tests):** `lazer_dq/tests/test_summarize_feeds.py` — new test cases + update the one existing test that unpacks `_build_per_feed_data`'s return tuple.
- **Modify (docs):** `docs/summarize_feeds.md` — Arguments table row, usage example, Ranking & Filtering note.

### Reference: existing signatures (do not guess — these are current)

```python
def _build_per_feed_data(
    feed_ids, reports_dir, cluster, date, excluded, top_n,
    max_ros_map, min_hit_map, min_obs, floor, ceiling_mult, modes,
):
    # returns (per_feed_data, skipped, topup_rows, zero_passer_rows, modes_with_data)

def write_allowed_sheet(
    ws, per_feed_data, skipped_feeds, date, cluster, modes, sessions,
    ceiling_mult=DEFAULT_TOPUP_CEILING_MULT,
):
    ...
```

Existing `main()` unpacks five values:

```python
(
    per_feed_data,
    skipped,
    topup_rows,
    zero_passer_rows,
    modes_with_data,
) = _build_per_feed_data(...)
```

Test helper already in the test file (reuse, do **not** redefine):

```python
def _stat(publisher_id, ros, hit=80.0, n_obs=10000):
    return {
        "publisher_id": str(publisher_id),
        "rmse_over_spread": str(ros),
        "hit_rate_0.1pct": str(hit),
        "n_observations": str(n_obs),
    }
```

Note on `_stat` rows and `rank_top_n`: the rankings-sheet writer reads `rmse`, `n_observations`, etc., but `rank_top_n` only needs `publisher_id` + `rmse_over_spread`, and `_build_per_feed_data` stores the ranked dicts as-is. For `_build_per_feed_data` unit tests we only assert on `publisher_id`s in `ranked`/`filtered`, so `_stat` rows are sufficient (no `rmse` key needed).

---

## Task 1: `_build_per_feed_data` — manual-exclude filter path + cell counter

**Files:**

- Modify: `lazer_dq/summarize_feeds.py` (`_build_per_feed_data`)
- Modify: `lazer_dq/tests/test_summarize_feeds.py` (new tests + update existing unpack)

- [ ] **Step 1: Write the failing tests**

Add these tests to `lazer_dq/tests/test_summarize_feeds.py` (the `_build_per_feed_data` and `_write_stats_csv` imports/helpers already exist in the file). They write real `stats.csv` files so the function's `load_stats` path runs:

```python
# ---------- _build_per_feed_data with manual_exclude ----------


def test_build_per_feed_data_manual_exclude_keeps_pub_in_ranked_not_filtered(tmp_path):
    """80 stays visible in 'ranked' (rankings) but is removed from 'filtered' (allowed)."""
    reports = tmp_path / "dq_reports"
    _write_stats_csv(
        reports,
        "lazer-prod",
        "hk-equities",
        884,
        "2026-05-19",
        body_rows=[
            "80,5000,0.001,0.2,90.0\n",  # best r/s — would top the allowed list
            "5,5000,0.001,0.5,90.0\n",
            "7,5000,0.001,0.6,90.0\n",
        ],
        header="publisher_id,n_observations,rmse,rmse_over_spread,hit_rate_0.1pct\n",
    )
    (
        per_feed,
        skipped,
        topup_rows,
        zero_passer_rows,
        modes_with_data,
        manual_excluded_cells,
    ) = _build_per_feed_data(
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
        manual_exclude={80},
    )
    md = per_feed[884]["hk-equities"]
    ranked_ids = {r["publisher_id"] for r in md["ranked"]}
    filtered_ids = {r["publisher_id"] for r in md["filtered"]}
    assert "80" in ranked_ids  # still visible in rankings
    assert "80" not in filtered_ids  # removed from allowed
    assert filtered_ids == {"5", "7"}
    assert manual_excluded_cells == 1


def test_build_per_feed_data_manual_exclude_below_floor_backfills_next_best(tmp_path):
    """Removing 80 drops passers below the floor → next-best near-miss is topped up."""
    reports = tmp_path / "dq_reports"
    _write_stats_csv(
        reports,
        "lazer-prod",
        "hk-equities",
        884,
        "2026-05-19",
        body_rows=[
            "80,5000,0.001,0.2,90.0\n",  # passer, but manually excluded
            "5,5000,0.001,0.5,90.0\n",  # passer
            "7,5000,0.002,1.3,90.0\n",  # near-miss (1.0 < r/s <= 2.0)
            "9,5000,0.002,1.7,90.0\n",  # near-miss → backfill substitute
        ],
        header="publisher_id,n_observations,rmse,rmse_over_spread,hit_rate_0.1pct\n",
    )
    (per_feed, _s, _t, _z, _m, cells) = _build_per_feed_data(
        feed_ids=[884],
        reports_dir=reports,
        cluster="lazer-prod",
        date="2026-05-19",
        excluded={0},
        top_n=10,
        max_ros_map={"hk-equities": 1.0},
        min_hit_map={"hk-equities": 80.0},
        min_obs=1000,
        floor=3,
        ceiling_mult=2.0,
        modes=["hk-equities"],
        manual_exclude={80},
    )
    md = per_feed[884]["hk-equities"]
    filtered_ids = {r["publisher_id"] for r in md["filtered"]}
    # 80 gone; passer 5 plus the two near-miss top-ups (7, 9) reach floor of 3.
    assert "80" not in filtered_ids
    assert filtered_ids == {"5", "7", "9"}
    assert md["n_topup"] == 2
    assert cells == 1


def test_build_per_feed_data_manual_exclude_above_floor_just_shrinks(tmp_path):
    """Plenty of passers above the floor → removing 80 just drops it, no substitute added."""
    reports = tmp_path / "dq_reports"
    _write_stats_csv(
        reports,
        "lazer-prod",
        "hk-equities",
        884,
        "2026-05-19",
        body_rows=[
            "80,5000,0.001,0.2,90.0\n",  # passer, excluded
            "5,5000,0.001,0.3,90.0\n",
            "7,5000,0.001,0.4,90.0\n",
            "9,5000,0.001,0.5,90.0\n",
        ],
        header="publisher_id,n_observations,rmse,rmse_over_spread,hit_rate_0.1pct\n",
    )
    (per_feed, _s, _t, _z, _m, cells) = _build_per_feed_data(
        feed_ids=[884],
        reports_dir=reports,
        cluster="lazer-prod",
        date="2026-05-19",
        excluded={0},
        top_n=10,
        max_ros_map={"hk-equities": 1.0},
        min_hit_map={"hk-equities": 80.0},
        min_obs=1000,
        floor=2,  # 3 remaining passers comfortably exceed the floor
        ceiling_mult=2.0,
        modes=["hk-equities"],
        manual_exclude={80},
    )
    md = per_feed[884]["hk-equities"]
    filtered_ids = {r["publisher_id"] for r in md["filtered"]}
    assert filtered_ids == {"5", "7", "9"}  # 80 dropped, no extra pulled in
    assert md["n_topup"] == 0
    assert cells == 1


def test_build_per_feed_data_manual_exclude_default_is_noop(tmp_path):
    """No manual_exclude arg → 80 stays in both ranked and filtered; counter is 0."""
    reports = tmp_path / "dq_reports"
    _write_stats_csv(
        reports,
        "lazer-prod",
        "hk-equities",
        884,
        "2026-05-19",
        body_rows=["80,5000,0.001,0.2,90.0\n", "5,5000,0.001,0.5,90.0\n"],
        header="publisher_id,n_observations,rmse,rmse_over_spread,hit_rate_0.1pct\n",
    )
    (per_feed, _s, _t, _z, _m, cells) = _build_per_feed_data(
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
    md = per_feed[884]["hk-equities"]
    assert "80" in {r["publisher_id"] for r in md["filtered"]}
    assert cells == 0
```

Also update the **existing** test `test_build_per_feed_data_honors_modes_parameter` to unpack six values (it currently unpacks five). Change its unpacking block to:

```python
    (
        per_feed,
        skipped,
        topup_rows,
        zero_passer_rows,
        modes_with_data,
        manual_excluded_cells,
    ) = _build_per_feed_data(
```

(and add `assert manual_excluded_cells == 0` after the existing assertions in that test).

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py -k "manual_exclude or honors_modes" -v`
Expected: the four new `manual_exclude` tests FAIL (`ValueError: not enough values to unpack (expected 6, got 5)` / `TypeError: ... unexpected keyword argument 'manual_exclude'`), and `honors_modes` FAILS on the 6-tuple unpack.

- [ ] **Step 3: Implement the change in `_build_per_feed_data`**

In `lazer_dq/summarize_feeds.py`, change the signature to add the keyword param (default `None`) after `modes`:

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

Immediately after the docstring, normalize the param and add the counter alongside the existing counters:

```python
    manual_exclude = manual_exclude or set()
    per_feed_data: dict = {}
    skipped: list[int] = []
    topup_rows = 0
    zero_passer_rows = 0
    modes_with_data = 0
    manual_excluded_cells = 0
```

Inside the per-mode loop, the `ranked = rank_top_n(kept, ...)` line stays unchanged (80 still visible). Replace the single `apply_filter(kept, ...)` call with a manual-exclude strip first:

```python
            ranked = rank_top_n(kept, n=top_n, excluded=set())  # already excluded
            # Manual exclusion applies to the allowed sheet only: strip the IDs
            # from the filter input but leave `ranked` untouched.
            filter_input = [
                r for r in kept if int(r["publisher_id"]) not in manual_exclude
            ]
            if len(filter_input) != len(kept):
                manual_excluded_cells += 1
            selected, n_passed, n_topup = apply_filter(
                filter_input,
                max_ros_map[mode],
                min_hit_map[mode],
                min_obs,
                floor,
                ceiling_mult,
            )
```

(`int(r["publisher_id"])` is safe here: every row in `kept` already passed an `int(...)` parse in the kept-building loop above.)

Finally, add the counter to the return tuple:

```python
    return (
        per_feed_data,
        skipped,
        topup_rows,
        zero_passer_rows,
        modes_with_data,
        manual_excluded_cells,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py -k "manual_exclude or honors_modes" -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git commit -m "feat(summarize-feeds): manual-exclude filter path in _build_per_feed_data

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `write_allowed_sheet` — title-row exclusion note

**Files:**

- Modify: `lazer_dq/summarize_feeds.py` (`write_allowed_sheet`)
- Modify: `lazer_dq/tests/test_summarize_feeds.py` (new tests)

- [ ] **Step 1: Write the failing tests**

Add to `lazer_dq/tests/test_summarize_feeds.py` (the `write_allowed_sheet` and `_ranked_row` imports/helpers already exist):

```python
def test_write_allowed_sheet_writes_manual_exclude_note_in_title_row(tmp_path):
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
        manual_exclude={80, 55},
    )
    # Note lives in the title row (row 1), column 3 — no row shift.
    assert ws.cell(row=1, column=3).value == "Manually excluded from allowed: 55, 80"
    # Layout below the title is unchanged: headers at row 2, data from row 3.
    assert ws.cell(row=2, column=1).value == "Feed ID"
    assert ws.cell(row=3, column=1).value == 884
    assert ws.cell(row=3, column=2).value == "(aggregate)"


def test_write_allowed_sheet_no_note_when_manual_exclude_empty(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    per_feed = {
        884: {
            "hk-equities": {
                "ranked": [_ranked_row(5)],
                "filtered": [_ranked_row(5)],
                "n_passed": 1,
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
    assert ws.cell(row=1, column=3).value is None  # no note
    assert ws.cell(row=2, column=1).value == "Feed ID"
    assert ws.cell(row=3, column=1).value == 884
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py -k "manual_exclude_note or no_note_when_manual" -v`
Expected: `writes_manual_exclude_note...` FAILS (`TypeError: ... unexpected keyword argument 'manual_exclude'`). `no_note_when_manual...` may pass already (no note expected) — that's fine; it guards against regressions once the param exists.

- [ ] **Step 3: Implement the note**

In `write_allowed_sheet`, add the param to the signature (after `ceiling_mult`):

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
    manual_exclude=None,
) -> None:
```

Immediately after the existing `# Row 1: title (single cell, no merge).` block that sets cell `(1, 1)`, add:

```python
    # Optional note in the otherwise-empty title row (no row shift): records
    # which publishers were held out of the allowed lists for this run.
    manual_exclude = manual_exclude or set()
    if manual_exclude:
        note = "Manually excluded from allowed: " + ", ".join(
            str(p) for p in sorted(manual_exclude)
        )
        ws.cell(row=1, column=3, value=note).font = bold
```

(`bold` is already defined a few lines above in this function.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py -k "manual_exclude_note or no_note_when_manual" -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git commit -m "feat(summarize-feeds): title-row note for manually-excluded publishers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `main()` — `--exclude-publisher` flag, wiring, stdout summary

**Files:**

- Modify: `lazer_dq/summarize_feeds.py` (`main`)
- Modify: `lazer_dq/tests/test_summarize_feeds.py` (end-to-end test)

- [ ] **Step 1: Write the failing test**

Add to `lazer_dq/tests/test_summarize_feeds.py` (imports `sys`, `main`, `load_workbook`, `_write_stats_csv` already present):

```python
def test_main_exclude_publisher_end_to_end(tmp_path, monkeypatch, capsys):
    """--exclude-publisher 80: 80 visible in rankings, absent from allowed, stdout reports it."""
    reports = tmp_path / "dq_reports"
    _write_stats_csv(
        reports,
        "lazer-prod",
        "hk-equities",
        884,
        "2026-05-19",
        body_rows=[
            "80,5000,0.001,0.2,90.0\n",  # best r/s — would lead allowed if not excluded
            "5,5000,0.001,0.5,90.0\n",
            "7,5000,0.001,0.6,90.0\n",
        ],
        header="publisher_id,n_observations,rmse,rmse_over_spread,hit_rate_0.1pct\n",
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
            "--exclude-publisher",
            "80",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0

    captured = capsys.readouterr().out
    assert "Manually excluded from allowed: [80]" in captured
    assert "1 feed/session cells" in captured

    wb = load_workbook(out, data_only=True)

    # rankings: 80 still present as a publisher_id.
    rank = wb["rankings"]
    rankings_pub_ids = set()
    for r in range(1, 30):
        for c in range(1, 7):
            v = rank.cell(r, c).value
            if isinstance(v, int):
                rankings_pub_ids.add(v)
    assert 80 in rankings_pub_ids

    # allowed: the REGULAR JSON (row 4, col 3) excludes 80, includes the substitutes.
    allowed = wb["allowed"]
    assert allowed.cell(row=1, column=3).value == "Manually excluded from allowed: 80"
    json_cell = allowed.cell(row=4, column=3).value
    assert "80" not in json_cell
    assert "5, 7" in json_cell
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py::test_main_exclude_publisher_end_to_end -v`
Expected: FAIL — `argparse` errors on the unknown `--exclude-publisher` flag (`SystemExit` code `2`), so the `exc.value.code == 0` assertion fails.

- [ ] **Step 3: Implement the flag and wiring in `main()`**

In `lazer_dq/summarize_feeds.py`, add the argument near the other ranking knobs (e.g. right after the `--topup-ceiling-mult` argument):

```python
    parser.add_argument(
        "--exclude-publisher",
        nargs="+",
        type=int,
        default=None,
        metavar="PUB_ID",
        help="Publisher ID(s) to hold out of the 'allowed' sheet for this run "
        "only. They remain visible in 'rankings'. The redundancy floor "
        "auto-backfills the next-best publisher where needed.",
    )
```

After `args = parser.parse_args()` (and alongside the other derived values, e.g. just before the `_build_per_feed_data` call), build the set:

```python
    manual_exclude = set(args.exclude_publisher or [])
```

Update the `_build_per_feed_data` call to pass it and unpack the sixth return value:

```python
    (
        per_feed_data,
        skipped,
        topup_rows,
        zero_passer_rows,
        modes_with_data,
        manual_excluded_cells,
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

Update the `write_allowed_sheet` call to pass the set:

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
        manual_exclude=manual_exclude,
    )
```

In the stdout summary block near the end of `main()` (after the existing `print(f"Rows with 0 passers: ...")` line, before `sys.exit(0)`), add:

```python
    if manual_exclude:
        print(
            f"Manually excluded from allowed: {sorted(manual_exclude)} → "
            f"applied to {manual_excluded_cells} feed/session cells"
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py::test_main_exclude_publisher_end_to_end -v`
Expected: PASS.

- [ ] **Step 5: Run the full test module to confirm no regressions**

Run: `python3 -m pytest lazer_dq/tests/test_summarize_feeds.py -v`
Expected: all PASS (including the pre-existing tests, which exercise the default no-flag path unchanged).

- [ ] **Step 6: Commit**

```bash
git add lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py
git commit -m "feat(summarize-feeds): add --exclude-publisher CLI flag

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Documentation

**Files:**

- Modify: `docs/summarize_feeds.md`

- [ ] **Step 1: Add the flag to the Arguments table**

In `docs/summarize_feeds.md`, add this row to the Arguments table (after the `--topup-ceiling-mult` row):

```markdown
| `--exclude-publisher` | Publisher ID(s) to hold out of the `allowed` sheet only (still shown in `rankings`); floor auto-backfills the next-best | none (off) |
```

- [ ] **Step 2: Add a usage example**

Under the `## Usage` section, add a new example block after the "Override ranking knobs" example:

````markdown
```bash
# Temporarily hold a jittery publisher out of the allowed lists (kept visible in rankings)
python -m lazer_dq.summarize_feeds \
    --csv feeds.csv --cluster lazer-prod --date 2026-05-06 \
    --exclude-publisher 80
```
````

- [ ] **Step 3: Add a Ranking & Filtering note**

At the end of the `## Ranking & Filtering` section, add:

```markdown
### Per-run publisher exclusion (`--exclude-publisher`)

`--exclude-publisher 80 [55 ...]` holds the given publisher IDs out of the
`allowed` sheet for this run only. The excluded publishers **remain visible in
the `rankings` sheet** (so their metrics can still be inspected), but they are
dropped before the threshold/floor filter that builds the `allowed` lists.
Because removal can push a feed/session below `--redundancy-floor`, the
existing top-up logic automatically backfills the next-best eligible publisher
("auto next-best" substitution) — feeds already above the floor simply lose the
excluded publisher with no replacement. When the flag is used, the `allowed`
sheet title row notes which publishers were excluded, and the run summary
prints how many feed/session cells were affected. This is a temporary,
per-run override; it does not touch `publishers.md`.
```

- [ ] **Step 4: Verify docs render and commit**

Run: `pre-commit run --files docs/summarize_feeds.md`
Expected: prettier / trailing-whitespace / end-of-file hooks all Passed (prettier may reformat the table — accept its formatting).

```bash
git add docs/summarize_feeds.md
git commit -m "docs(summarize-feeds): document --exclude-publisher flag

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full lazer_dq test suite**

Run: `python3 -m pytest lazer_dq/tests/ -v`
Expected: all PASS.

- [ ] **Step 2: Run pre-commit across all touched files**

Run: `pre-commit run --files lazer_dq/summarize_feeds.py lazer_dq/tests/test_summarize_feeds.py docs/summarize_feeds.md docs/superpowers/specs/2026-06-03-summarize-feeds-exclude-publisher-design.md docs/superpowers/plans/2026-06-03-summarize-feeds-exclude-publisher.md`
Expected: black, prettier, trailing-whitespace, end-of-file hooks all Passed (commit any auto-fixes the hooks make).

- [ ] **Step 3: Manual smoke check of the help text**

Run: `python3 -m lazer_dq.summarize_feeds --help`
Expected: `--exclude-publisher PUB_ID [PUB_ID ...]` appears in the help output with the description.

---

## Self-Review Notes

- **Spec coverage:** two-layer exclusion (Task 1), rankings-untouched / allowed-removed (Task 1 tests), floor-based auto next-best backfill (Task 1 below-floor + above-floor tests), CLI flag with multiple IDs (Task 3), stdout summary line + title-row note (Tasks 2 & 3), no-op parity (Task 1 default test + full-suite regression in Task 3 Step 5), docs (Task 4). All spec sections map to a task.
- **Return-arity change:** `_build_per_feed_data` now returns six values; the one existing test that unpacks it is updated in Task 1 Step 1, and `main()` is updated in Task 3 Step 3. No other callers exist.
- **No row shift:** the title-row note keeps the `allowed` sheet's row-2 headers / row-3 data layout identical, so all pre-existing `allowed`-sheet position assertions remain valid.

```

```
