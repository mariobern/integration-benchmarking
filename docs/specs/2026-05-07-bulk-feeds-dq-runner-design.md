# Bulk Feeds DQ Runner — Design

**Status:** Approved (brainstorming → ready for implementation plan)
**Date:** 2026-05-07
**Branch:** `time-filter-queries`
**Author:** mario@pyth.network (with Claude)

## Problem

Today, batch DQ evaluation of N Pyth Lazer feeds runs through `evaluate_feeds.py`,
which loops over a CSV and calls `papermill.execute_notebook(...)` against
`publisher_benchmark_eval.ipynb` once per row. This is slow (notebook execution
overhead per feed), generates intermediate `executed_notebook_*.ipynb` files,
and depends on the notebook as a runtime artifact.

A standalone Python module — `evaluate_feed_standalone.py` (currently untracked
on `time-filter-queries`) — already replaces the notebook for the single-feed
case, with SQL-level time filtering and the same outputs. We want a bulk runner
built around it so we can review 20+ feeds in one invocation, with the same UX
as today's CSV-driven flow.

## Goals

- Bulk-run DQ evaluation across many feeds via a single command, using a CSV
  input identical in format to today's `price_id_list.csv` /
  `MV_Mario_1.csv`.
- Drop papermill / notebook execution from the batch path; use the standalone
  engine directly for speed and simplicity.
- Preserve the existing per-feed outputs (`plots.html`, `stats.csv`,
  appended `feed_readiness.csv`) bit-for-bit.
- Leave today's `evaluate_feeds.py`, the notebook, the bash loop, and the
  standalone engine untouched, so the new path is purely additive and the old
  paths remain available during transition.

## Non-Goals

- Parallel execution. Sequential only. (Considered and explicitly deferred —
  blast radius and ClickHouse load concerns can be addressed later if needed.)
- In-process import of the standalone engine. Considered ("Approach B") and
  rejected: the standalone uses module-level globals (`global feed_id, date,
mode, ...`), so in-process iteration would require a non-trivial refactor.
- Aggregated cross-feed dashboard / index page. Out of scope for this work.
- Per-row cluster override. `--cluster` stays global; if per-row clusters
  become a need, that's a future 4th CSV column.
- Refactor of `evaluate_feed_standalone.py`. Zero edits to the engine.

## Approach

**Approach A — Subprocess loop (selected).** A new file
`pythresearch/data_quality/lazer/evaluate_feeds_bulk.py` reads the CSV,
computes per-row times, and shells out to the standalone engine once per row:

```
python3 -m pythresearch.data_quality.lazer.evaluate_feed_standalone \
    --feed-id <id> --date <date> --mode <mode> --cluster <cluster> \
    --start-time <hh:mm:ss> --end-time <hh:mm:ss> \
    --output-path <path> --target-pub-count <n>
```

`subprocess.run(argv, check=False)` runs each invocation with stdio inherited
from the parent so progress streams live. One bad feed never aborts the batch.

### Why subprocess over in-process

- **Zero changes to the validated engine.** The user just confirmed the
  standalone works — touching it would re-introduce risk we don't need.
- **Crash isolation.** A bad query, OOM, or matplotlib state leak in feed 7
  cannot corrupt feeds 8-20.
- **No global-variable refactor.** The engine sets module-level globals in
  `main()` (`global feed_id, date, mode, cluster, ...`); in-process iteration
  would require threading those through every helper.
- **Cost is negligible.** Python/pandas startup adds ~1-2s per feed against a
  per-feed analysis runtime measured in tens of seconds (ClickHouse queries
  dominate). For a 20-feed batch, this is in the noise.

## Components

### 1. New file — `pythresearch/data_quality/lazer/evaluate_feeds_bulk.py`

Structure mirrors today's `evaluate_feeds.py`:

