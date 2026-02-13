# Plan: Multi-Date Support for Benchmark Scripts

## Context

All three benchmark-related scripts (`publisher_feeds.py`, `quick_benchmark.py`, `publisher_benchmark.py`) currently operate on a single date per evaluation. The user wants to add CLI flags for specifying multiple dates — either as an explicit list (`--date d1 d2 d3`) or a range (`--start-date`/`--end-date`). This enables multi-day trend analysis, backfill processing, and weekly reports without manually re-running for each date.

**Implementation order**: easiest first — `publisher_feeds.py` → `quick_benchmark.py` → `publisher_benchmark.py`.

**Design decisions**:
- Support both `--date` (explicit list, `nargs="+"`) and `--start-date`/`--end-date` (range), mutually exclusive
- For `publisher_benchmark.py`, date flags **override** the CSV date column (CSV provides feed_id+mode only)
- Backward compatible: single date still works identically

---

## Phase 0: Shared Date Utility

**New file**: `date_utils.py`

```python
def expand_date_args(
    date_list: list[str] | None,
    start_date: str | None,
    end_date: str | None,
) -> list[str]:
    """Resolve --date list or --start-date/--end-date range into sorted YYYY-MM-DD list."""

def validate_date_args(args) -> None:
    """Validate mutual exclusivity of --date vs --start-date/--end-date."""
```

- Validates mutual exclusivity, date parsing, start <= end
- Returns sorted, deduplicated `list[str]`
- Used by all three scripts

---

## Phase 1: publisher_feeds.py (Simplest)

**Why easiest**: Only generates a CSV feed list — no evaluations, no complex summary stats.

### CLI Changes

Add to argparser (lines 295-352):
```
--date         nargs="+"   Explicit date(s). Overrides --date-offset.
--start-date   str         Range start (inclusive). Requires --end-date. Overrides --date-offset.
--end-date     str         Range end (inclusive). Requires --start-date. Overrides --date-offset.
```

Validation: `--date` and `--start-date`/`--end-date` are mutually exclusive. Both override `--date-offset`.

### Core Logic Change (main(), lines 368-397)

```python
# After querying feeds (once, for discovery):
feeds = get_publisher_feeds(client, ...)

# If explicit dates provided, expand: one row per (feed, date)
if dates:
    feeds = [
        FeedInfo(price_id=f.price_id, date=d, asset_class=f.asset_class)
        for f in feeds for d in dates
    ]
```

Feed discovery still uses `--date-offset` / `--time-window` to find currently active feeds. The date flags only control what dates appear in the output CSV rows.

### Output Changes

CSV format unchanged: `price_id,date,asset_class` (no header). Multi-date produces multiple rows per feed:
```
327,2026-02-10,fx
327,2026-02-11,fx
1163,2026-02-10,us-equities
1163,2026-02-11,us-equities
```

Console summary adds: unique feed count, date range, total rows.

### Files Modified
- `date_utils.py` — new (~50 lines)
- `publisher_feeds.py` — ~30 lines changed

---

## Phase 2: quick_benchmark.py (Medium)

### CLI Changes (lines 1849-1928)

- Change existing `--date` from single string to `nargs="+"` (backward compatible for single value)
- Add `--start-date` / `--end-date` for range (single-feed mode only)
- CSV mode already handles per-row dates — no new flags needed there

### Core Logic Change

`evaluate_feed_two_queries()` stays unchanged (single date). The change is in `main()` (lines 2002-2026):

**Single-feed mode**: Loop over resolved dates, collect results:
```python
dates = expand_date_args(args.date, args.start_date, args.end_date)
results = []
for d in dates:
    result = evaluate_feed_two_queries(..., d, ...)
    results.append(result)
```

With `--workers > 1`, parallelize via ThreadPoolExecutor (same pattern as CSV mode).

**CSV mode**: Unchanged — each CSV row already has its own date.

### `args.date` type change

`nargs="+"` changes `args.date` from `str` to `list[str]`. All code using `args.date` in single-feed mode must handle this:
- Validation (line 1937): `not args.date` still works (empty list is falsy)
- Passing to functions: use loop over dates instead of single call

### Summary Stats (compute_summary_stats, line 1693)

Add per-date breakdown when `len(unique_dates) > 1`:
```
Per-date breakdown:
  2026-02-10    ready=45  not_ready=3  error=2
  2026-02-11    ready=44  not_ready=4  error=2
```

Existing aggregate summary stays as-is (shown first, then per-date detail).

### Files Modified
- `quick_benchmark.py` — ~60 lines changed (CLI, main loop, summary)

---

