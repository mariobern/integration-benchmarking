# Design: `summarize_feeds.py` — DQ Summary Workbook for Bulk Feed Runs

**Date:** 2026-05-07
**Author:** mario@pyth.network
**Status:** Approved (pending implementation)

## Goal

Generate a single Excel workbook that summarizes the per-publisher DQ outputs of `evaluate_feeds_bulk.py` across the four US-equity sessions (regular / pre / post / overnight), so the user can:

1. Skim the top-10 publishers per (feed, mode) on one screen, side-by-side across modes.
2. Copy paste-ready `allowedPublisherIds` JSON arrays into `after.json` for governance changes.

Replaces the current workflow of opening 4× `dq_reports/.../stats.csv` files per feed.

## Non-Goals

- Re-running the engine. This script consumes existing `stats.csv` outputs only.
- Multi-date aggregation. One date per run; users invoke multiple times for trend analysis.
- Pretty plots. The runner already produces `plots.html` per (feed, mode, date).
- Modifying `after.json`. Output is paste-ready JSON; the user does the paste.

## Architecture

**Module:** `pythresearch/data_quality/lazer/summarize_feeds.py`, sibling to `evaluate_feeds_bulk.py`.

**Function decomposition** (one purpose each, ~40-80 lines):

| Function | Purpose |
|---|---|
| `load_excluded_publishers(publishers_md_path) -> set[int]` | Parse `publishers.md` markdown table, return IDs whose `Name` ends with `.Test`, plus `0` (always). |
| `discover_feeds(csv_path) -> list[int]` | Distinct feed_ids from CSV column 1, in the order first seen. |
| `load_stats(reports_dir, cluster, mode, feed_id, date) -> list[dict] \| None` | Read `dq_reports/<cluster>/<mode>/<feed_id>/<date>/stats.csv`. Return `None` if missing. |
| `rank_top_n(stats, n, excluded) -> list[dict]` | Drop excluded publisher_ids, sort ascending by `rmse_over_spread`, take top `n`. |
| `apply_filter(stats, max_ros, min_hit, min_obs, fallback_n) -> tuple[list[dict], bool]` | Apply per-mode thresholds. Return `(passers, False)` if any pass, else `(top_fallback_n_of_input, True)`. Empty input → `([], False)`. |
| `compute_aggregate(per_session_arrays) -> list[int]` | Sorted union of arrays. Empty if all empty. |
| `write_rankings_sheet(ws, per_feed_data, date, cluster)` | Populate sheet 1 (multi-feed, modes side-by-side). |
| `write_allowed_sheet(ws, per_feed_data, skipped_feeds, date, cluster)` | Populate sheet 2 (tabular, paste-ready). |
| `main()` | argparse → discover → for each feed gather mode data → write workbook → stdout summary. |

**Mode → session label mapping:**

| CLI mode | after.json session |
|---|---|
| `us-equities` | `REGULAR` |
| `us-equities-pre` | `PRE_MARKET` |
| `us-equities-post` | `POST_MARKET` |
| `us-equities-overnight` | `OVER_NIGHT` |

## CLI

```
python3 -m pythresearch.data_quality.lazer.summarize_feeds \
    --csv MV_Mario_3_pre.csv \
    --cluster lazer-prod \
    --date 2026-05-06 \
    [--reports-dir dq_reports] \
    [--publishers-md publishers.md] \
    [--output dq_summary_lazer-prod_2026-05-06.xlsx] \
    [--max-rmse-over-spread-regular 1.0] \
    [--min-hit-rate-regular 80] \
    [--max-rmse-over-spread-pre 2.0] \
    [--min-hit-rate-pre 50] \
    [--max-rmse-over-spread-post 2.0] \
    [--min-hit-rate-post 50] \
    [--max-rmse-over-spread-overnight 3.0] \
    [--min-hit-rate-overnight 25] \
    [--min-n-observations 1000] \
    [--top-n 10] \
    [--fallback-top 3]
```

**Required:** `--csv`, `--cluster`, `--date`.
**All other flags optional with the defaults shown above.**

The CSV's `mode` and `date` columns are ignored for selection — column 1 (feed_id) is the only thing read. The script independently probes all 4 modes per feed using `--date`.

## Data Flow

