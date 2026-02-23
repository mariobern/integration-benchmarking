# Plan: Multi-Feed-ID Support for publisher_benchmark.py

## Context

`quick_benchmark.py` already supports two modes:

1. **CSV mode**: `--csv feeds.csv`
2. **Single-feed mode**: `--feed-id 327 328 --date 2025-10-06 --mode fx` (no CSV required)

`publisher_benchmark.py` currently requires `--csv` always. The `--feed-id` flag only **filters** CSV rows. The goal is parity: if feed IDs are given directly with `--date` and `--mode`, CSV should be optional.

## Changes

### File: `publisher_benchmark.py`

**1. Make `--csv` optional** (line 2219)

Change `required=True` to `required=False` (or remove `required` entirely).

**2. Add `--mode` argument**

Add a new `--mode` argument for single-feed mode (same as quick_benchmark.py):

```python
parser.add_argument("--mode", type=str, help="Asset class: fx, metals, us-equities, commodity, us-treasuries")
```

**3. Repurpose `--feed-id` for dual behavior**

Currently `--feed-id` is stored as `dest="feed_ids"` and only filters CSV rows. In the new design:

- **With `--csv`**: `--feed-id` filters CSV rows (unchanged behavior)
- **Without `--csv`**: `--feed-id` is primary input, combined with `--date`/`--start-date`/`--end-date` + `--mode`

No need to change `dest` — the same `args.feed_ids` list works for both paths.

**4. Add validation logic** (after `args = parser.parse_args()`, ~line 2306)

Mirroring quick_benchmark.py's pattern:

```python
if args.csv and args.mode:
    parser.error("--mode is for single-feed mode. Use either --csv OR (--feed-id, --date, --mode)")
elif not args.csv and not (args.feed_ids and args.mode):
    parser.error("Either --csv or all of (--feed-id, --date, --mode) are required")
```

When `--csv` is absent:

- `--feed-id` + `--mode` are required
- `--date` or `--start-date/--end-date` are required (not "overrides" anymore — they're primary)
- `--publisher-id` is required (can't extract from CSV filename)
- `--include-asset-class` / `--exclude-asset-class` / `--list-asset-classes` are invalid

**5. Add single-feed execution path** (after line 2366)

New `else` branch when `args.csv` is None — builds feed list directly and calls `evaluate_publisher_feed()`:

```python
if args.csv:
    # existing CSV path (unchanged)
    results = process_csv(...)
else:
    # Single-feed mode: cartesian product of feed_ids × dates
    config = load_config()
    feed_date_pairs = [
        (fid, d, args.mode) for fid in args.feed_ids for d in resolved_dates
    ]
    # Use ThreadPoolExecutor, call evaluate_publisher_feed() for each
    # Same parallel pattern as process_csv's inner loop (lines 1748-1783)
```

**6. Update CSV existence check** (line 2317-2320)

Guard with `if args.csv:` so it doesn't crash when CSV is None.

**7. Update epilog/help text** (lines 2188-2213)

Add examples for the new single-feed mode:

```
# Single-feed mode (no CSV needed)
python publisher_benchmark.py --publisher-id 55 --feed-id 327 --date 2025-10-06 --mode fx

# Multiple feed IDs × multiple dates
python publisher_benchmark.py --publisher-id 55 --feed-id 327 328 --date 2025-10-06 2025-10-07 --mode us-equities

# Date range
python publisher_benchmark.py --publisher-id 55 --feed-id 327 --start-date 2025-10-01 --end-date 2025-10-06 --mode fx
```

### File: `CLAUDE.md`

Update the publisher_benchmark.py section to document the new single-feed mode examples and that `--csv` is now optional.

## Key design decisions

- **Mutual exclusivity**: `--csv` and `--mode` cannot be used together (same pattern as quick_benchmark). The `--date` flags work as overrides in CSV mode and as primary input in single-feed mode.
- **`--publisher-id` becomes required** in single-feed mode (no filename to extract from). In CSV mode it remains optional (extracted from filename).
- **Reuse existing function**: The single-feed path calls `evaluate_publisher_feed()` directly (same function `process_csv` uses internally), avoiding code duplication.
- **Summary stats**: The existing `compute_summary_stats()` and `write_results_csv()` work on `list[PublisherBenchmarkResult]` regardless of source — no changes needed there.

## Verification

```bash
# Test single-feed mode (one feed, one date)
python publisher_benchmark.py --publisher-id 55 --feed-id 327 --date 2025-10-06 --mode fx

# Test cartesian product (2 feeds × 2 dates = 4 evaluations)
python publisher_benchmark.py --publisher-id 55 --feed-id 327 328 --date 2025-10-06 2025-10-07 --mode fx

# Test date range
python publisher_benchmark.py --publisher-id 55 --feed-id 327 --start-date 2025-10-01 --end-date 2025-10-03 --mode us-equities --workers 4

# Test validation errors
python publisher_benchmark.py --feed-id 327 --mode fx  # should error: missing --date and --publisher-id
python publisher_benchmark.py --csv feeds.csv --mode fx  # should error: --mode with --csv

# Test CSV mode still works (regression)
python publisher_benchmark.py --csv publisher_55_feeds.csv
python publisher_benchmark.py --csv publisher_55_feeds.csv --feed-id 327 --date 2025-10-06
```
