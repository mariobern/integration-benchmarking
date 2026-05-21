# Evaluate Feeds Bulk Tool

Runs the lazer DQ engine (`evaluate_feed_standalone`) once per CSV row as a subprocess. Replaces the papermill-on-notebook flow with a flat, notebook-free batch runner.

- CSV in: `feed_id,date,mode` per row
- Output: per-feed DQ reports written by the standalone engine under `--output-path`
- Failures are soft: a non-zero exit from the engine logs the failure and the batch continues

## When to Use

| Scenario                                    | Use This Tool                            |
| ------------------------------------------- | ---------------------------------------- |
| Run DQ across many feed/date/mode tuples    | Yes                                      |
| Need notebook artifacts (`.ipynb`) per feed | No                                       |
| Single feed, ad-hoc                         | Call `evaluate_feed_standalone` directly |

## Usage

```bash
# Default CSV (price_id_list.csv)
python -m lazer_dq.evaluate_feeds_bulk --cluster lazer-prod

# Custom CSV
python -m lazer_dq.evaluate_feeds_bulk --csv MV_Mario_1.csv --cluster lazer-prod

# Override the per-row window (skips mode-based time computation)
python -m lazer_dq.evaluate_feeds_bulk \
    --csv MV_Mario_1.csv --cluster lazer-prod \
    --start-time 14:30:00 --end-time 21:00:00

# Custom output dir + target publisher count
python -m lazer_dq.evaluate_feeds_bulk \
    --csv MV_Mario_1.csv --cluster lazer-prod \
    --output-path dq_reports --target-pub-count 6
```

## Arguments

| Argument             | Description                                     | Default             |
| -------------------- | ----------------------------------------------- | ------------------- |
| `--csv`              | CSV file with `feed_id,date,mode` rows          | `price_id_list.csv` |
| `--cluster`          | Cluster name (e.g. `lazer-prod`) — **required** | —                   |
| `--start-time`       | Override start time `HH:MM:SS` UTC              | per-row from mode   |
| `--end-time`         | Override end time `HH:MM:SS` UTC                | per-row from mode   |
| `--output-path`      | Base directory for engine output                | `dq_reports`        |
| `--target-pub-count` | Target publisher count passed to the engine     | `4`                 |

## CSV Format

```
feed_id,date,mode
1021,2026-05-04,us-equities
1060,2026-05-04,us-equities-pre
922,2026-04-13,us-equities-overnight
2503,2026-05-04,hk-equities
```

- Empty rows are skipped.
- Rows with fewer than 3 columns are skipped with a warning.
- Whitespace around cells is trimmed.

## Time Window Resolution

When `--start-time` / `--end-time` are not both provided, the window is computed per row from the `mode` column. Local market windows are converted to UTC via `zoneinfo` (handles EDT/EST automatically based on the date; HKT is fixed UTC+8 with no DST).

| Mode                                                          | Local window      | Timezone           |
| ------------------------------------------------------------- | ----------------- | ------------------ |
| `us-equities-pre`                                             | 08:30:00–09:30:00 | `America/New_York` |
| `us-equities-post`                                            | 16:30:00–17:30:00 | `America/New_York` |
| `us-equities-overnight`                                       | 20:00:00–21:00:00 | `America/New_York` |
| `hk-equities`                                                 | 09:30:00–10:30:00 | `Asia/Hong_Kong`   |
| `us-equities` _(or any other value, including unknown modes)_ | 09:30:00–10:30:00 | `America/New_York` |

Providing **both** `--start-time` and `--end-time` bypasses mode-based computation for every row.

## Engine Invocation

For each row, the runner shells out to:

```
python -m lazer_dq.evaluate_feed_standalone \
    --feed-id <id> --date <date> --mode <mode> --cluster <cluster> \
    --start-time <hh:mm:ss> --end-time <hh:mm:ss> \
    --output-path <path> --target-pub-count <n>
```

The engine's stdio is inherited so its progress logs stream live to the terminal.

## Output

The runner itself writes no files — the standalone engine owns all output. After the loop, the runner prints:

```
Processed <N> feeds: <S> succeeded, <F> failed.
Failed: ['<feed_id>@<date>', ...]   # only if any failed
```

Exit code: `0` if all rows succeeded, `1` if any row failed.

## Errors

- **Missing CSV file** → hard error, exit `1`.
- **Per-row engine failure** → logged, recorded in the failed list, batch continues. Final exit code is `1`.
- **Malformed CSV row** (blank / fewer than 3 columns) → warning, row skipped.