```
CSV (MV_Mario_3_pre.csv)
  │  column 1 → distinct feed_ids
  ▼
For each feed_id:
  For each mode in [us-equities, us-equities-pre, us-equities-post, us-equities-overnight]:
    path = <reports_dir>/<cluster>/<mode>/<feed_id>/<date>/stats.csv
    if not exists:
      record (mode → None)   # rendered as "(no data)" downstream
      continue
    rows = csv.DictReader(path)
    rows = [r for r in rows if int(r['publisher_id']) not in excluded]
    ranked = sorted(rows, key=lambda r: float(r['rmse_over_spread']))[:top_n]
    filtered, is_fallback = apply_filter(rows, max_ros[mode], min_hit[mode], min_obs, fallback_top)
    record (mode → {'ranked': ranked, 'filtered': filtered, 'is_fallback': is_fallback})

  if all 4 modes recorded as None for this feed:
    skipped_feeds.append(feed_id)

per_feed_data[feed_id] = { mode: { 'ranked': [...], 'filtered': [...], 'is_fallback': bool } | None }

Workbook (1 file):
  sheet "rankings" — all feeds stacked, modes side-by-side (top-N from `ranked`)
  sheet "allowed"  — tabular, paste-ready (publisher_ids from `filtered`)
                   — footer block lists skipped_feeds (if any)
```

## Filtering Rules

**Per-mode thresholds (defaults; CLI flags override):**

| Mode | `rmse_over_spread ≤` | `hit_rate_0.1pct ≥` |
|---|---|---|
| `us-equities` (regular) | 1.0 | 80% |
| `us-equities-pre` | 2.0 | 50% |
| `us-equities-post` | 2.0 | 50% |
| `us-equities-overnight` | 3.0 | 25% |

**Always-applied:** `n_observations ≥ 1000` (single global flag, not per-mode).

**Excluded publishers:** parsed dynamically from `publishers.md` at startup. Set = `{0} ∪ {ids whose Name ends with ".Test"}`. Excluded *before* ranking, so they appear in neither sheet.

**Fallback:** if zero publishers pass thresholds for a (feed, mode) cell but the input had at least 1 publisher after exclusions, the `allowed` sheet uses the top-`fallback-top` (default 3) by `rmse_over_spread` and flags the row `FALLBACK: 0 passed filter` in `Notes`. The `rankings` sheet always shows the unfiltered top-`top-n`.

**`spread` clarification:** in `rmse_over_spread`, "spread" = `ask_price - bid_price` from the benchmark (Refinitiv) data, averaged over the time window per publisher. So `rmse_over_spread = 1.0` means the publisher's typical price error equals one full bid-ask spread. Scale-free, so thresholds transfer across feeds with different price scales. (Source: `evaluate_feed_standalone.py:152, 174, 182`.)

## Output Workbook

**Filename:** `dq_summary_<cluster>_<date>.xlsx`. Default location: current working directory. Overwrite without prompting.

### Sheet 1: `rankings`

All feeds stacked vertically. Per feed: a header row, a column-header row, top-`top-n` ranking rows × 4 mode blocks side-by-side, blank divider row.

| col | A | B–F | G | H–L | M | N–R | S | T–X |
|---|---|---|---|---|---|---|---|---|
| | rank | us-equities (pub, n_obs, rmse, r/s, hit%) | ⎵ | us-equities-pre … | ⎵ | us-equities-post … | ⎵ | us-equities-overnight … |

**Formatting (openpyxl):**
- Workbook title in row 1 (merged across A:X), bold, font size 14.
- Per-feed banner `=== Feed N ===` (merged across A:X), bold, font size 12.
- Column headers: bold, light gray fill, frozen pane below.
- Numeric cells: `rmse` and `r/s` formatted to 4 decimals; `hit%` to 2 decimals + `%`.
- Modes with no data: render `(no data)` once in the publisher_id cell of rank-1, leave subsequent rank rows blank for that block.

### Sheet 2: `allowed`

Tabular, no merges, paste-friendly.