## Phase 3: publisher_benchmark.py (Hardest)

### CLI Changes (lines 2126-2200)

```
--date         nargs="+"   Override CSV dates with these explicit dates.
--start-date   str         Override CSV dates with range start.
--end-date     str         Override CSV dates with range end.
```

When provided, CSV's date column is **ignored**. Each unique (feed_id, mode) is evaluated for every specified date.

### Core Logic Change (process_csv, line 1631)

```python
def process_csv(..., date_override: list[str] | None = None):
    # Read CSV as before
    feeds_raw = [(feed_id, date, mode) for row in reader]

    # Apply date override
    if date_override:
        unique_feeds = list({(fid, mode) for fid, _, mode in feeds_raw})
        feeds_to_process = [(fid, d, mode) for fid, mode in unique_feeds for d in date_override]
    else:
        feeds_to_process = feeds_raw  # existing behavior
```

`evaluate_publisher_feed()` stays unchanged — processes one (feed_id, date, mode) tuple.

### Summary Stats (compute_summary_stats, line 515)

Add per-date section when multiple dates present:

**Console**:
```
PER-DATE BREAKDOWN
Date          Total  Pass  Fail  Error  Pass%  Med NRMSE  Med Hit%
2026-02-10      45    40     3      2  88.9%   0.003241   99.12%
2026-02-11      45    41     2      2  91.1%   0.003108   99.24%
```

**CSV**: Append `PER_DATE_BREAKDOWN` section after existing `SUMMARY` section (only when multiple dates).

### Files Modified
- `publisher_benchmark.py` — ~80 lines changed (CLI, process_csv, summary, CSV output)

---

## Backward Compatibility

| Scenario | Behavior |
|----------|----------|
| `publisher_feeds.py --publisher-id 55` | Identical (uses --date-offset 1) |
| `quick_benchmark.py --feed-id 327 --date 2026-02-10 --mode fx` | Identical (single date) |
| `publisher_benchmark.py --csv feeds.csv` | Identical (CSV dates used as-is) |
| `daily_benchmark_runner.py` | Unchanged — passes `--date-offset` to publisher_feeds, no date flags to publisher_benchmark |

---

## `lru_cache` Note

`get_market_hours_filter_sql()` and similar functions use `@lru_cache(maxsize=32)`. With many dates the cache may churn. Increase `maxsize` to 128 during Phase 2 as a low-risk improvement.

---

## Verification

### Phase 0 (date_utils.py):
```bash
python -c "from date_utils import expand_date_args; print(expand_date_args(['2026-02-10'], None, None))"
python -c "from date_utils import expand_date_args; print(expand_date_args(None, '2026-02-10', '2026-02-12'))"
```

### Phase 1 (publisher_feeds.py):
```bash
# Single date (backward compat)
python publisher_feeds.py --publisher-id 55
# Explicit dates
python publisher_feeds.py --publisher-id 55 --date 2026-02-10 2026-02-11
# Date range
python publisher_feeds.py --publisher-id 55 --start-date 2026-02-10 --end-date 2026-02-12
# Verify CSV has multiple rows per feed
```

### Phase 2 (quick_benchmark.py):
```bash
# Single date (backward compat)
python quick_benchmark.py --feed-id 2944 --date 2026-02-11 --mode us-equities
# Multi-date
python quick_benchmark.py --feed-id 2944 --date 2026-02-10 2026-02-11 --mode us-equities
# Date range
python quick_benchmark.py --feed-id 2944 --start-date 2026-02-10 --end-date 2026-02-11 --mode us-equities
# CSV mode (unchanged)
python quick_benchmark.py --csv price_id_list.csv
```

### Phase 3 (publisher_benchmark.py):
```bash
# No date flags (backward compat)
python publisher_benchmark.py --csv publisher_55_feeds.csv --publisher-id 55
# Date override
python publisher_benchmark.py --csv publisher_55_feeds.csv --publisher-id 55 --date 2026-02-10 2026-02-11
# Date range override
python publisher_benchmark.py --csv publisher_55_feeds.csv --publisher-id 55 --start-date 2026-02-10 --end-date 2026-02-12
# Verify per-date breakdown in summary
```

---

## Key Files

| File | Phase | Action |
|------|-------|--------|
| `date_utils.py` | 0 | Create (~50 lines) |
| `publisher_feeds.py` | 1 | Modify (~30 lines) |
| `quick_benchmark.py` | 2 | Modify (~60 lines) |
| `publisher_benchmark.py` | 3 | Modify (~80 lines) |
| `portal/batch/daily_benchmark_runner.py` | — | Verify no breakage (read-only) |