- `compute_times_from_mode(date: str, mode: str) -> tuple[str, str]` — pure
  helper. Returns `(start_utc, end_utc)` as `HH:MM:SS` strings, computing
  NY→UTC conversion via `zoneinfo.ZoneInfo("America/New_York")` /
  `ZoneInfo("UTC")` based on the date and mode. Mode→NY-time mapping:

  | Mode                            | NY start | NY end   |
  | ------------------------------- | -------- | -------- |
  | `us-equities-pre`               | 08:30:00 | 09:30:00 |
  | `us-equities-post`              | 16:30:00 | 17:30:00 |
  | `us-equities-overnight`         | 20:00:00 | 21:00:00 |
  | _anything else / `us-equities`_ | 09:30:00 | 10:30:00 |

- `run_standalone(feed_id, date, mode, cluster, start_time, end_time,
output_path, target_pub_count) -> bool` — builds argv list, calls
  `subprocess.run(argv, check=False)`, returns `True` iff `returncode == 0`.
  Stdio inherited (no `capture_output=True`).

- `process_csv(csv_file, cluster, start_time_override, end_time_override,
output_path, target_pub_count) -> tuple[int, int, list[str]]` — iterates the
  CSV. For each row: skip blanks, warn on rows with <3 columns, resolve times
  (override if provided, else `compute_times_from_mode`), call
  `run_standalone`, track `(succeeded_count, failed_count, failed_descriptors)`
  where each failed descriptor is the string `"{feed_id}@{date}"`.

- `main()` — argparse identical to current `evaluate_feeds.py`:

  | Flag                 | Required | Default                      |
  | -------------------- | -------- | ---------------------------- |
  | `--csv`              | no       | `price_id_list.csv`          |
  | `--cluster`          | yes      | —                            |
  | `--start-time`       | no       | (computed per-row from mode) |
  | `--end-time`         | no       | (computed per-row from mode) |
  | `--output-path`      | no       | `dq_reports`                 |
  | `--target-pub-count` | no       | `4`                          |

  Calls `process_csv`, prints summary line, exits with code `0` if no failures
  or `1` otherwise.

### 2. Test file — `pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py`

13 pytest tests with `unittest.mock.patch` on `subprocess.run`:

1. `test_time_computation_us_equities_pre`
2. `test_time_computation_us_equities_post`
3. `test_time_computation_us_equities_overnight`
4. `test_time_computation_default_mode`
5. `test_cli_time_override_bypasses_mode_computation`
6. `test_argv_construction` — every CSV column + every CLI flag → correct argv
7. `test_csv_skips_blank_lines`
8. `test_csv_skips_short_rows`
9. `test_csv_tolerates_whitespace` — `MV_Mario_1.csv`-style leading spaces
10. `test_csv_missing_file_exits_1`
11. `test_exit_code_zero_on_all_success`
12. `test_exit_code_one_on_any_failure` — and confirms other rows still ran
13. `test_summary_line_counts`

Run:

```bash
pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py -v \
    --cov=pythresearch.data_quality.lazer.evaluate_feeds_bulk \
    --cov-report=term-missing
```

Coverage target: ≥80% on the new module. Standalone engine, ClickHouse queries,
and filesystem outputs are out of scope (owned by `evaluate_feed_standalone.py`,
already validated manually).

### 3. New file — `pythresearch/data_quality/lazer/tests/__init__.py`

Empty file, present so pytest discovers the package.

## Per-Row Execution Flow

```
for each row in csv:
    1. parse → (feed_id, date, mode), skip blanks, warn-and-skip if <3 cols
    2. resolve times:
         if --start-time/--end-time on CLI → use override
         else → compute_times_from_mode(date, mode)
    3. argv = ["python3", "-m", "pythresearch.data_quality.lazer.evaluate_feed_standalone",
              "--feed-id", feed_id, "--date", date, "--mode", mode,
              "--cluster", cluster, "--start-time", t0, "--end-time", t1,
              "--output-path", output_path, "--target-pub-count", str(n)]
    4. result = subprocess.run(argv, check=False)   # stdio inherited
    5. if result.returncode == 0:
           succeeded += 1
       else:
           failed += 1
           failed_list.append(f"{feed_id}@{date}")
       (no abort — continue to next row)

after loop:
    print(f"Processed {n} feeds: {succeeded} succeeded, {failed} failed.")
    if failed_list: print(f"Failed: {failed_list}")
    sys.exit(0 if failed == 0 else 1)
```