```
A1: Allowed Publishers — lazer-prod — 2026-05-06    (cell A1 only, bold, no merge)
A2: Feed ID  | Session     | allowedPublisherIds          | Notes      (bold, light gray)
A3: 1021     | (aggregate) | [11, 20, 22, 35, 41, 42, 65] |
A4: 1021     | REGULAR     | [42, 45, 22, 65, 12, 80]     |
A5: 1021     | PRE_MARKET  | (no data)                    | mode missing for 2026-05-06
A6: 1021     | POST_MARKET | [11, 35, 20]                 | FALLBACK: 0 passed filter
A7: 1021     | OVER_NIGHT  | [20, 32]                     |
A8: (blank divider)
A9: 1060     | (aggregate) | [12, 19, 22, 45]             |
...
```

**Column rules:**

| Col | Content |
|---|---|
| A — Feed ID | Numeric. Repeated on every row of a feed's group (no merging). |
| B — Session | `(aggregate)` first, then `REGULAR`, `PRE_MARKET`, `POST_MARKET`, `OVER_NIGHT` in that order. |
| C — allowedPublisherIds | Pure JSON array text, e.g. `[11, 35, 20]`. Sorted ascending. For "mode missing", value is the literal string `(no data)`. This is the cell to copy. |
| D — Notes | Free text. `FALLBACK: 0 passed filter` for fallback rows; `mode missing for <date>` for `(no data)` rows; empty otherwise. |

**Aggregate semantics:** sorted union of the per-session arrays we actually emit (after exclusions and fallbacks). If every session for a feed is `(no data)`, aggregate is `(no data)`. JSON arrays sorted ascending so output is stable across runs (diff-friendly).

**Cell coloring (openpyxl):**
- Light yellow fill on column D for `FALLBACK` rows.
- Light gray fill on column D for `(no data)` rows.
- Never affects copy-paste of column C.

**Sheet behavior:**
- Row 2 frozen so column headers stay visible while scrolling.
- Excel auto-filter enabled on row 2 — lets the user filter by session, by feed, or hide `(no data)` rows.
- No merged cells anywhere on this sheet.

**Skipped-feeds footer:** if any feeds in `--csv` had zero data across all 4 modes, append after the last data row:

```
A_last+2: "Feeds skipped (no data for any mode):"   (bold)
A_last+3: 1234   (column A only)
A_last+4: 5678
```

If zero feeds were skipped, the footer is omitted.

## Error Handling

**Hard errors (exit 1):**
- `--csv` file missing.
- `publishers.md` missing (we need it to build the exclusion set; refusing to run is safer than letting `.Test` publishers leak through).
- `dq_reports/<cluster>/` missing entirely.
- After processing, no feed produced any data (likely user error — wrong date or cluster).

**Soft errors (warn-and-continue, exit 0 if any feed had data):**
- Individual feed/mode `stats.csv` missing → render as `(no data)` cell.
- CSV row malformed (empty, fewer columns than required, non-numeric feed_id) → skip with one-line warning.
- `stats.csv` row with non-numeric `rmse_over_spread` / `hit_rate_0.1pct` / `n_observations` → skip that publisher with warning.
- `publishers.md` malformed table row → skip with warning.

**Logical edge cases:**
- All publishers excluded for a mode → treat as `(no data)`.
- Filter returns zero **and** ranked list empty after exclusions → `(no data)` (no fallback to invent from nothing).
- Filter returns zero with `< fallback_top` publishers in input → fallback to whatever exists (1 or 2), still flagged `FALLBACK`.
- Aggregate union empty across all sessions for a feed → aggregate is `(no data)`.

**Output file already exists** → overwrite without prompting.

## Stdout Summary

After workbook write, print:

```
Summary written to dq_summary_lazer-prod_2026-05-06.xlsx
Feeds in CSV: 35
Feeds with at least one mode: 32
Feeds skipped (no data anywhere): 3 → [1234, 5678, 9012]
Modes with data: 96/128 cells
Excluded publishers: 0 + 24 .Test (sample: 23, 25, 27, ...)
Fallbacks triggered: 4 cells
Skipped malformed rows: 0
```

## Dependencies

- **New:** `openpyxl` (add to `requirements.in`, regenerate `requirements.txt` via `pip-compile`).
- **Existing (unused for this script):** `pandas` is in the env but not used; we work directly with `csv.DictReader` and openpyxl primitives. Keeps the script independent of pandas' Excel quirks.
- **Stdlib only otherwise:** `argparse`, `csv`, `json`, `pathlib`, `re` (for `publishers.md` parsing), `sys`.

