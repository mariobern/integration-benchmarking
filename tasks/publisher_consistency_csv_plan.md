# Plan: Add Publisher Consistency to CSV Output

## Context

The publisher consistency report (cross-date pass/fail matrix with classifications) currently displays in the terminal but is either missing from or incomplete in the CSV output. The goal is to ensure the CSV output includes the full publisher consistency report for `quick_benchmark.py`, `quick_benchmark_95.py`, and `feed_uptime.py`. Skipping `publisher_benchmark.py` and `publisher_benchmark_95.py` per user decision (single-publisher scripts, no publisher consistency concept).

## Current State

| Script                | Terminal consistency               | CSV consistency         | CSV classifications | Requires --detailed |
| --------------------- | ---------------------------------- | ----------------------- | ------------------- | ------------------- |
| quick_benchmark.py    | Yes (with --detailed + multi-date) | Yes (PUBLISHER SUMMARY) | No                  | Yes                 |
| quick_benchmark_95.py | Same as above                      | Same as above           | No                  | Yes                 |
| feed_uptime.py        | Yes (with multi-date)              | Yes (PUBLISHER SUMMARY) | No                  | No                  |

**What's missing:**

1. **quick_benchmark.py / \_95**: Publisher consistency only writes to CSV when `--detailed` is used. Should always write when multi-date.
2. **All three scripts**: Classifications (always_passing, always_failing, intermittent) are printed to terminal but NOT included in the CSV.

## Files to Modify

1. `/home/mariobern/integration-benchmarking/quick_benchmark.py`
2. `/home/mariobern/integration-benchmarking/quick_benchmark_95.py`
3. `/home/mariobern/integration-benchmarking/feed_uptime.py`

## Changes

### 1. quick_benchmark.py — `write_results_csv()` (line ~1894)

**Move publisher summary out of `if include_detailed:` block.**

Currently at line 1894-1906, the publisher summary is inside the `if include_detailed:` block. Move it to after the detailed block so it always runs when multiple dates exist:

```python
# After the detailed section closes (after line 1892)...
# Always write publisher summary when multi-date (moved OUT of include_detailed block)
unique_dates = {r.date for r in results}
if len(unique_dates) > 1:
    publisher_summary = compute_publisher_summary(
        results,
        include_extended_hours=include_extended_hours,
        include_overnight=include_overnight,
    )
    write_publisher_summary_csv(
        writer,
        publisher_summary,
        include_extended_hours=include_extended_hours,
        include_overnight=include_overnight,
    )
```

### 2. quick_benchmark.py — `write_publisher_summary_csv()` (line ~1578)

**Add classifications section after publisher rows.** After writing all publisher rows (line 1670), add:

```python
# Write classifications
writer.writerow([])
writer.writerow(["PUBLISHER CLASSIFICATIONS"])

sessions_to_classify = [TradingSession.REGULAR.value]
if include_extended_hours:
    sessions_to_classify.extend([TradingSession.PREMARKET.value, TradingSession.AFTERHOURS.value])
if include_overnight:
    sessions_to_classify.append(TradingSession.OVERNIGHT.value)

for session_name in sessions_to_classify:
    classifications = publisher_summary["classifications"][session_name]
    _fmt = lambda ids: ";".join(str(x) for x in ids) if ids else ""
    writer.writerow([f"{session_name}_always_passing", _fmt(classifications["always_passing"])])
    writer.writerow([f"{session_name}_always_failing", _fmt(classifications["always_failing"])])
    writer.writerow([f"{session_name}_intermittent", _fmt(classifications["intermittent"])])
```

### 3. quick_benchmark.py — `main()` (line ~2539)

**Move terminal print out of `if args.detailed` block.** Currently:

```python
if args.detailed and len({r.date for r in results}) > 1:
    publisher_summary = compute_publisher_summary(...)
    print_publisher_summary(...)
```

Change to:

```python
if len({r.date for r in results}) > 1:
    publisher_summary = compute_publisher_summary(...)
    print_publisher_summary(...)
```

### 4. quick_benchmark_95.py — Mirror all changes from quick_benchmark.py

Apply the identical three changes to `quick_benchmark_95.py` (same line numbers, same code).

### 5. feed_uptime.py — `write_results_csv()` (line ~817)

**Add classifications after the PUBLISHER SUMMARY rows.** After line 851 (end of summary row loop), add classification rows:

```python
# Write classifications
writer.writerow([])
writer.writerow(["PUBLISHER CLASSIFICATIONS"])

for session_name in session_names:
    always_passing = []
    always_failing = []
    intermittent = []
    for row in summary_rows:
        stats = row["sessions"].get(session_name, {})
        pass_dates = stats.get("pass_dates", 0)
        fail_dates = stats.get("fail_dates", 0)
        if pass_dates + fail_dates == 0:
            continue
        pid = int(row["publisher_id"])
        if pass_dates > 0 and fail_dates == 0:
            always_passing.append(pid)
        elif fail_dates > 0 and pass_dates == 0:
            always_failing.append(pid)
        else:
            intermittent.append(pid)

    _fmt = lambda ids: ";".join(str(x) for x in ids) if ids else ""
    writer.writerow([f"{session_name}_always_passing", _fmt(always_passing)])
    writer.writerow([f"{session_name}_always_failing", _fmt(always_failing)])
    writer.writerow([f"{session_name}_intermittent", _fmt(intermittent)])
```

## CSV Output Format (New Sections)

After the existing `PUBLISHER SUMMARY` table, the CSV will now include:

```csv
PUBLISHER CLASSIFICATIONS
regular_always_passing,11;32;55
regular_always_failing,99
regular_intermittent,44;77
premarket_always_passing,11;55
premarket_always_failing,
premarket_intermittent,32
```

This matches the terminal output format where classifications are listed per session.

## Verification

1. **quick_benchmark.py** — Run with multi-date, WITHOUT `--detailed`:

   ```bash
   source venv/bin/activate
   python3 quick_benchmark.py --feed-id 327 --start-date 2026-02-10 --end-date 2026-02-12 --mode fx --output /tmp/test_qb.csv
   ```

   - Verify PUBLISHER SUMMARY + PUBLISHER CLASSIFICATIONS sections appear in CSV
   - Verify terminal still prints the consistency report

2. **quick_benchmark_95.py** — Same test as above with `quick_benchmark_95.py`

3. **feed_uptime.py** — Run with multi-date:

   ```bash
   python3 feed_uptime.py --feed-id 922 --start-date 2026-02-10 --end-date 2026-02-12 --mode us-equities --output /tmp/test_fu.csv
   ```

   - Verify PUBLISHER CLASSIFICATIONS section appears after PUBLISHER SUMMARY in CSV

4. For all scripts: Verify single-date runs still work normally (no summary/classifications section)