## CLI

Identical to today's `evaluate_feeds.py`. Drop-in mental model:

```bash
python3 -m pythresearch.data_quality.lazer.evaluate_feeds_bulk \
    --csv MV_Mario_1.csv \
    --cluster lazer-prod
```

With overrides:

```bash
python3 -m pythresearch.data_quality.lazer.evaluate_feeds_bulk \
    --csv MV_Mario_1.csv \
    --cluster lazer-prod \
    --start-time 18:00:00 --end-time 19:00:00 \
    --output-path dq_reports \
    --target-pub-count 4
```

## Outputs (preserved, unchanged)

The standalone engine writes:

- `<output-path>/<cluster>/<mode>/<feed_id>/<date>/plots.html` — full plotly
  HTML page with all charts embedded
- `<output-path>/<cluster>/<mode>/<feed_id>/<date>/stats.csv` — per-feed
  metrics
- `<output-path>/<cluster>/<mode>/feed_readiness.csv` — appended summary
  across all runs (deduped on `feed_id` + `target_date`, last-write wins)

The bulk runner adds nothing to this tree.

## Files Touched

**Added (3):**

- `pythresearch/data_quality/lazer/evaluate_feeds_bulk.py`
- `pythresearch/data_quality/lazer/tests/__init__.py`
- `pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py`

**Untouched (intentional):**

- `pythresearch/data_quality/lazer/evaluate_feeds.py` — original papermill loop
- `pythresearch/data_quality/lazer/evaluate_feed_standalone.py` — engine
- `pythresearch/data_quality/lazer/publisher_benchmark_eval.ipynb` — interactive
- `pythresearch/data_quality/lazer/evaluate_feeds_against_benchmark.sh` — legacy bash

## Failure Handling

- **Per-row failure → continue.** Mirror today's `evaluate_feeds.py` behavior.
  One bad feed must not kill a 20-feed batch.
- **No retries.** A failure is logged and we move on. Operator decides what to
  re-run.
- **End-of-run summary.** Single line: `Processed N feeds: M succeeded, K
failed.` plus, if non-empty, `Failed: [feed_id@date, ...]`. Avoids
  scrolling-through-stdout to count outcomes.
- **Process exit code.** `0` iff every row succeeded, else `1`. Useful for CI
  and for `&&` chaining.
- **Missing CSV file.** `FileNotFoundError` → printed error → `sys.exit(1)`,
  matching today's `evaluate_feeds.py:151-153` behavior.

## Validation Plan

After implementation, before merging:

1. Run the new bulk runner on `MV_Mario_1.csv` (27 rows) and confirm
   `dq_reports/` tree has 27 `plots.html` + 27 `stats.csv` files at the
   expected paths.
2. Spot-check 2-3 plot files visually against output produced by the old
   papermill flow (or a single-feed run of `evaluate_feed_standalone.py`) on
   the same input. They must match.
3. Inject a deliberate failure (e.g., a bogus `feed_id` row) and confirm:
   batch continues, summary line lists the failed descriptor, exit code is
   `1`.
4. Run the test suite, confirm ≥80% coverage on
   `evaluate_feeds_bulk.py`.

## Out-of-scope follow-ups (not in this work)

These came up during brainstorming but were explicitly deferred:

- Parallel execution (multiprocessing.Pool, ThreadPoolExecutor, or `xargs -P`)
- Consolidating the engine + bulk runner into one script with a `--csv`
  flag on `evaluate_feed_standalone.py`
- Cross-feed aggregated dashboard / index page
- Cleanup of stale `executed_notebook_*.ipynb` files in the working tree and
  adding `executed_notebook_*.ipynb` to `.gitignore`
- Tracking `evaluate_feed_standalone.py` in git (currently untracked on
  `time-filter-queries`)