## Testing

Tests at `pythresearch/data_quality/lazer/tests/test_summarize_feeds.py`. Pytest, ≥ 80% coverage.

**Unit tests** (pure functions):

1. `test_load_excluded_publishers_extracts_dot_test_and_zero` — fixture markdown returns expected set.
2. `test_load_excluded_publishers_handles_malformed_row` — bad row skipped, valid rows parsed.
3. `test_rank_top_n_sorts_ascending_by_rmse_over_spread` — ordering correct.
4. `test_rank_top_n_excludes_excluded_publishers` — excluded IDs absent from output.
5. `test_apply_filter_returns_passers_when_present` — passers returned, `fallback=False`.
6. `test_apply_filter_returns_fallback_when_zero_pass` — top-3 returned, `fallback=True`.
7. `test_apply_filter_returns_partial_when_under_fallback_size` — 2-publisher input, returns 2, `fallback=True`.
8. `test_apply_filter_returns_empty_when_input_empty` — empty input, empty output, no fallback.
9. `test_apply_filter_uses_per_mode_thresholds` — same input + different thresholds → different counts.
10. `test_compute_aggregate_is_sorted_union_of_per_session_arrays` — dedup, sort.
11. `test_compute_aggregate_empty_when_all_sessions_empty` — empty in, empty out.
12. `test_discover_feeds_returns_distinct_feed_ids_from_csv` — duplicates collapsed, order preserved.
13. `test_discover_feeds_skips_malformed_rows` — bad rows skipped, warning emitted.

**Integration tests** (`tmp_path`):

14. `test_load_stats_returns_none_for_missing_file`.
15. `test_load_stats_parses_real_csv_format` — uses fixture mimicking the real schema.
16. `test_main_writes_workbook_for_one_feed_one_mode` — happy path: one mode populated, three `(no data)`. Open with openpyxl, assert sheet existence + key cell values.
17. `test_main_skipped_feeds_section_lists_zero_data_feeds` — 2 feeds, only 1 has data; assert workbook footer + stdout summary.
18. `test_main_no_data_anywhere_exits_nonzero` — empty `dq_reports`, `sys.exit(1)`.
19. `test_main_excluded_publishers_never_appear_in_either_sheet` — `.Test` publisher with stellar `rmse_over_spread` not present.

**Fixtures** (reused):
- `tmp_publishers_md` — minimal markdown table with one `.Test`, one `.Production`.
- `tmp_dq_reports_tree(tmp_path)` — builder helper creating the full `dq_reports/<cluster>/<mode>/<feed>/<date>/stats.csv` tree with parameterized rows.
- `tmp_csv` — small CSV mimicking `MV_Mario_*.csv`.

**Not tested:** exact openpyxl cell formatting (colors, fonts, freezes); argparse help text.

**TDD order:** unit tests 1–13 in order, then integration 16, then unit edge-cases 4/7/11, then integration 17–19.

**Run:**

```bash
pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v \
    --cov=pythresearch.data_quality.lazer.summarize_feeds \
    --cov-report=term-missing
```

## Open Items (for follow-up, not blocking)

- **`pass_fail` column in `stats.csv` is unhelpful** — every publisher across every observed run is `fail`, including ones with `rmse_over_spread = 0.018` and `hit_rate = 100%`. Worth opening a separate issue against `evaluate_feed_standalone.py` to either fix the criterion or remove the column. Not blocking this script (we ignore `pass_fail`).
- **`evaluate_feed_standalone.py:96` omits `us-equities-overnight`** from its secondary EST filter, so overnight stats reflect only the wrapper window. Documented in the prior conversation; not blocking this script.

## Spec Self-Review

- [x] **Placeholders:** none. All thresholds, filenames, and column layouts specified concretely.
- [x] **Internal consistency:** mode → session mapping referenced consistently across CLI, data flow, and `allowed` sheet sections. Aggregate semantics consistent in Filtering Rules and Output Workbook sections.
- [x] **Scope:** single script, one workbook, one date — fits one implementation plan.
- [x] **Ambiguity:** `(aggregate)` literal vs aggregate-as-derived-data clarified (literal string in column B, computed value in column C). Fallback behavior with `< fallback_top` inputs explicitly stated.
